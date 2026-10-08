"""
core/verify.py - "what exactly works on this box".

Nothing in CastleKeep claims a containment tier, a backend, or an enforced
rule unless this file proved it on the machine in front of you. The probe
output can be stale, binaries get swapped, and the documentation contradicts
itself in places. So: ask the binary, then ask it again by actually running
something and watching it fail.

Three kinds of check:
  * inspect  - no sandbox, just ask (binary present, probe, Lemonade up)
  * validate - `--dry-run`, which parses and validates then exits. Free.
  * live     - really spawn a sandbox and look at what came back. The only
               checks that prove anything.

The negative tests matter more than the positive ones. "The agent read the
file" proves plumbing. "The agent could not read the file, and here is the
refusal" proves containment.
"""

import json
import os
import time

from . import policy as policy_mod
from . import tools as tools_mod

BAIT_DIR = ".verify"
BAIT_NAME = "not-granted.txt"
BAIT_TEXT = ("CastleKeep verification bait. If the agent can read this line, "
             "the filesystem policy is NOT being enforced.\n")


def _under(child, parent):
    """Is `child` inside `parent`? Case-insensitive, as Windows is."""
    try:
        c = os.path.normcase(os.path.abspath(child))
        p = os.path.normcase(os.path.abspath(parent))
        return c == p or c.startswith(p.rstrip("\\/") + os.sep)
    except Exception:
        return False


def _granted_paths(app):
    pol = app.reload_policy()
    ctx = app.path_ctx() if hasattr(app, "path_ctx") else {}
    out = []
    for kind in ("read", "write"):
        for raw in (pol.get("paths") or {}).get(kind) or []:
            try:
                out.append(policy_mod.expand(raw, ctx))
            except Exception:
                pass
    return out


def _pick_bait_dir(app):
    """Somewhere outside every granted path. Returns (dir, file, problem)."""
    granted = _granted_paths(app)
    candidates = [
        os.path.join(os.environ.get("TEMP") or os.environ.get("TMP") or
                     os.path.join(os.path.expanduser("~"), "AppData", "Local",
                                  "Temp"),
                     "castlekeep-bait"),
        os.path.join(os.environ.get("PUBLIC") or r"C:\Users\Public",
                     "castlekeep-bait"),
        os.path.join(app.project_dir, BAIT_DIR),
    ]
    for d in candidates:
        if any(_under(d, g) for g in granted):
            continue
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            continue
        return d, os.path.join(d, BAIT_NAME), None
    return None, None, (
        "Every location this check knows about is inside a granted path, so "
        "there is nowhere to put a file the sandbox should not be able to "
        "read. Granted right now: %s. Narrow paths.read before trusting any "
        "claim of containment." % (", ".join(granted) or "nothing"))


def _step(sid, title, status, detail="", evidence=None, kind="live"):
    return {"type": "step", "id": sid, "title": title, "status": status,
            "detail": detail, "evidence": evidence, "kind": kind,
            "at": time.time()}


