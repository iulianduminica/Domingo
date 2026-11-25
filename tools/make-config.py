#!/usr/bin/env python3
"""Write a domingo.json for this machine, with values read from the machine.

  python tools/make-config.py            # writes domingo.json here
  python tools/make-config.py --peer     # also writes the second-device config

Nothing is hardcoded: the label comes from the hostname, the address from
Tailscale if it is running, the engine from discovery. The token is generated
once and preserved on later runs, so saved bookmarks keep working.

The files it writes contain a secret. They are gitignored for that reason.
"""

import argparse
import json
import pathlib
import secrets
import socket
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import domingo as app                                          # noqa: E402


def tailnet_dns():
    """This machine's Tailscale HTTPS name, e.g. my-pc.my-tailnet.ts.net."""
    for tool in ("tailscale", "tailscale.com"):
        try:
            out = subprocess.run([tool, "status", "--json"], capture_output=True,
                                 timeout=10, text=True).stdout
            return json.loads(out)["Self"]["DNSName"].rstrip(".")
        except Exception:
            continue
    return ""


def existing_token():
    for name in ("domingo.json", "strata-lite.json"):
        p = HERE / name
        if p.is_file():
            try:
                tok = (json.loads(p.read_text("utf-8-sig")) or {}).get("token")
                if tok:
                    return tok
            except Exception:
                pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--peer", action="store_true", help="also write domingo.peer.json for the second device")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--serve-port", type=int, default=8443, help="the HTTPS port Tailscale Serve listens on")
    a = ap.parse_args()

    url, key, model, src = app.discover()
    token = existing_token() or secrets.token_urlsafe(12)
    name = socket.gethostname()
    ips = app.tailnet_ips()
    tailnet = ips[0] if ips else ""
    dns = tailnet_dns()
    peer_base = ("https://%s:%d" % (dns, a.serve_port)) if dns else (
        ("http://%s:%d" % (tailnet, a.port)) if tailnet else "")

    cfg = {"host": "127.0.0.1", "port": a.port, "token": token, "name": name}
    if url:
        cfg["url"] = url
    if key:
        cfg["key"] = key
    if model:
        cfg["model"] = model
    if peer_base:
        cfg["advertise"] = peer_base
    (HERE / "domingo.json").write_text(json.dumps(cfg, indent=2) + "\n", "utf-8")

    print("discovered : %s  %s  %s   from %s" % (url or "(none)", "key found" if key else "no key",
                                                 model or "(none)", src or "args"))
    print("label      : %s" % name)
    print("tailnet    : %s" % (dns or ("ip " + tailnet if tailnet else "(no Tailscale name found)")))
    print()
    print("wrote      : %s" % (HERE / "domingo.json"))
    print("           : %s" % json.dumps(cfg))
    print()
    print("start it   : %s" % ("run.cmd" if sys.platform == "win32" else "./run.sh"))
    if dns:
        print("serve it   : tailscale serve --bg --https=%d localhost:%d" % (a.serve_port, a.port))
    if a.peer:
        if not peer_base:
            print("\n--peer needs a Tailscale name or address; none found, so nothing was written.")
            return 1
        peer = {"url": peer_base, "key": token, "host": "127.0.0.1", "port": a.port,
                "open": True, "name": "%s over the network" % name}
        (HERE / "domingo.peer.json").write_text(json.dumps(peer, indent=2) + "\n", "utf-8")
        print("wrote      : %s  ->  %s" % (HERE / "domingo.peer.json", json.dumps(peer)))
    print()
    print("open from any device: %s/?t=%s" % (peer_base or ("http://127.0.0.1:%d" % a.port), token))
    print("The token in the URL is remembered, so a plain bookmark works after the first visit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
