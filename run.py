#!/usr/bin/env python3
"""
CastleKeep - start here.

    python run.py              start the app and open the browser
    python run.py --no-browser start the app, do not open a browser
    python run.py --port 7777  use a different port
    python run.py --check      print the host report and exit

Python 3.9+. No packages to install - this is stdlib only on purpose, so the
whole thing survives a conference wifi network and a locked-down laptop.
"""

import argparse
import os
import sys
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


import bootstrap                              # noqa: E402
bootstrap.purge(HERE)   # never import stale .pyc - see bootstrap.py

from core.app import App                      # noqa: E402
from core.server import make_server           # noqa: E402

BANNER = r"""
   /\_/\      CastleKeep
  ( o.o )     a local agent that can only do what you let it
   > ^ <
"""


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="print the host report and exit")
    # --no-model used to exist to bypass a hard exit when Lemonade was not
    # serving the configured model. The launch screen reports that case and
    # offers a retry, so there is nothing left to bypass.
    args = ap.parse_args()

    print(BANNER)
    app = App(HERE)
    print("  project    %s" % app.project_dir)
    print("  workspace  %s" % app.workspace)
    print("  policy     %s" % app.policy_path)
    print("  model      %s   (from config.json, read just now)"
          % (app.cfg.get("lemonade") or {}).get("model"))
    print("")
    print("  Checking what this machine can enforce...")
    app.start()

    width = max(len(n["level"]) for n in app.startup_notes) if app.startup_notes else 5
    for n in app.startup_notes:
        print("  %-*s  %s" % (width, n["level"], n["message"]))
    print("")

    if args.check:
        return 0 if not any(n["level"] == "error" for n in app.startup_notes) else 1

    # The model is not optional, but refusing to start is no longer the way to
    # say so: the launch screen checks Lemonade itself, shows exactly what is
    # wrong, and has a Re-check button. Exiting here would leave the person
    # staring at a terminal instead of at the screen built to explain this.
    w = app.warmup_state()
    if w.get("state") in ("no-model", "unreachable"):
        print("  Lemonade: %s" % w.get("error"))
        if w.get("suggestions"):
            print("")
            print("  It is serving these similar names:")
            for m in w["suggestions"]:
                print("    %s" % m)
        print("")
        print("    python workshop\\models.py            list what is served")
        print("    python workshop\\models.py --pick X   wire X into config.json")
        print("")
        print("  Starting anyway. The launch screen will show this, and the")
        print("  policy and sandbox tabs work without a model. Fix it and press")
        print("  Re-check - no restart needed.")
        print("")

    port = args.port or (app.cfg.get("ui") or {}).get("port", 7701)
    ui_dir = os.path.join(HERE, "ui")
    try:
        httpd = make_server(app, ui_dir, port)
    except OSError as e:
        print("  Could not bind 127.0.0.1:%d - %s" % (port, e))
        print("  Try:  python run.py --port %d" % (port + 1))
        return 1

    url = "http://127.0.0.1:%d/" % port
    print("  Phase 1 walkthrough %sphase1" % url)
    print("  Launch your App     %s" % url)
    print("  Personal Assistant  %sapp" % url)
    print("  Ctrl-C to stop.")
    print("")

    # The warm-up is already running in the background. Report it here rather
    # than silently, because on a 35B MoE it is the longest thing that happens
    # at startup and a line of output is cheaper than a confused user.
    if app.warmup_state().get("state") == "warming":
        print("  Warming %s" % app.lemonade.model)
        print("  Loading the weights now, so the first message in the chat")
        print("  window does not have to wait for them.")
        print("")

    if not args.no_browser and (app.cfg.get("ui") or {}).get("openBrowser", True):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
