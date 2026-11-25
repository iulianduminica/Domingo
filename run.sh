#!/bin/sh
# Domingo on macOS and Linux. Run it with:  ./run.sh   (or: sh run.sh)
#
# Options live in domingo.json next to this file. Copy domingo.example.json to
# get the shape. To reach a model server on another machine, that file needs
# the address and the key, for example:
#   { "url": "https://your-machine.ts.net:8443", "key": "<the shared token>", "open": true }
cd "$(dirname "$0")" || exit 1

PY="${DOMINGO_PY:-}"
[ -z "$PY" ] && PY="$(command -v python3)"
[ -z "$PY" ] && PY="$(command -v python)"
if [ -z "$PY" ]; then
  echo "Domingo needs Python 3.9 or newer, and none was found."
  echo "  macOS:  xcode-select --install    (a few hundred MB, no account needed)"
  echo "          or  brew install python"
  echo "  Linux:  sudo apt install python3  (or your distribution's package)"
  echo "  Then run ./run.sh again."
  exit 1
fi

exec "$PY" -u domingo.py "$@"
