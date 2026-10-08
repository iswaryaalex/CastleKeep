#!/usr/bin/env python3
"""
Which model should CastleKeep talk to?

Lemonade on this box serves a couple of hundred models, and the name in
config.json has to match one of them exactly or every request comes back
404 model_not_found. Eyeballing that list is not a good use of anyone's time.

    python workshop\\models.py                 what is served, grouped
    python workshop\\models.py qwen            only names matching 'qwen'
    python workshop\\models.py qwen --all      search the whole catalogue too
    python workshop\\models.py --pick <name>   write that name into config.json
    python workshop\\models.py --check         is the configured model there?

Two different lists matter here and confusing them wastes an afternoon.
`/models` returns what is INSTALLED and ready to serve. `/models?show_all=true`
returns the whole catalogue, most of which is not on this disk. A name can be
perfectly real, appear under --all, and still 404 at chat time because nobody
pulled it. --all marks which is which.

Listing does not load anything. --pick edits config.json and nothing else - a
running CastleKeep notices the file changed, repoints at the new model and
starts warming it, the same way a policy.json edit lands without a restart.
"""

import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

import bootstrap                             # noqa: E402
bootstrap.purge(PROJECT)   # never import stale .pyc - see bootstrap.py

from core.app import App                     # noqa: E402
from core.lemonade import Lemonade           # noqa: E402

CONFIG = os.path.join(PROJECT, "config.json")

# What this workshop actually needs from a model: it has to hold a system
# prompt describing nine tools, decide to call one, and keep going after the
# result comes back. Small models will chat happily and never call a tool,
# which looks like CastleKeep is broken when it is not.
WANT = ("qwen", "llama", "mistral", "phi", "gemma", "hermes", "olmo")


def catalogue(lem):
    """Everything Lemonade knows about, installed or not."""
    url = "%s%s/models?show_all=true" % (lem.base, lem.prefix or "")
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print("  (could not read the full catalogue: %s)" % e)
        return []
    items = body.get("data") if isinstance(body, dict) else body
    return sorted((m.get("id") if isinstance(m, dict) else str(m))
                  for m in (items or []))


def main():
    args = sys.argv[1:]
    app = App(PROJECT)
    lem = Lemonade(app.cfg)
    h = lem.health()

    if not h.get("reachable"):
        print("\n  Lemonade is not answering at %s" % lem.base)
        print("  %s\n" % (h.get("note") or ""))
        return 2

    models = sorted(h.get("models") or [])
    configured = (app.cfg.get("lemonade") or {}).get("model")
    print("\n  Lemonade at %s, route %s, %d models"
          % (lem.base, h.get("routePrefix"), len(models)))
    print("  config.json currently asks for: %s" % configured)
    print("  %s\n" % ("that model IS served" if configured in models
                      else "*** that model is NOT served ***"))

    if "--check" in args:
        return 0 if configured in models else 1

    if "--pick" in args:
        name = args[args.index("--pick") + 1]
        if name not in models:
            print("  '%s' is not installed." % name)
            if name in catalogue(lem):
                print("")
                print("  It IS in Lemonade's catalogue, so the name is right -")
                print("  it just is not on this disk. Pull it in Lemonade, then")
                print("  run this again. Until then it will 404 at chat time.")
                print("")
                return 1
            near = [m for m in models if name.lower() in m.lower()]
            if near:
                print("  Installed names containing that text:")
                for m in near[:15]:
                    print("    %s" % m)
            print("")
            return 1
        cfg = json.load(open(CONFIG, encoding="utf-8"))
        cfg.setdefault("lemonade", {})["model"] = name
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
        print("  config.json now points at %s" % name)
        print("  A running CastleKeep picks this up on its next poll and starts")
        print("  loading the new weights - no restart needed.\n")
        return 0

    term = args[0].lower() if args and not args[0].startswith("-") else None
    if term:
        hits = [m for m in models if term in m.lower()]
        print("  Installed and ready to serve - %d matching '%s':\n"
              % (len(hits), term))
        for m in hits:
            print("    %s" % m)
        if not hits:
            print("    (none)")
        print("")

        if "--all" in args:
            every = catalogue(lem)
            more = [m for m in every if term in m.lower() and m not in models]
            print("  In the catalogue but NOT installed - %d more:\n" % len(more))
            for m in more:
                print("    %s" % m)
            if not more:
                print("    (none)")
            print("")
            print("  Pull one of these in Lemonade before --pick, or it will")
            print("  404 at chat time exactly like the name you have now.")
            print("")
        elif not hits:
            print("  Nothing installed matches. Try --all to search the whole")
            print("  catalogue:  python workshop\\models.py %s --all\n" % term)
        return 0

    # No search term: show the families likely to be able to call a tool,
    # rather than dumping two hundred names.
    print("  Likely candidates for an agent (everything else is hidden -")
    print("  pass a search term to see the full list):\n")
    for family in WANT:
        hits = [m for m in models if family in m.lower()]
        if not hits:
            continue
        print("  %s" % family)
        for m in hits[:12]:
            print("    %s" % m)
        if len(hits) > 12:
            print("    ... and %d more, try: python workshop\\models.py %s"
                  % (len(hits) - 12, family))
        print("")

    print("  Then:  python workshop\\models.py --pick <exact name>\n")
    print("  One thing to check after picking. CastleKeep asks the backend for")
    print("  native tool calls first and falls back to describing the tools in")
    print("  the prompt if that 404s or errors. Both work, but native is more")
    print("  reliable - verify.py reports which mode you ended up in.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