def run_all(app, include_network=True):
    """Generator of SSE-shaped events. Ends with a {"type":"report"} event."""
    results = []

    def emit(ev):
        if ev.get("type") == "step":
            results.append(ev)
        return ev

    yield {"type": "begin", "at": time.time(),
           "project": app.project_dir, "exe": app.mxc.exe}

    # ---- inspect --------------------------------------------------------

    if not app.mxc.available:
        yield emit(_step("binary", "Find wxc-exec", "fail", app.mxc.exe_error,
                         kind="inspect"))
        yield _report(app, results)
        return

    ver = app.mxc.version()
    yield emit(_step("binary", "Find wxc-exec", "pass",
                     "%s%s" % (app.mxc.exe, (" (%s)" % ver) if ver else ""),
                     kind="inspect"))

    probe = app.mxc.probe(refresh=True)
    app.probe = probe
    app.caps = probe.get("capabilities") or {}
    if not probe.get("available"):
        yield emit(_step("probe", "Ask the host what it can enforce", "fail",
                         probe.get("error"), probe.get("raw"), kind="inspect"))
        yield _report(app, results)
        return

    caps = app.caps
    yield emit(_step("probe", "Ask the host what it can enforce", "pass",
                     "Tier: %s" % caps.get("_tierLabel"),
                     probe, kind="inspect"))

    for key, label in (("denyPaths", "Explicit denied paths"),
                       ("leastPrivilege", "Least privilege"),
                       ("captureDenials", "Denial receipts (captureDenials)"),
                       ("hostLoopback", "Inbound host loopback"),
                       ("perHostRules", "Per-host network rules"),
                       ("ui", "UI restrictions")):
        c = caps.get(key) or {}
        yield emit(_step("cap:" + key, label,
                         "pass" if c.get("supported") else "warn",
                         c.get("why") or "Supported on this host.", kind="inspect"))

    # ---- validate -------------------------------------------------------

    ctx = app.path_ctx()
    ver_cmd = tools_mod.shell_cmd("ver")

    dialect, trace = policy_mod.negotiate_dialect(app.mxc, app.policy, ctx, ver_cmd)
    app.dialect = dialect
    yield emit(_step("dialect", "Which network dialect does this host accept",
                     "pass" if dialect != "none" else "fail",
                     "Using the '%s' dialect." % dialect, trace, kind="validate"))

    for name, mutate, note in _policy_variants():
        pol = mutate(json.loads(json.dumps(app.policy)))
        try:
            cfg, _ = policy_mod.compile_config(
                pol, ctx, ver_cmd, dialect=dialect, caps=None,
                capture_dir=app.capture_dir)
        except policy_mod.PolicyError as e:
            yield emit(_step("dry:" + name, note, "fail", str(e), kind="validate"))
            continue
        run = app.mxc.execute(cfg, label="dry-run: " + name, dry_run=True)
        app.record_run(run)
        ok = run["outcome"] == "ok"
        yield emit(_step("dry:" + name, note, "pass" if ok else "warn",
                         run.get("reason") or "Accepted.",
                         {"config": cfg, "stderr": run.get("stderr", "")[:1200]},
                         kind="validate"))

    # ---- live -----------------------------------------------------------

    # The bait file has to live somewhere the policy does NOT grant, or the
    # negative test is not a test at all.
    #
    # This went wrong once and it is worth recording why. The bait used to be
    # written to <project>\.verify\, and the day someone added ${project} to
    # paths.read the test started reporting "THIS SHOULD HAVE BEEN REFUSED AND
    # WAS NOT" - a containment failure - when the truth was that the bait was
    # sitting inside a granted directory and the sandbox was behaving perfectly.
    # A negative test that can be silently invalidated by an unrelated policy
    # edit is worse than no test, because it cries wolf about the one thing you
    # most need to believe.
    #
    # So: pick a location that is outside every granted path, and if no such
    # location can be found, say that instead of pretending to test.
    bait_dir, bait, bait_problem = _pick_bait_dir(app)
    if bait:
        with open(bait, "w", encoding="utf-8") as f:
            f.write(BAIT_TEXT)

    granted = os.path.join(app.workspace, "verify-granted.txt")
    with open(granted, "w", encoding="utf-8") as f:
        f.write("CastleKeep verification. Reading this from inside the sandbox "
                "is expected - the workspace is granted.\n")

    def live(sid, title, command, expect, detail_ok="", pol=None):
        """expect is 'ok' or 'denied'. Returns the run."""
        p = pol or app.reload_policy()
        # The cwd has to be somewhere this policy grants. Hardcoding the
        # workspace works only while every policy happens to grant it; a
        # sandbox launched with an ungranted cwd dies at CreateProcessW and
        # reports it as the command being refused.
        cfg, _ = policy_mod.compile_config(
            p, ctx, command, cwd=app.working_dir(p), dialect=app.dialect,
            caps=app.caps, capture_dir=app.capture_dir)
        run = app.mxc.execute(cfg, label=title)
        app.record_run(run)
        got_ok = run["outcome"] == "ok"
        if expect == "ok":
            status = "pass" if got_ok else "fail"
            why = detail_ok if got_ok else (run.get("reason") or
                                            (run.get("stderr") or "")[:300])
        else:
            status = "pass" if not got_ok else "fail"
            why = ((run.get("reason") or "refused") if not got_ok else
                   "THIS SHOULD HAVE BEEN REFUSED AND WAS NOT. Do not claim "
                   "containment until this passes.")
        return run, _step(sid, title, status, why,
                          {"command": command,
                           "outcome": run["outcome"],
                           "exitCode": run.get("exitCode"),
                           "stdout": (run.get("stdout") or "")[:800],
                           "stderr": (run.get("stderr") or "")[:800]})

    run, ev = live("live:cmd", "cmd.exe runs inside a sandbox",
                   tools_mod.shell_cmd("ver"), "ok",
                   "cmd.exe started and exited cleanly.")
    yield emit(ev)
    cmd_works = ev["status"] == "pass"

    run, ev = live("live:pwsh", "PowerShell runs inside a sandbox",
                   tools_mod.shell_ps("Write-Output 'castlekeep-ok'"), "ok",
                   "PowerShell started. Tools that need structured output will work.")
    yield emit(ev)
    ps_works = ev["status"] == "pass"
    if not ps_works:
        yield emit(_step("live:pwsh:note", "PowerShell fallback", "warn",
                         "read_file, write_file, device_info, disk_space and "
                         "list_processes all need PowerShell. If it will not "
                         "start, grant read access to "
                         "${windir}\\System32\\WindowsPowerShell and to "
                         "${windir}\\Microsoft.NET, and try again."))

    if bait_problem:
        yield emit(_step("live:bait", "Somewhere to put a file the agent "
                                      "must not read", "fail", bait_problem))

    if ps_works and bait:
        run, ev = live("live:read-granted", "Read a file the policy grants",
                       tools_mod._b_read_file({"path": granted}), "ok",
                       "The granted path is readable, so grants are taking effect.")
        yield emit(ev)

        run, ev = live("live:write-granted", "Write inside the workspace",
                       tools_mod._b_write_file(
                           {"path": os.path.join(app.workspace, "verify-write.txt"),
                            "content": "written from inside the sandbox\n"}), "ok",
                       "The workspace is writable.")
        yield emit(ev)

        run, ev = live("live:read-denied",
                       "Refuse a file the policy does NOT grant",
                       tools_mod._b_read_file({"path": bait}), "denied")
        leaked = BAIT_TEXT.split(".")[0] in (run.get("stdout") or "")
        if leaked:
            ev["status"] = "fail"
            ev["detail"] = ("The bait file's contents came back. The filesystem "
                            "policy is not being enforced on this host.")
        yield emit(ev)

        run, ev = live("live:write-denied",
                       "Refuse a write the policy does NOT grant",
                       tools_mod._b_write_file(
                           {"path": os.path.join(bait_dir, "should-not-exist.txt"),
                            "content": "x"}), "denied")
        if os.path.exists(os.path.join(bait_dir, "should-not-exist.txt")):
            ev["status"] = "fail"
            ev["detail"] = "The file was created. Write policy is not enforced."
        yield emit(ev)
    elif cmd_works and bait:
        # PowerShell is down, so fall back to cmd's `type`. Same question,
        # cruder instrument: if the bait text comes back, the grant list is
        # not being enforced.
        run, ev = live("live:read-denied",
                       "Refuse a file the policy does NOT grant",
                       tools_mod.shell_cmd("type %s" % tools_mod._q(bait)), "denied")
        if BAIT_TEXT.split(".")[0] in (run.get("stdout") or ""):
            ev["status"] = "fail"
            ev["detail"] = ("The bait file's contents came back from %s. The "
                            "filesystem policy is not being enforced on this "
                            "host." % bait)
        yield emit(ev)
        ev["evidence"] = dict(ev.get("evidence") or {}, baitPath=bait)

    # UI policy
    run, ev = live("live:ui", "UI restrictions do not break a console process",
                   tools_mod.shell_cmd("echo ui-ok"), "ok",
                   "The UI lockdown applied without stopping normal work.")
    yield emit(ev)

    # Timeout
    slow = json.loads(json.dumps(app.reload_policy()))
    slow.setdefault("limits", {})["timeoutMs"] = 3000
    run, ev = live("live:timeout", "The timeout is enforced",
                   tools_mod.shell_cmd("ping -n 20 127.0.0.1 >nul"), "denied",
                   pol=slow)
    ev["title"] = "The timeout is enforced"
    ev["detail"] = ("Killed after about %sms, as configured."
                    % run.get("durationMs") if ev["status"] == "pass"
                    else "A 20-second command finished under a 3-second timeout. "
                         "process.timeout is not being applied.")
    yield emit(ev)

    # Network
    if include_network:
        deny = json.loads(json.dumps(app.reload_policy()))
        deny.setdefault("network", {})["outbound"] = "deny"
        run, ev = live("live:net-deny", "Outbound 'deny' really blocks the network",
                       tools_mod._b_fetch_url({"url": "http://example.com"}),
                       "denied", pol=deny)
        if ev["status"] == "fail" and "<html" in (run.get("stdout") or "").lower():
            ev["detail"] = ("A page came back with outbound set to deny. The "
                            "network policy is not being enforced on this host.")
        yield emit(ev)

        allow = json.loads(json.dumps(app.reload_policy()))
        allow.setdefault("network", {})["outbound"] = "allow"
        run, ev = live("live:net-allow", "Outbound 'allow' lets traffic through",
                       tools_mod._b_fetch_url({"url": "http://example.com"}),
                       "ok", "The toggle works in both directions.", pol=allow)
        if ev["status"] == "fail":
            ev["status"] = "warn"
            ev["detail"] += ("  (This can also just mean the machine has no "
                             "internet right now.)")
        yield emit(ev)

        # The one that matters for the architecture: loopback from inside.
        run, ev = live("live:loopback",
                       "A sandboxed process cannot reach Lemonade on loopback",
                       tools_mod._b_fetch_url(
                           {"url": app.lemonade.base + "/api/v1/models"}),
                       "denied", pol=allow)
        ev["detail"] = (
            "Confirmed - which is exactly why the model stays on the host and "
            "only tool calls go inside."
            if ev["status"] == "pass" else
            "Loopback got through. Not a problem, but it means the usual "
            "AppContainer loopback restriction is not in play here.")
        if ev["status"] == "fail":
            ev["status"] = "warn"
        yield emit(ev)

    # ---- tool catalogue -------------------------------------------------

    sample = {
        "list_files": {"path": app.workspace},
        "read_file": {"path": granted, "maxLines": 5},
        "write_file": {"path": os.path.join(app.workspace, "verify-tool.txt"),
                       "content": "ok\n"},
        "move_file": None,
        "device_info": {},
        "disk_space": {},
        "list_processes": {"top": 3},
        "fetch_url": None,
        "run_command": None,
        # The triage tools read and write the mailbox, which the root
        # policy.json does not grant, so they run under the triage policy
        # instead. Skipping them with "covered by the checks above" would be
        # a lie: nothing above touches ${mailbox}.
        "list_messages": {},
        "read_message": {"id": "2026-10-06-northwind-invoice"},
        "search_mail": {"query": "invoice"},
        "list_events": {},
        "find_free_slot": {},
        "draft_reply": {"subject": "verify", "body": "verify\n"},
        "draft_invite": {"title": "verify", "date": "2026-10-09", "start": "09:00"},
        "archive_message": None,
        "label_message": None,
    }

    # Why a tool was skipped, where "covered above" would not be true.
    skip_why = {
        "move_file":
            "Cannot work on this tier at all: a read-write grant carries "
            "create and write but not DELETE, so move is refused even inside "
            "one granted folder. Not a policy anybody chose.",
        "archive_message":
            "Needs a write grant on ${mailbox}\\archive, which the default "
            "triage policy deliberately withholds. That refusal is the demo - "
            "asserting 'ok' here would make this report contradict the "
            "workshop. Grant it in the Policy tab and it succeeds.",
        "label_message":
            "Needs a write grant on ${mailbox}\\labels, which the default "
            "triage policy deliberately withholds. Same reason as "
            "archive_message.",
    }
    has_triage = os.path.isfile(app.policy_path_for("triage"))
    triage_pol = app.reload_policy("triage") if has_triage else None
    for t in tools_mod.CATALOGUE:
        args = sample.get(t.name)
        if args is None:
            yield emit(_step("tool:" + t.name, "Tool: %s" % t.name, "skip",
                             skip_why.get(t.name, "Covered by the checks above.")))
            continue
        if t.agent == "triage" and not has_triage:
            yield emit(_step("tool:" + t.name, "Tool: %s" % t.name, "skip",
                             "No policies\\triage.json yet - run through setup "
                             "in the app first, then re-run this."))
            continue
        pol = triage_pol if t.agent == "triage" else None
        run, ev = live("tool:" + t.name, "Tool: %s" % t.name,
                       t.build(args, ctx), "ok", "Returned usable output.",
                       pol=pol)
        if ev["status"] == "fail":
            ev["status"] = "warn"
            ev["detail"] += ("  This tool will report a refusal to the model "
                             "rather than data.")
        yield emit(ev)

    # ---- Lemonade -------------------------------------------------------

    h = app.lemonade.health()
    yield emit(_step("lemonade", "Lemonade Server is up",
                     "pass" if h.get("reachable") else "fail",
                     h.get("note") or ("%s, %d model(s)"
                                       % (h.get("routePrefix"), len(h.get("models") or []))),
                     h, kind="inspect"))

    if h.get("reachable"):
        # A fail, not a warn. "Lemonade is up" and "Lemonade is serving the
        # model we named" are different claims, and letting the second one
        # pass as a warning is how a preflight comes back green on a setup
        # where the agent cannot answer a single message.
        yield emit(_step("lemonade:model", "Lemonade is serving the configured model",
                         "pass" if h.get("modelPresent") else "fail",
                         h.get("note") or app.lemonade.model,
                         h.get("models"), kind="inspect"))

        if h.get("modelPresent"):
            w = app.lemonade.warmup()
            yield emit(_step(
                "lemonade:warm", "The model loads and answers",
                "pass" if w.get("ok") else "fail",
                ("Warm in %.1fs. Startup does this too, so the first message "
                 "in the chat window will not stall." % (w["ms"] / 1000.0))
                if w.get("ok") else w.get("error"), kind="inspect"))

            native, detail = _probe_tool_calling(app)
            yield emit(_step("lemonade:tools", "Does the backend accept native tool calls",
                             "pass" if native else "warn", detail, kind="inspect"))

    yield _report(app, results)


