"""
core/icsfeed.py - the live calendar.

Google Calendar publishes a "secret address in iCal format": an unguessable
read-only URL that needs no credential at all. That makes the calendar the one
half of a Google account CastleKeep can read at runtime, on every machine, with
nothing shipped that could be abused.

Mail cannot work this way and the difference is worth stating once, because it
is the reason this file exists and workshop\\mail-snapshot.py still has to be
run by hand:

    calendar   secret .ics URL   read-only by construction   no credential
    mail       IMAP / Gmail API  read AND write              a real credential

So: the calendar refreshes itself during the session, and the mailbox is a
snapshot taken before it.

WHAT THIS IS NOT
----------------
Like core/postman.py, this is NOT the agent fetching anything, and the UI must
not say that it is. This is the calendar SERVER's feed, pulled on the host,
outside any sandbox. It has to be: a sandboxed process on this tier cannot
reach the network at all - see the capability table in mxc.py.

The agent's half is unchanged. list_events and find_free_slot still go through
a sandbox, still read mailbox\\calendar, and are still refused if
policies\\base.json does not grant it.

NOT CLOBBERING THE AGENTS
-------------------------
mailbox\\calendar\\<date>.json is written by two different things: this feed,
and sync_vaults merging invitations the persona agents produced. A refresh
that simply overwrote the day file would silently delete the appointment the
health agent made ninety seconds earlier, which is the single most valuable
artefact in the whole workshop.

So every event carries where it came from. Events from this feed are stamped
`source: "calendar"` with an `ics:` sourceId; events from an agent carry their
own agent id. A refresh replaces only the `ics:` ones and leaves everything
else exactly where it was.
"""

import json
import os
import re
import threading
import time
import urllib.request

FOLDER = "calendar"
SOURCE = "calendar"
PREFIX = "ics:"          # marks an event this feed owns

DEFAULT_BACK = 7
DEFAULT_AHEAD = 45
DEFAULT_REFRESH_MIN = 10


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse(text, days_back=DEFAULT_BACK, days_ahead=DEFAULT_AHEAD):
    """An .ics body, as one record per day inside the window.

    A deliberately small parser: VEVENT, UID, DTSTART, DTEND, SUMMARY,
    LOCATION. Two things it does NOT do, and both matter when you look at the
    result:

      * Recurrence is ignored. An RRULE event appears once, at its first
        instance, which may be years ago. The count comes back so a caller can
        say how much of the calendar fell down that hole.

      * Attendees are not read. No agent here ever emails anybody, so the
        field is carried empty rather than half-filled.

    The window exists because a real calendar is not a workshop calendar. The
    first run of this against a live Google feed returned 310 days starting in
    2021, which is not a thing anybody wants in the bubble.
    """
    lo, hi = window(days_back, days_ahead)
    days, cur, recurring, skipped = {}, None, 0, 0

    # Unfold first. ICS wraps long lines with CRLF and a single space or tab,
    # and a SUMMARY split across two lines is a title that silently loses its
    # second half.
    text = text.replace("\r\n ", "").replace("\r\n\t", "")
    text = text.replace("\n ", "").replace("\n\t", "")

    for line in text.splitlines():
        if line.startswith("BEGIN:VEVENT"):
            cur = {}
        elif line.startswith("END:VEVENT") and cur is not None:
            day = cur.get("day")
            if cur.get("recurring"):
                recurring += 1
            if day and lo <= day <= hi:
                days.setdefault(day, []).append({
                    "start": cur.get("start", ""),
                    "end": cur.get("end", ""),
                    "title": unescape(cur.get("title", "(untitled)")),
                    "attendees": [],
                    "location": unescape(cur.get("location", "")),
                    "source": SOURCE,
                    "sourceId": PREFIX + (cur.get("uid") or
                                          (day + cur.get("start", ""))),
                })
            elif day:
                skipped += 1
            cur = None
        elif cur is None:
            continue
        elif line.startswith("DTSTART"):
            cur["day"], cur["start"] = ics_time(line)
        elif line.startswith("DTEND"):
            _, cur["end"] = ics_time(line)
        elif line.startswith("RRULE"):
            cur["recurring"] = True
        elif line.startswith("UID:"):
            cur["uid"] = line.split(":", 1)[1].strip()
        elif line.startswith("SUMMARY:"):
            cur["title"] = line.split(":", 1)[1]
        elif line.startswith("LOCATION:"):
            cur["location"] = line.split(":", 1)[1]

    out = [{"id": d, "date": d, "events": sorted(evs, key=lambda e: e["start"])}
           for d, evs in sorted(days.items())]
    return out, {"window": "%s to %s" % (lo, hi), "outsideWindow": skipped,
                 "recurring": recurring}


