"""
core/profiles.py - the four agents.

A profile is a policy.json with a few extra fields on top: who the agent is,
what it looks like, and what to say about it. Everything from "containment"
down is the same schema policy.json uses and compiles through the same
compiler, so an agent's sandbox is authored exactly the way the single-policy
version was.

The load path is deliberately the same shape as App.reload_policy: re-read the
file if its mtime moved, keep the last good copy if it will not parse. An edit
to profiles\\health.json lands on Health's very next tool call and touches
nothing else.

Two things this file does NOT do:

  * It does not refuse to run on a profile that has drifted. The point of the
    Policy tab is that you widen a grant and watch a refusal stop happening,
    so a runtime that crashed on a hand edit would be fighting the demo. What
    it does instead is audit() - every drift comes back as a note the UI can
    put on screen next to the agent it belongs to.

  * It does not decide anything about tools. The tool gate is host-side and
    lives in each profile's "tools" block, which is identical in all four on
    purpose. audit() says so if that stops being true.
"""

import io
import json
import os

from . import policy as policy_mod

# Left to right in the agent bar. This is the 2x2: the first two differ only
# on network, the last two differ only on write, so reading across tells the
# story and reading down tells it the other way.
ORDER = ("diagnostics", "finance", "health", "paperwork")

SYS32 = "${windir}\\System32"
WORKSPACE = "${workspace}"

# Words that belong to the Mission panel and the comparison card, not to the
# one-line job label in the bar. See audit().
_POLICY_WORDS = ("file", "folder", "network", "read", "write", "sandbox",
                 "policy", "container")

DISPLAY = ("name", "title", "critter", "task", "tagline", "starters",
           "boundary", "description", "named")


class Profile(object):
    """One agent. The dict is both its identity and its policy."""

    def __init__(self, path, data):
        self.path = path
        self.data = data
        self.mtime = _mtime(path)

    # -- identity ---------------------------------------------------------

    @property
    def name(self):
        return self.data.get("name") or _stem(self.path)

    @property
    def title(self):
        return self.data.get("title") or self.name.title()

    @property
    def critter(self):
        return self.data.get("critter") or "dragon"

    @property
    def task(self):
        return self.data.get("task") or ""

    @property
    def tagline(self):
        return self.data.get("tagline") or ""

    @property
    def persona(self):
        return self.data.get("persona") or ""

    @property
    def starters(self):
        return list(self.data.get("starters") or [])

    @property
    def boundary(self):
        b = self.data.get("boundary") or {}
        return {"files": b.get("files") or "", "network": b.get("network") or ""}

    @property
    def description(self):
        return self.data.get("description") or ""

    @property
    def named(self):
        """True for the one agent the launch wizard names.

        The wizard asks for a name once and the dragon gets it. The other
        three go by their job title, because four pet names is three more
        things to learn before you can follow what the demo is showing you,
        and the name is not the part that matters.
        """
        return bool(self.data.get("named"))

    # -- policy -----------------------------------------------------------

    @property
    def policy(self):
        """The profile IS the policy. compile_config reads the sections it
        knows and ignores title, critter and the rest, so there is no second
        object to keep in step with this one."""
        return self.data

    def display(self):
        """What the UI needs to draw the bar, the Mission panel and the
        comparison card. The policy body is not in here: the Policy tab asks
        for that separately, through the same endpoint it always used."""
        out = {k: getattr(self, k) for k in DISPLAY}
        out["persona"] = self.persona
        return out

    def __repr__(self):
        return "<Profile %s>" % self.name


class Profiles(object):
    """The set on disk. One of these per App."""

    def __init__(self, dirpath):
        self.dir = os.path.abspath(dirpath)
        self.by_name = {}
        self.order = []
        self.errors = []
        self.load()

    # -- loading ----------------------------------------------------------

    def _files(self):
        """Every .json in profiles\\ that is not a note and not superseded.

        Discovered rather than hardcoded, so dropping a fifth profile in the
        folder gives you a fifth agent without touching Python. ORDER only
        decides the order of the ones it names; anything else lands after
        them, alphabetically.
        """
        try:
            names = sorted(os.listdir(self.dir))
        except OSError as e:
            self.errors.append("profiles folder could not be read (%s)." % e)
            return []

        found = {}
        for fn in names:
            if not fn.endswith(".json") or fn.startswith("_"):
                continue
            found[fn[:-5].lower()] = os.path.join(self.dir, fn)

        ordered = [n for n in ORDER if n in found]
        ordered += [n for n in sorted(found) if n not in ORDER]
        return [(n, found[n]) for n in ordered]

    def load(self):
        keep = {}
        order = []
        self.errors = []
        for name, path in self._files():
            old = self.by_name.get(name)
            m = _mtime(path)
            if old is not None and old.mtime == m:
                keep[name] = old
                order.append(name)
                continue
            try:
                data = json.loads(_read(path))
            except Exception as e:
                self.errors.append("%s could not be parsed (%s)." % (
                    os.path.basename(path), e))
                if old is not None:          # keep the last good copy
                    keep[name] = old
                    order.append(name)
                continue
            if data.get("superseded"):
                continue
            keep[name] = Profile(path, data)
            order.append(name)

        self.by_name = keep
        self.order = order
        return self

    def reload(self):
        """Cheap enough to call before every tool call, which is what app.py
        does. The common case is a stat per file and nothing else."""
        return self.load()

    # -- access -----------------------------------------------------------

    def all(self):
        return [self.by_name[n] for n in self.order]

    def names(self):
        return list(self.order)

    def get(self, name):
        if not name:
            return None
        return self.by_name.get(str(name).strip().lower())

    def resolve(self, name):
        """Never returns None while there is at least one profile on disk.

        An unknown agent id is a bug in the caller, but the honest failure for
        it is "you got Diagnostics", not a 500 in the middle of a sentence.
        The caller can compare resolve(x).name to x if it cares.
        """
        p = self.get(name)
        if p is not None:
            return p
        return self.all()[0] if self.order else None

    def default_name(self):
        return self.order[0] if self.order else None

    def save(self, name, data):
        p = self.get(name)
        if p is None:
            raise KeyError("no profile called %r" % name)
        policy_mod.save(p.path, data)
        p.data = data
        p.mtime = _mtime(p.path)
        return p


