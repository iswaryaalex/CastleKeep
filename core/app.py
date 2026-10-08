"""
core/app.py - shared state. One of these per process.
"""

import json
import os
import threading
import time

from . import policy as policy_mod
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

        ws = (self.cfg.get("agent") or {}).get("workspace") or "workspace"
        self.workspace = os.path.abspath(os.path.join(self.project_dir, ws))
        os.makedirs(self.workspace, exist_ok=True)
        self.capture_dir = os.path.join(self.project_dir, "receipts")

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
        return policy_mod.path_context(self.project_dir, self.workspace)

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

    def reload_policy(self):
        """Read policy.json from disk if it changed. Called before every
        single tool call - the whole demo depends on an edit landing on the
        next call without a restart."""
        m = _mtime(self.policy_path)
        if m != self._policy_mtime:
            try:
                self.policy = policy_mod.load(self.policy_path)
                self._policy_mtime = m
            except Exception as e:
                self.note("warn", "policy.json could not be parsed (%s). Still "
                                  "using the last good copy." % e)
        return self.policy

    def save_policy(self, new_policy):
        policy_mod.save(self.policy_path, new_policy)
        self.policy = new_policy
        self._policy_mtime = _mtime(self.policy_path)
        return self.policy

    def compile_for(self, pol, command, cwd=None):
        cwd = cwd or (self.workspace if os.path.isdir(self.workspace) else None)
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


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None
