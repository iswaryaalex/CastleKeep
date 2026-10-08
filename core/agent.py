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
import time

from . import policy as policy_mod
from . import tools as tools_mod

SYSTEM = """You are {name}, the agent inside CastleKeep. The person in front of \
you chose that name for you, so answer to it. You help them understand and fix \
their own Windows device.

How you work:
- You run entirely on this machine. The model is served locally by Lemonade. \
Nothing the person says goes to the internet.
- You have tools. Every tool call runs inside a fresh, throwaway sandbox with \
a security policy the person controls. You do not control that policy and you \
cannot work around it.
- If a tool comes back refused, say so plainly and say which rule stopped it. \
Do not retry the same thing. Do not pretend you got the data. If the person \
wants that access, tell them which knob in the Policy tab to change.

How you answer:
- Short. A sentence or two of plain prose, then the finding.
- Give real numbers when you have them. Never invent one.
- When you spot something worth fixing, say what you would do and ask before \
doing it.
"""


def _fmt_result(run, tool_name, notes):
    """What the model sees after a tool call. Honest about refusals, because
    a model that thinks it got data will confabulate the rest of the turn."""
    outcome = run["outcome"]
    if outcome == "ok":
        body = (run.get("stdout") or "").strip()
        return body[:8000] if body else "(the command produced no output)"

    if outcome == "blocked":
        return (
            "REFUSED BY POLICY. The sandbox started, the command ran, and the "
            "security policy stopped it: %s. Detail: %s\n"
            "Tell the user this was blocked and which policy rule would need to "
            "change. Do not try the same path again."
            % (run.get("reason"), (run.get("detail") or "")[:400])
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

    tail = ((run.get("stderr") or "") + (run.get("stdout") or "")).strip()
    return "The command failed (exit %s). %s" % (run.get("exitCode"), tail[:1500])


class Agent:
    def __init__(self, app):
        self.app = app              # core.app.App

    # -- one tool call ----------------------------------------------------

    def call_tool(self, name, arguments, emit):
        app = self.app
        t0 = time.time()

        # Re-read the policy from disk for THIS call. Not cached, not
        # inherited from the start of the turn. This is what makes an edit in
        # the Policy tab land on the very next tool call.
        pol = app.reload_policy()
        gate = (pol.get("tools") or {})
        tool = tools_mod.BY_NAME.get(name)

        if tool is None:
            emit({"type": "tool_result", "name": name, "outcome": "unknown-tool",
                  "text": "No such tool."})
            return "There is no tool called %r. Available: %s" % (
                name, ", ".join(sorted(tools_mod.BY_NAME)))

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
            command, tool = tools_mod.build_command(name, arguments)
        except Exception as e:
            return "Could not build that command: %s" % e

        cfg, notes = app.compile_for(pol, command)
        emit({"type": "tool_call", "name": name, "arguments": arguments,
              "command": command, "config": cfg, "notes": notes})

        run = app.mxc.execute(cfg, label=name,
                              timeout=(pol.get("limits") or {}).get("timeoutMs", 30000)
                              / 1000.0 + 30)
        run["arguments"] = arguments
        run["notes"] = notes
        run["tool"] = name
        app.record_run(run)
        emit({"type": "sandbox", "run": _public(run)})

        text = _fmt_result(run, name, notes)
        emit({"type": "tool_result", "name": name, "outcome": run["outcome"],
              "text": text[:4000]})
        return text

    # -- a whole turn -----------------------------------------------------

    def turn(self, user_text, history, emit):
        app = self.app
        pol = app.reload_policy()
        schemas = tools_mod.schemas(pol)

        # .replace rather than .format, because the prompt below it is edited
        # often and one stray brace in an example would turn a text edit into
        # a KeyError at chat time.
        system = SYSTEM.replace("{name}", app.assistant_name())
        messages = [{"role": "system", "content": system + _policy_briefing(pol, app)}]
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


def _policy_briefing(pol, app):
    """Tell the model what it can and cannot reach, in the model's own terms.
    This is not enforcement - MXC is enforcement - it just stops the model
    wasting turns on things that will certainly be refused."""
    p = policy_mod.normalise(pol)
    ctx = app.path_ctx()

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
    off = [n for n, t in (p.get("tools") or {}).items()
           if n in tools_mod.BY_NAME and not t]
    if off:
        lines.append("- Switched off entirely: %s" % ", ".join(sorted(off)))
    lines.append("Anything not listed as readable is not readable. Do not "
                 "guess at paths outside it.")
    return "\n".join(lines)
