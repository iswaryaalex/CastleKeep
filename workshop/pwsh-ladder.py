#!/usr/bin/env python3
"""
Why will PowerShell not start inside the sandbox?

cmd.exe runs fine, PowerShell dies with STATUS_DLL_INIT_FAILED (0xC0000142),
and five of the nine tools need PowerShell. The binary's error text blames the
UI lockdown and tells you to set ui.allowWindows. That may be right. It may
also be a missing read grant - PowerShell loads a great deal more than cmd
does, from Microsoft.NET, from the assembly cache, from WinSxS - and a DLL
that cannot be read fails to initialise in exactly this way.

Guessing between those is not useful. This runs the ladder: same trivial
PowerShell command every time, one variable changed per rung, and prints the
first rung that works.

    python workshop\\pwsh-ladder.py

It spawns real sandboxes. Nothing here is a dry run.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

from core.app import App                 # noqa: E402
from core import policy as policy_mod    # noqa: E402
from core import tools as tools_mod      # noqa: E402

WIN = os.environ.get("WINDIR") or r"C:\Windows"

# Each rung: (label, extra read grants, allow_windows). The point of ordering
# them this way is that each rung adds exactly one idea to the one above it,
# so whichever rung first passes names the cause.
LADDER = [
    ("baseline - System32 only, UI locked down",
     [], False),

    ("the binary's own suggestion: allow UI",
     [], True),

    ("+ .NET and the assembly cache",
     [os.path.join(WIN, "Microsoft.NET"), os.path.join(WIN, "assembly")], False),

    ("+ .NET, assembly cache, WinSxS",
     [os.path.join(WIN, "Microsoft.NET"), os.path.join(WIN, "assembly"),
      os.path.join(WIN, "WinSxS")], False),

    ("all of C:\\Windows, UI still locked down",
     [WIN], False),

    ("all of C:\\Windows, UI allowed",
     [WIN], True),

    ("the C:\\ root grant, UI allowed",
     ["C:\\"], True),
]

SCRIPT = "Write-Output 'castlekeep-pwsh-ok'"


def main():
    app = App(PROJECT)
    app.start()

    if not app.mxc.available:
        print("\n  wxc-exec is not available: %s\n" % app.mxc.exe_error)
        return 2

    base = app.reload_policy()
    ctx = app.path_ctx()
    command = tools_mod.shell_ps(SCRIPT)

    print("\nPowerShell ladder - %s\n" % (app.probe or {}).get("tier", "unknown tier"))

    winner = None
    for label, extra, allow_ui in LADDER:
        pol = json.loads(json.dumps(base))
        pol.setdefault("paths", {})
        pol["paths"]["read"] = list(pol["paths"].get("read") or []) + extra
        pol["paths"]["deny"] = []
        pol.setdefault("ui", {})["allowWindows"] = allow_ui

        cfg, _notes = policy_mod.compile_config(
            pol, ctx, command, caps=app.caps, dialect=app.dialect)
        run = app.mxc.execute(cfg, label="pwsh-ladder", timeout=60)

        ok = (run["outcome"] == "ok"
              and "castlekeep-pwsh-ok" in (run.get("stdout") or ""))
        print("  %s  %s" % ("PASS" if ok else "fail", label))
        if not ok:
            why = (run.get("reason") or run.get("stderr") or "").strip()
            if why:
                print("        %s" % why.replace("\n", " ")[:150])
        if ok:
            winner = (label, extra, allow_ui)
            break

    print("")
    if not winner:
        print("  Nothing on the ladder worked. PowerShell is not usable inside")
        print("  a sandbox on this host. That is a real finding, not a defeat:")
        print("  run the workshop on cmd.exe tools only (list_files, fetch_url,")
        print("  run_command) and say plainly that the rest need a shell this")
        print("  backend will not start.")
        return 1

    label, extra, allow_ui = winner
    print("  First rung that works: %s" % label)
    print("")
    print("  Put this in policy.json:")
    if extra:
        print("    paths.read  += %s" % json.dumps(extra))
    if allow_ui:
        print("    ui.allowWindows = true")
        print("")
        print("  Note what allowWindows costs you. It compiles to ui.disable =")
        print("  false, which lets the sandboxed process talk to the desktop.")
        print("  If this is the rung that fixed it, say so in the room rather")
        print("  than quietly shipping a weaker policy than the one on screen.")
    if extra == ["C:\\"]:
        print("")
        print("  A C:\\ root grant is read access to the whole drive. It will")
        print("  make PowerShell start and it will also make most of the")
        print("  refusals in the workshop stop happening. Do not demo with it.")
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
