"""
core/basecamp.py - the always-on base agent.

Four persona agents produce things. Each one writes an invitation into its own
invites\\ folder or a message into its own outbox\\, and then stops, because
that is the entire extent of what its policy lets it do. Nothing a persona
produces reaches the calendar by itself.

This is what reaches the calendar. A daemon thread that notices the vault has
changed and asks the base agent to merge it, over and over, for as long as the
app is running.

The one decision worth defending is that the merge runs in a REAL sandbox,
under policies\\base.json, every single time. It would have been considerably
easier to read the eight folders here, in Python, on the host - mailbox.py
already reads the mailbox that way for the UI pane, and the precedent was
right there. But that pane is a window onto files, and this is an agent doing
work. If the merge ran on the host then policies\\base.json would be a
decoration: a participant could delete every path out of it and watch the
counter keep ticking, which is the exact opposite of what this app spends an
hour arguing.

So the loop is:

    host-side fingerprint (free, decides WHEN to ask)
        -> one sandboxed sync_vaults call (decides WHETHER it is allowed)
            -> whatever MXC permitted, reported verbatim

Narrow the base policy while this is running and the next tick says so, in
Windows' own words, with no restart. That is the demo.
"""

import json
import os
import threading
import time

from . import agents as agents_mod
from . import icsfeed as icsfeed_mod
from . import mailbox as mailbox_mod
from . import postman as postman_mod
from . import vault as vault_mod

DEFAULT_INTERVAL_SEC = 20

# Long enough that a machine which has just woken up, or one where the model
# is mid-warmup, does not get hammered. Short enough that nobody in a room
# waits long enough to ask whether it is working.
MIN_INTERVAL_SEC = 5


