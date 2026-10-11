"""
core/postman.py - mail that arrives during the workshop.

The mailbox is a snapshot. A snapshot never changes, and a room that watches a
static inbox for an hour never sees the one thing the base agent exists to do:
notice that something new turned up.

So: some messages ship with a `releaseAt`, sit in mailbox\\scheduled\\, and are
moved into mailbox\\inbox\\ when their moment comes. From that moment they are
ordinary mail. Nothing downstream knows the difference.

WHAT THIS IS NOT
----------------
This is not the agent fetching mail, and the UI must not say that it is. This
is the POSTMAN. It stands in for Gmail's servers, and like Gmail's servers it
runs outside the sandbox with no policy over it. The agent's half is still
exactly what it was: list_messages and read_message, through a sandbox, under
policies\\base.json, refused if the grant is missing.

Keeping those two apart is the whole reason this is its own file. "The mail
server delivered a message" and "your assistant was allowed to read it" are
different sentences, and a workshop that blurs them teaches the wrong thing.

WHY NOT A LIVE IMAP POLL
------------------------
It was considered and rejected, for the reasons already set out at the top of
workshop\\mail-snapshot.py: Gmail caps simultaneous IMAP connections near
fifteen and flags many IPs hitting one account, so forty laptops lock the
account mid-session; shared live mail is shared mutable state, so one person
archiving changes everybody's inbox; and an app password would have to sit on
every machine in an app that spends its afternoon demonstrating prompt
injection.

A timed release costs none of that. It needs no network, no credential and no
conference wifi, and it fires identically on forty machines.

THE CLOCK
---------
Offsets are measured from an anchor written on first run to mailbox\\.postman.
The anchor is the moment setup finished, if a profile says so, otherwise the
moment the mailbox was made. That keeps a room that all finished setup within
a minute of each other roughly in step.

For anything that has to land on a cue rather than on a clock, the presenter
calls deliver_next() - POST /api/mailbox/deliver, or workshop\\deliver.py.
"""

import json
import os
import re
import time

SCHEDULED = "scheduled"
STATE_FILE = ".postman"

# "+12m", "+90s", "+1h30m", "+00:12:00", or an absolute "2026-10-10T14:30:00".
_REL = re.compile(r"^\+\s*(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$", re.I)
_CLOCK = re.compile(r"^\+\s*(\d{1,2}):(\d{2})(?::(\d{2}))?$")


# ---------------------------------------------------------------------------
# The clock
# ---------------------------------------------------------------------------

