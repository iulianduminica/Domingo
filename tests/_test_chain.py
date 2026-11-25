"""Runs the full topology on one machine:

  :8896  "the Mac"   ->  :8897  "the Halo"  ->  the model server

The Mac side holds only the shared token; the model's API key stays on the Halo.

With no arguments it uses the local Strata engine and the token in domingo.json.
For CI, point it at the stand-in engine:

  DOMINGO_ENGINE_URL=http://127.0.0.1:8890 DOMINGO_ENGINE_MODEL=fake-model \
      python tests/_test_chain.py
"""
import json, os, pathlib, subprocess, sys, tempfile, time, urllib.error, urllib.request

HERE = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS  %-40s %s" % (name, detail))
    else:
        fail += 1
        print("FAIL  %-40s %s" % (name, detail))


def call(url, path, body=None, token=None, timeout=120):
    req = urllib.request.Request(url + path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    return urllib.request.urlopen(req, timeout=timeout)


def wait(url, tries=40):
    for _ in range(tries):
        try:
            with call(url, "/healthz", token=token) as r:
                return json.loads(r.read().decode())
        except Exception:
            time.sleep(0.5)
    return None


ENGINE = os.environ.get("DOMINGO_ENGINE_URL")            # set in CI: the stand-in engine
MODEL = os.environ.get("DOMINGO_ENGINE_MODEL", "swift-1.5-iq3_s")
token = os.environ.get("DOMINGO_TEST_TOKEN") or "chain-test-token"
HALO = "http://127.0.0.1:8897"
MAC = "http://127.0.0.1:8896"

# Both instances get an empty config file. Without this they read the developer's
# real domingo.json, which puts a live token into the test run and its output.
RUNTIME = pathlib.Path(tempfile.mkdtemp())
CFG = RUNTIME / "empty.json"
CFG.write_text("{}", "utf-8")

halo_args = [PY, "-u", str(HERE / "domingo.py"), "--config", str(CFG), "--host", "127.0.0.1",
             "--port", "8897", "--token", token]
if ENGINE:
    halo_args += ["--url", ENGINE, "--model", MODEL]
halo = subprocess.Popen(halo_args)
mac = subprocess.Popen([PY, "-u", str(HERE / "domingo.py"), "--config", str(CFG), "--host", "127.0.0.1",
                        "--port", "8896", "--url", HALO, "--key", token, "--token", token,
                        "--model", MODEL])
try:
    h = wait(HALO + "")
    m = wait(MAC)
    check("Halo server up", bool(h), json.dumps(h or {})[:120])
    check("Mac server up", bool(m), json.dumps(m or {})[:120])

    # the shared server demands the token
    try:
        call(HALO, "/api/info")
        check("token required on the shared server", False, "answered without a token")
    except urllib.error.HTTPError as e:
        check("token required on the shared server", e.code == 401, "status %d" % e.code)
    with call(HALO, "/api/info", token=token) as r:
        info = json.loads(r.read().decode())
    check("token accepted, /api/info relayed", r.status == 200 and info.get("model"),
          "model=%s ctx=%s" % (info.get("model"), info.get("n_ctx")))

    # the Mac proxy: no key of its own, only the shared token
    with call(MAC, "/api/info", token=token) as r:
        info = json.loads(r.read().decode())
    check("Mac /api/info through two hops", r.status == 200 and info.get("model"),
          "model=%s vision=%s" % (info.get("model"), info.get("vision")))

    # chat over the chain, streamed
    t0 = time.time()
    parts, usage = [], None
    with call(MAC, "/api/chat", {"messages": [{"role": "user", "content":
            "Reply with exactly: CHAINED OK"}], "stream": True, "max_tokens": 40,
            "reasoning_effort": "low"}, token=token) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            js = line[5:].strip()
            if js == "[DONE]":
                break
            o = json.loads(js)
            if o.get("usage"):
                usage = o["usage"]
            ch = (o.get("choices") or [{}])[0]
            if (ch.get("delta") or {}).get("content"):
                parts.append(ch["delta"]["content"])
    text = "".join(parts)
    check("Mac chat streams through two hops", "CHAINED OK" in text,
          "%.1fs %r" % (time.time() - t0, text[:40]))
    check("usage crosses the chain", bool(usage), json.dumps(usage) if usage else "none")

    # raw /v1 relay (what the Mac's own UI would call)
    with call(MAC, "/v1/models", token=token) as r:
        raw = r.read().decode()
    check("Mac relays raw /v1/models", MODEL in raw, raw[:80].replace("\n", " "))
    with call(HALO, "/props", token=token) as r:
        raw = r.read().decode()
    check("Halo relays /props", "total_slots" in raw, raw[:60].replace("\n", " "))

    # the Mac UI page itself
    with call(MAC, "/", token=token) as r:
        html = r.read().decode()
    check("Mac serves its own UI", r.status == 200 and "Domingo" in html, "%d bytes" % len(html))

    print("\n%d passed, %d failed" % (ok, fail))
finally:
    for p in (mac, halo):
        p.terminate()
    time.sleep(1)
sys.exit(1 if fail else 0)



