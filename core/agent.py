"""
core/agent.py - the loop.

The loop runs on the host. Only the tool calls go into a sandbox, and each
one gets a fresh one-shot. MXC has no long-running-daemon shape on Windows
ProcessContainer - the contained process has to exit within its timeout - so
"an always-on agent living inside the sandbox" is not a thing that exists.
What exists is this: a supervisor outside, re-entering a one-shot container
per tool call, with the policy re-authored every time.

The practical consequence, and the one to say out loud in the room: CastleKeep
contains what the agent *does*, not what the agent *is*.
"""

import json
import os
import re
import time

from . import agents as agents_mod
from . import policy as policy_mod
from . import tools as tools_mod

_TAG = re.compile(r"<[^>]+>")


def _plain(text):
    """PowerShell serialises its streams as CLIXML when stderr is redirected,
    so a refusal arrives wrapped in markup. The model does not need the markup,
    and the 400-character budget below is far too small to spend on it - the
    real message would be pushed off the end by the XML preamble."""
    s = str(text or "")
    if "CLIXML" not in s and "<Objs" not in s:
        return s
    s = _TAG.sub(" ", s.replace("#< CLIXML", ""))
    # PowerShell escapes its own newlines in the serialised form.
    s = s.replace("_x000D__x000A_", " ").replace("_x000A_", " ")
    return " ".join(s.split())


def _covered(path, grants):
    p = os.path.normcase(os.path.normpath(path))
    for g in grants:
        g = os.path.normcase(os.path.normpath(g))
        if p == g or p.startswith(g + os.sep):
            return True
    return False


def _grant_diagnosis(tool, arguments, pol, ctx):
    """Which grant was actually missing, in the policy's own words.

    Windows will not tell you. PowerShell reports a refused write to
    mailbox\\labels as "Access to the path 'C:\\Users' is denied", naming the
    first directory it could not traverse rather than the one you asked for.
    Handed that, a model confidently blames whichever path it can see in the
    error and sends the user to change a rule that was never the problem.

    This runs only after MXC has already refused. It explains the refusal; it
    does not make it."""
    if tool is None or tool.paths is None:
        return ""
    try:
        want = tool.paths(arguments or {}, ctx)
    except Exception:
        return ""

    p = policy_mod.normalise(pol)

    def grants(kind):
        out = []
        for raw in p["paths"].get(kind) or []:
            try:
                out.append(policy_mod.expand(raw, ctx))
            except policy_mod.PolicyError:
                continue
        return out

    write = grants("write")
    # A read-write grant implies read. compile_config drops the duplicate
    # readonly entry, so the readable set has to be the union here too.
    read = grants("read") + write

    missing = []
    for path in want.get("write") or []:
        if not _covered(path, write):
            missing.append(("write", path))
    for path in want.get("read") or []:
        if not _covered(path, read):
            missing.append(("read", path))
    if not missing:
        return ""

    lines = ["", "Which grant was missing:"]
    for kind, path in missing:
        lines.append("- No %s access to %s. The policy would need that path "
                     "added to paths.%s." % (kind, path, kind))
    lines.append("The policy currently grants write on: %s."
                 % (", ".join(write) or "nothing"))
    lines.append("Quote that exact path back to the user and tell them to add "
                 "it in the Policy tab. You already have the path - do not ask "
                 "them for it. Do NOT blame a path that is already granted: "
                 "the error text from Windows usually names a parent directory "
                 "rather than the path that was actually refused.")
    return "\n".join(lines)


