"""
core/app.py - shared state. One of these per process.
"""

import json
import os
import platform
import threading
import time

from . import agents as agents_mod
from . import basecamp as basecamp_mod
from . import icsfeed as icsfeed_mod
from . import mailbox as mailbox_mod
from . import policy as policy_mod
from . import postman as postman_mod
from . import profile as profile_mod
from . import tools as tools_mod
from . import vault as vault_mod
from .lemonade import Lemonade
from .mxc import Mxc

# What the dragon is called before anyone has named it. The launch wizard
# offers this as the pre-filled suggestion, so most people keep it.
DEFAULT_ASSISTANT_NAME = "Max"

# Backdrop ids the launch page knows how to draw. Kept here as well as in the
# page so a typo in a hand-edited config.json comes back as "none" instead of
# an unstyled grey panel nobody can explain.
BACKDROP_IDS = ("none", "parchment", "stone", "hills")

# A deny list rather than an allow list, so that Jose, Bjorn and a name in
# Chinese all survive. The pages render the name through textContent and the
# wire format is JSON, so the only characters worth removing are the ones that
# would be ambiguous if either of those assumptions ever slipped.
_NAME_DROP = set("<>&\"\\{}")
_NAME_SPACE = set(chr(c) for c in range(0, 32)) | {chr(127)}


def _clean_name(value):
    """Trim a proposed assistant name down to something safe to print.

    It lands in the window titlebar, in the chat transcript and in the model's
    system prompt, so it is cleaned once here rather than escaped at each of
    those three sites. Returns "" for anything unusable, and the caller decides
    whether that is an error or just means "not named yet".
    """
    if not isinstance(value, str):
        return ""
    s = "".join(" " if c in _NAME_SPACE else ("" if c in _NAME_DROP else c)
                for c in value)
    return " ".join(s.split())[:24].strip(" -'.")


