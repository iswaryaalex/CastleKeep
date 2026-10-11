#!/usr/bin/env python3
"""
workshop/mail-snapshot.py - pull the workshop Gmail account into a seed file.

RUN THIS ONCE, AS THE PRESENTER, BEFORE THE WORKSHOP. Participants never run
it and never see a credential.

    python workshop\\mail-snapshot.py --dry-run     show what would be written
    python workshop\\mail-snapshot.py               write workshop\\mailbox-seed.json

It reads the inbox and calendar of one dummy Gmail account over IMAP and
writes them to workshop\\mailbox-seed.json, which IS committed. On every
machine, CastleKeep lays that seed down into mailbox\\ on first run.

Why a snapshot rather than having the sandbox talk to Gmail live:

  * The sandbox cannot reach the network usefully for this. Mail-over-files is
    what makes "read my inbox but only write to drafts" expressible in the
    policy file the workshop is about. See the header of core/mailbox.py.

  * Gmail caps simultaneous IMAP connections per account at around fifteen and
    flags many IPs hitting one account at once. A room of forty on conference
    wifi locks the account mid-session.

  * Shared live mail is shared mutable state. One person archiving a message
    would change everyone else's inbox.

  * A live app password would have to live somewhere the agent might read, in
    an app that spends its afternoon demonstrating prompt injection. See
    mailbox\\inbox\\2026-10-08-payment-update.json for why that is a bad pairing.

Credentials come from the environment, never from a file in this repo:

    set CK_GMAIL_USER=castlekeep.workshop@gmail.com
    set CK_GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx

The app password needs 2-step verification enabled on the dummy account and
IMAP turned on in Gmail settings. Use an account created for this and nothing
else. Revoke the app password when the workshop is over.

Stdlib only, like everything else here.
"""

import argparse
import email
import email.policy
import imaplib
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# Python puts the SCRIPT's folder on sys.path, not the working directory, so
# `import core` fails from workshop/ without this even when you run it from
# the project root.
sys.path.insert(0, ROOT)

from core import icsfeed                                  # noqa: E402
OUT = os.path.join(HERE, "mailbox-seed.json")

IMAP_HOST = "imap.gmail.com"


# ---------------------------------------------------------------------------
# Mail
# ---------------------------------------------------------------------------

def fetch_mailbox(user, password, folder="INBOX", limit=12):
    """Newest `limit` messages from one IMAP folder, as CastleKeep message
    dicts. Read-only: the connection is opened with readonly=True so nothing
    here can mark, move or delete anything in the real account."""
    out = []
    M = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        M.login(user, password)
        M.select(folder, readonly=True)
        ok, data = M.search(None, "ALL")
        if ok != "OK":
            return out
        ids = (data[0] or b"").split()[-limit:]
        for num in reversed(ids):
            ok, raw = M.fetch(num, "(BODY.PEEK[])")
            if ok != "OK" or not raw or not raw[0]:
                continue
            out.append(_to_message(raw[0][1], folder))
    finally:
        try:
            M.close()
        except Exception:
            pass
        M.logout()
    return [m for m in out if m]


def _to_message(raw, folder):
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    body = _body_text(msg)
    date = _iso_date(msg.get("Date") or "")
    subject = str(msg.get("Subject") or "(no subject)")
    return {
        "id": _slug(date[:10] + "-" + subject),
        "threadId": str(msg.get("Message-ID") or "")[:60],
        "from": str(msg.get("From") or ""),
        "to": str(msg.get("To") or ""),
        "subject": subject,
        "date": date,
        "labels": ["inbox" if folder.upper() == "INBOX" else folder.lower()],
        "unread": True,
        "snippet": " ".join(body.split())[:160],
        "body": body[:6000],
    }


