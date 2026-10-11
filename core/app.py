"""
core/app.py - shared state. One of these per process.
"""

import json
import os
import platform
import threading
import time

from . import policy as policy_mod
from . import profiles as profiles_mod
from . import tools as tools_mod
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

        # policy.json is the host-wide default. Nothing the agents do reads
        # it: every agent brings its own, out of profiles\. What still uses
        # this one is the machinery that is not any agent's - the Run tab's
        # dry run, the dialect negotiation at startup, and verify.py - which
        # need a policy to compile and must not borrow one agent's boundary
        # to make a claim about the host.
        self.policy = policy_mod.load(self.policy_path)
        self._policy_mtime = _mtime(self.policy_path)

        self.profiles_dir = os.path.join(self.project_dir, "profiles")
        self.profiles = profiles_mod.Profiles(self.profiles_dir)

        ws = (self.cfg.get("agent") or {}).get("workspace") or "workspace"
        self.workspace = os.path.abspath(os.path.join(self.project_dir, ws))
        os.makedirs(self.workspace, exist_ok=True)
        self.capture_dir = os.path.join(self.project_dir, "receipts")

        self.events_dir = os.path.join(self.project_dir, "agent-events")
        os.makedirs(self.events_dir, exist_ok=True)

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

    def events_dir_for(self, agent_name):
        """Absolute path to the event folder owned by this agent."""
        return os.path.join(self.events_dir, agent_name)

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

    # -- agents -----------------------------------------------------------

    def reload_profiles(self):
        """Re-stat profiles\\ and re-read whatever moved. Called before every
        tool call, for the same reason reload_policy is: an edit to an agent's
        profile has to land on that agent's next call, and only on that
        agent's."""
        return self.profiles.reload()

    def profile(self, agent=None):
        """The agent named, or the first one. None only if the folder is
        empty, which the startup notes will already have complained about."""
        return self.profiles.resolve(agent)

    def policy_for(self, agent=None):
        """Which policy a request compiles under.

        Pass an agent id and you get that agent's profile. Pass nothing and
        you get policy.json, which is the host's own default and belongs to
        the Run tab and verify rather than to anybody in the bar. Keeping the
        two apart is what lets the Run tab make a claim about this machine
        without that claim quietly being Finance's boundary.
        """
        if not agent:
            return self.reload_policy()
        p = self.reload_profiles().get(agent)
        if p is None:
            return self.reload_policy()
        return p.policy

    def agent_label(self, p):
        """What to call an agent on screen and in the other agents' prompts.

        One function so there is one answer. The dragon answers to the name
        from the launch wizard, so the bar, the transcript, the roster every
        other agent is given and the Mission panel all have to use that name
        and not "Diagnostics", or the person is told to switch to an agent
        that is not in the bar under that label.
        """
        if p is None:
            return "the agent"
        return self.assistant_name() if p.named else p.title

    def agent_summaries(self):
        """The bar, the Mission panel and the comparison card, in one list,
        each entry carrying the agent's whole policy body."""
        out = []
        notes = profiles_mod.audit(self.profiles)
        for p in self.profiles.all():
            d = p.display()
            d["label"] = self.agent_label(p)
            d["notes"] = [n for n in notes if n["profile"] == p.name]
            # The policy body travels with the summary. Four small dicts, and
            # the alternative is the Mission panel describing one agent's
            # boundary from a second request that can arrive after the bar has
            # already been redrawn for a different one.
            d["policy"] = p.policy
            out.append(d)
        return out

    def profile_notes(self):
        """The audit, including the entries that belong to no single agent."""
        return profiles_mod.audit(self.reload_profiles())

    # -- startup ----------------------------------------------------------

    def start(self):
        # Pick up any config.json edit made since this process booted. Rescan
        # used to re-probe MXC and re-check Lemonade while still asking about
        # whatever model name was read at import time, which made the one
        # button labelled "re-examine this machine" unable to fix the single
        # most common setup mistake.
        self.reload_config()

        self.reload_profiles()

        # Create per-agent event folders so agents always have a place to write.
        for p in self.profiles.all():
            os.makedirs(os.path.join(self.events_dir, p.name), exist_ok=True)

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

    def recent_runs(self, limit=60, agent=None):
        with self.lock:
            rows = self.runs
            if agent:
                rows = [r for r in rows if r.get("agent") == agent]
            return [_slim(r) for r in rows[-limit:]][::-1]

    def refusals(self, limit=40, agent=None):
        with self.lock:
            bad = [r for r in self.runs
                   if r.get("outcome") in ("blocked", "refused-to-start", "host-gate")]
            if agent:
                bad = [r for r in bad if r.get("agent") == agent]
            return [_slim(r) for r in bad[-limit:]][::-1]


def _slim(r):
    keep = ("seq", "id", "agent", "tool", "label", "outcome", "kind", "reason",
            "detail", "offendingField", "command", "arguments", "durationMs",
            "exitCode", "startedAt", "dryRun", "containment", "notes")
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