def _fmt_result(run, tool_name, notes, diagnosis=""):
    """What the model sees after a tool call. Honest about refusals, because
    a model that thinks it got data will confabulate the rest of the turn."""
    outcome = run["outcome"]
    if outcome == "ok":
        body = (run.get("stdout") or "").strip()
        return body[:8000] if body else "(the command produced no output)"

    if outcome == "blocked":
        return (
            "REFUSED BY POLICY. The sandbox started, the command ran, and the "
            "security policy stopped it: %s. Detail: %s%s\n"
            "Tell the user this was blocked and which policy rule would need to "
            "change. Do not try the same path again."
            % (run.get("reason"), _plain(run.get("detail"))[:400], diagnosis)
        )

    if outcome == "refused-to-start":
        return (
            "THE SANDBOX WOULD NOT START. MXC refused to build a container for "
            "this policy rather than build a weaker one: %s%s\n"
            "This is a policy problem, not something you can route around. "
            "Report it to the user and stop."
            % (run.get("reason"),
               (" (field: %s)" % run["offendingField"]) if run.get("offendingField") else "")
        )

    tail = _plain((run.get("stderr") or "") + (run.get("stdout") or "")).strip()
    return "The command failed (exit %s). %s%s" % (
        run.get("exitCode"), tail[:1500], diagnosis)


class Agent:
    def __init__(self, app, agent_id=None):
        self.app = app              # core.app.App
        # Which subagent this is. Everything that used to be a module constant
        # - the prompt, the tool set, the policy file - now hangs off this.
        self.agent_id = agent_id or app.active_agent()
        self.record = agents_mod.get(self.agent_id)

    # -- one tool call ----------------------------------------------------

    def call_tool(self, name, arguments, emit):
        app = self.app
        t0 = time.time()

        # Re-read the policy from disk for THIS call. Not cached, not
        # inherited from the start of the turn. This is what makes an edit in
        # the Policy tab land on the very next tool call.
        pol = app.reload_policy(self.agent_id)
        gate = (pol.get("tools") or {})
        mine = {t.name: t for t in tools_mod.for_agent(self.agent_id)}
        tool = mine.get(name)

        if tool is None:
            emit({"type": "tool_result", "name": name, "outcome": "unknown-tool",
                  "text": "No such tool."})
            return "There is no tool called %r available to %s. Available: %s" % (
                name, self.record["label"], ", ".join(sorted(mine)))

        if not gate.get(name, not tool.danger):
            rec = {
                "id": "gate-%d" % (int(t0 * 1000) % 100000000),
                "label": name, "outcome": "host-gate",
                "kind": "host-gate", "command": None,
                "reason": "The tool '%s' is switched off in policy.json under "
                          "\"tools\". This gate is on the HOST - the request never "
                          "reached a sandbox, so MXC never saw it." % name,
                "startedAt": t0, "durationMs": 0, "arguments": arguments,
            }
            app.record_run(rec)
            emit({"type": "sandbox", "run": rec})
            emit({"type": "tool_result", "name": name, "outcome": "host-gate",
                  "text": rec["reason"]})
            return ("TOOL DISABLED. %s Tell the user they can switch it back on "
                    "in the Policy tab." % rec["reason"])

        try:
            command, tool = tools_mod.build_command(name, arguments, app.path_ctx())
        except Exception as e:
            return "Could not build that command: %s" % e

        cfg, notes = app.compile_for(pol, command)
        emit({"type": "tool_call", "name": name, "arguments": arguments,
              "command": command, "config": cfg, "notes": notes,
              "agent": self.agent_id})

        run = app.mxc.execute(cfg, label=name,
                              timeout=(pol.get("limits") or {}).get("timeoutMs", 30000)
                              / 1000.0 + 30)
        run["arguments"] = arguments
        run["notes"] = notes
        run["tool"] = name
        run["agent"] = self.agent_id
        app.record_run(run)
        emit({"type": "sandbox", "run": _public(run)})

        diagnosis = ""
        if run["outcome"] in ("blocked", "failed"):
            diagnosis = _grant_diagnosis(tool, arguments, pol, app.path_ctx())
            if diagnosis:
                run["missingGrants"] = diagnosis
        text = _fmt_result(run, name, notes, diagnosis)
        emit({"type": "tool_result", "name": name, "outcome": run["outcome"],
              "text": text[:4000]})
        return text

    # -- a whole turn -----------------------------------------------------

    def turn(self, user_text, history, emit):
        app = self.app
        pol = app.reload_policy(self.agent_id)
        schemas = tools_mod.schemas(pol, self.agent_id)

        system = agents_mod.system_prompt(self.agent_id, app.profile)
        messages = [{"role": "system",
                     "content": system + _policy_briefing(pol, app, self.agent_id)}]
        messages += history
        messages.append({"role": "user", "content": user_text})

        max_calls = (app.cfg.get("agent") or {}).get("maxToolCallsPerTurn", 8)
        used = 0
        final_text = []

        while True:
            assistant_text = []
            calls = []
            errored = False

            for ev in app.lemonade.chat(messages, tools=schemas or None, stream=True):
                kind = ev["type"]
                if kind == "token":
                    assistant_text.append(ev["text"])
                    emit({"type": "token", "text": ev["text"]})
                elif kind == "thinking":
                    emit({"type": "thinking", "text": ev["text"]})
                elif kind == "tool_calls":
                    calls = ev["calls"]
                elif kind == "notice":
                    emit({"type": "notice", "message": ev["message"]})
                elif kind == "error":
                    errored = True
                    emit({"type": "error", "message": ev["message"]})
                elif kind == "done":
                    pass

            text = "".join(assistant_text).strip()
            if errored:
                break
            if text:
                final_text.append(text)

            if not calls:
                break

            if used + len(calls) > max_calls:
                emit({"type": "notice",
                      "message": "Stopped after %d tool calls this turn "
                                 "(agent.maxToolCallsPerTurn in config.json)."
                                 % max_calls})
                break

            messages.append({
                "role": "assistant",
                "content": text or None,
                "tool_calls": [{"id": c["id"], "type": "function",
                                "function": {"name": c["name"],
                                             "arguments": json.dumps(c["arguments"])}}
                               for c in calls],
            })

            for c in calls:
                used += 1
                result = self.call_tool(c["name"], c["arguments"], emit)
                messages.append({"role": "tool", "tool_call_id": c["id"],
                                 "name": c["name"], "content": result})

            emit({"type": "turn_continue"})

        emit({"type": "done", "text": "\n\n".join(final_text)})
        return "\n\n".join(final_text)


