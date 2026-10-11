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

SYSTEM = """You are {name}, one of the agents inside CastleKeep. Your job is \
{task}.

{persona}

How you work:
- You run entirely on this machine. The model is served locally by Lemonade. \
Nothing the person says goes to the internet.
- You have tools. Every tool call runs inside a fresh, throwaway sandbox with \
a security policy the person controls. Each agent here gets a different one, \
and yours is set out below. You do not control it and you cannot work around \
it.
- The other agents are separate conversations. You cannot see what they have \
been asked and they cannot see this. If something the person wants is outside \
your boundary, name the agent that has it and let them switch.
- If a tool comes back refused, say so plainly and say which rule stopped it. \
Do not retry the same thing. Do not pretend you got the data. If the person \
wants that access, tell them which knob in the Policy tab to change.

How you answer:
- Short. A sentence or two of plain prose, then the finding.
- Give real numbers when you have them. Never invent one.
- When you spot something worth fixing, say what you would do and ask before \
doing it.
"""

# There is deliberately no handover text here. Switching agent in the UI swaps
# the whole conversation rather than carrying one across, so a model is never
# handed a transcript produced under a boundary that is not its own. The
# history that arrives with a turn is always that agent's own history.


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
    def __init__(self, app, agent=None):
        self.app = app              # core.app.App
        self.requested = agent
        p = app.profile(agent)
        # The id, not the object. Profiles.reload() hands back a new Profile
        # whenever the file moves, so anything held across a turn goes stale
        # exactly when it matters: the tool call after the person saved an
        # edit.
        self.name = p.name if p is not None else None
        self.title = p.title if p is not None else "the agent"

    def profile(self):
        """Re-fetched per call, never cached."""
        return self.app.reload_profiles().get(self.name) if self.name else None

    def policy(self):
        """This agent's own policy, re-read from disk for THIS call. Not
        cached, not inherited from the start of the turn. An edit in the
        Policy tab lands on the very next tool call, and lands only on the
        agent whose file was edited.

        With no profiles on disk at all we fall back to policy.json, so a
        stripped-down copy of this app with the profiles folder deleted still
        runs as the single-agent version it used to be.
        """
        p = self.profile()
        return p.policy if p is not None else self.app.reload_policy()

    def display_name(self):
        """The launch wizard names one agent, the dragon. Everyone else goes
        by their job title, because a room full of pet names is harder to
        follow, not friendlier."""
        return self.app.agent_label(self.profile())

    # -- one tool call ----------------------------------------------------

    def call_tool(self, name, arguments, emit):
        app = self.app
        t0 = time.time()

        pol = self.policy()
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
                "agent": self.name,
                "label": name, "outcome": "host-gate",
                "kind": "host-gate", "command": None,
                "reason": "The tool '%s' is switched off under \"tools\" in %s. "
                          "This gate is on the HOST - the request never reached "
                          "a sandbox, so MXC never saw it." % (name, self._file()),
                "startedAt": t0, "durationMs": 0, "arguments": arguments,
            }
            app.record_run(rec)
            emit({"type": "sandbox", "run": rec})
            emit({"type": "tool_result", "name": name, "outcome": "host-gate",
                  "text": rec["reason"]})
            return ("TOOL DISABLED. %s This is not a containment result and you "
                    "should not describe it as one. Tell the user they can switch "
                    "it back on in the Policy tab." % rec["reason"])

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
        # Which agent's boundary this ran under. The Run tab lists every
        # sandbox this process has spawned, and with four agents in play a row
        # that does not say whose it was cannot be read at all.
        run["agent"] = self.name
        app.record_run(run)
        emit({"type": "sandbox", "run": _public(run)})

        text = _fmt_result(run, name, notes)
        emit({"type": "tool_result", "name": name, "outcome": run["outcome"],
              "text": text[:4000]})
        return text

    def _file(self):
        return "profiles\\%s.json" % self.name if self.name else "policy.json"

    # -- the prompt -------------------------------------------------------

    def system_prompt(self, pol=None):
        """Who this agent is, what it is for, what it can reach, and who to
        hand over to. Built per turn, from the file on disk, so editing a
        persona is the same kind of edit as editing a path grant."""
        pol = self.policy() if pol is None else pol
        p = self.profile()
        # .replace rather than .format, because the prompt above is edited
        # often and one stray brace in an example would turn a text edit into
        # a KeyError at chat time.
        out = SYSTEM.replace("{name}", self.display_name())
        out = out.replace("{task}", (p.task.lower() if p else
                                     "helping with this Windows machine"))
        out = out.replace("{persona}", (p.persona if p else "").strip())
        return out + _policy_briefing(pol, self.app) + _roster(self.app, self.name)

    # -- a whole turn -----------------------------------------------------

    def turn(self, user_text, history, emit):
        app = self.app
        pol = self.policy()
        schemas = tools_mod.schemas(pol)

        max_hist = (app.cfg.get("agent") or {}).get("maxHistoryMessages", 12)
        if len(history) > max_hist:
            history = history[-max_hist:]

        # history is this agent's own and nobody else's. The UI keeps a
        # separate thread per agent, so there is never a stretch of transcript
        # here that was produced under a different policy.
        messages = [{"role": "system", "content": self.system_prompt(pol)}]
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
                elif kind == "perf":
                    emit({"type": "perf", "ttftMs": ev["ttftMs"]})
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
        "\n\nToday's date: %s" % time.strftime("%d %B %Y"),
        "The sandbox policy in force right now:",
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


def _roster(app, me):
    """The other agents and what each one can reach.

    Without this the model knows only its own walls, so the best it can manage
    when asked for something outside them is "I cannot do that" - which is
    true and useless. With it, a refusal comes with somewhere to go, and the
    person learns the shape of the four boxes by being sent around them.
    """
    others = [p for p in app.profiles.all() if p.name != me]
    if not others:
        return ""
    lines = ["", "", "The person can switch to these agents in the bar at the "
                   "top. You cannot call them and you cannot see their "
                   "conversations. Send the person to one by name when what "
                   "they want is clearly its job:"]
    for p in others:
        lines.append("- %s. %s Can reach: %s, %s."
                     % (app.agent_label(p), p.tagline, p.boundary["files"],
                        p.boundary["network"]))
    return "\n".join(lines)