def _body_text(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_content()
                except Exception:
                    continue
        return ""
    try:
        return msg.get_content()
    except Exception:
        return ""


def _iso_date(raw):
    try:
        return email.utils.parsedate_to_datetime(raw).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return "1970-01-01T00:00:00"


def _slug(s):
    out = "".join(c if (c.isalnum() or c in "-_") else "-"
                  for c in str(s).lower())
    return re.sub(r"-+", "-", out)[:60].strip("-") or "message"


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------
#
# The parser lives in core/icsfeed.py, not here. The app needs it too - it
# refreshes the calendar at runtime from the same secret .ics address - and
# two copies of a timezone converter is two chances to be an hour out.

def fetch_calendar(ics_url, days_back=7, days_ahead=45):
    return icsfeed.fetch(ics_url, days_back, days_ahead)


# ---------------------------------------------------------------------------

def _load_existing():
    """The previous snapshot, so a half-run does not throw away the other
    half. Returns {} if there is nothing there yet."""
    try:
        with open(OUT, "r", encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be written and touch nothing")
    ap.add_argument("--limit", type=int, default=12,
                    help="how many of the newest messages to take")
    ap.add_argument("--private-folder", default=None,
                    help="an IMAP label to snapshot as the private folder - the "
                         "one the default base agent policy cannot read")
    ap.add_argument("--ics", default=os.environ.get("CK_GMAIL_ICS"),
                    help="Google Calendar secret .ics address (or CK_GMAIL_ICS)")
    ap.add_argument("--days-back", type=int, default=7,
                    help="how far back to keep calendar events. Default 7.")
    ap.add_argument("--days-ahead", type=int, default=45,
                    help="how far ahead to keep calendar events. Default 45.")
    args = ap.parse_args()

    user = os.environ.get("CK_GMAIL_USER")
    pw = os.environ.get("CK_GMAIL_APP_PASSWORD")

    # The two halves need different things, so they are allowed to run
    # separately. The calendar comes from a secret .ics address, which is an
    # unguessable read-only URL and needs NO credential at all. The mailbox
    # needs IMAP, which needs an app password.
    #
    # Demanding the app password before handing over a calendar that does not
    # use it is how somebody ends up creating a credential they did not need.
    if not user or not pw:
        if not args.ics:
            print("  Nothing to do.")
            print("")
            print("  For the mailbox, set both of these and run again:")
            print("    set CK_GMAIL_USER=you@gmail.com")
            print("    set CK_GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx")
            print("")
            print("  For the calendar ALONE, no credential is needed:")
            print("    python workshop\\mail-snapshot.py --ics <secret .ics address>")
            print("")
            print("  Google Calendar -> Settings -> your calendar ->")
            print("  'Secret address in iCal format'. Treat that URL as a")
            print("  password: anyone holding it can read the calendar.")
            print("")
            return 2
        print("  No IMAP credentials - taking the calendar only.")
        user = None

    existing = _load_existing()
    seed = {
        "_readme": "Snapshot of the workshop Gmail account, written by "
                   "workshop/mail-snapshot.py. CastleKeep lays this down into "
                   "mailbox/ on first run. Participants never log in to "
                   "anything; this file is the whole mailbox.",
        "_account": user or existing.get("_account"),
        # Keep whatever the last run produced for the half this run is not
        # doing. A calendar-only run must not wipe the inbox somebody
        # snapshotted an hour ago.
        "inbox": existing.get("inbox") or [],
        "private": existing.get("private") or [],
        "calendar": existing.get("calendar") or [],
        "scheduled": existing.get("scheduled") or [],
    }

    if user:
        print("  Reading %s as %s (read-only)" % (IMAP_HOST, user))
        seed["inbox"] = fetch_mailbox(user, pw, "INBOX", args.limit)
        print("  inbox      %d messages" % len(seed["inbox"]))

        if args.private_folder:
            seed["private"] = fetch_mailbox(user, pw, args.private_folder, 6)
            for m in seed["private"]:
                m["labels"] = ["private"]
            print("  private    %d messages (from %s)"
                  % (len(seed["private"]), args.private_folder))

    if args.ics:
        seed["calendar"], cal = fetch_calendar(args.ics, args.days_back,
                                               args.days_ahead)
        print("  calendar   %d days  (%s)" % (len(seed["calendar"]), cal["window"]))
        if cal["outsideWindow"]:
            print("             %d events outside the window were dropped"
                  % cal["outsideWindow"])
        if cal["recurring"]:
            print("             %d recurring events kept only their FIRST "
                  "instance - this parser does not expand RRULE"
                  % cal["recurring"])

    if args.dry_run:
        print("\n  --dry-run, nothing written. Would write %s\n" % OUT)
        for m in seed["inbox"][:5]:
            print("    %s  %s" % (m["date"][:16], m["subject"][:60]))
        return 0

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(seed, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("\n  Wrote %s" % OUT)
    print("  Commit it. Delete mailbox\\ on any machine to pick it up.")
    print("  Then revoke the app password when the workshop is over.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