def _public(run):
    """Trim a run record for the wire - the full config stays, it is the
    interesting part, but the raw streams get capped."""
    out = dict(run)
    out["stdout"] = (out.get("stdout") or "")[:6000]
    out["stderr"] = (out.get("stderr") or "")[:6000]
    return out


def _policy_briefing(pol, app, agent_id=None):
    """Tell the model what it can and cannot reach, in the model's own terms.
    This is not enforcement - MXC is enforcement - it just stops the model
    wasting turns on things that will certainly be refused."""
    p = policy_mod.normalise(pol)
    ctx = app.path_ctx()
    mine = {t.name for t in tools_mod.for_agent(agent_id)}

    def show(kind):
        vals = p["paths"].get(kind) or []
        try:
            return [policy_mod.expand(v, ctx) for v in vals]
        except Exception:
            return vals

    lines = [
        "\n\nThe sandbox policy in force right now:",
        "- Readable: %s" % (", ".join(show("read")) or "nothing"),
        "- Writable: %s" % (", ".join(show("write")) or "nothing"),
    ]
    if show("deny"):
        lines.append("- Explicitly denied: %s" % ", ".join(show("deny")))
    lines.append("- Outbound network: %s"
                 % (p["network"].get("outbound") or "deny"))
    lines.append("- Tool call timeout: %ss"
                 % int((p["limits"].get("timeoutMs") or 30000) / 1000))
    off = [n for n, t in (p.get("tools") or {}).items() if n in mine and not t]
    if off:
        lines.append("- Switched off entirely: %s" % ", ".join(sorted(off)))
    lines.append("Anything not listed as readable is not readable. Do not "
                 "guess at paths outside it.")
    return "\n".join(lines)
