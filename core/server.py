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

from . import policy as policy_mod
from . import tools as tools_mod
from . import verify as verify_mod
from .agent import Agent

UI_DIR = None   # set by make_server

# Page aliases, checked before the extensionless-route rule.
PAGES = {
    "/": "/launch.html",
    "/app": "/index.html",
    "/launch": "/launch.html",
}

_EXTRA_TYPES = {".woff2": "font/woff2", ".woff": "font/woff"}


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
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/api/"):
                q = urllib.parse.parse_qs(parsed.query)
                self.q = {k: v[0] for k, v in q.items() if v}
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

    def _api_get(self, path):
        app = self.app
        agent = (getattr(self, "q", {}) or {}).get("agent")
        if path == "/api/state":
            pol = app.reload_policy()
            app.reload_profiles()
            # config.json gets the same treatment as policy.json: edited on
            # disk, picked up on the next poll. The UI should never be able to
            # disagree with the file about which model it is talking to.
            app.refresh_config()
            return self._json({
                "version": "1.0.0",
                "projectDir": app.project_dir,
                "workspace": app.workspace,
                "probe": app.probe,
                "capabilities": app.caps,
                "dialect": app.dialect,
                "negotiation": app.negotiation,
                "notes": app.startup_notes,
                "lemonade": app.lemonade.health(),
                "warmup": app.warmup_state(),
                # The host's own default, which belongs to the Run tab and to
                # verify. The agents each bring their own and are listed
                # separately below.
                "policy": pol,
                "lint": policy_mod.lint(pol, app.path_ctx(), app.caps),
                "tools": tools_mod.describe(pol),
                "profiles": app.agent_summaries(),
                "defaultAgent": app.profiles.default_name(),
                "profileNotes": app.profile_notes(),
                "paths": app.path_ctx(),
                "runs": app.recent_runs(),
                "refusals": app.refusals(),
                "mxcExe": app.mxc.exe,
                "mxcError": app.mxc.exe_error,
                "setup": app.setup(),
                "host": app.host_info(),
                "workspaceFiles": app.workspace_count(),
            })
        if path == "/api/config/reload":
            # Cheap: no MXC re-probe. Just the file.
            return self._json({"changed": app.refresh_config(),
                               "lemonade": app.lemonade.health(),
                               "warmup": app.warmup_state(),
                               "notes": app.startup_notes})
        if path == "/api/profiles":
            return self._json({"profiles": app.agent_summaries(),
                               "defaultAgent": app.profiles.default_name(),
                               "notes": app.profile_notes()})
        if path == "/api/policy":
            # ?agent=health is that agent's own file. No agent at all is
            # policy.json, which is the host default and nobody's boundary.
            return self._json(app.policy_for(agent))
        if path == "/api/runs":
            return self._json({"runs": app.recent_runs(200, agent=agent)})
        if path == "/api/refusals":
            return self._json({"refusals": app.refusals(200, agent=agent)})
        if path == "/api/health":
            return self._json({"lemonade": app.lemonade.health(),
                               "warmup": app.warmup_state(),
                               "mxc": app.probe})
        return self._json({"error": "no such endpoint"}, 404)

    # -- POST -------------------------------------------------------------

    def _api_post(self, path):
        app = self.app

        if path == "/api/setup":
            # The launch wizard's two answers. Deliberately the only write the
            # launch page makes: it reports on the machine, it does not change
            # it, and the one thing it does persist is the thing the person
            # typed.
            body = self._body()
            try:
                saved = app.save_setup(name=body.get("assistantName"),
                                       backdrop=body.get("backdrop"))
            except ValueError as e:
                return self._json({"saved": False, "error": str(e)}, 400)
            except OSError as e:
                return self._json({"saved": False,
                                   "error": "config.json could not be written "
                                            "(%s)." % e}, 500)
            return self._json({"saved": True, "setup": saved})

        if path == "/api/policy":
            # The policy body arrives either as the whole body, the way it
            # always did, or wrapped with the agent it belongs to. Both shapes
            # are accepted so that a saved copy of the old single-policy UI
            # still works against this server.
            body = self._body()
            agent = body.pop("agent", None) if isinstance(body, dict) else None
            incoming = body.get("policy") if (agent and "policy" in body) else body
            lint = policy_mod.lint(incoming, app.path_ctx(), app.caps)
            if any(n["level"] == "error" for n in lint):
                return self._json({"saved": False, "lint": lint}, 400)
            if agent:
                prof = app.profiles.get(agent)
                if prof is None:
                    return self._json({"saved": False,
                                       "error": "no agent called %r" % agent}, 404)
                app.profiles.save(prof.name, incoming)
            else:
                app.save_policy(incoming)
            return self._json({"saved": True, "agent": agent,
                               "policy": app.policy_for(agent), "lint": lint,
                               "notes": app.profile_notes()})

        if path == "/api/policy/preview":
            body = self._body()
            pol = body.get("policy") or app.policy_for(body.get("agent"))
            cmd = body.get("command") or tools_mod.shell_cmd("dir /b")
            try:
                cfg, notes = app.compile_for(pol, cmd)
            except policy_mod.PolicyError as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"config": cfg, "notes": notes,
                               "lint": policy_mod.lint(pol, app.path_ctx(), app.caps)})

        if path == "/api/policy/dryrun":
            body = self._body()
            who = body.get("agent")
            pol = app.policy_for(who)
            cfg, notes = app.compile_for(pol, tools_mod.shell_cmd("ver"))
            label = "policy dry-run (%s)" % who if who else "policy dry-run"
            run = app.mxc.execute(cfg, label=label, dry_run=True)
            run["agent"] = who
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

            who = body.get("agent")
            agent = Agent(app, who)
            if who and agent.name != who:
                self._sse({"type": "notice", "message":
                           "There is no agent called %r, so this went to %s."
                           % (who, agent.title)})
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
        # Python's table predates woff2 on some builds, and a font served as
        # application/octet-stream is refused outright by Firefox.
        ctype = (_EXTRA_TYPES.get(os.path.splitext(full)[1].lower())
                 or mimetypes.guess_type(full)[0]
                 or "application/octet-stream")
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
