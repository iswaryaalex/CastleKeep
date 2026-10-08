"""
core/server.py - a small local HTTP server. Stdlib only.

Binds to 127.0.0.1. There is no auth because there is no remote: if something
else can already reach your loopback interface and make POSTs, CastleKeep is
not your problem. It does check the Origin header, so a random web page you
happen to have open cannot drive it.
"""

import json
import mimetypes
import os
import posixpath
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import agents as agents_mod
from . import mailbox as mailbox_mod
from . import policy as policy_mod
from . import profile as profile_mod
from . import tools as tools_mod
from . import verify as verify_mod
from .agent import Agent

UI_DIR = None   # set by make_server

# Page aliases, checked before the extensionless-route rule.
PAGES = {
    "/": "/launch.html",
    "/app": "/index.html",
    "/launch": "/launch.html",
    "/onboard": "/onboard.html",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "CastleKeep"
    protocol_version = "HTTP/1.1"

    # -- plumbing ---------------------------------------------------------

    def log_message(self, fmt, *args):
        if self.app.cfg.get("verboseHttp"):
            super().log_message(fmt, *args)

    @property
    def app(self):
        return self.server.app

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = urllib.parse.urlparse(origin).hostname
        return host in ("127.0.0.1", "localhost", "::1")

    def _send(self, code, body=b"", ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=str), "application/json")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def _sse_open(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

    def _sse(self, obj):
        try:
            self.wfile.write(("data: %s\n\n"
                              % json.dumps(obj, default=str)).encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            raise _ClientGone()

    # -- routing ----------------------------------------------------------

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path.startswith("/api/"):
                return self._api_get(path)
            return self._static(path)
        except Exception:
            self._json({"error": traceback.format_exc()}, 500)

    def do_PUT(self):
        return self.do_POST()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._origin_ok():
            return self._json({"error": "cross-origin request refused"}, 403)
        try:
            return self._api_post(path)
        except _ClientGone:
            return
        except Exception:
            try:
                self._json({"error": traceback.format_exc()}, 500)
            except Exception:
                pass

    # -- GET --------------------------------------------------------------

    def _agent_param(self):
        """Which subagent this request is about.

        Absent means the active one from the profile. An explicit empty string
        means the root policy.json - that is how Phase 1 and anything written
        before subagents existed keep addressing the file they always meant."""
        # keep_blank_values, because "?agent=" is a meaningful request - it
        # means the root policy.json - and the default would silently drop it
        # and hand back the active agent's policy instead.
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query,
                                  keep_blank_values=True)
        if "agent" not in q:
            return self.app.active_agent()
        return q["agent"][0] or None

    def _api_get(self, path):
        app = self.app
        if path == "/api/state":
            agent_id = self._agent_param()
            pol = app.reload_policy(agent_id)
            # config.json gets the same treatment as policy.json: edited on
            # disk, picked up on the next poll. The UI should never be able to
            # disagree with the file about which model it is talking to.
            app.refresh_config()
            return self._json({
                "version": "1.0.0",
                "projectDir": app.project_dir,
                "workspace": app.workspace,
                "mailbox": app.mailbox,
                "profile": app.profile,
                "agents": agents_mod.describe(app.profile),
                "activeAgent": agent_id,
                "policyFile": app.rel_policy_path(agent_id),
                "probe": app.probe,
                "capabilities": app.caps,
                "dialect": app.dialect,
                "negotiation": app.negotiation,
                "notes": app.startup_notes,
                "lemonade": app.lemonade.health(),
                "warmup": app.warmup_state(),
                "policy": pol,
                "lint": policy_mod.lint(pol, app.path_ctx(), app.caps),
                "tools": tools_mod.describe(pol, agent_id),
                "paths": app.path_ctx(),
                "runs": app.recent_runs(),
                "refusals": app.refusals(),
                "mxcExe": app.mxc.exe,
                "mxcError": app.mxc.exe_error,
            })
        if path == "/api/config/reload":
            # Cheap: no MXC re-probe. Just the file.
            return self._json({"changed": app.refresh_config(),
                               "lemonade": app.lemonade.health(),
                               "warmup": app.warmup_state(),
                               "notes": app.startup_notes})
        if path == "/api/policy":
            return self._json(app.reload_policy(self._agent_param()))
        if path == "/api/profile":
            return self._json({"profile": app.profile,
                               "agents": agents_mod.describe(app.profile)})
        if path == "/api/mailbox":
            # Host-side read, not sandboxed - exactly like Lemonade. This
            # draws the pane so somebody can see what the agent is working on.
            # It is NOT how the agent reads mail: that goes through the tools,
            # into a sandbox, under the policy. If this pane and the agent
            # disagree about what is readable, the policy is working.
            return self._json(mailbox_mod.summary(app.mailbox))
        if path == "/api/runs":
            return self._json({"runs": app.recent_runs(200)})
        if path == "/api/refusals":
            return self._json({"refusals": app.refusals(200)})
        if path == "/api/health":
            return self._json({"lemonade": app.lemonade.health(),
                               "warmup": app.warmup_state(),
                               "mxc": app.probe})
        return self._json({"error": "no such endpoint"}, 404)

    # -- POST -------------------------------------------------------------

    def _api_post(self, path):
        app = self.app

        if path == "/api/profile":
            body = self._body()
            saved, written = app.set_profile(body)
            return self._json({"profile": saved, "policiesWritten": written,
                               "agents": agents_mod.describe(saved)})

        if path == "/api/profile/reset":
            profile_mod.clear(app.project_dir)
            app.profile = None
            return self._json({"ok": True})

        if path == "/api/policy":
            agent_id = self._agent_param()
            incoming = self._body()
            lint = policy_mod.lint(incoming, app.path_ctx(), app.caps)
            if any(n["level"] == "error" for n in lint):
                return self._json({"saved": False, "lint": lint}, 400)
            saved = app.save_policy(incoming, agent_id)
            return self._json({"saved": True, "policy": saved, "lint": lint,
                               "policyFile": app.rel_policy_path(agent_id)})

        if path == "/api/policy/preset":
            body = self._body()
            agent_id = body.get("agent") or self._agent_param()
            saved = app.apply_preset(agent_id, body.get("preset"))
            if saved is None:
                return self._json({"error": "no such preset"}, 404)
            return self._json({"saved": True, "policy": saved,
                               "lint": policy_mod.lint(saved, app.path_ctx(),
                                                       app.caps)})

        if path == "/api/policy/preview":
            body = self._body()
            pol = body.get("policy") or app.reload_policy(self._agent_param())
            cmd = body.get("command") or tools_mod.shell_cmd("dir /b")
            try:
                cfg, notes = app.compile_for(pol, cmd)
            except policy_mod.PolicyError as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"config": cfg, "notes": notes,
                               "lint": policy_mod.lint(pol, app.path_ctx(), app.caps)})

        if path == "/api/policy/dryrun":
            pol = app.reload_policy(self._agent_param())
            cfg, notes = app.compile_for(pol, tools_mod.shell_cmd("ver"))
            run = app.mxc.execute(cfg, label="policy dry-run", dry_run=True)
            app.record_run(run)
            return self._json({"run": _slim(run), "notes": notes})

        if path == "/api/warmup":
            # The launch screen's retry. Somebody who got a red model line,
            # alt-tabbed, started Lemonade or ran models.py --pick, and came
            # back needs a way to re-ask without restarting the process - so
            # this re-reads config.json and re-resolves the route prefix
            # before deciding, rather than warming whatever was true at boot.
            app.reload_config()
            app.lemonade.prefix = None
            app.lemonade_health = h = app.lemonade.health()
            if not h.get("reachable"):
                app.warmup = {"state": "unreachable", "error": h.get("note")}
            elif not h.get("modelPresent"):
                app.warmup = {"state": "no-model", "error": h.get("note"),
                              "suggestions": h.get("suggestions") or []}
            else:
                app.start_warmup()
            return self._json({"ok": True, "lemonade": h,
                               "warmup": app.warmup_state()})

        if path == "/api/rescan":
            app.startup_notes = []
            app.mxc._probe_cache = None
            app.lemonade.prefix = None
            app.start()
            return self._json({"ok": True, "probe": app.probe,
                               "capabilities": app.caps, "notes": app.startup_notes})

        if path == "/api/chat":
            body = self._body()
            self._sse_open()

            # Say what is actually wrong. Without this the user types a
            # message, the request 404s inside the client, and a stack trace
            # about model_not_found arrives in the chat window - which reads
            # as "the app is broken" rather than "the model name in
            # config.json does not match anything Lemonade is serving".
            w = app.warmup_state()
            if w.get("state") in ("no-model", "unreachable", "failed"):
                self._sse({"type": "error", "message": w.get("error") or
                           "The model is not available."})
                self._sse({"type": "done", "text": ""})
                return
            if w.get("state") == "warming":
                self._sse({"type": "notice", "message":
                           "Loading %s into memory - the first answer will be "
                           "slow, the rest will not." % (w.get("model") or "the model")})

            agent = Agent(app, body.get("agent"))
            try:
                agent.turn(body.get("message") or "",
                           body.get("history") or [], self._sse)
            except _ClientGone:
                return
            except Exception:
                self._sse({"type": "error", "message": traceback.format_exc()})
                self._sse({"type": "done", "text": ""})
            return

        if path == "/api/tool":
            body = self._body()
            self._sse_open()
            agent = Agent(app, body.get("agent"))
            try:
                text = agent.call_tool(body.get("name") or "",
                                       body.get("arguments") or {}, self._sse)
                self._sse({"type": "done", "text": text})
            except _ClientGone:
                return
            except Exception:
                self._sse({"type": "error", "message": traceback.format_exc()})
                self._sse({"type": "done", "text": ""})
            return

        if path == "/api/verify":
            self._sse_open()
            try:
                for ev in verify_mod.run_all(app):
                    self._sse(ev)
            except _ClientGone:
                return
            except Exception:
                self._sse({"type": "error", "message": traceback.format_exc()})
            self._sse({"type": "done"})
            return

        return self._json({"error": "no such endpoint"}, 404)

    # -- static -----------------------------------------------------------

    def _static(self, path):
        # The front door is the launch screen, not the app. It is where the
        # host and the model get checked and the weights get loaded, so
        # arriving anywhere else first means arriving before the app can
        # answer. /app is an alias rather than a rename so that anyone with
        # /index.html bookmarked still lands somewhere.
        alias = PAGES.get(path.rstrip("/") or "/")
        if alias:
            path = alias
        # Extensionless page routes. Somebody reading the workshop handout will
        # type /phase1, not /phase1.html, and a 404 at that moment costs more
        # than three lines of code.
        elif "." not in posixpath.basename(path):
            path = path.rstrip("/") + ".html"
        rel = posixpath.normpath(urllib.parse.unquote(path)).lstrip("/")
        full = os.path.normpath(os.path.join(UI_DIR, rel))
        if not full.startswith(UI_DIR) or not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",
                                                  "image/svg+xml"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)


class _ClientGone(Exception):
    pass


def _slim(run):
    out = dict(run)
    out["stdout"] = (out.get("stdout") or "")[:4000]
    out["stderr"] = (out.get("stderr") or "")[:4000]
    return out


def make_server(app, ui_dir, port):
    global UI_DIR
    UI_DIR = os.path.abspath(ui_dir)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    httpd.app = app
    return httpd
