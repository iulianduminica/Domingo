#!/usr/bin/env python3
"""Start the real Domingo, ask it over HTTP, shut it down.

Plain Python, no shell syntax, no pipes on the child: its output goes to a file,
and the child is terminated and waited for, so the script never exits with a
child's pipes left open. Works the same on Windows, macOS and Linux.

  python tools/boot-check.py
  DOMINGO_ENGINE_URL=http://127.0.0.1:8890 python tools/boot-check.py
"""

import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKEN = "boot-check-token"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def main():
    port = free_port()
    base = "http://127.0.0.1:%d" % port
    cmd = [sys.executable, "-u", str(ROOT / "domingo.py"),
           "--host", "127.0.0.1", "--port", str(port), "--token", TOKEN]
    if os.environ.get("DOMINGO_ENGINE_URL"):
        cmd += ["--url", os.environ["DOMINGO_ENGINE_URL"]]
    if os.environ.get("DOMINGO_ENGINE_MODEL"):
        cmd += ["--model", os.environ["DOMINGO_ENGINE_MODEL"]]

    tmp = pathlib.Path(tempfile.mkdtemp())
    log = open(tmp / "server.log", "w", encoding="utf-8", errors="replace")
    print("boot check: " + " ".join(x.replace(str(ROOT), ".") for x in cmd))
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(tmp))
    steps = []
    try:
        health, status = None, None
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                status, body = get(base + "/healthz")
                health = json.loads(body)
                break
            except Exception:
                time.sleep(0.5)
        steps.append(("GET /healthz with no credentials",
                      status == 200 and health and health.get("ok") is True,
                      "%s %s" % (status, health)))
        steps.append(("the answer is minimal",
                      bool(health) and set(health) <= {"ok", "version"},
                      sorted(health or {})))
        st, html = get(base + "/")
        steps.append(("GET / serves the UI", st == 200 and "<title>Domingo" in html,
                      "%d bytes" % len(html)))
        try:
            get(base + "/api/info")
            steps.append(("GET /api/info is closed without a token", False, "answered 200"))
        except urllib.error.HTTPError as e:
            steps.append(("GET /api/info is closed without a token", e.code == 401, "status %d" % e.code))
        req = urllib.request.Request(base + "/api/info", headers={"X-Domingo-Token": TOKEN})
        with urllib.request.urlopen(req, timeout=20) as r:
            st, body = r.status, r.read().decode()
        data = json.loads(body)
        steps.append(("GET /api/info with the token", st == 200 and bool(data.get("model")),
                      "model=%s ctx=%s" % (data.get("model"), data.get("n_ctx"))))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
            proc.wait(timeout=5)
        log.close()

    failed = 0
    for name, cond, detail in steps:
        print(("  PASS  " if cond else "  FAIL  ") + name + ("   " + str(detail)[:90] if detail else ""))
        failed += not cond
    if failed:
        print("  server log:\n    " + (tmp / "server.log").read_text("utf-8", "replace").strip().replace("\n", "\n    "))
    print("boot check: %d of %d steps passed" % (len(steps) - failed, len(steps)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
