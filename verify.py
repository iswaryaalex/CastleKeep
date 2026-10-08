#!/usr/bin/env python3
"""
Answers one question: what, exactly, works on this machine?

    python verify.py                 everything
    python verify.py --no-network    skip the tests that need the internet
    python verify.py --quiet         only the summary

Writes verify-report.json and VERIFY-REPORT.md next to this file. Run it
before you tell a room that something is contained.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bootstrap                      # noqa: E402
bootstrap.purge(HERE)   # never verify stale .pyc - see bootstrap.py

from core.app import App              # noqa: E402
from core import verify as V          # noqa: E402

COLOUR = {
    "pass": "\033[32m PASS \033[0m",
    "fail": "\033[31m FAIL \033[0m",
    "warn": "\033[33m WARN \033[0m",
    "skip": "\033[90m skip \033[0m",
}
PLAIN = {"pass": " PASS ", "fail": " FAIL ", "warn": " WARN ", "skip": " skip "}

HEADINGS = {
    "inspect": "What the host says about itself",
    "validate": "What the binary will accept  (--dry-run, nothing spawned)",
    "live": "What actually happened when a sandbox ran",
}


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-colour", action="store_true")
    args = ap.parse_args()

    # Windows Terminal handles ANSI; the old conhost often does not.
    plain = args.no_colour or (os.name == "nt"
                               and not os.environ.get("WT_SESSION"))
    marks = PLAIN if plain else COLOUR

    app = App(HERE)
    app.probe = app.mxc.probe()
    app.caps = app.probe.get("capabilities") or {}

    print("\nCastleKeep - verifying this machine\n")
    seen_kind = None
    report = None

    for ev in V.run_all(app, include_network=not args.no_network):
        if ev["type"] == "begin":
            print("  executor  %s" % (ev.get("exe") or "not found"))
            print("")
            continue
        if ev["type"] == "report":
            report = ev
            continue
        if ev["type"] != "step":
            continue
        if ev.get("kind") != seen_kind:
            seen_kind = ev.get("kind")
            print("\n  %s" % HEADINGS.get(seen_kind, seen_kind))
            print("  " + "-" * 62)
        if args.quiet and ev["status"] in ("pass", "skip"):
            continue
        print("  %s %s" % (marks.get(ev["status"], ev["status"]), ev["title"]))
        detail = (ev.get("detail") or "").strip()
        if detail and ev["status"] != "pass":
            for line in _wrap(detail, 66):
                print("         %s" % line)

    print("")
    if not report:
        print("  Verification did not complete.")
        return 2

    c = report["counts"]
    print("  %d passed, %d warnings, %d failed, %d skipped"
          % (c.get("pass", 0), c.get("warn", 0), c.get("fail", 0), c.get("skip", 0)))
    print("  Tier      %s" % (report.get("tier") or "unknown"))
    print("  Dialect   %s" % report.get("dialect"))
    if report.get("savedMarkdown"):
        print("  Report    %s" % report["savedMarkdown"])
    print("")

    fails = [s for s in report["steps"] if s["status"] == "fail"]
    if fails:
        print("  Until these pass, do not describe this setup as contained:")
        for s in fails:
            print("    - %s" % s["title"])
        print("")
        return 1
    return 0


def _wrap(text, width):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(line)
    return out


if __name__ == "__main__":
    sys.exit(main())
