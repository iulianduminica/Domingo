#!/bin/sh
# Turn the container's environment into Domingo's arguments, then exec the server
# so it stays PID 1 and receives SIGTERM. Plain sh: no bash, no GNU tools.
set -eu

ARGS="--host ${DOMINGO_HOST:-127.0.0.1} --port ${DOMINGO_PORT:-8899}"
[ -n "${DOMINGO_TOKEN:-}" ]     && ARGS="$ARGS --token ${DOMINGO_TOKEN}"
[ -n "${DOMINGO_URL:-}" ]       && ARGS="$ARGS --url ${DOMINGO_URL}"
[ -n "${DOMINGO_KEY:-}" ]       && ARGS="$ARGS --key ${DOMINGO_KEY}"
[ -n "${DOMINGO_MODEL:-}" ]     && ARGS="$ARGS --model ${DOMINGO_MODEL}"
[ -n "${DOMINGO_NAME:-}" ]      && ARGS="$ARGS --name ${DOMINGO_NAME}"
[ -n "${DOMINGO_ADVERTISE:-}" ] && ARGS="$ARGS --advertise ${DOMINGO_ADVERTISE}"

# A config file in the mounted volume wins over the defaults and fills any gap.
if [ -f /data/domingo.json ]; then
  ARGS="$ARGS --config /data/domingo.json"
fi

# Binding beyond loopback without a token is refused by the app itself. Say it
# here too, so the container log explains the exit instead of just exiting.
case "${DOMINGO_HOST:-127.0.0.1}" in
  127.0.0.1|localhost|::1) ;;
  *)
    if [ -z "${DOMINGO_TOKEN:-}" ] && [ ! -f /data/domingo.json ]; then
      echo "DOMINGO_HOST is ${DOMINGO_HOST} and DOMINGO_TOKEN is empty." >&2
      echo "Set DOMINGO_TOKEN, or run with DOMINGO_HOST=127.0.0.1 and a published port." >&2
      exit 1
    fi
    ;;
esac

# shellcheck disable=SC2086
exec python -u /app/domingo.py $ARGS "$@"