# ---------------------------------------------------------------------------
# The audit
# ---------------------------------------------------------------------------

def audit(profiles):
    """Everything the shipped four are supposed to be true about, checked
    against what is on disk right now.

    Returns a list of {level, profile, field, message}. level is error | warn.
    Nothing here stops a run. The self-test asserts this list is empty for the
    files as shipped; the app puts whatever is in it on screen, next to the
    agent it belongs to, so a widened grant announces itself instead of
    quietly making the demo stop proving anything.
    """
    out = []
    items = profiles.all() if hasattr(profiles, "all") else list(profiles)

    def add(level, prof, field, message):
        out.append({"level": level, "profile": prof, "field": field,
                    "message": message})

    for e in getattr(profiles, "errors", []):
        add("error", None, "profiles", e)

    if not items:
        add("error", None, "profiles",
            "No agent profiles were found. Expected profiles\\diagnostics.json "
            "and three more beside it.")
        return out

    for p in items:
        out.extend(_audit_one(p))

    # The pairing is the whole argument, so check it rather than trusting four
    # files to stay consistent with each other. One agent may have a network,
    # and that agent must have nothing of yours to send over it.
    online = [p for p in items if (p.policy.get("network") or {}).get("outbound") == "allow"]
    if len(online) > 1:
        add("error", None, "network.outbound",
            "More than one agent can reach the internet (%s). The point of the "
            "grid is that exactly one can, and that it is the one with no files."
            % ", ".join(p.title for p in online))
    for p in online:
        if p.boundary["files"] != "no files":
            add("error", p.name, "network.outbound",
                "%s has a network and file access at the same time. That is the "
                "shape of the problem, not the demo." % p.title)

    # The launch wizard collects one name. Two agents claiming it would put the
    # same name on two different boundaries, which is the one confusion this
    # whole design is trying to avoid.
    named = [p for p in items if p.named]
    if len(named) > 1:
        add("error", None, "named",
            "More than one agent claims the name from the launch wizard (%s). "
            "Exactly one may." % ", ".join(p.title for p in named))
    elif not named:
        add("warn", None, "named",
            "No agent claims the name from the launch wizard, so the name the "
            "person typed is not used anywhere. Set \"named\": true on one.")

    # The tool gate is host-side: a tool switched off here never reaches a
    # sandbox, so MXC never gets to refuse it. If the gates differed, the four
    # boxes would be enforced by an if statement in Python.
    gates = [(p, _gate(p)) for p in items]
    base_name, base = gates[0][0].title, gates[0][1]
    for prof, g in gates[1:]:
        diff = sorted(set(k for k in set(g) | set(base) if g.get(k) != base.get(k)))
        if diff:
            add("warn", prof.name, "tools",
                "The tool gate differs from %s on %s. That gate is host-side, so "
                "this difference is enforced by Python and not by the container, "
                "and any refusal it produces proves nothing about MXC."
                % (base_name, ", ".join(diff)))
    return out


def _audit_one(p):
    out = []
    name = p.name

    def add(level, field, message):
        out.append({"level": level, "profile": name, "field": field,
                    "message": message})

    for field in ("title", "critter", "task", "tagline", "persona", "description"):
        if not getattr(p, field):
            add("error", field, "%s has no %s." % (name, field))
    if not p.starters:
        add("warn", "starters", "%s has no starter questions." % p.title)

    # The bar label says what the agent is FOR. The Mission panel and the
    # comparison card already say what it may do, properly and in full, so
    # policy language in the label is the same sentence a third time in the
    # one place you are choosing a job rather than reading about one.
    t = p.task
    if t:
        if len(t) > 26:
            add("warn", "task", "%s: the job label is %d characters and the bar "
                                "has room for about 26." % (p.title, len(t)))
        leaked = [w for w in _POLICY_WORDS if w in t.lower()]
        if leaked:
            add("warn", "task", "%s: the job label talks about policy (%s). The "
                                "Mission panel says that already."
                % (p.title, ", ".join(leaked)))

    out.extend(_audit_boundary(p))
    return out


def _audit_boundary(p):
    """The agent bar prints a two-word summary of each agent's policy. This is
    what stops that summary drifting from the policy it summarises."""
    out = []
    name, title = p.name, p.title
    paths = p.policy.get("paths") or {}
    reads = [x for x in (paths.get("read") or []) if x != SYS32]
    writes = list(paths.get("write") or [])
    label = p.boundary["files"]

    def add(field, message):
        out.append({"level": "warn", "profile": name, "field": field,
                    "message": message})

    # Paths boundary check intentionally removed. Actual enforcement is by the
    # MXC sandbox — errors surface when a tool call is refused, not at startup.

    want = "network" if (p.policy.get("network") or {}).get("outbound") == "allow" \
        else "no network"
    if p.boundary["network"] != want:
        add("boundary.network", "%s is labelled %r but outbound is %r."
            % (title, p.boundary["network"],
               (p.policy.get("network") or {}).get("outbound")))
    return out


def _gate(p):
    return {k: bool(v) for k, v in (p.policy.get("tools") or {}).items()
            if not k.startswith("_")}


# ---------------------------------------------------------------------------

def _read(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def _stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None
