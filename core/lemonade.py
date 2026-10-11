"""
core/lemonade.py - talks to Lemonade Server, which runs the model on this
machine and never leaves it.

Lemonade is on the HOST, deliberately. It is not in the sandbox and does not
need to be: the thing we are containing is what the agent *does*, not what it
thinks. Keeping inference on the host also removes the single most common way
these demos die - AppContainers are blocked from loopback by default, so a
sandboxed process cannot reach 127.0.0.1 without an explicit exemption, and
when it fails it fails silently.

stdlib only: urllib. No requests, no openai package.
"""

import json
import re
import time
import urllib.error
import urllib.request

# Lemonade has moved its route prefix around between versions, and a hard-coded
# guess is a bad first impression. Try them in order.
ROUTE_PREFIXES = ["/api/v1", "/api/v0", "/v1", ""]

THINK = re.compile(r"<think>.*?</think>\s*", re.S | re.I)
OPEN_THINK = re.compile(r"<think>.*\Z", re.S | re.I)


class LemonadeError(Exception):
    pass


def _post(url, payload, timeout, stream=False):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json",
                 "Accept": "text/event-stream" if stream else "application/json"},
        method="POST")
    return urllib.request.urlopen(req, timeout=timeout)


def _get(url, timeout):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


class Lemonade:
    def __init__(self, cfg):
        lc = cfg.get("lemonade") or {}
        self.base = (lc.get("baseUrl") or "http://127.0.0.1:13305").rstrip("/")
        self.model = lc.get("model")
        self.temperature = lc.get("temperature", 0.3)
        self.max_tokens = lc.get("maxTokens", 1536)
        self.timeout = lc.get("requestTimeoutSec", 300)
        self.tool_mode = lc.get("toolCallMode", "auto")   # auto | native | prompted
        self.enable_thinking = lc.get("enableThinking", False)
        self.tool_call_max_tokens = lc.get("toolCallMaxTokens", 256)
        self.prefix = None
        self._native_ok = None if self.tool_mode == "auto" else (
            self.tool_mode == "native")

    # -- discovery ---------------------------------------------------------

    def health(self):
        """Find the route prefix and list the models. Returns a plain dict the
        UI can render without interpretation."""
        last = None
        for prefix in ROUTE_PREFIXES:
            url = "%s%s/models" % (self.base, prefix)
            try:
                with _get(url, 8) as r:
                    body = json.loads(r.read().decode("utf-8", "replace"))
            except Exception as e:
                last = "%s -> %s" % (url, e)
                continue

            items = body.get("data") if isinstance(body, dict) else body
            models = []
            for m in items or []:
                models.append(m.get("id") if isinstance(m, dict) else str(m))
            self.prefix = prefix
            loaded = self.model in models if self.model else False

            # If the name is wrong, the useful thing is not "wrong name" - it
            # is "here are the four you probably meant". Two hundred model
            # names is not a list anybody reads.
            near = []
            if self.model and not loaded:
                stem = re.split(r"[-_.]", self.model)[0].lower()
                near = [m for m in models if stem and stem in m.lower()][:8]

            return {
                "reachable": True,
                "baseUrl": self.base,
                "routePrefix": prefix or "/",
                "models": models,
                "model": self.model,
                "modelPresent": loaded,
                "suggestions": near,
                "note": None if loaded else
                        ("Lemonade is running but is not serving '%s'. Nothing "
                         "the agent does will work until this matches. %s"
                         "Run `python workshop\\models.py` to list and pick one."
                         % (self.model,
                            ("Closest names it does serve: %s. "
                             % ", ".join(near)) if near else "")),
            }

        return {
            "reachable": False,
            "baseUrl": self.base,
            "models": [],
            "model": self.model,
            "modelPresent": False,
            "suggestions": [],
            "note": "Could not reach Lemonade Server. Start it with "
                    "`lemonade-server serve` and check lemonade.baseUrl in "
                    "config.json. Last attempt: %s" % last,
        }

    def _url(self, path):
        if self.prefix is None:
            self.health()
        return "%s%s%s" % (self.base, self.prefix or "", path)

    # -- warm up -----------------------------------------------------------

    def warmup(self, timeout=None):
        """Send one throwaway prompt so the weights are resident before a
        human is waiting on them.

        A 35B MoE has to be read off disk and laid out in memory on first use.
        On a Strix Halo box that is tens of seconds. If the first request is
        the user's first chat message, they watch a dragon do nothing and
        conclude the thing is broken - and in a workshop, so does the room.
        So: pay that cost at startup, where a progress line is expected, and
        hand the user a model that answers immediately.

        One token is enough. We are loading weights, not generating text.
        """
        t0 = time.time()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "Say OK."}],
            "max_tokens": 1,
            "temperature": 0,
            "stream": False,
        }
        try:
            with _post(self._url("/chat/completions"), payload,
                       timeout or self.timeout) as r:
                body = json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            missing = "model_not_found" in detail or e.code == 404
            return {"ok": False, "ms": int((time.time() - t0) * 1000),
                    "modelMissing": missing,
                    "error": ("Lemonade does not have '%s' loaded. %s"
                              % (self.model, detail)) if missing else
                             "HTTP %s from Lemonade: %s" % (e.code, detail)}
        except Exception as e:
            return {"ok": False, "ms": int((time.time() - t0) * 1000),
                    "modelMissing": False,
                    "error": "Could not reach Lemonade: %s" % e}

        ms = int((time.time() - t0) * 1000)
        if not (body.get("choices") or []):
            return {"ok": False, "ms": ms, "modelMissing": False,
                    "error": "Lemonade answered but returned no choices: %s"
                             % json.dumps(body)[:200]}
        return {"ok": True, "ms": ms, "modelMissing": False, "error": None}

    # -- chat --------------------------------------------------------------

    def chat(self, messages, tools=None, stream=True):
        """Yields events:
            {"type": "token",      "text": str}
            {"type": "thinking",   "text": str}
            {"type": "tool_calls", "calls": [{"id","name","arguments"}]}
            {"type": "done",       "finish": str}
            {"type": "error",      "message": str}
        Tool calls are negotiated: try the native `tools` parameter first, and
        if the server will not take it, fall back to asking the model for a
        JSON block in its text. Both paths produce the same event.
        """
        use_native = self._native_ok
        if use_native is None:
            use_native = True

        # Use a smaller token budget when the model is continuing a tool loop —
        # it only needs to emit a short JSON call, not a prose answer.
        last = messages[-1] if messages else {}
        mt = (self.tool_call_max_tokens
              if (tools and last.get("role") == "tool") else None)

        if tools and use_native:
            try:
                got_any = False
                for ev in self._chat_once(messages, tools=tools, stream=stream,
                                          max_tokens=mt):
                    got_any = True
                    yield ev
                if got_any:
                    self._native_ok = True
                    return
            except LemonadeError as e:
                if not _looks_like_tool_rejection(str(e)):
                    yield {"type": "error", "message": str(e)}
                    return
                self._native_ok = False
                yield {"type": "notice",
                       "message": "This backend would not accept the tools "
                                  "parameter, so CastleKeep switched to prompted "
                                  "tool calls. Same tools, different wire format."}

        # Prompted mode (or no tools at all).
        msgs = messages
        if tools:
            msgs = _inject_tool_prompt(messages, tools)
        buf = []
        try:
            for ev in self._chat_once(msgs, tools=None, stream=stream):
                if ev["type"] == "token":
                    buf.append(ev["text"])
                    continue
                yield ev
        except LemonadeError as e:
            yield {"type": "error", "message": str(e)}
            return

        text = "".join(buf)
        if tools:
            calls, prose = _parse_prompted_calls(text)
            if prose:
                yield {"type": "token", "text": prose}
            if calls:
                yield {"type": "tool_calls", "calls": calls}
                return
        elif text:
            yield {"type": "token", "text": text}

    def _chat_once(self, messages, tools=None, stream=True, max_tokens=None):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "stream": bool(stream),
        }
        if not self.enable_thinking:
            payload["enable_thinking"] = False
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        url = self._url("/chat/completions")
        try:
            resp = _post(url, payload, self.timeout, stream=stream)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:1500]
            raise LemonadeError("HTTP %s from %s: %s" % (e.code, url, detail))
        except Exception as e:
            raise LemonadeError("Could not reach %s: %s" % (url, e))

        if not stream:
            body = json.loads(resp.read().decode("utf-8", "replace"))
            for ev in _events_from_message(
                    (body.get("choices") or [{}])[0].get("message") or {}):
                yield ev
            yield {"type": "done", "finish": "stop"}
            return

        pending = {}            # index -> {"id","name","arguments"}
        finish = "stop"
        in_think = False
        t_request = time.time()
        first_token_sent = False
        with resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                choice = (chunk.get("choices") or [{}])[0]
                finish = choice.get("finish_reason") or finish
                delta = choice.get("delta") or choice.get("message") or {}

                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = pending.setdefault(idx, {"id": None, "name": "",
                                                    "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]

                piece = delta.get("content")
                rtext = delta.get("reasoning_content") or delta.get("reasoning")
                if rtext:
                    yield {"type": "thinking", "text": rtext}
                if not piece:
                    continue
                # qwen3 emits <think>...</think> inline when reasoning is on.
                if in_think:
                    if "</think>" in piece:
                        head, piece = piece.split("</think>", 1)
                        yield {"type": "thinking", "text": head}
                        in_think = False
                    else:
                        yield {"type": "thinking", "text": piece}
                        continue
                if "<think>" in piece:
                    head, tail = piece.split("<think>", 1)
                    if head:
                        yield {"type": "token", "text": head}
                    if "</think>" in tail:
                        think, piece = tail.split("</think>", 1)
                        yield {"type": "thinking", "text": think}
                    else:
                        yield {"type": "thinking", "text": tail}
                        in_think = True
                        continue
                if piece:
                    if not first_token_sent:
                        yield {"type": "perf",
                               "ttftMs": int((time.time() - t_request) * 1000)}
                        first_token_sent = True
                    yield {"type": "token", "text": piece}

        if pending:
            calls = []
            for _, slot in sorted(pending.items()):
                calls.append({
                    "id": slot["id"] or ("call_%d" % len(calls)),
                    "name": slot["name"],
                    "arguments": _loads_loose(slot["arguments"]),
                })
            if not first_token_sent:
                yield {"type": "perf",
                       "ttftMs": int((time.time() - t_request) * 1000)}
            yield {"type": "tool_calls", "calls": calls}
        yield {"type": "done", "finish": finish}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _looks_like_tool_rejection(msg):
    m = msg.lower()
    return any(s in m for s in (
        "tool", "unsupported", "unknown field", "not supported", "400",
        "422", "unrecognized", "invalid"))


def _events_from_message(message):
    tcs = message.get("tool_calls") or []
    content = message.get("content") or ""
    content = THINK.sub("", content)
    if content.strip():
        yield {"type": "token", "text": content}
    if tcs:
        calls = []
        for i, tc in enumerate(tcs):
            fn = tc.get("function") or {}
            calls.append({"id": tc.get("id") or "call_%d" % i,
                          "name": fn.get("name", ""),
                          "arguments": _loads_loose(fn.get("arguments"))})
        yield {"type": "tool_calls", "calls": calls}


def _loads_loose(s):
    if isinstance(s, dict):
        return s
    if not s:
        return {}
    try:
        return json.loads(s)
    except ValueError:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
    return {"_raw": s}


TOOL_BLOCK = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>|```(?:json)?\s*(\{[^`]*?\"tool\"[^`]*?\})\s*```",
    re.S)


