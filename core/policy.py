"""
core/policy.py - turns the friendly policy.json into the MXCConfiguration
JSON that wxc-exec actually parses, and says out loud what it did.

Two rules this file exists to honour:

  1. Policy is immutable once a sandbox is provisioned. There is no reload.
     So we compile a fresh config for every single tool call, from whatever
     is on disk at that instant. That is why an edit in the Policy tab shows
     up on the very next tool call and never on the one already running.

  2. Reject, don't degrade. If this host cannot enforce something the policy
     asks for, we do not quietly drop it and carry on. We either send it and
     let MXC refuse the run, or we leave it out and put a loud note in the
     result. Which of the two is a setting, and the default is the noisy one.
"""

import json
import os
import re

SCHEMA_VERSION = "0.8.0-alpha"


class PolicyError(Exception):
    pass


# ---------------------------------------------------------------------------
# Loading, saving, variables
# ---------------------------------------------------------------------------

_VAR = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def path_context(project_dir, workspace_dir, mailbox_dir=None):
    env = os.environ
    return {
        "project": project_dir,
        "workspace": workspace_dir,
        # The triage subagent's whole world. Kept out of ${workspace} on
        # purpose: granting the workspace should not silently grant somebody's
        # mail, and the two want different read/write shapes anyway.
        "mailbox": mailbox_dir or os.path.join(project_dir, "mailbox"),
        "home": env.get("USERPROFILE") or os.path.expanduser("~"),
        "windir": env.get("WINDIR") or env.get("SystemRoot") or r"C:\Windows",
        "system32": os.path.join(env.get("WINDIR") or env.get("SystemRoot")
                                 or r"C:\Windows", "System32"),
        "temp": env.get("TEMP") or env.get("TMP") or r"C:\Windows\Temp",
        "programfiles": env.get("ProgramFiles") or r"C:\Program Files",
        "localappdata": env.get("LOCALAPPDATA") or "",
        "systemdrive": (env.get("SystemDrive") or "C:") + "\\",
    }


def expand(value, ctx):
    def sub(m):
        key = m.group(1).lower()
        if key not in ctx:
            raise PolicyError(
                "Unknown path variable ${%s}. Known ones: %s"
                % (m.group(1), ", ".join("${%s}" % k for k in sorted(ctx)))
            )
        return ctx[key]

    out = _VAR.sub(sub, value)
    out = os.path.expandvars(out)
    return os.path.normpath(out) if ("\\" in out or "/" in out) else out


