"""
core/app.py - shared state. One of these per process.
"""

import json
import os
import threading
import time

from . import agents as agents_mod
from . import mailbox as mailbox_mod
from . import policy as policy_mod
from . import profile as profile_mod
from . import tools as tools_mod
from .lemonade import Lemonade
from .mxc import Mxc


class App:
    def __init__(self, project_dir):
        self.project_dir = os.path.abspath(project_dir)
        self.config_path = os.path.join(self.project_dir, "config.json")
        self.policy_path = os.path.join(self.project_dir, "policy.json")
        self.cfg = _load_json(self.config_path)
        self._config_mtime = _mtime(self.config_path)
        self.policy = policy_mod.load(self.policy_path)
        self._policy_mtime = _mtime(self.policy_path)

        # Per-subagent policies, keyed by agent id. The root policy.json above
        # stays exactly where it was and keeps its old meaning: it is what
        # verify.py, pwsh-ladder.py and Phase 1 all read, and it is the
        # fallback for any agent that has no file of its own yet.
        self._policies = {}
        self._policy_mtimes = {}

        ws = (self.cfg.get("agent") or {}).get("workspace") or "workspace"
        self.workspace = os.path.abspath(os.path.join(self.project_dir, ws))
        os.makedirs(self.workspace, exist_ok=True)
        self.mailbox = os.path.abspath(os.path.join(
            self.project_dir,
            (self.cfg.get("mail") or {}).get("dir") or "mailbox"))
        mailbox_mod.ensure(self.mailbox, self.project_dir)
        self.capture_dir = os.path.join(self.project_dir, "receipts")

        self.profile = profile_mod.load(self.project_dir)

        self.lock = threading.Lock()
        self.runs = []
        self.run_seq = 0
        self.subscribers = []

        self.mxc = Mxc(self.cfg, self.project_dir, on_run=None)
        self.lemonade = Lemonade(self.cfg)

        self.probe = None
        self.caps = {}
        self.dialect = "modern"
        self.negotiation = []
        self.startup_notes = []
        self.lemonade_health = {}
        self.warmup = {"state": "cold"}
        self._warmup_thread = None

    # -- paths ------------------------------------------------------------

    def path_ctx(self):
        return policy_mod.path_context(self.project_dir, self.workspace,
                                       self.mailbox)

    # -- profile ----------------------------------------------------------

    def active_agent(self):
        p = self.profile or {}
        return p.get("activeAgent") or agents_mod.DEFAULT_ID

    def set_profile(self, incoming):
        """Save the profile and lay down a policy file for each subagent the
        participant chose.

        The preset only lands if that agent has no policy file yet. Re-running
        onboarding should not silently throw away a policy somebody has spent
        the last ten minutes editing - and overwriting the one artefact the
        workshop is about would be the single worst thing this function could
        do."""
        self.profile = profile_mod.save(self.project_dir, incoming)
        written = []
        for agent_id in self.profile["subagents"]:
            path = self.policy_path_for(agent_id)
            if os.path.exists(path):
                continue
            pol = agents_mod.preset(agent_id, self.profile["presets"].get(agent_id))
            if pol is None:
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            policy_mod.save(path, pol)
            written.append(agent_id)
        self._policies.clear()
        self._policy_mtimes.clear()
        return self.profile, written

    def apply_preset(self, agent_id, preset_id):
        """Overwrite one agent's policy with a named preset. Unlike
        set_profile this is explicit - the participant clicked a preset in the
        Policy tab knowing it replaces what is there."""
        pol = agents_mod.preset(agent_id, preset_id)
        if pol is None:
            return None
        return self.save_policy(pol, agent_id)

    # -- config -----------------------------------------------------------

    def reload_config(self):
        """Re-read config.json if it changed on disk.

        policy.json has always reloaded itself - the whole demo depends on an
        edit landing without a restart. config.json did not, which meant you
        could fix the model name, hit Rescan, and watch the UI keep showing
        the old one because the Lemonade client was still holding the name it
        was constructed with. Two files, two lifetimes, one confused user.

        Returns True if the Lemonade settings changed, so the caller knows to
        warm the new model.
        """
        m = _mtime(self.config_path)
        if m == self._config_mtime:
            return False
        before = json.dumps((self.cfg or {}).get("lemonade") or {}, sort_keys=True)
        try:
            self.cfg = _load_json(self.config_path)
        except Exception as e:
            self.note("warn", "config.json could not be parsed (%s). Still "
                              "using the last good copy." % e)
            return False
        self._config_mtime = m
        after = json.dumps((self.cfg or {}).get("lemonade") or {}, sort_keys=True)
        if before == after:
            return False

        self.lemonade = Lemonade(self.cfg)
        self.warmup = {"state": "cold"}
        self._warmup_thread = None
        return True

    def refresh_config(self):
        """reload_config() plus the Lemonade re-check that has to follow it.

        Separate from start() because this runs on every /api/state poll and
        start() shells out to wxc-exec --probe. Re-reading a small JSON file is
        free; re-probing the sandbox backend several times a second is not.
        """
        if not self.reload_config():
            return False
        self.lemonade_health = h = self.lemonade.health()
        if not h.get("reachable"):
            self.note("error", h.get("note"))
            self.warmup = {"state": "unreachable", "error": h.get("note")}
        elif not h.get("modelPresent"):
            self.note("error", h.get("note"))
            self.warmup = {"state": "no-model", "error": h.get("note"),
                           "suggestions": h.get("suggestions") or []}
        else:
            self.note("info", "Now pointing at %s. Loading it." % h.get("model"))
            self.start_warmup()
        return True

    # -- policy -----------------------------------------------------------

    def policy_path_for(self, agent_id=None):
        """Where one agent's policy lives. None means the root policy.json,
        which is what Phase 1, verify.py and pwsh-ladder.py all mean."""
        if not agent_id:
            return self.policy_path
        rec = agents_mod.get(agent_id)
        return os.path.join(self.project_dir, *rec["policyFile"].split("/"))

    def rel_policy_path(self, agent_id=None):
        """The policy file as the UI should name it. The Policy tab says which
        file it is editing out loud, because with more than one of them on
        disk "Save" is otherwise a guess."""
        return rel(self.policy_path_for(agent_id), self.project_dir)

    def reload_policy(self, agent_id=None):
        """Read a policy from disk if it changed. Called before every single
        tool call - the whole demo depends on an edit landing on the next call
        without a restart.

        Called with no argument it behaves exactly as it always did, so the
        callers that predate subagents did not have to change."""
        if not agent_id:
            m = _mtime(self.policy_path)
            if m != self._policy_mtime:
                try:
                    self.policy = policy_mod.load(self.policy_path)
                    self._policy_mtime = m
                except Exception as e:
                    self.note("warn", "policy.json could not be parsed (%s). "
                                      "Still using the last good copy." % e)
            return self.policy

        path = self.policy_path_for(agent_id)
        m = _mtime(path)
        if m is None:
            # No file for this agent yet - onboarding has not run, or somebody
            # deleted it. Fall back to the root policy rather than to an empty
            # dict: an empty policy grants nothing, and "every tool call is
            # refused" is a confusing way to learn your file is missing.
            return self.reload_policy()
        if m != self._policy_mtimes.get(agent_id) or agent_id not in self._policies:
            try:
                self._policies[agent_id] = policy_mod.load(path)
                self._policy_mtimes[agent_id] = m
            except Exception as e:
                self.note("warn", "%s could not be parsed (%s). Still using the "
                                  "last good copy." % (rel(path, self.project_dir), e))
                if agent_id not in self._policies:
                    return self.reload_policy()
        return self._policies[agent_id]

    def save_policy(self, new_policy, agent_id=None):
        path = self.policy_path_for(agent_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        policy_mod.save(path, new_policy)
        if not agent_id:
            self.policy = new_policy
            self._policy_mtime = _mtime(path)
            return self.policy
        self._policies[agent_id] = new_policy
        self._policy_mtimes[agent_id] = _mtime(path)
        return new_policy

    def working_dir(self, pol):
        """Where the contained process starts.

        It has to be somewhere the policy actually grants. A sandbox launched
        with a cwd it cannot reach fails with 'Access is denied' before the
        command runs at all - which reads on screen as the tool being refused,
        when what was really refused was the working directory. That is the
        worst failure this app can produce, because it is a real refusal
        reported against the wrong thing.

        So: derive it from the policy rather than assuming the workspace.
        Prefer somewhere writable, fall back to somewhere readable, and finally
        to System32, which every policy must grant or no tool could start.
        Narrow the policy and the cwd narrows with it."""
        ctx = self.path_ctx()
        paths = (policy_mod.normalise(pol).get("paths") or {})

        def usable(kind):
            for raw in paths.get(kind) or []:
                try:
                    full = policy_mod.expand(raw, ctx)
                except policy_mod.PolicyError:
                    continue
                if os.path.isdir(full):
                    yield full

        for full in usable("write"):
            return full
        system32 = ctx["system32"].lower()
        for full in usable("read"):
            if full.lower() != system32:
                return full
        return ctx["system32"] if os.path.isdir(ctx["system32"]) else None

    def compile_for(self, pol, command, cwd=None):
        cwd = cwd or self.working_dir(pol)
        return policy_mod.compile_config(
            pol, self.path_ctx(), command, cwd=cwd, caps=self.caps,
            dialect=self.dialect, capture_dir=self.capture_dir)

    # -- startup ----------------------------------------------------------

    def start(self):
        # Pick up any config.json edit made since this process booted. Rescan
        # used to re-probe MXC and re-check Lemonade while still asking about
        # whatever model name was read at import time, which made the one
        # button labelled "re-examine this machine" unable to fix the single
        # most common setup mistake.
        self.reload_config()
        self.probe = self.mxc.probe()
        self.caps = self.probe.get("capabilities") or {}
        if not self.probe.get("available"):
            self.note("error", self.probe.get("error") or
                      "wxc-exec --probe did not succeed. Tool calls will not run.")
        else:
            self.note("info", "Containment tier on this host: %s"
                      % self.caps.get("_tierLabel", "unknown"))
            for w in self.probe.get("warnings") or []:
                self.note("warn", w)

            probe_cmd = tools_mod.shell_cmd("ver")
            self.dialect, self.negotiation = policy_mod.negotiate_dialect(
                self.mxc, self.policy, self.path_ctx(), probe_cmd)
            if self.dialect == "none":
                self.note("error",
                          "wxc-exec rejected both network dialects on this host. "
                          "Runs will carry no network policy. Check the Run tab "
                          "for the exact validation messages.")
            else:
                self.note("info", "Network policy will be written in the '%s' "
                                  "dialect on this host." % self.dialect)

        # Lemonade. "Reachable" is not the same as "wired in", and conflating
        # the two is how a preflight comes back green and the first chat
        # message 404s. The server being up tells you almost nothing; the
        # question is whether it is serving the model this config names.
        self.lemonade_health = h = self.lemonade.health()
        if not h.get("reachable"):
            self.note("error", h.get("note"))
            self.warmup = {"state": "unreachable", "error": h.get("note")}
        elif not h.get("modelPresent"):
            # An error, not a warning. Every single thing the agent does runs
            # through this model.
            self.note("error", h.get("note"))
            self.warmup = {"state": "no-model", "error": h.get("note"),
                           "suggestions": h.get("suggestions") or []}
        else:
            self.note("info", "Lemonade is serving %s at %s%s."
                      % (h.get("model"), h.get("baseUrl"),
                         h.get("routePrefix") or ""))
            self.start_warmup()
        return self

    # -- warm up ----------------------------------------------------------

    def start_warmup(self):
        """Load the weights in the background while the user reads the UI.

        Non-blocking on purpose: the server should come up and the browser
        should open immediately. The UI shows the model as warming and the
        chat box says so, which is a far better first impression than an
        instant-looking app that then stalls for forty seconds on the first
        message.
        """
        # Only decline if one is genuinely still running. A finished thread
        # must not block a second attempt, or fixing the model name and
        # hitting Rescan leaves the app stuck on the old failure.
        t = getattr(self, "_warmup_thread", None)
        if t is not None and t.is_alive():
            return
        self.warmup = {"state": "warming", "startedAt": time.time(),
                       "model": self.lemonade.model}

        def go():
            r = self.lemonade.warmup()
            if r.get("ok"):
                self.warmup = {"state": "ready", "ms": r["ms"],
                               "model": self.lemonade.model}
                self.note("info", "Model warm in %.1fs - the first message "
                                  "will not stall." % (r["ms"] / 1000.0))
            else:
                self.warmup = {"state": "failed", "ms": r.get("ms"),
                               "error": r.get("error"),
                               "modelMissing": r.get("modelMissing"),
                               "model": self.lemonade.model}
                self.note("error", r.get("error"))

        self._warmup_thread = threading.Thread(target=go, daemon=True)
        self._warmup_thread.start()

    def warmup_state(self):
        return getattr(self, "warmup", {"state": "unknown"})

    def note(self, level, message):
        if message:
            self.startup_notes.append({"level": level, "message": message,
                                       "at": time.time()})

    # -- run log ----------------------------------------------------------

    def record_run(self, rec):
        with self.lock:
            self.run_seq += 1
            rec["seq"] = self.run_seq
            self.runs.append(rec)
            if len(self.runs) > 400:
                del self.runs[:-400]

    def recent_runs(self, limit=60):
        with self.lock:
            return [_slim(r) for r in self.runs[-limit:]][::-1]

    def refusals(self, limit=40):
        with self.lock:
            bad = [r for r in self.runs
                   if r.get("outcome") in ("blocked", "refused-to-start", "host-gate")]
            return [_slim(r) for r in bad[-limit:]][::-1]


def _slim(r):
    keep = ("seq", "id", "tool", "label", "outcome", "kind", "reason", "detail",
            "offendingField", "command", "arguments", "durationMs", "exitCode",
            "startedAt", "dryRun", "containment", "notes")
    out = {k: r.get(k) for k in keep if k in r}
    out["stdout"] = (r.get("stdout") or "")[:2000]
    out["stderr"] = (r.get("stderr") or "")[:2000]
    out["config"] = r.get("config")
    return out


def rel(path, base):
    """A path as a human would say it out loud, for notes and error messages."""
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return path


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None
