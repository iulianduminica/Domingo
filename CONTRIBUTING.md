# Contributing

Domingo is one Python file, one HTML file, and a set of test suites. It installs
nothing at runtime. If you want to change it, this is the shortest path in.

## Setup

Clone it and run it. There is no install step, because there are no dependencies.

    git clone https://github.com/iulianduminica/Domingo.git
    cd Domingo
    run.cmd                      # Windows
    ./run.sh                     # macOS, Linux

Python 3.9 or newer is the requirement. The app imports the standard library only.

The test suites need two extra things: Node with Playwright for the browser checks,
and mypy for the typecheck. Both are dev-only.

    pip install -r requirements-dev.txt
    npm install
    npx playwright install chromium

## Running the tests

One command runs everything, on any machine, with no model server and no GPU:

    python tools/ci-run.py

It starts `tests/fake_engine.py`, a stand-in that answers the handful of routes
Domingo uses, points a real Domingo at it, runs every suite, and shuts both down.
The suites are:

    tests/_test_startup.py    the version check, the public /healthz, the advertise refusal
    tests/_test_lite.py       HTTP: auth, streaming, relay, errors
    tests/_test_chain.py      two Domingo instances in a row, the second-device topology
    tools/boot-check.py       start the real server, ask it over HTTP, shut it down
    tests/_browser_test.cjs   36 checks in a real browser: streaming, markdown, history, images
    tests/_audit.cjs          contrast of every text node, hit targets, type floors
    tests/_debug_layout.cjs   the left-edge grid at two viewports

Against your own running Strata, point them at it instead:

    python tests/_test_lite.py http://127.0.0.1:8899 <your token>
    node tests/_browser_test.cjs "http://127.0.0.1:8899/?t=<your token>"

## Layout

    domingo.py              the server: discovery, auth, SSE relay, static files, peer relay
    static/ui.html          the whole client: styles, markup, script, in one file
    static/*.png            icons, drawn by _genicon.py
    _genicon.py             renders the icon with zlib and struct, no image library
    tools/                  make-config, boot-check, ci-run, notices, check-secrets
    tests/                  the suites above, plus the stand-in engine
    docs/screenshots/       the images the README shows

## Things that are easy to get wrong

The handler is named `route`, not `handle`. `BaseHTTPRequestHandler.handle` is the
connection loop. Override it and the server stops serving requests after the first one.

The body cache is cleared at the top of every request. One handler instance serves
every request on a keep-alive connection, so a cached POST body would be replayed by
the next request. That bug showed up as random "messages required" errors.

The relay loop breaks on `[DONE]`. The engine keeps the socket open after it finishes,
so a proxy that waits for the connection to close hangs forever. `close_connection`
reads backwards the first time: `False` means keep-alive.

Do not send sampling parameters. Temperature, top_p, top_k, min_p, n_predict and seed
belong to the engine. The browser suite asserts that the payload carries only
`messages`, `model`, `stream` and `reasoning_effort`, and it fails if you add a key.

Do not send the assistant placeholder. `buildMessages` skips the message with
`streaming: true`, which is the reply being built. An empty trailing assistant turn
confuses the chat template.

Keep `/healthz` public and minimal. The container healthcheck needs a route with no
credentials, so it answers `{ok, version}` to strangers and adds upstream detail only
to authenticated callers. Adding a field there is publishing it.

Discovery ranks files, and probes them. A `*.ready.json` from a live server beats an
instance config, which beats an install config whose port is usually stale after a
restart. Ranking is not enough: each candidate is asked `/v1/models` with its key,
because `/health` answers for everyone and proves nothing.

Config files are read as `utf-8-sig`. Notepad and PowerShell write a byte-order mark,
and `json.loads` rejects it.

The test suites must not read your `domingo.json`. It holds a real token. The chain
suite passes an empty config to every instance it starts, and
`tools/check-secrets.py` fails the build when a token appears in a tracked file.

The client is one HTML file on purpose. There is no build step, so a change is
visible on reload. Keep it that way: no bundler, no framework, no web fonts.

New animation goes behind `prefers-reduced-motion`. The audit suite checks that the
greeting is fully visible and its animation duration is near zero when reduced motion
is on.

History is saved with a replacer that drops keys starting with `_`. A DOM node stored
on a message object makes `JSON.stringify` throw on a cycle, and history stops saving
with no visible error. Runtime DOM references live in a `WeakMap` instead.

## Style for documents

Plain prose. Short sentences. No em dashes as connectors, no bold label at the start
of every bullet, no section that lists the project's flaws to be seen criticising them.
`python tools/check-secrets.py --placeholders` runs in CI and catches the leftovers.

## Pull requests

Run `python tools/ci-run.py` and paste the summary. If you changed the interface,
run `node tests/_shots.cjs <url>` and attach the screenshots. If you changed spacing
or colour, run `node tests/_audit.cjs <url>`: contrast below 4.5:1, type under 11px,
or a control under 28x28 will show up there.