def window(days_back, days_ahead):
    now = time.time()
    fmt = lambda t: time.strftime("%Y-%m-%d", time.localtime(t))
    return fmt(now - days_back * 86400), fmt(now + days_ahead * 86400)


def unescape(v):
    """ICS escapes commas, semicolons and newlines. A location reads as
    'Hall 4\\, room 12' otherwise, which looks like a bug in CastleKeep."""
    return (str(v or "").replace("\\n", " ").replace("\\N", " ")
            .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")).strip()


def ics_time(line):
    """One DTSTART/DTEND line as (YYYY-MM-DD, HH:MM), in LOCAL time.

    Three forms turn up in a Google export and they do not mean the same
    thing:

        DTSTART;VALUE=DATE:20261022                   all-day, no time
        DTSTART;TZID=Europe/London:20261022T143000    wall time in that zone
        DTSTART:20261022T133000Z                      UTC

    Taking the digits as they come - which this did until it was measured -
    shows a 14:30 appointment as 13:30 for anyone whose calendar exports UTC.
    Being an hour out on a doctor's appointment is a quiet, plausible wrong
    answer, which is the worst kind for this app to produce.
    """
    if ":" not in line:
        return None, ""
    head, v = line.split(":", 1)
    v = v.strip()
    m = re.match(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?)?", v)
    if not m:
        return None, ""
    y, mo, d, hh, mi, _ss = m.groups()
    if not hh:
        return "%s-%s-%s" % (y, mo, d), ""

    naive = (int(y), int(mo), int(d), int(hh), int(mi))
    if v.endswith("Z"):
        return to_local(naive, "UTC")
    tzid = re.search(r"TZID=([^;:]+)", head)
    if tzid:
        return to_local(naive, tzid.group(1))
    # No marker at all: a floating time, which already means wall time.
    return "%s-%s-%s" % (y, mo, d), "%s:%s" % (hh, mi)


def to_local(naive, tzname):
    """Move a wall time from one zone to this machine's zone.

    zoneinfo is standard library from 3.9, but the IANA database is not always
    present on Windows without tzdata. If the zone cannot be resolved the time
    is returned unchanged rather than guessed at - a wrong hour reported as
    fact is worse than an hour that was never converted."""
    y, mo, d, hh, mi = naive
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        local = datetime(y, mo, d, hh, mi, tzinfo=ZoneInfo(tzname)).astimezone()
        return local.strftime("%Y-%m-%d"), local.strftime("%H:%M")
    except Exception:
        return "%04d-%02d-%02d" % (y, mo, d), "%02d:%02d" % (hh, mi)


def fetch(url, days_back=DEFAULT_BACK, days_ahead=DEFAULT_AHEAD, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": "CastleKeep/1.0 (local workshop app; read-only)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
    return parse(body, days_back, days_ahead)


# ---------------------------------------------------------------------------
# Writing, without treading on the agents
# ---------------------------------------------------------------------------

def _mine(event):
    return str((event or {}).get("sourceId") or "").startswith(PREFIX)


def _invented(event):
    """A made-up event from the built-in sample calendar.

    Swept away the first time a real feed lands, so that switching icsUrl on
    after a machine has already been set up gives the same clean result as
    having had it on from the start."""
    return (event or {}).get("source") == "seed"


def _read_day(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            got = json.load(f)
        return got.get("events") or [] if isinstance(got, dict) else []
    except (OSError, ValueError):
        return []


def _write_day(path, date, events):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"id": date, "date": date,
                   "events": sorted(events, key=lambda e: e.get("start") or "")},
                  f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def merge_into(mailbox_dir, days):
    """Put the feed on disk and leave every agent-made event alone.

    Three passes, and the third is the one people forget: an event moved to a
    different day in Google leaves a copy behind on the old day, so any `ics:`
    event no longer in the feed has to be swept up wherever it is sitting."""
    folder = os.path.join(mailbox_dir, FOLDER)
    os.makedirs(folder, exist_ok=True)
    fresh = {d["date"]: d["events"] for d in days}
    added = kept = stale = 0

    # 1 and 2: every day the feed covers, rebuilt from ours + theirs.
    for date, events in fresh.items():
        path = os.path.join(folder, date + ".json")
        existing = _read_day(path)
        theirs = [e for e in existing if not _mine(e) and not _invented(e)]
        kept += len(theirs)
        added += len(events)
        _write_day(path, date, theirs + list(events))

    # 3: days the feed no longer covers but which still hold our events.
    try:
        names = [n for n in os.listdir(folder) if n.endswith(".json")]
    except OSError:
        names = []
    for name in names:
        date = name[:-5]
        if date in fresh:
            continue
        path = os.path.join(folder, name)
        events = _read_day(path)
        left = [e for e in events if not _mine(e) and not _invented(e)]
        if len(left) != len(events):
            stale += len(events) - len(left)
            _write_day(path, date, left)

    return {"added": added, "keptFromAgents": kept, "removedStale": stale,
            "days": len(fresh)}


# ---------------------------------------------------------------------------
# What the app calls
# ---------------------------------------------------------------------------

def settings(cfg):
    c = (cfg or {}).get("calendar") or {}
    try:
        mins = float(c.get("refreshMinutes") or DEFAULT_REFRESH_MIN)
    except (TypeError, ValueError):
        mins = DEFAULT_REFRESH_MIN
    return {
        "url": (c.get("icsUrl") or "").strip(),
        "refreshSec": max(60.0, mins * 60.0),
        "daysBack": int(c.get("daysBack") or DEFAULT_BACK),
        "daysAhead": int(c.get("daysAhead") or DEFAULT_AHEAD),
    }


def refresh(app, force=False):
    """Pull the feed and merge it. Safe to call often; it throttles itself.

    Never raises. A calendar that cannot be reached - no wifi, a rotated
    secret address, a captive portal - must leave the last good copy on disk
    and say so, not blank the pane and not take the app down with it."""
    s = settings(app.cfg)
    state = dict(getattr(app, "calendar", None) or {"state": "cold"})
    if not s["url"]:
        return {"state": "off",
                "note": "No calendar.icsUrl in config.json. The calendar is "
                        "whatever the mailbox seed laid down."}

    now = time.time()
    if not force and state.get("at") and now - state["at"] < s["refreshSec"]:
        return state

    try:
        days, meta = fetch(s["url"], s["daysBack"], s["daysAhead"])
    except Exception as e:
        # Keep whatever was there. Report the failure next to it.
        out = dict(state)
        out.update({"state": "error", "error": str(e)[:300], "checkedAt": now})
        app.calendar = out
        return out

    merged = merge_into(app.mailbox, days)
    out = {"state": "ok", "at": now, "checkedAt": now,
           "days": merged["days"], "events": merged["added"],
           "keptFromAgents": merged["keptFromAgents"],
           "removedStale": merged["removedStale"],
           "window": meta["window"], "recurring": meta["recurring"],
           "outsideWindow": meta["outsideWindow"]}
    app.calendar = out
    return out


def refresh_async(app, force=False):
    """Refresh without making somebody wait for it.

    Used on the setup POST: the browser is about to navigate to the app and a
    slow or captive network would otherwise hold that request open for the
    full socket timeout."""
    t = threading.Thread(target=lambda: refresh(app, force), daemon=True,
                         name="castlekeep-calendar")
    t.start()
    return t