def _inject_tool_prompt(messages, tools):
    lines = [
        "You can run tools. To run one, reply with ONLY this, and nothing else:",
        "",
        "<tool_call>{\"tool\": \"<name>\", \"arguments\": {...}}</tool_call>",
        "",
        "One tool call per reply. Wait for the result before the next one.",
        "When you have enough information, answer in plain prose with no tool call.",
        "",
        "Available tools:",
    ]
    for t in tools:
        fn = t.get("function") or t
        lines.append("- %s: %s" % (fn.get("name"), fn.get("description", "")))
        params = (fn.get("parameters") or {}).get("properties") or {}
        for pname, spec in params.items():
            lines.append("    %s (%s) %s" % (pname, spec.get("type", "string"),
                                             spec.get("description", "")))
    block = {"role": "system", "content": "\n".join(lines)}
    out = list(messages)
    insert_at = 1 if out and out[0].get("role") == "system" else 0
    out.insert(insert_at, block)
    return out


def _parse_prompted_calls(text):
    text = THINK.sub("", text or "")
    text = OPEN_THINK.sub("", text)
    calls, spans = [], []
    for m in TOOL_BLOCK.finditer(text):
        raw = m.group(1) or m.group(2)
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        name = obj.get("tool") or obj.get("name")
        if not name:
            continue
        calls.append({"id": "call_%d" % len(calls), "name": name,
                      "arguments": obj.get("arguments") or obj.get("args") or {}})
        spans.append(m.span())

    prose = text
    for start, end in reversed(spans):
        prose = prose[:start] + prose[end:]
    return calls, prose.strip()
