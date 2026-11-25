#!/usr/bin/env python3
"""Domingo - a small, light chat client for a Strata (OpenAI-compatible) model server.

One file, standard library only. It serves a single-page chat UI and proxies it to
the local Strata API, adding the API key server-side so:

  * the browser never sees the key,
  * CORS is a non-issue (the engine sends no CORS headers),
  * the same file runs as a shared server on the machine that hosts the model,
    or as a local proxy on a machine that reaches the model over the network.

Usage
  python domingo.py                                    # find a local Strata, UI on :8899
  python domingo.py --host 0.0.0.0 --token secret      # share on the LAN / tailnet
  python domingo.py --url http://HOST:PORT --key KEY   # reach a remote engine
  python domingo.py --advertise https://host.ts.net:8443   # announce a proxy address

Config file (domingo.json next to this file, else ~/.domingo.json) holds any of:
  url, key, model, host, port, token, name, system, open, advertise
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Checked before the http.server import below, so an old interpreter gets a
# sentence telling it what to install instead of an internal import error.
MIN_PYTHON = (3, 9)


def _python_too_old():
    sys.stderr.write(
        "Domingo needs Python %d.%d or newer. This is %d.%d.%d.\n"
        "  Windows: download from https://www.python.org/downloads/windows/ and tick\n"
        "           \"Add python.exe to PATH\" during setup.\n"
        "  macOS:   brew install python, or https://www.python.org/downloads/macos/\n"
        "  Linux:   sudo apt install python3   (or your package manager)\n"
        % (MIN_PYTHON[0], MIN_PYTHON[1],
           sys.version_info[0], sys.version_info[1], sys.version_info[2]))
    sys.exit(1)


if sys.version_info < MIN_PYTHON:
    _python_too_old()

from http import HTTPStatus                                    # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer   # noqa: E402

VERSION = "0.2.0"
MAX_BODY = 64 * 1024 * 1024          # room for base64 screenshots
UPSTREAM_TIMEOUT = 1800.0            # long: thinking models can run for minutes
FORWARD_FIELDS = (
    # Sampling is Strata's job: the engine's own /props defaults apply and Domingo
    # sends none of these. The list stays so a peer instance can pass them through.
    "messages", "model", "temperature", "top_p", "top_k", "min_p", "max_tokens",
    "n_predict", "reasoning_effort", "enable_thinking", "preserve_thinking",
    "stop", "seed", "tools", "stream", "response_format", "repeat_penalty",
    "presence_penalty", "frequency_penalty", "logprobs", "logit_bias",
    "n_probs", "chat_template_kwargs", "user",
)
STATIC = Path(__file__).resolve().parent / "static"
# engine endpoints relayed to a peer Domingo (everything under /v1/ is too)
ENGINE_ROUTES = frozenset(("/health", "/healthz", "/props", "/slots", "/abort",
                           "/tokenize", "/detokenize", "/models", "/completion"))


# --------------------------------------------------------------------------- #
# finding a running Strata server
# --------------------------------------------------------------------------- #

def config_dirs():
    """Directories where Strata writes its run configs, per platform."""
    home = Path.home()
    out = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        out += [Path(local) / "Strata" / "runtime", Path(local) / "Strata" / "install"]
    out += [home / ".strata" / "data" / "native-instances",
            home / ".strata" / "runtime",
            home / ".local" / "share" / "Strata" / "runtime",
            home / ".config" / "Strata" / "runtime",
            home / "Library" / "Application Support" / "Strata" / "runtime"]
    return [d for d in out if d.is_dir()]


def load_json(path):
    try:
        # utf-8-sig: Notepad and PowerShell like to write a BOM, which json rejects
        return json.loads(path.read_text("utf-8-sig", "replace").strip() or "{}")
    except Exception:
        return None


def candidates():
    """Every Strata endpoint + key on record, best guess first.

    A *.ready.json is written by a live server, so it beats the instance config,
    which beats the install config (whose port is often stale after a restart).
    """
    out = []
    for d in config_dirs():
        for p in d.glob("*.json"):
            data = load_json(p)
            if not data:
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                mtime = 0
            url = data.get("api_url")
            if not url and data.get("port"):
                url = "http://%s:%s" % (data.get("host") or "127.0.0.1", data["port"])
            if not url:
                continue
            rank = 0 if p.name.endswith(".ready.json") else (2 if p.name.startswith("strata-") else 1)
            out.append({"url": url.rstrip("/"), "key": data.get("api_key"),
                        "model": data.get("model_id") or data.get("model_name"),
                        "rank": rank, "mtime": mtime, "src": str(p)})
    out.sort(key=lambda c: (c["rank"], -c["mtime"]))
    return out


def api_ok(url, key, timeout=4.0):
    """True when /v1/models answers with this key. /health is open, so it proves nothing."""
    req = urllib.request.Request(url.rstrip("/") + "/v1/models")
    if key:
        req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        return e.code not in (401, 403)
    except Exception:
        return False


def discover():
    """The recorded endpoint whose key actually works -> (url, key, model, source)."""
    cands = candidates()
    for c in cands:
        if c["key"] and api_ok(c["url"], c["key"]):
            return c["url"], c["key"], c["model"], c["src"]
    for c in cands:                                   # reachable but keyless is still useful
        code, _ = health(c["url"], c["key"], timeout=3.0)
        if code == 200:
            return c["url"], c["key"], c["model"], c["src"]
    if cands:
        c = cands[0]
        return c["url"], c["key"], c["model"], c["src"] + " (not answering right now)"
    return None, None, None, ""


def health(url, key=None, timeout=6.0):
    """GET <url>/health, with /healthz as a fallback (a Domingo peer)."""
    base = url.rstrip("/")
    for path in ("/health", "/healthz"):
        req = urllib.request.Request(base + path,
                                     headers={"Authorization": "Bearer " + key} if key else {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return e.code, "auth"
        except Exception:
            continue
    return 0, "unreachable"


def resolve_key(url, candidates):
    """Pick the first key that is accepted by <url>/v1/models."""
    base = url.rstrip("/")
    for key in [k for k in candidates if k] + [None]:
        req = urllib.request.Request(base + "/v1/models")
        if key:
            req.add_header("Authorization", "Bearer " + key)
        try:
            with urllib.request.urlopen(req, timeout=8.0) as r:
                r.read()
            return key
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                continue
            return key
        except Exception:
            return key
    return None


def tailnet_ips():
    """IPv4 addresses in 100.64.0.0/10 (Tailscale's range) on this host."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if ip.startswith("100.64.") or ip.startswith("100."))


# --------------------------------------------------------------------------- #
# request handling
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Domingo/" + VERSION
    cfg = None                                          # injected namespace

    # ---- small helpers ---------------------------------------------------- #
    def log_message(self, fmt, *args):
        if self.server.verbose:
            sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def send_json(self, code, obj, extra=None):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_file(self, path, ctype, cache="no-cache", extra=None):
        try:
            data = path.read_bytes()
        except OSError:
            return self.send_json(404, {"error": "missing %s" % path.name})
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def read_body(self):
        # read the body exactly once per request, and always read it: leaving an
        # unread POST body in the socket desynchronizes the next request on a
        # keep-alive connection, which hangs the client.
        if getattr(self, "_body", None) is None:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                self._body = b""
            elif length > MAX_BODY:
                raise ValueError("body too large (%d bytes)" % length)
            else:
                self._body = self.rfile.read(length)
        return self._body
    def authorized(self):
        token = self.cfg.token
        if not token:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            if hmac.compare_digest(auth[7:].strip(), str(token)):
                return True
        q = urllib.parse.urlparse(self.path).query
        given = urllib.parse.parse_qs(q).get("t", [""])[0]
        if not given:
            # X-Domingo-Token; X-Strata-Token is accepted for pre-rename clients
            given = self.headers.get("X-Domingo-Token", "") or self.headers.get("X-Strata-Token", "")
        if not given:
            cookie = self.headers.get("Cookie", "")
            m = re.search(r"(?:^|;\s*)(?:domingo|slite)=([^;]+)", cookie)
            given = urllib.parse.unquote(m.group(1)) if m else ""
        return hmac.compare_digest(str(given), str(token))

    def upstream(self, path, body=None, headers=None, method=None):
        base = self.cfg.url.rstrip("/")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data else "GET"))
        req.add_header("Content-Type", "application/json")
        if self.cfg.key:
            req.add_header("Authorization", "Bearer " + self.cfg.key)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        return urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT)

    def passthrough(self, path, body, query=""):
        """Forward a JSON call and return the decoded answer, or a forwarded error."""
        try:
            with self.upstream(path + query, body) as r:
                raw = r.read().decode("utf-8", "replace")
                self.send_json(r.status, json.loads(raw) if raw.strip().startswith(("{", "[")) else {"raw": raw})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")[:4000]
            try:
                obj = json.loads(raw)
            except Exception:
                obj = {"error": raw or e.reason}
            self.send_json(e.code, obj)
        except Exception as e:
            self.send_json(502, {"error": "upstream unreachable: %s" % e})

    def relay_post(self, path, body=None):
        """Forward a POST and report what came back (used for /abort)."""
        try:
            with self.upstream(path, body if body is not None else {}) as r:
                self.send_json(r.status, {"ok": True, "upstream": r.status})
        except urllib.error.HTTPError as e:
            self.send_json(e.code, {"ok": False, "upstream": e.code})
        except Exception as e:
            self.send_json(502, {"ok": False, "error": str(e)})

    # ---- routes ----------------------------------------------------------- #
    # NOTE: do not name this handle(); BaseHTTPRequestHandler.handle() is the
    # connection loop, and overriding it silently kills every request.
    def do_GET(self):
        self.route()

    def do_HEAD(self):
        self.route()

    def do_POST(self):
        self.route()

    # the shell is public: opening a bookmark without a token should show the app
    # with a clear "unauthorized" state, not a raw 401 page. Only data needs a token.
    PUBLIC_PATHS = ("/", "/index.html", "/manifest.webmanifest", "/healthz")

    def is_public(self, path):
        return path in self.PUBLIC_PATHS or path.endswith((".png", ".svg", ".ico"))

    def route(self, read=True):
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, parsed.query
        try:
            # one handler instance serves every request on a keep-alive connection,
            # so the body cache must be cleared per request or the next POST would
            # replay this one's payload.
            self._body = None
            if self.command in ("POST", "PUT"):
                self.read_body()                    # drain first: auth failures included
            # ?t=<token> once: remember it in a cookie AND serve the page as-is.
            # Redirecting here would strip the token from the URL before the page
            # loads, leaving the UI dependent on a cookie Safari may not keep.
            if path == "/" and self.cfg.token:
                given = urllib.parse.parse_qs(query).get("t", [""])[0]
                if given and hmac.compare_digest(given, str(self.cfg.token)):
                    self.send_file(STATIC / "ui.html", "text/html; charset=utf-8",
                                   extra={"Set-Cookie": "domingo=%s; Path=/; Max-Age=31536000; SameSite=Lax"
                                                      % urllib.parse.quote(str(self.cfg.token))})
                    return
            if path in ("/", "/index.html"):
                self.send_file(STATIC / "ui.html", "text/html; charset=utf-8")
                return
            if path == "/manifest.webmanifest":
                self.send_file(STATIC / "manifest.webmanifest", "application/manifest+json")
                return
            if path.endswith(".png") or path.endswith(".svg") or path.endswith(".ico"):
                name = path.lstrip("/").replace("..", "")
                self.send_file(STATIC / name, "image/png" if path.endswith(".png") else "image/svg+xml",
                               cache="public, max-age=86400")
                return
            if not self.authorized() and not self.is_public(path):
                if self.cfg.token:
                    self.send_json(401, {"error": "unauthorized",
                                         "hint": "open %s/?t=<token> once, or set the token in Settings"
                                                 % ("http://127.0.0.1:%d" % self.cfg.port)})
                else:
                    self.send_json(404, {"error": "not found"})
                return
            if path == "/healthz":
                # Public, so a container healthcheck needs no credentials. Unauthenticated
                # it answers with the bare minimum: that this process is up.
                if not self.authorized():
                    self.send_json(200, {"ok": True, "version": VERSION})
                    return
                code, body = health(self.cfg.url, self.cfg.key)
                cached = getattr(self.server, "info_cache", (0, {}))[1] or {}
                self.send_json(200, {"ok": code in (200, 401), "upstream": self.cfg.url,
                                     "upstream_status": code, "upstream_body": body[:400],
                                     "model": self.cfg.model or cached.get("model"), "version": VERSION})
                return
            if path == "/api/info":
                self.info()
                return
            if path == "/api/chat":
                self.chat()
                return
            if path == "/api/abort":
                self.relay_post("/abort")                     # engine-specific; may 404, that is fine
                return
            if path == "/api/probe":
                self.probe()
                return
            # Raw OpenAI routes: a Domingo on another device can proxy through
            # this one, so the real API key only ever lives next to the model.
            if path.startswith("/v1/") or path in ENGINE_ROUTES:
                self.relay(path, query)
                return
            self.send_json(404, {"error": "not found"})
        except BrokenPipeError:
            self.close_connection = True                      # client is gone
        except ValueError as e:
            self.send_json(400, {"error": str(e)})
        except Exception as e:                                        # never kill the thread
            sys.stderr.write("error on %s: %s\n%s\n" % (self.path, e, traceback.format_exc()))
            try:
                self.send_json(500, {"error": "%s: %s" % (type(e).__name__, e)})
            except Exception:
                pass

    # ---- the chat call, streamed straight through ------------------------- #
    def chat(self):
        raw = self.read_body()
        if not raw:
            return self.send_json(400, {"error": "empty body"})
        req = json.loads(raw.decode("utf-8"))
        out = {k: req[k] for k in FORWARD_FIELDS if k in req}
        if not out.get("messages"):
            return self.send_json(400, {"error": "messages required"})
        out.setdefault("model", self.cfg.model)
        stream = bool(req.get("stream"))

        if not stream:
            self.passthrough("/v1/chat/completions", out)
            return

        out.setdefault("stream_options", {"include_usage": True})
        t0 = time.time()
        try:
            up = self.upstream("/v1/chat/completions", out)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")[:4000]
            return self.send_json(e.code, {"error": raw})
        except Exception as e:
            return self.send_json(502, {"error": "upstream unreachable: %s" % e})

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True          # close after the stream, no keep-alive reuse
        usage, status = None, 200
        prev_tail = b""
        try:
            while True:
                chunk = up.read(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
                # The engine keeps its socket open after the last SSE event, so the
                # only reliable end-of-stream signal is the [DONE] marker itself.
                if b"[DONE]" in prev_tail + chunk:
                    break
                prev_tail = chunk[-16:]
        except (BrokenPipeError, ConnectionResetError):
            status = 499                                            # client stopped
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read().decode("utf-8", "replace")
            sys.stderr.write("chat upstream %s: %s\n" % (e.code, raw[:200]))
        except Exception as e:
            status = 502
            sys.stderr.write("chat stream broke: %s\n" % e)
        finally:
            up.close()
            rate = ""
            if usage:
                dt = max(time.time() - t0, 0.001)
                rate = " %d tok in, %d tok out, %.1f tok/s" % (
                    usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                    usage.get("completion_tokens", 0) / dt)
            self.log_message("chat %s %.1fs%s", status, time.time() - t0, rate)

    # ---- raw relay for peer servers --------------------------------------- #
    def relay(self, path, query=""):
        """Forward a raw engine call, adding the key here. Used by a peer Domingo."""
        body = self.read_body() if self.command in ("POST", "PUT") else None
        payload = None
        if body:
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                payload = None
        target = path + (("?" + query) if query else "")
        try:
            up = self.upstream(target, payload)
        except urllib.error.HTTPError as e:
            return self.send_json(e.code, {"error": e.read().decode("utf-8", "replace")[:4000]})
        except Exception as e:
            return self.send_json(502, {"error": "upstream unreachable: %s" % e})

        ctype = up.headers.get("Content-Type") or "application/json"
        self.send_response(up.status)
        self.send_header("Content-Type", ctype)
        if "event-stream" in ctype:
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            prev = b""
            try:
                while True:
                    chunk = up.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    if b"[DONE]" in prev + chunk:
                        break
                    prev = chunk[-16:]
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                up.close()
            return
        raw = up.read()
        up.close()
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    # ---- connectivity test for saved endpoints (server-side, so CORS is moot) -- #
    def probe(self):
        body = json.loads((self.read_body() or b"{}").decode("utf-8"))
        url = (body.get("url") or "").strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return self.send_json(400, {"error": "url must be http(s)://host:port"})
        # tokens to try: the caller's, none, then our own - a server probing itself
        # through a share has no reason to carry the secret around in the browser
        seen, tries = set(), []
        for t in (body.get("token"), None, self.cfg.token):
            if str(t) not in seen:
                seen.add(str(t))
                tries.append(t)
        t0, code, text = time.time(), 0, "unreachable"
        for t in tries:
            code, text = health(url.rstrip("/"), t, timeout=6.0)
            if code not in (401, 403):
                break
        self.send_json(200, {"url": url, "status": code, "ms": int((time.time() - t0) * 1000),
                             "body": text[:300]})

    # ---- /api/info: what am I talking to ---------------------------------- #
    def info(self):
        cached = getattr(self.server, "info_cache", None)
        if cached and time.time() - cached[0] < 20:
            return self.send_json(200, cached[1])
        out = {"server": self.cfg.name, "version": VERSION, "url": self.cfg.url,
               "model": self.cfg.model, "models": [], "n_ctx": None, "vision": False,
               "build": "", "slots": None, "key_set": bool(self.cfg.key)}
        try:
            with self.upstream("/v1/models") as r:
                for m in json.loads(r.read().decode()).get("data", []):
                    out["models"].append({"id": m.get("id"),
                                          "ctx": (m.get("meta") or {}).get("n_ctx"),
                                          "alias_of": m.get("alias_of"),
                                          "vision": "image" in ((m.get("architecture") or {})
                                                                 .get("input_modalities") or [])})
        except Exception as e:
            out["error"] = "models: %s" % e
        if not out["model"] and out["models"]:            # a proxy server knows it from the peer
            out["model"] = out["models"][0]["id"]
        try:
            with self.upstream("/props") as r:
                p = json.loads(r.read().decode())
                gen = p.get("default_generation_settings") or {}
                out["n_ctx"] = gen.get("n_ctx")
                # Strata owns sampling. Domingo reads the engine's defaults and shows
                # them; it never sends temperature/top_p/max of its own.
                out["sampling"] = gen.get("params") or {}
                out["slots"] = p.get("total_slots")
                out["vision"] = bool((p.get("modalities") or {}).get("vision"))
                out["build"] = p.get("build_info", "")
                out["sleeping"] = bool(p.get("is_sleeping"))
        except Exception as e:
            out.setdefault("error", "props: %s" % e)
        self.server.info_cache = (time.time(), out)
        self.send_json(200, out)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    verbose = False

    def handle_error(self, request, client):
        exc = sys.exc_info()[1]
        if not isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client)


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def parse_args():
    ap = argparse.ArgumentParser(description="Domingo - light chat UI for a Strata model server.")
    ap.add_argument("--url", help="Strata API base URL, e.g. http://127.0.0.1:18500")
    ap.add_argument("--key", help="Strata API key (server-side only; never sent to the browser)")
    ap.add_argument("--model", help="model id to select by default")
    ap.add_argument("--host", help="bind address (default 127.0.0.1; 0.0.0.0 to share)")
    ap.add_argument("--port", type=int, help="port for the UI (default 8899)")
    ap.add_argument("--token", help="shared token required by clients")
    ap.add_argument("--name", help="label shown in the UI")
    ap.add_argument("--system", help="default system prompt")
    ap.add_argument("--advertise", help="the address your other devices actually use, "
                                        "e.g. https://host.ts.net:8443 when a proxy forwards to this port")
    ap.add_argument("--config", help="JSON config file (default domingo.json next to this file)")
    ap.add_argument("--open", action="store_true", help="open the browser on start")
    ap.add_argument("--verbose", action="store_true", help="log every request")
    ap.add_argument("--version", action="version", version="domingo " + VERSION)
    args = ap.parse_args()

    # config order: --config, then domingo.json next to this file, then the home file.
    # The pre-rename names (strata-lite.json, .strata-lite.json) are still read.
    here = Path(__file__).resolve().parent
    home = Path.home()
    if args.config:
        path = Path(args.config).expanduser()
    else:
        path = next((p for p in (here / "domingo.json", here / "strata-lite.json",
                                 home / ".domingo.json", home / ".strata-lite.json")
                     if p.is_file()), here / "domingo.json")
    file_cfg = load_json(path) if path.is_file() else {}
    if args.config and args.config != "auto" and not file_cfg:
        print("note: config file %s not found or not JSON; continuing without it" % path)
    for field in ("url", "key", "model", "host", "port", "token", "name", "system", "advertise"):
        if getattr(args, field) is None and field in file_cfg:
            setattr(args, field, file_cfg[field])
    if not args.open and file_cfg.get("open"):
        args.open = True
    args.port = int(args.port or 8899)
    args.host = args.host or "127.0.0.1"
    args.name = args.name or socket.gethostname()
    return args


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = parse_args()
    src = ""
    if not args.url:
        args.url, found_key, found_model, src = discover()
        args.key = args.key or found_key
        args.model = args.model or found_model
    if not args.url:
        sys.exit("domingo: no Strata server found and --url not given.\n"
                 "  start Strata, or pass --url http://<host>:<port> --key <api key>")

    keys = [args.key] if args.key else []
    if not args.key:                                        # try the keys recorded for this URL first
        same = [c["key"] for c in candidates() if c["key"] and c["url"].rstrip("/") == args.url.rstrip("/")]
        any_ = [c["key"] for c in candidates() if c["key"]]
        keys = same + [k for k in any_ if k not in same]
    args.key = resolve_key(args.url, keys)

    code, body = health(args.url, args.key)
    if code == 0:
        print("warning: %s is not answering /health yet (%s). The UI will keep retrying." % (args.url, body))
    elif code in (401, 403):
        sys.exit("domingo: %s rejected the API key (401). Pass --key <key>." % args.url)
    sys.stdout.flush()

    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.token:
        sys.exit("domingo: refusing to bind %s without --token (the engine is open to your network).\n"
                 "  use --token <secret>, or --host 127.0.0.1." % args.host)

    # A proxy (Tailscale Serve, a reverse proxy, a tunnel) forwards to a loopback
    # bind, so the interface check above never fires even though the app is
    # reachable from other machines. --advertise makes that explicit, and it is
    # refused without a token for the same reason.
    if args.advertise and not args.token:
        sys.exit("domingo: refusing to advertise %s without --token.\n"
                 "  a device outside this machine would reach the model with no check.\n"
                 "  use --token <secret>." % args.advertise)

    srv = Server((args.host, args.port), Handler)
    srv.verbose = args.verbose
    Handler.cfg = args
    shown = [args.name, ""]
    local = "http://127.0.0.1:%d" % args.port
    urls = [local]
    if args.host in ("0.0.0.0", "::"):
        for ip in tailnet_ips():
            urls.append("http://%s:%d" % (ip, args.port))
    suffix = ("/?t=%s" % args.token) if args.token else ""
    print("Domingo %s" % VERSION)
    print("  model    %s" % (args.model or "(ask the server)"))
    print("  upstream %s  %s" % (args.url, "key set" if args.key else "no key"))
    print("  config   %s" % (src or "args"))
    print("  open     " + ("\n           ".join(u + suffix for u in urls)))
    if args.host in ("0.0.0.0", "::"):
        print("  sharing  on every interface; token required: %s" % ("yes" if args.token else "NO"))
    if args.advertise:
        print("  beyond this machine: %s (a proxy forwards here)" % args.advertise)
        print("           devices must present the token; open %s%s" % (args.advertise, suffix))
    sys.stdout.flush()
    if args.open:
        threading.Timer(0.6, lambda: __import__("webbrowser").open(local + suffix)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        srv.shutdown()


if __name__ == "__main__":
    main()
