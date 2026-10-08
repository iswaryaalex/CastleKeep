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
import time

from . import agents as agents_mod


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

    subs = [s for s in (p.get("subagents") or []) if s in known]
    if not subs:
        subs = [agents_mod.DEFAULT_ID]

    presets = {}
    for s in subs:
        chosen = (p.get("presets") or {}).get(s)
        if agents_mod.preset(s, chosen) is None:
            chosen = agents_mod.default_preset(s)
        presets[s] = chosen

    return {
        "userName": (p.get("userName") or "").strip(),
        "agentName": (p.get("agentName") or "").strip() or "Assistant",
        "subagents": subs,
        "presets": presets,
        "activeAgent": p.get("activeAgent") if p.get("activeAgent") in subs else subs[0],
        "completedAt": p.get("completedAt") or time.time(),
    }


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