def _policy_variants():
    def base(p):
        return p

    def with_deny(p):
        p.setdefault("paths", {})["deny"] = [r"${windir}\System32\drivers\etc"]
        return p

    def with_lp(p):
        p.setdefault("advanced", {})["leastPrivilege"] = True
        return p

    def with_capture(p):
        p.setdefault("advanced", {})["captureDenials"] = True
        return p

    def net_allow(p):
        p.setdefault("network", {})["outbound"] = "allow"
        return p

    def local_net(p):
        p.setdefault("network", {})["localNetwork"] = True
        return p

    def ui_open(p):
        p.setdefault("ui", {})["allowWindows"] = True
        p["ui"]["clipboard"] = "all"
        return p

    return [
        ("base", base, "The policy you have now validates"),
        ("deny", with_deny, "A config carrying filesystem.deniedPaths"),
        ("leastprivilege", with_lp, "A config asking for leastPrivilege"),
        ("capture", with_capture, "A config asking for denial receipts"),
        ("netallow", net_allow, "A config allowing outbound traffic"),
        ("localnet", local_net, "A config allowing inbound local network"),
        ("uiopen", ui_open, "A config relaxing the UI lockdown"),
    ]


def _probe_tool_calling(app):
    """Ask Lemonade for one tiny completion with a tools array, and see
    whether it survives the wire. Separate from whether the model is any good
    at using them."""
    probe_tools = [{
        "type": "function",
        "function": {"name": "ping", "description": "Reply with pong.",
                     "parameters": {"type": "object", "properties": {}, "required": []}},
    }]
    msgs = [{"role": "user", "content": "Call the ping tool."}]
    try:
        saw_error, saw_calls, saw_text = None, False, False
        for ev in app.lemonade.chat(msgs, tools=probe_tools, stream=True):
            if ev["type"] == "error":
                saw_error = ev["message"]
            elif ev["type"] == "tool_calls":
                saw_calls = True
            elif ev["type"] == "token":
                saw_text = True
        if saw_error:
            return False, "Native tool calls failed: %s  Prompted mode will be used." % saw_error[:300]
        if saw_calls:
            return True, "The backend returned a native tool_calls response."
        return False, ("The request was accepted but the model answered in prose "
                       "instead of calling the tool. CastleKeep will fall back to "
                       "prompted tool calls, which works with any backend.")
    except Exception as e:
        return False, "Native tool calls failed: %s" % e


