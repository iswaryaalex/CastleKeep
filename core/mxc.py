"""
core/mxc.py - the only place in CastleKeep that knows how to talk to MXC.

Everything here is driven by the wxc-exec command line contract, which is:

    wxc-exec.exe [CONFIG_PATH]
                 [--config <path>]            path to config JSON file
                 [--config-base64 <b64>]      base64-encoded JSON config
                 [--dry-run]                  parse and validate, then exit
                 [--probe]                    run the fallback detector, emit JSON
                 [--debug]                    debug/console output
                 [--experimental]             enable experimental backends
                 [--allow-testing-features]   testing-only features
                 [--log-file <path>]          diagnostic log (appends)
                 [--audit] [--audit-verbose]  permissive capture + policy authoring
                 [--delete --containername N] delete a container profile
                 [--force-reclaim]            tear down an orphaned sandbox VM
                 [-- <command...>]            override process.commandLine

CastleKeep uses --probe, --dry-run and --config-base64. It never uses --audit,
because --audit turns the restrictions OFF for the run, and a workshop about
containment should not quietly run uncontained.
"""

import base64
import json
import os
import platform
import re
import shutil
import subprocess
import time
import uuid

# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------

_EXE_BY_PLATFORM = {
    "Windows": "wxc-exec.exe",
    "Linux": "lxc-exec",
    "Darwin": "mxc-exec-mac",
}


def _arch_dir():
    m = platform.machine().lower()
    if m in ("amd64", "x86_64"):
        return "x64"
    if m in ("arm64", "aarch64"):
        return "arm64"
    return m


class BinaryNotFound(Exception):
    pass