def _clean_backdrop(value):
    v = (value or "none")
    return v if v in BACKDROP_IDS else "none"


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
        # No synthetic calendar when a live .ics address is configured.
        mailbox_mod.ensure(
            self.mailbox, self.project_dir,
            seed_calendar=not icsfeed_mod.settings(self.cfg)["url"])
        self.vault = os.path.abspath(os.path.join(
            self.project_dir,
            (self.cfg.get("vault") or {}).get("dir") or "vault"))
        self.capture_dir = os.path.join(self.project_dir, "receipts")

        self.profile = profile_mod.load(self.project_dir)
        # Seeded with whatever accounts setup collected, so the GitHub records
        # say the participant's own handle rather than a placeholder. Safe to
        # run before onboarding: connectors() is empty then and the seed falls
        # back to its own defaults.
        vault_mod.ensure(self.vault, self.project_dir, self.connectors())

        # Last known state of the live calendar feed. Filled in by
        # icsfeed.refresh; "cold" until something asks for it.
        self.calendar = {"state": "cold"}

        # The always-on base agent. Idle until start() decides there is a
        # profile with a base policy to run under.
        self.basecamp = basecamp_mod.Basecamp(self)

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
                                       self.mailbox, self.vault)

    def tool_ctx(self, agent_id=None):
        """path_ctx plus the three things a tool needs to know about its caller.

        agentVault / agentData / agentId are NOT policy variables and never
        reach expand() - see the note in policy.path_context. They exist so a
        persona's record tools can reach its own folder without the model
        naming a root, and so an invitation can be stamped with the agent that
        produced it. Keeping them out of the variable table means lint() and
        compile_config() stay agent-agnostic: a policy file means the same
        thing no matter who is about to run under it."""
        ctx = self.path_ctx()
        if not agent_id:
            return ctx
        rec = agents_mod.get(agent_id)
        ctx["agentId"] = rec["id"]
        ctx["agentData"] = rec.get("dataFolder") or ""
        ctx["agentVault"] = (os.path.join(self.vault, rec["vault"])
                             if rec.get("vault") else "")
        return ctx

    # -- profile ----------------------------------------------------------

    def active_agent(self):
        p = self.profile or {}
        return p.get("activeAgent") or agents_mod.DEFAULT_ID

    def connectors(self):
        return (self.profile or {}).get("connectors") or {}

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
        # Lay down any vault folder that does not exist yet and seed it with
        # the handles just typed. Same never-overwrite rule as the policy
        # files above: somebody re-running setup to change a theme must not
        # lose the invitations their agents have already produced.
        vault_mod.ensure(self.vault, self.project_dir, self.connectors())
        # Start the session clock here, if nothing has started it yet. Mail
        # scheduled for "+6m" means six minutes after the room finished
        # setup, and this is the only moment that knows when that was.
        #
        # Establish, not reset: somebody who re-runs setup twenty minutes in
        # to change a theme must not have the remaining post pushed back by
        # twenty minutes. Rehearsing the whole session again is what
        # workshop\deliver.py --reset-clock is for.
        postman_mod.anchor(self.mailbox, self.profile)
        # Pull the real calendar now that setup is done. In the background:
        # the browser is about to navigate to the app, and a captive network
        # would otherwise hold this request open for the whole socket timeout.
        icsfeed_mod.refresh_async(self)
        # The base agent may have had no policy a moment ago. Now it does.
        self.basecamp.start()
        return self.profile, written

    def apply_preset(self, agent_id, preset_id):
        """Overwrite one agent's policy with a named preset. Unlike
        set_profile this is explicit - the participant clicked a preset in the
        Policy tab knowing it replaces what is there."""
        pol = agents_mod.preset(agent_id, preset_id)
        if pol is None:
            return None
        return self.save_policy(pol, agent_id)

    def host_info(self):
        """The processor name and installed memory, for the one line on the
        launch page that says which machine this is.

        Asked of Windows rather than written into config.json, because the
        entire point of that line is to show the person their own box. On a
        Ryzen AI machine this comes back as the real part number, which is
        the claim the workshop wants to make and the claim it should not be
        allowed to make on a box that is not one.
        """
        cached = getattr(self, "_host_info", None)
        if cached is not None:
            return cached

        info = {"cpu": None, "memoryGB": None, "arch": platform.machine() or None}
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            try:
                name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                info["cpu"] = " ".join(str(name).split()) or None
            finally:
                winreg.CloseKey(key)
        except Exception:
            pass

        try:
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            st = _MemStatus()
            st.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                # Round to the nearest 4 GB. The installed figure is what the
                # box was sold with; the exact byte count is a few hundred MB
                # short of it because firmware has already taken its cut, and
                # "127 GB" on a 128 GB machine reads like a fault.
                gb = st.ullTotalPhys / float(1024 ** 3)
                info["memoryGB"] = int(round(gb / 4.0) * 4) or int(round(gb))
        except Exception:
            pass

        self._host_info = info
        return info

    def workspace_count(self):
        """How many files sit in the workspace, for the launch page's fourth
        readiness row. Shallow and best-effort: this is a sentence on a status
        line, not an inventory, and it must not stall the poll."""
        try:
            n = 0
            for entry in os.scandir(self.workspace):
                if entry.is_file():
                    n += 1
                    if n >= 999:
                        break
            return n
        except OSError:
            return None

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

    def set_model(self, name):
        """Point the whole app at a different installed model, from the UI.

        Writes lemonade.model into config.json exactly as workshop\\models.py
        --pick does, then lets refresh_config pick it up on the next poll and
        warm it. Validated against what Lemonade actually serves, so the UI
        cannot write a name that will 404 at chat time."""
        h = self.lemonade.health()
        served = h.get("models") or []
        if name not in served:
            return {"ok": False, "error": "Lemonade is not serving '%s'." % name,
                    "models": served}
        cfg = _load_json(self.config_path)
        cfg.setdefault("lemonade", {})["model"] = name
        _save_json(self.config_path, cfg)
        # Force the reload path to fire even within the same poll tick.
        self._config_mtime = None
        self.refresh_config()
        return {"ok": True, "model": name}

    def set_agent_model(self, agent_id, name):
        """Give one agent its own model, or clear the override (name falsy).

        Stored in the profile, not config.json: it is a per-agent choice that
        belongs with the other per-agent choices (its critter, its preset), and
        the agent loop reads it through model_for() on every turn. This is the
        router demo - switching agents can switch which model Lemonade serves,
        with nothing changed but one field on one request."""
        if not agents_mod.get(agent_id):
            return {"ok": False, "error": "no such agent"}
        if name:
            served = (self.lemonade.health().get("models")) or []
            if name not in served:
                return {"ok": False,
                        "error": "Lemonade is not serving '%s'." % name}
        prof = dict(self.profile or {})
        models = dict(prof.get("agentModels") or {})
        if name:
            models[agent_id] = name
        else:
            models.pop(agent_id, None)
        prof["agentModels"] = models
        self.profile = profile_mod.save(self.project_dir, prof)
        return {"ok": True, "agentModels": self.profile.get("agentModels") or {}}

    def model_for(self, agent_id):
        """The model this agent should run on: its own override if set, else the
        global default. None means 'use the Lemonade client's configured model'
        so an agent with no override costs nothing extra."""
        models = (self.profile or {}).get("agentModels") or {}
        return models.get(agent_id) or None

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

    # -- setup ------------------------------------------------------------

    def setup(self):
        """The two answers the launch wizard collects, read back from disk.

        Read straight out of config.json rather than from a side file, so a
        hand edit is as good as a trip through the wizard and there is only
        one place to look when the name on screen is wrong.
        """
        agent = self.cfg.get("agent") or {}
        ui = self.cfg.get("ui") or {}
        name = _clean_name(agent.get("assistantName"))
        return {
            "assistantName": name or DEFAULT_ASSISTANT_NAME,
            "backdrop": _clean_backdrop(ui.get("backdrop")),
            # The resume signal. No name on disk means nobody has been through
            # the wizard on this machine, so it opens at the welcome; once a
            # name is saved it opens at the readiness checks instead, because
            # that is the only step worth repeating.
            "named": bool(name),
        }

    def assistant_name(self):
        return self.setup()["assistantName"]

    def save_setup(self, name=None, backdrop=None):
        """Write the wizard's answers into config.json.

        Read-modify-write of the whole file, not a targeted patch: config.json
        is hand-edited too, and the _note keys in it are real keys that have to
        survive the round trip. Only the two leaves we own are touched, so the
        lemonade subtree comes back byte-identical and reload_config() stays
        quiet - saving a name must not tear down the Lemonade client or throw
        away a warm model.
        """
        try:
            cfg = _load_json(self.config_path)
        except Exception:
            cfg = dict(self.cfg or {})

        if name is not None:
            cleaned = _clean_name(name)
            if not cleaned:
                raise ValueError("A name is needed - up to 24 characters, "
                                 "and not only punctuation.")
            cfg.setdefault("agent", {})["assistantName"] = cleaned
        if backdrop is not None:
            cfg.setdefault("ui", {})["backdrop"] = _clean_backdrop(backdrop)

        tmp = self.config_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
        os.replace(tmp, self.config_path)

        # Adopt the new copy here rather than letting the next poll find it.
        # Otherwise the mtime changes, reload_config() re-reads, finds the
        # lemonade subtree unchanged and returns False - correct, but it would
        # have re-read the file for nothing.
        self.cfg = cfg
        self._config_mtime = _mtime(self.config_path)
        return self.setup()

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

        # Last, because it spawns sandboxes and there is no point doing that
        # before we know whether this host can build one.
        self.basecamp.start()
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


def _save_json(path, obj):
    """Atomic write, so a half-written config.json is never read as truncated
    - it is read as 'not onboarded'-style garbage otherwise, and the model
    setting is exactly the thing somebody is changing when they are impatient."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None
