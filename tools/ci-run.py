#!/usr/bin/env python3
"""Run every suite against a stand-in engine, on one machine, with no GPU.

Starts tests/fake_engine.py and a real Domingo pointed at it, runs the suites,
shuts both down, and prints one summary. CI calls this; so can you:

  python tools/ci-run.py

The browser suites need Node and Playwright. If Node is missing the run is marked
incomplete, and in CI (DOMINGO_CI=1) it fails, so a green run always means the
browser suites ran.
"""

import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable
IS_CI = os.environ.get("DOMINGO_CI") == "1"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait(url, tries=80):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def main():
    tmp = pathlib.Path(tempfile.mkdtemp())
    engine_port, app_port = free_port(), free_port()
    engine_url = "http://127.0.0.1:%d" % engine_port
    base = "http://127.0.0.1:%d" % app_port
    token = "ci-test-token"
    model = "fake-model"

    env = dict(os.environ)
    env.update({
        "DOMINGO_ENGINE_URL": engine_url,
        "DOMINGO_ENGINE_MODEL": model,
        "DOMINGO_TEST_TOKEN": token,
        "DOMINGO_SHOTS": str(tmp / "shots"),
        "PYTHONUNBUFFERED": "1",
    })
    logs = {}

    def start(name, cmd):
        logs[name] = open(tmp / (name + ".log"), "w", encoding="utf-8", errors="replace")
        return subprocess.Popen(cmd, stdout=logs[name], stderr=subprocess.STDOUT,
                                cwd=str(ROOT), env=env)

    engine = start("engine", [PY, "-u", str(ROOT / "tests" / "fake_engine.py"),
                              "--port", str(engine_port), "--model", model])
    if not wait(engine_url + "/health"):
        print("the stand-in engine did not start; log:\n" + (tmp / "engine.log").read_text("utf-8", "replace"))
        engine.terminate()
        return 1
    app = start("app", [PY, "-u", str(ROOT / "domingo.py"), "--host", "127.0.0.1",
                        "--port", str(app_port), "--token", token,
                        "--url", engine_url, "--model", model])
    if not wait(base + "/healthz"):
        print("Domingo did not start; log:\n" + (tmp / "app.log").read_text("utf-8", "replace"))
        app.terminate()
        engine.terminate()
        return 1
    print("engine %s   app %s   model %s\n" % (engine_url, base, model))

    node = shutil.which("node")
    suites = [
        ("startup behaviour", [PY, "tests/_test_startup.py"], True),
        ("http suite", [PY, "tests/_test_lite.py", base, token], True),
        ("two-hop chain", [PY, "tests/_test_chain.py"], True),
        ("boot check", [PY, "tools/boot-check.py"], True),
    ]
    browser_suites = [
        ("browser suite", [node, "tests/_browser_test.cjs", base + "/?t=" + token]),
        ("design audit", [node, "tests/_audit.cjs", base + "/?t=" + token]),
        ("layout probe", [node, "tests/_debug_layout.cjs", base + "/?t=" + token]),
    ]

    results = []
    for name, cmd, _ in suites:
        t0 = time.time()
        r = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True)
        tail = (r.stdout + r.stderr).strip().splitlines()
        summary = next((l for l in reversed(tail) if "passed" in l), tail[-1] if tail else "")
        results.append((name, r.returncode == 0, "%.1fs  %s" % (time.time() - t0, summary)))
        print("%-18s %s  %s" % (name, "ok  " if r.returncode == 0 else "FAIL", summary))
        if r.returncode != 0:
            print("      " + "\n      ".join(l for l in tail if "FAIL" in l)[:1500])

    if node:
        for name, cmd in browser_suites:
            t0 = time.time()
            r = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True)
            tail = (r.stdout + r.stderr).strip().splitlines()
            summary = next((l for l in reversed(tail) if "passed" in l), tail[-1] if tail else "")
            results.append((name, r.returncode == 0, "%.1fs  %s" % (time.time() - t0, summary)))
            print("%-18s %s  %s" % (name, "ok  " if r.returncode == 0 else "FAIL", summary))
            if r.returncode != 0:
                print("      " + "\n      ".join(l for l in tail if "FAIL" in l)[:1500])
    else:
        missing = IS_CI and 1 or 0
        results.append(("browser suites", not missing, "node not on PATH"))
        print("%-18s %s  node not on PATH" % ("browser suites", "FAIL" if missing else "SKIP"))

    for p in (app, engine):
        p.terminate()
        try:
            p.wait(timeout=15)
        except Exception:
            p.kill()
            p.wait(timeout=5)
    for f in logs.values():
        f.close()

    failed = [n for n, ok, _ in results if not ok]
    print("\n%s" % ("all suites passed" if not failed else "FAILED: " + ", ".join(failed)))
    shots = tmp / "shots"
    if shots.is_dir():
        print("screenshots from this run: %s" % shots)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
