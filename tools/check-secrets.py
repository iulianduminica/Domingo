#!/usr/bin/env python3
"""Refuse to ship a secret, a personal path, or an unfilled placeholder.

  python tools/check-secrets.py                # secrets and personal identifiers
  python tools/check-secrets.py --placeholders # unfilled template strings

It reads the files git tracks (or every file, outside a repo), skips binaries,
and prints one line per finding with the file and line. Exit code 1 means stop.
"""

import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# A real credential, a machine-specific identity, or a private network name.
SECRET_RULES = [
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("openai-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("pem private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("windows user path", re.compile(r"[A-Za-z]:[\\/]{1,2}[Uu]sers[\\/](?!\$|%\{)[A-Za-z0-9._-]+")),
    ("unix home path", re.compile(r"(?<![\w/])/Users/[A-Za-z0-9._-]{3,}")),
    ("tailnet hostname", re.compile(r"(?<![-\w.])\b(?!your-machine\.|host\.|pc\.|example\.|my-tailnet\.)"
                                    r"[a-z0-9-]+\.(?:[a-z0-9-]+\.)?ts\.net\b")),
    ("token value in json", re.compile(r'"(token|key)"\s*:\s*"(?!\s*<|\s*$|\s*\{\{)[^"]{8,}"')),
    ("password in url", re.compile(r"https?://[^/\s:]+:[^@\s]{6,}@\b")),
]

PLACEHOLDER_RULES = [
    # Angle-bracket slots like <your token> are instructions to the reader and are
    # wanted. These patterns catch leftovers from writing the template.
    ("name placeholder", re.compile(r"your-name|Your Name|\[your|octocat")),
    ("todo", re.compile(r"\b(TODO|FIXME|XXX|CHANGE_ME|REPLACE_WITH)\b")),
    ("account placeholder", re.compile(r"your[-_]?(?:github|username|repo|account)")),
]

# Files that legitimately carry a value the rules would flag.
ALLOW = {
    "tools/check-secrets.py":     "the patterns themselves",
    "domingo.example.json":       "placeholders are the point of the file",
    "docker-compose.yml":         "replace-me-with-a-long-secret is an instruction",
    "tests/_test_startup.py":     "verifytoken and verify.ts.net are fixtures, not credentials",
    "tools/make-config.py":       "the docstring shows the shape of a tailnet name",
}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".zip"}
TEXT_EXT = {".py", ".md", ".json", ".html", ".cmd", ".sh", ".command", ".cjs", ".toml",
            ".yml", ".yaml", ".txt", ".webmanifest", ".css", ".js", ""}


def tracked():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=str(ROOT),
                             capture_output=True, text=True, timeout=30).stdout
        paths = [ROOT / p for p in out.split("\0") if p]
        if paths:
            return paths
    except Exception:
        pass
    # Not a checkout: walk the tree, skipping caches and ignored directories.
    skip = {"__pycache__", "node_modules", ".git", ".mypy_cache", ".venv", "venv",
            ".ruff_cache", ".pytest_cache", "dist", "build"}
    found = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or any(x in p.parts for x in skip):
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel in ("domingo.json", "domingo.mac.json", "domingo.direct.json",
                   "domingo.peer.json") or rel.startswith("docs/screenshots"):
            continue
        found.append(p)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placeholders", action="store_true")
    a = ap.parse_args()
    rules = SECRET_RULES + (PLACEHOLDER_RULES if a.placeholders else [])
    label = "secrets and personal paths" + (" and placeholders" if a.placeholders else "")

    hits = 0
    scanned = 0
    for p in sorted(tracked()):
        try:
            rel = p.relative_to(ROOT).as_posix()
        except ValueError:
            continue
        if p.suffix in SKIP_EXT:
            continue
        if p.suffix not in TEXT_EXT and p.suffix != "":
            continue
        if rel in ALLOW:
            continue
        try:
            text = p.read_text("utf-8", "replace")
        except Exception:
            continue
        scanned += 1
        for i, line in enumerate(text.splitlines(), 1):
            for name, rx in rules:
                m = rx.search(line)
                if m:
                    print("  %s  %s:%d  %s" % (name, rel, i, m.group(0)[:70]))
                    hits += 1
    print("%s: %d file(s) scanned, %d finding(s)" % (label, scanned, hits))
    if hits:
        print("  fix the lines above, or add the file to ALLOW with a reason")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