def _report(app, results):
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    report = {
        "type": "report",
        "at": time.time(),
        "host": os.environ.get("COMPUTERNAME") or "",
        "exe": app.mxc.exe,
        "tier": (app.caps or {}).get("_tierLabel"),
        "dialect": app.dialect,
        "counts": counts,
        "steps": results,
        "probe": app.probe,
    }
    try:
        out = os.path.join(app.project_dir, "verify-report.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        report["savedTo"] = out
        md = os.path.join(app.project_dir, "VERIFY-REPORT.md")
        with open(md, "w", encoding="utf-8") as f:
            f.write(_markdown(report))
        report["savedMarkdown"] = md
    except Exception as e:
        report["saveError"] = str(e)
    return report


_ICON = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skip": "skip",
         "running": "...."}


def _markdown(report):
    lines = [
        "# What works on this machine",
        "",
        "Generated by CastleKeep `verify.py` on %s."
        % time.strftime("%Y-%m-%d %H:%M", time.localtime(report["at"])),
        "",
        "Host: `%s`  " % (report.get("host") or "unknown"),
        "Executor: `%s`  " % report.get("exe"),
        "Containment tier: **%s**  " % (report.get("tier") or "unknown"),
        "Network dialect: **%s**" % report.get("dialect"),
        "",
        "Totals: " + ", ".join("%s %s" % (v, k)
                               for k, v in sorted(report["counts"].items())),
        "",
    ]
    for kind, title in (("inspect", "What the host says about itself"),
                        ("validate", "What the binary will accept (dry-run only)"),
                        ("live", "What actually happened when a sandbox ran")):
        rows = [s for s in report["steps"] if s.get("kind") == kind]
        if not rows:
            continue
        lines += ["## %s" % title, ""]
        for s in rows:
            lines.append("- **%s** %s - %s"
                         % (_ICON.get(s["status"], s["status"]), s["title"],
                            (s.get("detail") or "").replace("\n", " ")))
        lines.append("")
    fails = [s for s in report["steps"] if s["status"] == "fail"]
    if fails:
        lines += ["## Do not claim containment until these pass", ""]
        for s in fails:
            lines.append("- %s - %s" % (s["title"], s.get("detail") or ""))
        lines.append("")
    return "\n".join(lines)
