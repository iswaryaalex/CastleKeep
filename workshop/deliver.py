#!/usr/bin/env python3
"""
workshop/deliver.py - the presenter's postbox.

Mail that arrives during the session lives in mailbox\\scheduled\\ until its
`releaseAt` comes round. Most of it lands on a timer and needs nothing from
you. This is for the rest: the message that should land on a cue, and the
rehearsal you do the night before.

    python workshop\\deliver.py                 what is still to come, and when
    python workshop\\deliver.py --now           deliver the next one, now
    python workshop\\deliver.py --now <id>      deliver that one, now
    python workshop\\deliver.py --reset-clock   start the session clock again

Run it in a second terminal while the app is up. Delivery is host-side - see
the header of core/postman.py for why that is the honest arrangement and not
a shortcut.

The app has to be running. Stdlib only, like everything else here.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_PORT = 7701


def _call(base, path, payload=None):
    url = base + path
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data, {"Content-Type": "application/json"},
        method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.URLError as e:
        print("  Could not reach %s - is the app running?\n  %s" % (url, e))
        return None


def _when(item):
    if item.get("onCue"):
        return "on cue"
    secs = item.get("dueIn")
    if secs is None:
        return "unknown"
    if secs <= 0:
        return "due now"
    if secs < 90:
        return "%ds" % secs
    return "%dm" % round(secs / 60.0)


def show(base):
    state = _call(base, "/api/basecamp")
    if state is None:
        return 1
    post = state.get("post") or []
    print("")
    if not post:
        print("  The sack is empty. Everything has been delivered.")
        print("  python workshop\\deliver.py --reset-clock  starts the session again,")
        print("  but it will not un-deliver anything. Delete mailbox\\ for a clean run.")
        print("")
        return 0
    print("  %d still to come:\n" % len(post))
    for item in post:
        print("    %-9s %-26s %s" % (_when(item), item["id"], item["subject"][:52]))
    print("")
    print("  python workshop\\deliver.py --now            delivers the first of those")
    print("  python workshop\\deliver.py --now <id>       delivers one by name")
    print("")
    return 0


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--now", nargs="?", const="", default=None, metavar="ID",
                    help="deliver the next scheduled message, or one by id")
    ap.add_argument("--reset-clock", action="store_true",
                    help="start the session clock again from now")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()
    base = "http://127.0.0.1:%d" % args.port

    if args.reset_clock:
        got = _call(base, "/api/mailbox/reset-clock", {})
        if got is None:
            return 1
        print("\n  Session clock restarted. Timed mail is due from now.\n")
        return show(base)

    if args.now is None:
        return show(base)

    got = _call(base, "/api/mailbox/deliver", {"id": args.now} if args.now else {})
    if got is None:
        return 1
    if not got.get("delivered"):
        print("\n  Nothing delivered.%s\n"
              % (" No message with that id is waiting." if args.now else
                 " The sack is empty."))
        return 1
    m = got["message"]
    print("\n  Delivered: %s" % m["subject"])
    print("             from %s" % m["from"])
    print("  The badge on the bubble has moved. %d still to come.\n"
          % got.get("remaining", 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