def anchor(mailbox_dir, profile=None):
    """When the workshop clock started, as an epoch float.

    Written once and then left alone. Re-deriving it on every tick would mean
    a message due at +12m kept being twelve minutes away for ever."""
    path = os.path.join(mailbox_dir, STATE_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            got = json.load(f)
        if isinstance(got, dict) and got.get("anchor"):
            return float(got["anchor"])
    except (OSError, ValueError, TypeError):
        pass

    started = (profile or {}).get("completedAt")
    try:
        started = float(started)
    except (TypeError, ValueError):
        started = None
    if not started:
        try:
            started = os.path.getmtime(mailbox_dir)
        except OSError:
            started = time.time()

    _write_state(mailbox_dir, {"anchor": started})
    return started


def reset_anchor(mailbox_dir, when=None):
    """Start the clock again from now. The presenter's rehearsal button: run
    through the workshop twice on one machine without deleting the mailbox."""
    when = float(when or time.time())
    _write_state(mailbox_dir, {"anchor": when})
    return when


def _write_state(mailbox_dir, obj):
    path = os.path.join(mailbox_dir, STATE_FILE)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except OSError:
        pass


def due_at(release, base):
    """Turn a releaseAt value into an epoch float, or None if unreadable.

    None means "do not deliver on a timer". Such a message waits for
    deliver_next(), which is a perfectly good thing for a message to do."""
    if release is None:
        return None
    if isinstance(release, (int, float)):
        return base + float(release)

    s = str(release).strip()
    m = _CLOCK.match(s)
    if m:
        h, mi, sec = (int(x or 0) for x in m.groups())
        return base + h * 3600 + mi * 60 + sec
    m = _REL.match(s)
    if m and any(m.groups()):
        h, mi, sec = (int(x or 0) for x in m.groups())
        return base + h * 3600 + mi * 60 + sec
    # Absolute, as an ISO-ish string.
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M",
                "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(s, fmt))
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# The sack
# ---------------------------------------------------------------------------

def ensure(mailbox_dir, scheduled_items=None):
    """Make mailbox\\scheduled\\ and lay down anything not already there.

    Never overwrites and never re-creates a message that has already been
    delivered. Delivery removes the file from scheduled\\, so a message that
    is gone from here is a message somebody has already read - putting it back
    on a restart would be the rudest thing this function could do."""
    folder = os.path.join(mailbox_dir, SCHEDULED)
    os.makedirs(folder, exist_ok=True)
    if not _first_run(mailbox_dir):
        return folder
    for item in scheduled_items or []:
        mid = str(item.get("id") or "").strip()
        if not mid:
            continue
        path = os.path.join(folder, mid + ".json")
        if os.path.exists(path) or _delivered(mailbox_dir, mid):
            continue
        with open(path, "w", encoding="utf-8") as f:
            json.dump(item, f, indent=2, ensure_ascii=False)
            f.write("\n")
    return folder


def _first_run(mailbox_dir):
    """True until the first delivery or the first tick marks the sack seeded.

    Without this, a scheduled message delivered and then read would reappear
    in the sack the next time the app started."""
    path = os.path.join(mailbox_dir, STATE_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return not (json.load(f) or {}).get("seeded")
    except (OSError, ValueError, TypeError):
        return True


def mark_seeded(mailbox_dir):
    path = os.path.join(mailbox_dir, STATE_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f) or {}
    except (OSError, ValueError, TypeError):
        state = {}
    state["seeded"] = True
    _write_state(mailbox_dir, state)


def _delivered(mailbox_dir, mid):
    return os.path.exists(os.path.join(mailbox_dir, "inbox", mid + ".json"))


def _names(folder):
    try:
        return sorted(n for n in os.listdir(folder) if n.endswith(".json"))
    except OSError:
        return []


def pending(mailbox_dir, base=None, profile=None):
    """Everything still in the sack, soonest first.

    Each entry carries `dueAt` and `dueIn`, so the Run tab can say "the next
    one lands in four minutes" rather than leaving a presenter guessing."""
    base = base if base is not None else anchor(mailbox_dir, profile)
    folder = os.path.join(mailbox_dir, SCHEDULED)
    now = time.time()
    out = []
    for name in _names(folder):
        try:
            with open(os.path.join(folder, name), "r", encoding="utf-8") as f:
                msg = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(msg, dict):
            continue
        when = due_at(msg.get("releaseAt"), base)
        out.append({
            "id": msg.get("id") or name[:-5],
            "from": msg.get("from") or "",
            "subject": msg.get("subject") or "",
            "releaseAt": msg.get("releaseAt"),
            "dueAt": when,
            "dueIn": None if when is None else int(when - now),
            "onCue": when is None,
        })
    out.sort(key=lambda m: (m["dueAt"] is None, m["dueAt"] or 0))
    return out


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def _move_in(mailbox_dir, mid):
    """scheduled\\<id>.json -> inbox\\<id>.json, on the HOST.

    os.replace, not a sandboxed move. This is the mail server putting a
    message in a mailbox, and a mail server is not something the participant's
    policy governs. The agent's read of it, a moment later, very much is."""
    src = os.path.join(mailbox_dir, SCHEDULED, mid + ".json")
    dst = os.path.join(mailbox_dir, "inbox", mid + ".json")
    try:
        with open(src, "r", encoding="utf-8") as f:
            msg = json.load(f)
    except (OSError, ValueError):
        return None
    msg.pop("releaseAt", None)
    msg["unread"] = True
    msg["deliveredAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    # A message with no date of its own is dated NOW, because now is when it
    # arrived. That keeps the shipped messages evergreen: a seed hard-coded to
    # October 2026 reads as three weeks stale the first time this workshop is
    # run in November, and "look, new mail" lands badly when the new mail is
    # the oldest thing in the list.
    if not msg.get("date"):
        msg["date"] = msg["deliveredAt"]
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(msg, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, dst)
        os.remove(src)
    except OSError:
        return None
    return msg


def tick(mailbox_dir, profile=None):
    """Deliver everything that is due. Returns the messages delivered."""
    base = anchor(mailbox_dir, profile)
    now = time.time()
    out = []
    for item in pending(mailbox_dir, base):
        if item["dueAt"] is None or item["dueAt"] > now:
            continue
        msg = _move_in(mailbox_dir, item["id"])
        if msg:
            out.append(msg)
    mark_seeded(mailbox_dir)
    return out


def deliver_next(mailbox_dir, profile=None, message_id=None):
    """Deliver one message now, whatever its clock says.

    The presenter's cue. Timed delivery is right for a room that is reading
    its own screen; a cue is right for the moment somebody is talking over
    the top of it.

    With no id this takes the head of the sack, which is the next one due.
    With an id it takes that one, so the message that has no clock at all can
    be fired at the moment it is worth firing."""
    items = pending(mailbox_dir, profile=profile)
    if not items:
        return None
    if message_id:
        wanted = str(message_id).strip()
        if not any(i["id"] == wanted for i in items):
            return None
    msg = _move_in(mailbox_dir, message_id or items[0]["id"])
    mark_seeded(mailbox_dir)
    return msg
