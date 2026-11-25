#!/usr/bin/env python3
"""A stand-in for a Strata engine, standard library only.

The test suites talk to a real model server, which CI does not have. This answers
the handful of routes Domingo uses, with fixed text, so the suites run the same
code paths on any machine in a few seconds and with no GPU.

  GET  /health              -> {"status":"ok"}
  GET  /props               -> defaults, slots, build info
  GET  /v1/models           -> one model, "fake-model"
  GET  /slots               -> one idle slot
  POST /v1/chat/completions -> SSE: reasoning deltas, content deltas, usage, [DONE]

Usage:  python fake_engine.py [--port 8890] [--model fake-model]
"""

import argparse
import base64
import json
import re
import time
import urllib.parse
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DELAY = 0.02                      # seconds between streamed chunks, set by --delay

MARKDOWN = (
    "### Plan\n\n"
    "Small, repeatable, and easy to keep.\n\n"
    "- **Mon**: deep work block\n- **Wed**: review the week\n\n"
    "| Day | Focus | Length |\n| --- | --- | --- |\n| Mon | Deep work | 90 min |\n| Wed | Review | 30 min |\n\n"
    "```python\nschedule = {\"mon\": \"deep\", \"wed\": \"review\"}\nprint(schedule[\"mon\"])\n```\n\n"
    "Keep it under `30 minutes` on review days."
)
THINKING = (
    "The request is a plain one. I will answer with a heading, a list, a small table "
    "and a code block so every markdown feature is exercised."
)


def chunks(text, size=7):
    for i in range(0, len(text), size):
        yield text[i:i + size]


def first_pixel(png):
    """The top-left pixel of a PNG, 8-bit RGB or RGBA.

    Row 0, column 0 needs no filter reconstruction: Sub, Up and Paeth all add
    nothing when there is no left and no above pixel, so the raw bytes are the
    value. Returns (r, g, b) or None.
    """
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    i, idat, meta = 8, b"", None
    while i + 8 <= len(png):
        ln = int.from_bytes(png[i:i + 4], "big")
        tag = png[i + 4:i + 8]
        data = png[i + 8:i + 8 + ln]
        if tag == b"IHDR":
            meta = (int.from_bytes(data[0:4], "big"), int.from_bytes(data[4:8], "big"),
                    data[8], data[9])          # w, h, bit depth, colour type
        elif tag == b"IDAT":
            idat += data
        elif tag == b"IEND":
            break
        i += 12 + ln
    if not meta or meta[2] != 8 or meta[3] not in (2, 6):
        return None
    try:
        raw = zlib.decompress(idat)
    except Exception:
        return None
    n = 3 if meta[3] == 2 else 4
    if len(raw) < 1 + n:
        return None
    return (raw[1], raw[2], raw[3])


