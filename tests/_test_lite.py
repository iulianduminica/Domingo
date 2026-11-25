"""End-to-end checks against a running Strata Lite server."""
import json, sys, time, urllib.request, urllib.error

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
TOKEN = sys.argv[2] if len(sys.argv) > 2 else ""
ok = fail = 0


def call(path, body=None, headers=None, stream=False, timeout=180):
    req = urllib.request.Request(BASE + path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if TOKEN:
        req.add_header("X-Strata-Token", TOKEN)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=timeout)


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS  %-34s %s" % (name, detail))
    else:
        fail += 1
        print("FAIL  %-34s %s" % (name, detail))


# 1. info
with call("/api/info") as r:
    info = json.loads(r.read().decode())
check("GET /api/info", r.status == 200 and info.get("model"),
      "model=%s ctx=%s vision=%s slots=%s build=%r" % (info.get("model"), info.get("n_ctx"),
                                                       info.get("vision"), info.get("slots"), info.get("build")))

# 2. streaming passthrough, unbuffered?
t0 = time.time()
first = last = None
parts, reasoning, usage, finish = [], [], None, None
with call("/api/chat", {
    "messages": [{"role": "user", "content": "Count from 1 to 6, then say DONE. Keep it tiny."}],
    "stream": True, "max_tokens": 120, "reasoning_effort": "low", "temperature": 0.2,
}) as r:
    ctype = r.headers.get("Content-Type")
    for raw in r:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        now = time.time() - t0
        js = line[5:].strip()
        if js == "[DONE]":
            last = now
            break
        o = json.loads(js)
        if first is None:
            first = now
        if o.get("usage"):
            usage = o["usage"]
        ch = (o.get("choices") or [{}])[0]
        d = ch.get("delta") or {}
        if d.get("content"):
            parts.append(d["content"])
        if d.get("reasoning_content"):
            reasoning.append(d["reasoning_content"])
        if ch.get("finish_reason"):
            finish = ch["finish_reason"]
text = "".join(parts)
check("POST /api/chat stream: content", len(text) > 3, "%.1fs, %d chunks, %d chars, finish=%s" % (last or 0, len(parts), len(text), finish))
check("POST /api/chat stream: reasoning", len(reasoning) > 0, "%d reasoning chunks" % len(reasoning))
check("POST /api/chat stream: usage", bool(usage), json.dumps(usage) if usage else "none")
check("stream is unbuffered", first is not None and len(parts) > 3,
      "first chunk +%.2fs, %d incremental chunks" % (first or 0, len(parts)))
check("stream content-type", ctype and "event-stream" in ctype, str(ctype))

# 3. non-stream
with call("/api/chat", {"messages": [{"role": "user", "content": "Reply with exactly: PING"}],
                       "max_tokens": 40, "reasoning_effort": "low"}) as r:
    d = json.loads(r.read().decode())
check("POST /api/chat non-stream", d.get("choices") and "PING" in d["choices"][0]["message"]["content"],
      repr(d["choices"][0]["message"]["content"])[:60])

# 4. parameters survive the proxy
with call("/api/chat", {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 5,
                       "reasoning_effort": "low", "temperature": 0.3, "top_p": 0.9,
                       "stream": True}) as r:
    raw = r.read().decode()
check("params accepted (temp/top_p/max)", '"finish_reason"' in raw, "engine accepted the payload")

# 5. vision through the proxy
png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
with call("/api/chat", {"messages": [{"role": "user", "content": [
        {"type": "text", "text": "One word: what colour?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + png}}]}],
        "max_tokens": 60, "reasoning_effort": "low"}) as r:
    d = json.loads(r.read().decode())
ans = d["choices"][0]["message"]["content"].strip()
check("vision image passes through", "red" in ans.lower(), repr(ans)[:60])

# 6. probe endpoint
with call("/api/probe", {"url": BASE, "token": TOKEN}) as r:
    d = json.loads(r.read().decode())
check("POST /api/probe", d.get("status") == 200, json.dumps(d)[:110])

# 7. rejects a bad probe target
try:
    call("/api/probe", {"url": "file:///etc/passwd"})
    check("probe rejects non-http", False, "no error raised")
except urllib.error.HTTPError as e:
    check("probe rejects non-http", e.code == 400, "status %d" % e.code)

# 8. bad request handling
try:
    call("/api/chat", {"stream": True})
    check("400 on missing messages", False, "no error raised")
except urllib.error.HTTPError as e:
    check("400 on missing messages", e.code == 400, "status %d" % e.code)

# 9. static + ui
with call("/") as r:
    html = r.read().decode()
check("GET / serves the app", r.status == 200 and "Domingo" in html, "%d bytes" % len(html))
with call("/manifest.webmanifest") as r:
    check("GET manifest", r.status == 200, "content-type %s" % r.headers.get("Content-Type"))

print("\n%d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