def resolve_binary(cfg, project_dir):
    """Find the executor. Returns an absolute path, or raises BinaryNotFound
    with every place that was looked at, because a silent miss here is the
    single most annoying way for this project to fail."""
    exe_name = _EXE_BY_PLATFORM.get(platform.system(), "wxc-exec.exe")
    arch = _arch_dir()
    tried = []

    def ok(p):
        tried.append(p)
        return p if p and os.path.isfile(p) else None

    explicit = (cfg.get("mxc") or {}).get("exePath")
    if explicit:
        p = ok(os.path.abspath(os.path.join(project_dir, os.path.expandvars(explicit))))
        if p:
            return p

    roots = []
    bin_dir = (cfg.get("mxc") or {}).get("binDir")
    if bin_dir:
        roots.append(os.path.abspath(os.path.join(project_dir, os.path.expandvars(bin_dir))))
    if os.environ.get("MXC_BIN_DIR"):
        roots.append(os.path.abspath(os.environ["MXC_BIN_DIR"]))
    roots += [
        # The copy that travels with this folder. First in the fallback list on
        # purpose: a workshop machine that cloned CastleKeep and nothing else
        # should still find an executor, and "it worked on the laptop it was
        # built on" is not a property worth shipping.
        os.path.join(project_dir, "bin"),
        os.path.join(project_dir, "..", "node_modules", "@microsoft", "mxc-sdk", "bin"),
        os.path.join(project_dir, "node_modules", "@microsoft", "mxc-sdk", "bin"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\MXC\bin"),
    ]

    for root in roots:
        root = os.path.abspath(root)
        # <root>/<arch>/wxc-exec.exe is the documented layout; <root>/wxc-exec.exe
        # is what you get if you point straight at the arch folder.
        for p in (os.path.join(root, arch, exe_name), os.path.join(root, exe_name)):
            if ok(p):
                return p

    onpath = shutil.which(exe_name)
    if onpath:
        return onpath
    tried.append("PATH")

    raise BinaryNotFound(
        "Could not find %s. Looked in:\n  %s\n\n"
        "Fix it by setting mxc.binDir or mxc.exePath in config.json, or by setting "
        "the MXC_BIN_DIR environment variable to the folder that contains %s\\%s."
        % (exe_name, "\n  ".join(tried), arch, exe_name)
    )


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

#: Structured refusal kinds wxc-exec emits. Taken from the binary's own error
#: enum, not invented here.
REFUSAL_KINDS = {
    "malformed_json",
    "schema_violation",
    "missing_command",
    "unsupported_field_for_backend",
    "invalid_command_override",
    "identity_shape_invalid",
    "unsupported_containment",
    "unsupported_phase",
    "runner_unavailable",
}

_JSON_OBJ = re.compile(r"\{(?:[^{}]|\{[^{}]*\})*\}", re.S)

# Things the *contained process* says when the policy did its job. These are
# not MXC errors - they are the sandbox working.
_DENIED_INSIDE = [
    # Two shapes, and missing the second one is expensive. cmd.exe says
    # "Access is denied." PowerShell says "Access to the path 'C:\\x' is
    # denied." Matching only the first classified every PowerShell refusal as
    # a plain command failure - so a real containment event was reported to
    # the room as a broken tool, and the model was told "the command failed"
    # instead of "REFUSED BY POLICY, do not retry". That is the one mistake
    # this file cannot afford to make.
    (re.compile(r"access (?:is denied|to the path\b[^\n]{0,200}?\bis denied)", re.I),
     "Windows refused the access"),
    (re.compile(r"UnauthorizedAccessException|\bPermissionDenied\b", re.I),
     "Windows refused the access"),
    (re.compile(r"\bEPERM\b|\bEACCES\b", re.I), "permission denied"),
    (re.compile(r"file not found|cannot find the (file|path)", re.I),
     "path not visible from inside the sandbox"),
    (re.compile(r"the system cannot find the path specified", re.I),
     "path not visible from inside the sandbox"),
    (re.compile(r"unable to (connect|resolve)|could not resolve host|connection refused",
                re.I), "network blocked"),
    (re.compile(r"getaddrinfo|network is unreachable|timed out", re.I), "network blocked"),
]


class SandboxRun(dict):
    """A single one-shot sandbox invocation, as a plain dict so it can go
    straight out of the HTTP API."""

    @property
    def ok(self):
        return self["outcome"] == "ok"


def _classify(exit_code, stdout, stderr):
    """Work out what actually happened. Three distinct outcomes, and keeping
    them distinct is the difference between a demo that teaches something and
    a demo that just prints red text.

      refused-to-start : MXC would not build the sandbox at all (reject,
                         don't degrade). The policy asked for something this
                         host cannot enforce.
      blocked          : the sandbox was built, the command ran, and the
                         policy stopped it from touching something.
      ok / failed      : the command ran and succeeded, or failed on its own
                         merits.
    """
    blob = (stderr or "") + "\n" + (stdout or "")

    # 1. Did wxc-exec itself refuse? It emits a structured error object.
    for m in _JSON_OBJ.finditer(stderr or ""):
        try:
            obj = json.loads(m.group(0))
        except ValueError:
            continue
        flat = json.dumps(obj)
        kind = None
        for k in REFUSAL_KINDS:
            if k in flat:
                kind = k
                break
        if kind or "reason" in obj or "offending_field" in obj or "offendingField" in obj:
            return {
                "outcome": "refused-to-start",
                "kind": kind or "schema_violation",
                "reason": obj.get("reason") or obj.get("message") or flat,
                "offendingField": obj.get("offending_field") or obj.get("offendingField"),
                "backend": obj.get("backend"),
                "correlationId": obj.get("correlation_id") or obj.get("correlationId"),
            }

    # 2. Unstructured refusal. wxc-exec prints a prose message and exits
    #    non-zero before the child ever starts. These are the ones worth
    #    recognising because they are the common ones on a real box.
    prose = [
        (r"is not supported by (this|the selected|the configured)",
         "unsupported_field_for_backend"),
        (r"are not (yet )?supported on Windows", "unsupported_field_for_backend"),
        (r"is not supported by the AppContainer fallback", "unsupported_field_for_backend"),
        (r"requires (schema version|either|an?) ", "schema_violation"),
        (r"Invalid configuration at", "schema_violation"),
        (r"Invalid schema version", "schema_violation"),
        (r"backend[_ ]unavailable|runner_unavailable|not available on this platform",
         "runner_unavailable"),
        (r"requires experimental mode|requires the --", "schema_violation"),
        (r"cannot be combined with|conflicts with|mutually exclusive",
         "schema_violation"),
    ]
    if exit_code != 0:
        for pat, kind in prose:
            m = re.search(pat, stderr or "", re.I)
            if m:
                line = _best_line(stderr, m.start())
                return {
                    "outcome": "refused-to-start",
                    "kind": kind,
                    "reason": line,
                    "offendingField": _guess_field(line),
                    "backend": None,
                    "correlationId": None,
                }

    # 3. The command ran. Did the policy block it?
    if exit_code != 0:
        for pat, why in _DENIED_INSIDE:
            m = pat.search(blob)
            if m:
                return {
                    "outcome": "blocked",
                    "kind": "policy",
                    "reason": why,
                    "detail": _best_line(blob, m.start()),
                    "offendingField": None,
                }

    if exit_code == 0:
        return {"outcome": "ok", "kind": None, "reason": None}

    return {
        "outcome": "failed",
        "kind": None,
        "reason": _best_line(blob, 0) or ("exit code %s" % exit_code),
    }


def _best_line(text, pos):
    if not text:
        return ""
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end == -1:
        end = len(text)
    return text[start:end].strip()[:400]


_FIELD = re.compile(
    r"\b((?:filesystem|network|ui|process|processContainer|lifecycle|fallback|runtimeConfig)"
    r"(?:\.[A-Za-z]+)*)\b"
)


def _guess_field(line):
    m = _FIELD.search(line or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# The executor
# ---------------------------------------------------------------------------

class Mxc:
    def __init__(self, cfg, project_dir, on_run=None):
        self.cfg = cfg
        self.project_dir = project_dir
        self.on_run = on_run          # callback(SandboxRun) for the live feed
        self.exe = None
        self.exe_error = None
        self._probe_cache = None
        try:
            self.exe = resolve_binary(cfg, project_dir)
        except BinaryNotFound as e:
            self.exe_error = str(e)

    # -- availability ------------------------------------------------------

    @property
    def available(self):
        return self.exe is not None

    def version(self):
        if not self.exe:
            return None
        try:
            r = subprocess.run([self.exe, "--version"], capture_output=True,
                               text=True, timeout=20)
            return (r.stdout or r.stderr).strip().splitlines()[0]
        except Exception:
            return None

    # -- probe -------------------------------------------------------------

    def probe(self, refresh=False):
        """`wxc-exec --probe` runs the fallback detector and prints JSON.
        This is the only honest source of truth for what this host can
        enforce. Never assume a tier - the binary gets swapped."""
        if self._probe_cache is not None and not refresh:
            return self._probe_cache

        if not self.exe:
            self._probe_cache = {
                "available": False,
                "error": self.exe_error,
                "tier": None,
            }
            return self._probe_cache

        try:
            r = subprocess.run([self.exe, "--probe"], capture_output=True,
                               text=True, timeout=120)
        except Exception as e:
            self._probe_cache = {"available": False, "error": str(e), "tier": None}
            return self._probe_cache

        raw = (r.stdout or "").strip() or (r.stderr or "").strip()
        data = None
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
            except ValueError:
                data = None

        if data is None:
            self._probe_cache = {
                "available": False,
                "error": "--probe did not return JSON (exit %s)" % r.returncode,
                "raw": raw[:2000],
                "tier": None,
            }
            return self._probe_cache

        data["available"] = True
        data["exe"] = self.exe
        data["capabilities"] = derive_capabilities(data)
        self._probe_cache = data
        return data

    # -- running -----------------------------------------------------------

    def execute(self, mxc_config, label="", dry_run=False, timeout=None,
                experimental=False):
        """One one-shot sandbox. Returns a SandboxRun."""
        run_id = uuid.uuid4().hex[:8]
        started = time.time()

        base = {
            "id": run_id,
            "label": label,
            "startedAt": started,
            "dryRun": bool(dry_run),
            "config": mxc_config,
            "command": (mxc_config.get("process") or {}).get("commandLine"),
            "containment": mxc_config.get("containment"),
        }

        if not self.exe:
            rec = SandboxRun(base, outcome="refused-to-start", kind="runner_unavailable",
                             reason=self.exe_error, exitCode=None, stdout="",
                             stderr=self.exe_error or "", durationMs=0)
            self._emit(rec)
            return rec

        payload = json.dumps(mxc_config, separators=(",", ":"))
        b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")

        argv = [self.exe, "--config-base64", b64]
        if dry_run:
            argv.append("--dry-run")
        if (self.cfg.get("mxc") or {}).get("debug"):
            argv.append("--debug")
        if experimental:
            argv.append("--experimental")
        log_dir = (self.cfg.get("mxc") or {}).get("logDir")
        if log_dir:
            log_dir = os.path.abspath(os.path.join(self.project_dir, log_dir))
            os.makedirs(log_dir, exist_ok=True)
            argv += ["--log-file", os.path.join(log_dir, "mxc-%s.log" % run_id)]

        wall = timeout or (((mxc_config.get("process") or {}).get("timeout") or 30000)
                           / 1000.0 + 30)

        try:
            r = subprocess.run(argv, capture_output=True, text=True,
                               timeout=wall, errors="replace")
            code, out, err = r.returncode, r.stdout or "", r.stderr or ""
        except subprocess.TimeoutExpired:
            code, out, err = None, "", "wxc-exec did not return within %ds" % wall
        except Exception as e:
            code, out, err = None, "", "failed to launch wxc-exec: %s" % e

        cls = _classify(code if code is not None else -1, out, err)
        if dry_run and code == 0:
            cls = {"outcome": "ok", "kind": None, "reason": "config is valid for this host"}

        rec = SandboxRun(
            base,
            exitCode=code,
            stdout=out[-20000:],
            stderr=err[-20000:],
            durationMs=int((time.time() - started) * 1000),
            **cls
        )
        self._emit(rec)
        return rec

    def _emit(self, rec):
        if self.on_run:
            try:
                self.on_run(rec)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# What the probe means for the knobs in the UI
# ---------------------------------------------------------------------------

def derive_capabilities(probe):
    """Turn a probe result into a plain answer for each policy knob:
    can this host enforce it, yes or no, and if not, why not.

    These rules come from wxc-exec's own validation messages. The important
    one, and the one that surprises people: at the AppContainer tier
    `filesystem.deniedPaths` is rejected outright - the binary says
    "Paths are denied by default unless granted via readwritePaths or
    readonlyPaths." It does not quietly drop the field. It refuses the run.
    """
    tier = (probe or {}).get("tier") or ""
    p = (probe or {}).get("probes") or {}
    base = tier.startswith("basecontainer") or tier in ("psec", "t1")
    appc = tier.startswith("appcontainer")

    def cap(ok, why=""):
        return {"supported": bool(ok), "why": why}

    ui_caps = p.get("uiCapabilities") or {}
    any_ui = any(bool(v) for v in ui_caps.values()) if ui_caps else True

    return {
        "readPaths": cap(True),
        "writePaths": cap(True),
        "denyPaths": cap(
            base and p.get("baseContainerSupportsDenyPaths", False),
            "This host is on the %s tier. Denied paths are only enforceable by "
            "BaseContainer, and this binary reports baseContainerSupportsDenyPaths="
            "%s. Everything is denied by default anyway - narrow the read and write "
            "lists instead." % (tier or "unknown",
                                p.get("baseContainerSupportsDenyPaths", False)),
        ),
        "outboundToggle": cap(True),
        "perHostRules": cap(
            False,
            "network.allowedHosts / blockedHosts are not supported on Windows by this "
            "binary. Outbound is all or nothing, or goes through a proxy.",
        ),
        "hostLoopback": cap(
            base,
            "ingress.hostLoopback='allow' is rejected by the AppContainer fallback. "
            "This is exactly why CastleKeep keeps the model on the host: nothing "
            "inside the sandbox ever needs to reach 127.0.0.1.",
        ),
        "ui": cap(any_ui, "" if any_ui else "This host reports no UI restriction support."),
        "leastPrivilege": cap(
            base,
            "leastPrivilege is not representable in a PSEC profile, so asking for it "
            "forces the run down to an AppContainer tier.",
        ),
        "captureDenials": cap(
            base,
            "captureDenials needs the native BaseContainer learning-mode APIs, or an "
            "AppContainer runner built with the guarded-WPR capture fallback. On the "
            "%s tier it will usually be refused." % (tier or "unknown"),
        ),
        "daclMutation": cap(
            appc or probe.get("needsDaclAugmentation", False),
            "Only the AppContainer+DACL tier mutates ACEs on your real paths.",
        ),
        "_tier": tier,
        "_tierLabel": {
            "basecontainer": "BaseContainer (tier 1, kernel-enforced)",
            "appcontainer-bfs": "AppContainer + BFS (tier 2)",
            "appcontainer-dacl": "AppContainer + DACL (tier 3)",
        }.get(tier, tier or "unknown"),
    }