def colour_of(urls):
    """Name a colour from the image, so the stub's answer depends on the input."""
    for u in urls:
        b64 = u.split(",", 1)[1] if "," in u else u
        try:
            px = first_pixel(base64.b64decode(b64))
        except Exception:
            px = None
        if not px:
            continue
        r, g, b = px
        if r > 180 and g < 90 and b < 90:
            return "Red"
        if r > 200 and 90 <= g < 200 and b < 130:
            return "Orange"
        if r > 200 and g > 180 and b < 150:
            return "Yellow"
        if b > 180 and r < 90:
            return "Blue"
        if g > 180 and r < 120:
            return "Green"
    return "Orange"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    model = "fake-model"
    quiet = True
    log_requests = False

    def log_message(self, fmt, *args):
        if not self.quiet:
            super().log_message(fmt, *args)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/health", "/healthz"):
            return self._json({"status": "ok"})
        if path == "/props":
            return self._json({
                "default_generation_settings": {"n_ctx": 262144, "params": {
                    "temperature": 1.0, "top_p": 0.95, "top_k": 20, "n_predict": -1}},
                "total_slots": 1, "model_alias": {}, "build_info": "fake-engine-1.0.0",
                "modalities": {"vision": True}, "is_sleeping": False,
                "model_path": "/fake/model.gguf", "models_autoload": [self.model],
                "chat_template": "{{ messages }}",
                "chat_template_caps": {"supports_tools": True, "supports_system_role": True},
            })
        if path == "/slots":
            return self._json([{"index": 0, "state": "idle"}])
        if path == "/v1/models":
            return self._json({"object": "list", "data": [
                {"id": self.model, "object": "model", "owned_by": "fake",
                 "ctx": 262144, "alias_of": None, "vision": True}]})
        return self._json({"error": {"message": "no such route: " + path}}, 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            req = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            req = {}
        if path != "/v1/chat/completions":
            return self._json({"error": {"message": "no such route: " + path}}, 404)

        msgs = req.get("messages") or []
        last = msgs[-1] if msgs else {}
        content = last.get("content")
        has_image = isinstance(content, list) and any(
            isinstance(p, dict) and (p.get("type") == "image_url" or "image_url" in p) for p in content)
        text = content if isinstance(content, str) else " ".join(
            p.get("text", "") for p in content if isinstance(p, dict)) if isinstance(content, list) else ""
        # A stub that always returns the same paragraph cannot prove a relay worked,
        # so honour the suites' "Reply with exactly: X" prompts and echo X back.
        exact = re.search(r"Reply with exactly:\s*(.+?)\s*$", text.strip())
        image_urls = [p.get("image_url", {}).get("url", "") for p in content
                      if isinstance(p, dict) and p.get("type") == "image_url"] if isinstance(content, list) else []
        if self.log_requests:
            print("chat: msgs=%d last_type=%s images=%d effort=%s" % (
                len(msgs), type(content).__name__, len(image_urls), req.get("reasoning_effort")), flush=True)
        if has_image:
            answer = colour_of(image_urls)
        elif exact:
            answer = exact.group(1)
        else:
            answer = MARKDOWN
        effort = req.get("reasoning_effort")
        # Mirrors the current engine's template: off answers straight away, low
        # thinks briefly, medium and above think at length.
        if effort in (None, "off"):
            think = ""
        elif effort == "low":
            think = "Brief look at the request, then answer."
        else:
            think = THINKING

        if not req.get("stream"):
            # the real engine answers a non-stream request with one JSON completion
            return self._json({
                "id": "fake", "object": "chat.completion", "model": req.get("model", self.model),
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": answer}}],
                "usage": {"prompt_tokens": 42, "completion_tokens": len(answer) // 4 + 1,
                          "total_tokens": 42 + len(answer) // 4}})

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def emit(obj):
            self._chunk("data: " + json.dumps(obj) + "\n\n")

        def emit_chunk(delta, finish=None):
            emit({"id": "fake", "object": "chat.completion.chunk", "model": req.get("model", self.model),
                  "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]})

        # A real model takes time. Streaming instantly would hide every state the
        # suites check between the first token and the last, so chunks are paced.
        emit_chunk({"role": "assistant"})
        for piece in chunks(think, 11):
            time.sleep(DELAY)
            emit_chunk({"reasoning_content": piece})
        for piece in chunks(answer):
            time.sleep(DELAY)
            emit_chunk({"content": piece})
        emit_chunk(None, finish="stop")
        emit({"id": "fake", "object": "chat.completion.chunk", "model": req.get("model", self.model),
              "choices": [],
              "usage": {"prompt_tokens": 42, "completion_tokens": len(answer) // 4 + 1,
                        "total_tokens": 42 + len(answer) // 4}})
        self._chunk(b"data: [DONE]\n\n")
        self._chunk(b"")
        self.close_connection = True

    def _chunk(self, payload):
        data = payload.encode() if isinstance(payload, str) else payload
        self.wfile.write(b"%X\r\n" % len(data) + data + b"\r\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8890)
    ap.add_argument("--model", default="fake-model")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--delay", type=float, default=0.02, help="seconds between streamed chunks")
    ap.add_argument("--log-requests", action="store_true", help="print one line per chat request")
    a = ap.parse_args()
    global DELAY
    DELAY = a.delay
    Handler.log_requests = a.log_requests
    Handler.model = a.model
    Handler.quiet = not a.verbose
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print("fake engine on http://%s:%d  model=%s" % (a.host, a.port, a.model), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