class Basecamp(object):
    def __init__(self, app):
        self.app = app
        self.lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._fingerprint = None

        # Everything the bubble draws. "cold" means the thread has not
        # completed a pass yet, which is different from "it ran and found
        # nothing" and the UI says so.
        self.state = {
            "state": "cold",
            "at": None,
            "merged": 0,       # invites + drafts, this pass
            "total": 0,        # since the app started
            "unread": 0,       # merged or delivered, not yet looked at
            "delivered": 0,    # messages the postman brought, this pass
            "refused": [],     # [{source, stage, error}]
            "outcome": None,   # the sandbox run's own outcome
            "reason": None,
            "runSeq": None,
        }

    # -- lifecycle --------------------------------------------------------

    def interval(self):
        cfg = (self.app.cfg.get("base") or {})
        try:
            n = float(cfg.get("syncIntervalSec") or DEFAULT_INTERVAL_SEC)
        except (TypeError, ValueError):
            n = DEFAULT_INTERVAL_SEC
        return max(MIN_INTERVAL_SEC, n)

    def enabled(self):
        """Only run once there is a profile and a base policy to run under.

        Before setup there is no policies\\base.json, and reload_policy would
        fall back to the root policy.json - which grants the workspace and
        nothing else, so every pass would be a refusal nobody asked for."""
        if not self.app.profile:
            return False
        return os.path.isfile(self.app.policy_path_for(agents_mod.BASE_ID))

    def start(self):
        """Idempotent. Called at startup and again whenever setup finishes,
        because the second of those is the moment a base policy first exists."""
        with self.lock:
            if self._thread is not None and self._thread.is_alive():
                self._wake.set()      # re-check enabled() right away
                return
            if not self.enabled():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="castlekeep-basecamp")
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def sync_now(self):
        """Ask for a pass on the next tick regardless of the fingerprint.

        Used by the bubble's refresh button. Forced rather than queued,
        because the honest answer to "did my policy edit fix it" is a sandbox
        run made after the edit, not a cached one from before it."""
        self._wake.set()
        self._fingerprint = None

    # -- the loop ---------------------------------------------------------

    def _loop(self):
        while not self._stop.is_set():
            try:
                if self.enabled():
                    self._tick()
            except Exception as e:
                # A background thread that dies takes the whole feature with
                # it and says nothing. Record and keep going.
                self._set(state="error", reason=str(e))
            self._wake.wait(self.interval())
            self._wake.clear()

    def _tick(self):
        # The post first, and on the HOST. This is the mail server putting
        # something in the inbox, not the agent reading it - see the header of
        # postman.py. It is in this thread only because this thread already
        # wakes up on the right cadence, not because the base agent does it.
        # The live calendar, on the host. Throttled inside refresh(), so
        # calling it on every tick costs one comparison most of the time.
        try:
            icsfeed_mod.refresh(self.app)
        except Exception:
            pass

        delivered = []
        try:
            delivered = postman_mod.tick(self.app.mailbox, self.app.profile)
        except Exception:
            pass
        if delivered:
            with self.lock:
                self.state["delivered"] = len(delivered)
                self.state["unread"] += len(delivered)
                self.state["at"] = time.time()
        elif self.state.get("delivered"):
            with self.lock:
                self.state["delivered"] = 0

        fp = self._stamp()
        # Two reasons to re-run, and the second one matters more than it looks.
        #
        #   1. Something in the vault changed - an agent produced an invitation
        #      or a draft and there is new work to collect.
        #
        #   2. The last run was not clean. A refusal is a state somebody is
        #      actively trying to fix, and the fix is an edit to a policy file,
        #      which changes nothing in the vault at all. Without this clause
        #      you could grant the missing path, watch the bubble stay red, and
        #      conclude the edit had not landed - when in fact nothing had
        #      thought to ask again. The policy file's mtime is in the stamp
        #      too, so the retry usually fires on the very next tick.
        clean = self.state["state"] == "ok"
        if fp == self._fingerprint and clean and not delivered:
            return
        run = self._run_sync()
        self._fingerprint = fp
        return run

    def _stamp(self):
        """What the vault looks like, plus which policy we would run under.

        policies\\base.json is part of the stamp because an edit to it changes
        the answer this thread gets without changing a single byte in the
        vault, and "my edit did nothing" is the worst thing this app can say
        to somebody who has just made a correct edit."""
        path = self.app.policy_path_for(agents_mod.BASE_ID)
        try:
            st = os.stat(path)
            pol = "%d:%d" % (st.st_mtime_ns, st.st_size)
        except OSError:
            pol = "none"
        return vault_mod.fingerprint(self.app.vault) + "||policy:" + pol

    def _run_sync(self):
        # Imported here, not at module import: agent.py imports tools, which
        # imports agents - and app.py imports this module while it is still
        # being constructed. A late import keeps that graph acyclic without
        # anybody having to hold it in their head.
        from .agent import Agent

        events = []
        agent = Agent(self.app, agents_mod.BASE_ID)
        text = agent.call_tool("sync_vaults", {}, events.append)

        run = next((e.get("run") for e in reversed(events)
                    if e.get("type") == "sandbox"), None) or {}
        outcome = run.get("outcome") or "unknown"

        if outcome != "ok":
            # A blocked or host-gated sync is the single most interesting
            # thing this thread can report, so it is kept whole rather than
            # flattened into "0 merged". _fmt_result has already turned the
            # run into the sentence the agent itself would have said.
            return self._set(state="blocked", outcome=outcome,
                             merged=0, refused=[],
                             reason=(run.get("reason") or text or "")[:600],
                             runSeq=run.get("seq"))

        result = _parse(run.get("stdout"))
        if result is None:
            return self._set(state="error", outcome=outcome, merged=0,
                             reason="sync_vaults returned something that was "
                                    "not the JSON summary it promises: "
                                    + (run.get("stdout") or "")[:300],
                             runSeq=run.get("seq"))

        merged = int(result.get("invites") or 0) + int(result.get("drafts") or 0)
        refused = [r for r in (result.get("refused") or []) if isinstance(r, dict)]
        with self.lock:
            total = self.state["total"] + merged
            unread = self.state["unread"] + merged
        # Partly refused is NOT "ok". Two of four agents getting through is
        # exactly the state a participant has just engineered by editing the
        # policy, and calling it a success would hide the thing they are
        # looking for.
        return self._set(state=("partial" if refused else "ok"),
                         outcome=outcome, merged=merged, total=total,
                         unread=unread, refused=refused, reason=None,
                         runSeq=run.get("seq"))

    def _set(self, **kw):
        with self.lock:
            self.state.update(kw)
            self.state["at"] = time.time()
            return dict(self.state)

    # -- what the bubble reads --------------------------------------------

    def mark_read(self):
        with self.lock:
            self.state["unread"] = 0

    def note_delivery(self, n):
        """A message arrived by some route other than the timer - the
        presenter's cue button. The badge has to move for that too, or the
        one delivery somebody is actually watching is the one that looks
        like nothing happened."""
        with self.lock:
            self.state["delivered"] = n
            self.state["unread"] += n
            self.state["at"] = time.time()

    def view(self):
        """The merged global view, plus how it got that way.

        The READ here is host-side, exactly like /api/mailbox and for the same
        reason - drawing a pane should not need a sandbox. What the policy
        gates is the WRITE: nothing appears below that sync_vaults was not
        allowed to put there. If this pane and the counter disagree, the
        counter is the one telling the truth about the policy."""
        with self.lock:
            sync = dict(self.state)
        summary = mailbox_mod.summary(self.app.mailbox)
        return {
            "sync": sync,
            "enabled": self.enabled(),
            "intervalSec": self.interval(),
            "pending": vault_mod.pending_count(self.app.vault),
            # The sack, with subjects. This is presenter material: the Run tab
            # draws it so you can see what lands next and fire it on a cue.
            # The bubble deliberately shows only the COUNT and the time to the
            # next one - a participant who reads tomorrow's subject lines off
            # their own screen has had the surprise spent on them early.
            "post": postman_mod.pending(self.app.mailbox,
                                        profile=self.app.profile),
            "calendarFeed": dict(getattr(self.app, "calendar", None)
                                 or {"state": "cold"}),
            "calendar": summary.get("calendar") or [],
            "inbox": summary.get("inbox") or [],
            "drafts": summary.get("drafts") or [],
        }


def _parse(stdout):
    """The JSON summary sync_vaults writes on its last line.

    Last line, not the whole buffer: PowerShell is entitled to put a warning
    above it and has done so before now."""
    for line in reversed((stdout or "").strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            got = json.loads(line)
        except ValueError:
            continue
        if isinstance(got, dict) and "invites" in got:
            return got
    return None
