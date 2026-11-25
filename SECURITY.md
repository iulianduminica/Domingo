# Security

## The shape of it

Domingo sits between a browser and a model server. It forwards prompts, adds the
model's API key on the server side, and streams the answer back. The browser never
sees the key.

It is not a localhost tool. It exists so you can talk to a model on one machine from
another machine. That is the whole point, and it is the whole risk.

The trust boundary is the token. Anyone who has it can use your model: send prompts,
read the answers, spend your GPU time, and reach whatever the engine can reach. If
your engine has tool access, file access, or a browsing capability, the token is the
key to that too.

## What is reachable, by default

The server binds `127.0.0.1:8899`. Nothing outside the machine can connect.

To share it you have two options, and the app enforces a token for both. Binding a
non-loopback address without `--token` is refused at startup. Setting `advertise`
without a token is refused too, because that field means a proxy is forwarding to
this port from outside the machine.

The recommended path is a tailnet: Tailscale Serve listens on `https://<name>.ts.net:8443`
and forwards to `localhost:8899`. The app stays bound to loopback, the transport is
encrypted, and the address is only reachable from your own network.

## How a second device authenticates

One shared bearer token. It is accepted in four places: the `Authorization: Bearer`
header, the `X-Domingo-Token` header, a `domingo` cookie, and a `?t=` query parameter
on the first visit, which sets the cookie and stores the token in that browser.

Comparison is constant time. There are no accounts, no sessions, and no per-device
revocation. Changing the token means restarting the server and updating each device.

## What is encrypted, and what is not

Domingo terminates no TLS of its own. Encryption comes from whatever fronts it,
usually Tailscale Serve. Behind that, the browser to server hop is HTTPS.

The server to engine hop is plain HTTP by default, because the engine listens on
loopback on the same machine. If you point Domingo at an engine on another machine,
you are sending prompts in the clear on that hop unless you put a tunnel in front of it.

Prompts and answers are not encrypted at rest by Domingo, because it stores no
prompts. Chat history lives in the browser that created it: localStorage for text,
IndexedDB for images. Anyone with your browser profile, or your unlocked machine, can
read it. Exported history files are plain JSON.

A token in a URL is not secret from: your browser history, any proxy in the path,
`Referer` headers on links you click, screenshots, and shell history if you script it.
The URL with the token is for the first visit. Bookmark the plain address afterwards.

## Do not

Do not bind `0.0.0.0` and reach for the token as an afterthought. The app refuses, and
that refusal is the point.

Do not expose this to the public internet. A tailnet is a network you control. A
public port on a model server gets scanned within minutes.

Do not put the token in a screenshot, a commit, an issue, or a README.
`tools/check-secrets.py` runs in CI and fails the build when a tracked file carries one.

Do not run an engine with tool or file access and share it on a network you do not
fully control. The token grants the model's capabilities, not just its text.

Do not rely on the Stop button as a server-side control. The engine has no abort
route, so Stop closes your browser's connection and leaves the generation running.

## Limits, stated plainly

Single shared token, no accounts, no per-user isolation, no roles.
No rate limiting, no lockout, no audit log of who asked what.
No CSRF token; the cookie is `SameSite=Lax` and the API needs a header on writes.
No Content-Security-Policy, no sandboxed rendering of model output.
No prompt-injection defence. Text from an attached image, a pasted page, or a
retrieved document is treated as instructions by the model, the same as yours.
No encryption at rest for history, because history is in the browser.
No verification that the engine you discovered is the engine you meant. Discovery
reads config files written by Strata on this machine.

These are the choices of a single-user tool built by one person for their own
devices. They are limits, not oversights, and they will not change into a
multi-tenant system.

## Reporting

Open a private security advisory: Security tab, "Report a vulnerability", at
`https://github.com/iulianduminica/Domingo/security/advisories/new`.

Include the version from `/api/info`, how you reached the server, and what you could
do that you should not have been able to. A short reproduction is worth more than a
long description.

You will get a reply, and a fix if the report is actionable. There is no SLA and no
bounty: this is a personal project, not a company. Do not open a public issue for a
vulnerability.
