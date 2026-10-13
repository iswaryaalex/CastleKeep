#!/usr/bin/env python3
"""
workshop/ask.py - drive one agent from the command line.

A rehearsal tool. It is the same HTTP endpoint the chat window uses, so what
you see here is exactly what a participant will see, minus the animation.

    python workshop\\ask.py base     "what came in that needs me today?"
    python workshop\\ask.py coding   "what needs me on GitHub?"
    python workshop\\ask.py health   "create an invite for my next appointment"

    python workshop\\ask.py --list                 which agents exist
    python workshop\\ask.py --tool base sync_vaults
    python workshop\\ask.py --tool base list_messages folder=private

Use it before the workshop to check that every question you plan to ask in the
room actually works on this machine with this model. A small model that fails
a tool call in front of forty people is recoverable; one that fails the FIRST
tool call is not.

The app has to be running. Stdlib only, like everything else here.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_PORT = 7701


def _stream(url, payload, show_tools=True):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    calls = 0
    try:
        resp = urllib.request.urlopen(req, timeout=900)
    except urllib.error.URLError as e:
        print("  Could not reach %s - is the app running?\n  %s" % (url, e))
        return 1
    with resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:])
            except ValueError:
                continue
            kind = ev.get("type")
            if kind == "tool_call" and show_tools:
                calls += 1
                print("  TOOL  %-16s %s"
                      % (ev["name"], json.dumps(ev.get("arguments") or {})[:90]))
            elif kind == "sandbox":
                run = ev.get("run") or {}
                mark = {"ok": "ok", "blocked": "BLOCKED BY POLICY",
                        "host-gate": "stopped on the host",
                        "refused-to-start": "SANDBOX REFUSED TO START"}
                print("        -> %s%s"
                      % (mark.get(run.get("outcome"), run.get("outcome")),
                         ("  (%s)" % run["reason"]) if run.get("reason") else ""))
            elif kind == "notice":
                print("  NOTE  %s" % ev.get("message", "")[:200])
            elif kind == "error":
                print("  ERROR %s" % ev.get("message", "")[:400])
            elif kind == "done":
                text = (ev.get("text") or "").strip()
                print("\n  ANSWER (%d tool call%s):\n" % (calls, "" if calls == 1 else "s"))
                for ln in (text or "(the model returned nothing)").splitlines():
                    print("    " + ln)
                print("")
    return 0


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("agent", nargs="?", help="agent id, e.g. base or health")
    ap.add_argument("message", nargs="?", help="what to ask it")
    ap.add_argument("extra", nargs="*", help="tool arguments as name=value")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--list", action="store_true", help="list the agents and exit")
    ap.add_argument("--tool", action="store_true",
                    help="run one tool directly instead of a chat turn")
    args = ap.parse_args()

    base = "http://127.0.0.1:%d" % args.port

    if args.list:
        try:
            with urllib.request.urlopen(base + "/api/profile", timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print("  Could not reach %s - is the app running?\n  %s" % (base, e))
            return 1
        print("")
        for a in data.get("agents") or []:
            if not a.get("enabled"):
                continue
            print("  %-16s %-11s %s" % (a["id"], a["role"], a["blurb"]))
            print("  %-16s %s" % ("", ", ".join(a["tools"])))
            for ex in a.get("examples") or []:
                print("  %-16s   \"%s\"" % ("", ex))
            print("")
        return 0

    if not args.agent:
        ap.print_help()
        return 2

    if args.tool:
        # python workshop\ask.py --tool base list_messages folder=private
        tool_name = args.message
        if not tool_name:
            print("  --tool needs a tool name.")
            return 2
        arguments = {}
        for pair in args.extra:
            k, _, v = pair.partition("=")
            arguments[k] = v
        print("\n  %s -> %s(%s)\n" % (args.agent, tool_name, json.dumps(arguments)))
        return _stream(base + "/api/tool",
                       {"agent": args.agent, "name": tool_name,
                        "arguments": arguments})

    if not args.message:
        print("  Give it something to ask.")
        return 2

    print("\n  %s <- %s\n" % (args.agent, args.message))
    return _stream(base + "/api/chat",
                   {"agent": args.agent, "message": args.message, "history": []})


if __name__ == "__main__":
    sys.exit(main())