def _strip_notes(obj):
    """Drop the _readme / _note keys so they never reach the wire."""
    if isinstance(obj, dict):
        return {k: _strip_notes(v) for k, v in obj.items()
                if not k.startswith("_")}
    if isinstance(obj, list):
        return [_strip_notes(v) for v in obj]
    return obj


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save(path, policy):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(policy, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


DEFAULTS = {
    "name": "policy",
    "containment": "processcontainer",
    "paths": {"read": [], "write": [], "deny": []},
    "network": {"outbound": "deny", "localNetwork": False},
    "ui": {"allowWindows": False, "clipboard": "none", "allowInputInjection": False},
    "limits": {"timeoutMs": 30000},
    "advanced": {
        "leastPrivilege": False,
        "learningMode": True,
        "captureDenials": False,
        "allowDaclMutation": True,
        "sendUnsupportedAnyway": False,
        "networkDialect": "auto",
    },
    "tools": {},
}


def normalise(policy):
    """Fill in missing sections so the rest of the code never has to guess."""
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in (policy or {}).items():
        if k.startswith("_"):
            out[k] = v
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Validation - things we can catch before the binary has to
# ---------------------------------------------------------------------------

def lint(policy, ctx, caps=None):
    """Returns a list of {level, field, message}. level is error | warn | info.
    An error means the run will certainly be refused; a warning means it
    probably will on this host."""
    out = []
    p = normalise(policy)

    def add(level, field, message):
        out.append({"level": level, "field": field, "message": message})

    for kind in ("read", "write", "deny"):
        for raw in p["paths"].get(kind) or []:
            try:
                full = expand(raw, ctx)
            except PolicyError as e:
                add("error", "paths.%s" % kind, str(e))
                continue
            if not os.path.isabs(full):
                add("error", "paths.%s" % kind,
                    "%s is not an absolute path. MXC only accepts absolute paths."
                    % raw)
            elif not os.path.exists(full):
                add("warn", "paths.%s" % kind,
                    "%s does not exist on this machine (resolves to %s). "
                    "The grant will be inert." % (raw, full))

    net = p["network"]
    if net.get("outbound") not in ("deny", "allow"):
        add("error", "network.outbound",
            "outbound must be 'deny' or 'allow'. Per-host rules are not supported "
            "on Windows by this binary.")
    if net.get("allowedHosts") or net.get("blockedHosts"):
        add("error", "network.allowedHosts",
            "network.allowedHosts / blockedHosts are not yet supported on Windows. "
            "wxc-exec rejects them at validation. Use outbound allow/deny.")

    if p["ui"].get("clipboard") not in ("none", "read", "write", "all"):
        add("error", "ui.clipboard", "clipboard must be none, read, write or all.")

    t = p["limits"].get("timeoutMs")
    if not isinstance(t, int) or t < 1000:
        add("error", "limits.timeoutMs", "timeoutMs must be an integer >= 1000.")

    if not (p["paths"].get("read") or p["paths"].get("write")):
        add("warn", "paths",
            "Nothing is granted at all. Every tool call will come back empty - "
            "which is a perfectly good thing to demonstrate once.")

    if caps:
        adv = p["advanced"]
        checks = [
            (p["paths"].get("deny"), "denyPaths", "paths.deny"),
            (adv.get("leastPrivilege"), "leastPrivilege", "advanced.leastPrivilege"),
            (adv.get("captureDenials"), "captureDenials", "advanced.captureDenials"),
            (net.get("localNetwork"), "hostLoopback", "network.localNetwork"),
        ]
        for requested, cap_key, field in checks:
            if requested and not caps.get(cap_key, {}).get("supported", True):
                add("warn", field, caps[cap_key].get("why", "Not supported on this host."))

        if net.get("outbound") == "deny" and net.get("localNetwork"):
            add("warn", "network.localNetwork",
                "Inbound allow combined with outbound deny is rejected by the "
                "AppContainer fallback, because privateNetworkClientServer is "
                "bidirectional. Expect a refusal on tier 3.")

    return out


# ---------------------------------------------------------------------------
# The compiler
# ---------------------------------------------------------------------------

def compile_config(policy, ctx, command, cwd=None, env=None, caps=None,
                   dialect="modern", capture_dir=None):
    """Build one MXCConfiguration. Returns (config, notes).

    `notes` records every decision that was not a straight pass-through, so
    the UI can show "you asked for X, here is what happened to X" instead of
    the config silently differing from the policy.
    """
    p = normalise(policy)
    notes = []
    caps = caps or {}
    adv = p["advanced"]
    send_anyway = bool(adv.get("sendUnsupportedAnyway"))

    def supported(key):
        c = caps.get(key)
        return True if c is None else bool(c.get("supported"))

    def unsupported_why(key):
        return (caps.get(key) or {}).get("why", "Not supported on this host.")

    def decide(key, field, requested):
        """Returns True if the field should go on the wire."""
        if not requested:
            return False
        if supported(key):
            return True
        if send_anyway:
            notes.append({
                "level": "info", "field": field,
                "message": "Sent anyway so you can see MXC refuse it. "
                           + unsupported_why(key),
            })
            return True
        notes.append({
            "level": "warn", "field": field,
            "message": "Left out of this run - this host cannot enforce it. "
                       + unsupported_why(key),
        })
        return False

    # -- filesystem -------------------------------------------------------
    def paths(kind):
        return [expand(x, ctx) for x in (p["paths"].get(kind) or [])]

    fs = {}
    ro, rw = paths("read"), paths("write")
    # A path granted read-write does not also need a read-only grant, and
    # sending both is a good way to get a confusing precedence question.
    ro = [x for x in ro if x.lower() not in {y.lower() for y in rw}]
    if ro:
        fs["readonlyPaths"] = ro
    if rw:
        fs["readwritePaths"] = rw
    deny = paths("deny")
    if decide("denyPaths", "paths.deny", bool(deny)):
        fs["deniedPaths"] = deny

    # -- network ----------------------------------------------------------
    outbound = p["network"].get("outbound", "deny")
    local = bool(p["network"].get("localNetwork"))

    if dialect == "none":
        net = {}
        # Always say something here. The quiet case is the dangerous one: the
        # policy asked for outbound deny, the block got dropped, and without
        # this note the screen would still read "Outbound: denied".
        if outbound == "deny":
            notes.append({
                "level": "error", "field": "network",
                "message": "You asked for outbound DENY, but this host rejected "
                           "every network dialect wxc-exec offers, so the run "
                           "carries no network policy at all. The sandbox is "
                           "most likely on the network. Do not claim the network "
                           "is contained until the Run tab shows otherwise.",
            })
        else:
            notes.append({
                "level": "warn", "field": "network",
                "message": "This host rejected every network dialect wxc-exec "
                           "offers, so the run carries no network policy at all. "
                           "Whatever the backend defaults to is what you get.",
            })
    elif dialect == "legacy":
        net = {
            "defaultPolicy": "allow" if outbound == "allow" else "block",
            "allowLocalNetwork": local,
        }
    else:
        net = {
            "egress": {"default": "allow" if outbound == "allow" else "deny"},
            "ingress": {"default": "allow" if local else "deny"},
        }
        if decide("hostLoopback", "network.localNetwork", local):
            net["ingress"]["hostLoopback"] = "allow"
        else:
            net["ingress"]["hostLoopback"] = "deny"

    # -- ui ---------------------------------------------------------------
    ui = {
        "disable": not bool(p["ui"].get("allowWindows")),
        "clipboard": p["ui"].get("clipboard", "none"),
        "injection": bool(p["ui"].get("allowInputInjection")),
    }

    # -- process ----------------------------------------------------------
    proc = {"commandLine": command, "timeout": int(p["limits"].get("timeoutMs", 30000))}
    if cwd:
        proc["cwd"] = cwd
    if env:
        proc["env"] = ["%s=%s" % (k, v) for k, v in env.items()]

    # -- processContainer -------------------------------------------------
    pc = {}
    if adv.get("learningMode"):
        pc["learningMode"] = True
    if decide("leastPrivilege", "advanced.leastPrivilege", adv.get("leastPrivilege")):
        pc["leastPrivilege"] = True
    if decide("captureDenials", "advanced.captureDenials", adv.get("captureDenials")):
        if not capture_dir:
            notes.append({"level": "warn", "field": "advanced.captureDenials",
                          "message": "No capture directory configured; skipped."})
        else:
            os.makedirs(capture_dir, exist_ok=True)
            pc["captureDenials"] = {
                "mode": "block",
                "outputPath": os.path.join(capture_dir, "denials.json"),
                "retainEtl": False,
            }

    cfg = {
        "version": SCHEMA_VERSION,
        "containment": p.get("containment", "processcontainer"),
        "process": proc,
        "ui": ui,
        "lifecycle": {"destroyOnExit": True},
    }
    if fs:
        cfg["filesystem"] = fs
    if net:
        cfg["network"] = net
    if pc:
        cfg["processContainer"] = pc
    if adv.get("allowDaclMutation") is not None:
        cfg["fallback"] = {"allowDaclMutation": bool(adv.get("allowDaclMutation"))}

    return cfg, notes


# ---------------------------------------------------------------------------
# Capability negotiation
# ---------------------------------------------------------------------------

def negotiate_dialect(mxc, policy, ctx, probe_command):
    """`--dry-run` parses and validates the config, then exits without
    spawning anything. That makes it free to ask the binary which network
    dialect it will accept on this host, instead of guessing and having
    every tool call fail.

    Returns ("modern" | "legacy" | "none", [trace...]).
    """
    trace = []
    for dialect in ("modern", "legacy"):
        cfg, _ = compile_config(policy, ctx, probe_command, dialect=dialect)
        run = mxc.execute(cfg, label="negotiate network dialect (%s)" % dialect,
                          dry_run=True, timeout=90)
        trace.append({
            "dialect": dialect,
            "outcome": run["outcome"],
            "reason": run.get("reason"),
        })
        if run["outcome"] == "ok":
            return dialect, trace

    # Last resort: no network block at all. Less expressive, but it runs.
    return "none", trace
