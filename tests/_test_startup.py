"""Startup behaviour: the version check, the public /healthz, the advertise refusal."""
import json, pathlib, subprocess, sys, tempfile, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable
ok = 0
fail = 0


def check(name, cond, detail=""):
    global ok, fail
    print(("PASS  " if cond else "FAIL  ") + name + ("   " + str(detail)[:120] if detail else ""))
    ok += cond
    fail += not cond


src = (ROOT / "domingo.py").read_text("utf-8")
import ast
try:
    ast.parse(src)
    check("domingo.py parses", True)
except SyntaxError as e:
    check("domingo.py parses", False, e)

# 1. the version check prints a plain sentence, not an import traceback
tmp = pathlib.Path(tempfile.mkdtemp())
old = tmp / "old.py"
old.write_text(src.replace("MIN_PYTHON = (3, 9)", "MIN_PYTHON = (9, 0)"), "utf-8")
r = subprocess.run([PY, str(old)], capture_output=True, text=True, timeout=30)
out = (r.stdout + r.stderr)
check("old interpreter gets a plain sentence", "needs Python 9.0 or newer" in out and r.returncode == 1,
      "rc=%d" % r.returncode)
check("no traceback on an old interpreter", "Traceback" not in out, out[:90])
check("it names what to install", "python.org/downloads" in out and "apt install python3" in out)

# 2. --advertise without a token is refused (point at a config with no token, so the
#    real domingo.json next to the script cannot supply one)
notok = tmp0 = None
nocfg = tmp / "notoken.json"
nocfg.write_text(json.dumps({"host": "127.0.0.1", "port": 8891, "url": "http://127.0.0.1:18500"}), "utf-8")
r = subprocess.run([PY, str(ROOT / "domingo.py"), "--config", str(nocfg),
                    "--advertise", "https://example.ts.net:8443"],
                   capture_output=True, text=True, timeout=60)
check("advertise without a token refuses to start", r.returncode == 1 and "refusing to advertise" in (r.stdout + r.stderr),
      (r.stdout + r.stderr).strip()[:110])

# 3. start with a token and advertise, then read /healthz with no credentials
cfg = tmp / "t.json"
cfg.write_text(json.dumps({"host": "127.0.0.1", "port": 8892, "token": "verifytoken",
                           "url": "http://127.0.0.1:18500", "advertise": "https://verify.ts.net:8443",
                           "name": "verify"}), "utf-8")
log = open(tmp / "srv.log", "w")
p = subprocess.Popen([PY, "-u", str(ROOT / "domingo.py"), "--config", str(cfg)],
                     stdout=log, stderr=subprocess.STDOUT, cwd=str(tmp))
try:
    body, code, last = None, None, None
    for _ in range(60):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8892/healthz", timeout=3) as f:
                body, code = f.read().decode(), f.status
            break
        except Exception as e:
            last = e
            continue
    check("/healthz answers with no credentials", body is not None and json.loads(body).get("ok") is True,
          "code=%s body=%s last=%s" % (code, body, last))
    j = json.loads(body)
    check("public /healthz leaks no upstream detail",
          set(j) <= {"ok", "version"}, sorted(j))
    with urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:8892/healthz", headers={"X-Domingo-Token": "verifytoken"}), timeout=5) as f:
        full = json.loads(f.read().decode())
    check("authenticated /healthz adds upstream detail", "upstream" in full, sorted(full))
    with urllib.request.urlopen("http://127.0.0.1:8892/api/info", timeout=5) as f:
        pass
    check("a data route still needs the token", False, "api/info returned 200 unauthenticated")
except urllib.error.HTTPError as e:
    check("a data route still needs the token", e.code == 401, "status %d" % e.code)
finally:
    p.terminate()
    p.wait(timeout=10)
    log.close()
    banner = (tmp / "srv.log").read_text("utf-8", "replace")
    check("banner announces the proxy address", "beyond this machine: https://verify.ts.net:8443" in banner,
          banner.strip().replace("\n", " | ")[:300])
    if body is None:
        print("  server log:\n    " + banner.strip().replace("\n", "\n    "))

print("\n%d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
