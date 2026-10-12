"""
core/profile.py - who is sitting here, and what they called their agent.

One small JSON file at the project root. It exists so the app has somewhere to
put the four answers onboarding collects, and so the launch screen can tell
"this machine has been set up" from "this machine has not" without guessing.

It is deliberately not in git. Forty people clone the same repo; the name they
type is theirs, not the repo's.

Nothing in here is a security boundary. A profile cannot grant access - it
records which policy file each subagent uses, and those files go through the
same lint and compile path as anything typed by hand.
"""

import json
import os
import re
import time

from . import agents as agents_mod

# The five faces. Kept here rather than in the UI because the profile is what
# persists them and normalise() has to be able to reject one that no longer
# exists - a profile naming a deleted species would draw an empty avatar on
# every screen in the app.
CRITTERS = ("fox", "cat", "owl", "bunny", "axolotl")

THEMES = ("parchment", "moonlit", "sakura")

# Validated here as well as in the browser. The onboarding form is the polite
# place to catch a typo; this is the place that stops a hand-edited or
# older-build profile putting something shaped like a path or a quote into a
# seed file. Neither check is a security boundary - the connectors only ever
# name local dummy data, nothing authenticates anywhere - but a username with
# a backslash in it turns into a confusing refusal three layers away.
_CONNECTOR_RULES = {
    "gmail": re.compile(r"^[A-Za-z0-9._%+-]+@gmail\.com$", re.I),
    "reddit": re.compile(r"^[A-Za-z0-9_-]{3,20}$"),
    "github": re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$"),
}


def path_for(project_dir):
    return os.path.join(project_dir, "profile.json")


def load(project_dir):
    """The profile, or None if onboarding has not happened yet.

    A corrupt file reads as None rather than raising: the cost of being wrong
    is that somebody re-types their name, and the cost of raising is a stack
    trace on the front door of the app."""
    try:
        with open(path_for(project_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("completedAt"):
        return None
    return normalise(data)


def normalise(profile):
    """Fill in anything missing and drop anything we do not recognise.

    Subagent ids are filtered against the registry, so a profile written by an
    older build - or hand-edited - cannot point the rail at an agent that no
    longer exists."""
    p = dict(profile or {})
    known = agents_mod.ids()
    personas = agents_mod.persona_ids()

    subs = [s for s in (p.get("subagents") or []) if s in known
            and s != agents_mod.BASE_ID]
    if not subs:
        subs = [agents_mod.DEFAULT_ID]
    # The base agent is not a choice. Four personas writing invitations into
    # folders that nothing ever reads is not a smaller version of this app, it
    # is a broken one - so it goes first and it always goes.
    subs = [agents_mod.BASE_ID] + subs

    presets = {}
    for s in subs:
        chosen = (p.get("presets") or {}).get(s)
        if agents_mod.preset(s, chosen) is None:
            chosen = agents_mod.default_preset(s)
        presets[s] = chosen

    chat_agents = [s for s in subs if s != agents_mod.BASE_ID]
    active = p.get("activeAgent")

    return {
        "userName": (p.get("userName") or "").strip(),
        "agentName": (p.get("agentName") or "").strip() or "Assistant",
        "subagents": subs,
        "presets": presets,
        "critters": _critters(p, subs, personas),
        "connectors": _connectors(p.get("connectors")),
        "theme": p.get("theme") if p.get("theme") in THEMES else THEMES[0],
        # Per-agent model overrides, kept for whatever agents still exist. Not
        # validated against Lemonade here - that is a live question the app
        # answers at set time; a name that stops being served just falls back
        # to the global model at chat time, which is the safe direction.
        "agentModels": {k: v for k, v in (p.get("agentModels") or {}).items()
                        if k in known and isinstance(v, str) and v},
        # The chat never opens on the base agent: it runs in the background
        # and has a bubble of its own, and landing somebody in it would start
        # them at the end of the story.
        "activeAgent": active if active in chat_agents else chat_agents[0],
        "completedAt": p.get("completedAt") or time.time(),
    }


def _critters(p, subs, personas):
    """One face per agent, all five distinct.

    Duplicates are resolved rather than rejected. A profile where two agents
    share a face is not dangerous, it is just confusing on screen - and the
    repair (hand the later one whichever species is still going spare) is
    obvious enough that stopping to ask about it would be worse."""
    want = p.get("critters") or {}
    out, taken = {}, set()
    order = [agents_mod.BASE_ID] + [s for s in subs if s != agents_mod.BASE_ID]
    for agent_id in order + personas:
        if agent_id in out:
            continue
        pick = want.get(agent_id)
        if pick not in CRITTERS or pick in taken:
            pick = next((c for c in CRITTERS if c not in taken), CRITTERS[0])
        out[agent_id] = pick
        taken.add(pick)
    return out


def _connectors(raw):
    """The three dummy accounts. An entry that does not match its shape is
    dropped, not corrected - an invented username seeded into somebody's
    GitHub records would be a quiet lie about whose data they are looking at."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key, rule in _CONNECTOR_RULES.items():
        value = str(raw.get(key) or "").strip()
        out[key] = value if rule.match(value) else ""
    return out


def save(project_dir, profile):
    """Atomic write, same shape as policy.save - a half-written profile.json
    is read as 'not onboarded' and silently throws away somebody's setup."""
    out = normalise(dict(profile or {}, completedAt=(profile or {}).get(
        "completedAt") or time.time()))
    path = path_for(project_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    return out


def clear(project_dir):
    """Start onboarding over. Used by the Settings tab and between workshop
    sessions on a shared machine. Leaves policies/ alone on purpose - those are
    the interesting artefact, and re-running onboarding overwrites them anyway."""
    try:
        os.remove(path_for(project_dir))
        return True
    except OSError:
        return False
