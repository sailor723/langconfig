# LAN access — letting other people use this instance

**Question this answers:** two people need to use LangConfig. What is the smallest thing
that works, and what does it cost?

**Short answer:** this app is single-user by construction — there is no authentication
anywhere (no login, no session, no token; all 43 routers in `backend/main.py` are open).
LAN mode is therefore **one door with a key each** — separate credentials, one shared
workspace. It gives other people working access to the same instance, behind their own
password, with *everything else shared*. That is a real capability and a real limitation;
both are spelled out below.

If you need two people with separate data, see §9 — that is a different project, and this
repo's own SaaS plan says so.

---

## 1. What LAN mode is

| | Default (`LANGCONFIG_LAN_ACCESS=off`) | LAN mode (`=on`) |
|---|---|---|
| Requests from this machine (127.0.0.1) | allowed | allowed, unchanged |
| Requests from the network | **allowed, unauthenticated** — no gate exists | allowed with the Basic-auth password |
| UI for other people | — | built bundle served from `:8765` |
| Local dev server (`:1421`) | works | works, and stays loopback-only |

The default column is worth reading twice: it is not "locked down", it is "no gate at
all". LAN mode is the thing that adds a gate; off means the old behaviour, where the
backend binds `0.0.0.0:8765` (`start.sh`) and **anything on the network can drive the
whole app** — run code, read any file, spend your API keys. Turning the flag on is
therefore a decision about *who* gets in, not about whether to protect anything.

## 2. How it actually works

Three mechanisms, in `backend/middleware/lan_guard.py` and the tail of `backend/main.py`:

1. **The gate is keyed on the source address, not the Host header.**
   `scope["client"]` is loopback (`127.0.0.0/8`, `::1`) → allowed. Anything else → HTTP
   Basic credentials required. This is why local development, the Vite dev-server proxy
   and the test suite needed no changes. It is *not* keyed on `Host:` or
   `X-Forwarded-For`, because both are trivially forged by exactly the attacker the gate
   exists to stop.
2. **It fails closed.** `LANGCONFIG_LAN_ACCESS=on` with an empty
   `LANGCONFIG_LAN_USERS` (and no legacy password) returns **503** to every network
   request rather than opening.
   A misconfigured gate must never silently become an open one.
3. **LAN users are served the built frontend from `:8765` itself.** One origin means the
   browser answers the 401 challenge on the document once, then attaches those credentials
   to every same-origin request — fetches, SSE streams (`/api/chat/...`, workflow
   execution) and the terminal's WebSocket alike.

### Why not just point people at Vite on `:1421`?

Two independent reasons, both fatal:

- `vite.config.ts` sets `allowedHosts: [process.env.VITE_ALLOWED_HOSTS || "localhost"]`,
  so Vite answers *"Blocked request. This host is not allowed."* for the LAN IP.
  (`VITE_ALLOWED_HOSTS` is read from the **shell**, not from `.env` — it is not run
  through `loadEnv`. Exporting it in `.env` silently does nothing.)
- Even with that fixed, the dev server proxies `/api` → `127.0.0.1:8765` **from
  loopback**, which the gate exempts by design. Going through Vite would bypass the gate
  entirely. That is why LAN users get the built bundle instead.

## 3. Turn it on

```bash
# 1. In .env (the single source of truth — start.sh and the backend both read it).
#    One credential per person, comma-separated name:password.
LANGCONFIG_LAN_ACCESS=on
LANGCONFIG_LAN_USERS=alice:<pw>,bob:<pw>,carol:<pw>
```

Each password can be generated with `openssl rand -hex 16`. Only the **first** colon
separates name from password, so a password may contain `:`.

```bash
# 2. Build the UI people will actually load, then start as usual.
npm run build
bash start.sh
```

`start.sh` prints the exact URL to hand over (names only — never passwords), e.g.:

```
  LAN (shared instance): http://192.168.3.23:8765
    accounts: alice bob carol  (passwords: LANGCONFIG_LAN_USERS in .env)
```

Rebuild (`npm run build`) after any frontend change — LAN users run the built bundle,
not the dev server's on-demand transform.

### Adding or removing a person

Edit the `LANGCONFIG_LAN_USERS` line and restart the backend. Nothing else changes:

```bash
# remove bob: everyone else keeps the same password, and nobody is told anything
LANGCONFIG_LAN_USERS=alice:<pw>,carol:<pw>
```

This is the whole reason for separate credentials. With one shared password, removing a
person means changing the password and re-notifying everyone — which is why people stop
doing it and the old password lives on.

**Limits of this:** separate credentials decide who gets *in*. They do not create users
inside the app — alice and bob still share one workspace, one settings row, one set of API
keys, and the app still cannot attribute an action to a person. For that, see §9.

The legacy single-credential pair (`LANGCONFIG_LAN_USER` + `LANGCONFIG_LAN_PASSWORD`) is
still honoured when `LANGCONFIG_LAN_USERS` is empty, so older `.env` files keep working;
`LANGCONFIG_LAN_USERS` wins when both are set.

## 4. Verify it, don't assume it

From **the other machine** (replace the IP):

```bash
curl -i http://192.168.3.23:8765/api/chat/health        # expect 401 + WWW-Authenticate
curl -i -u alice:<password> http://192.168.3.23:8765/api/chat/health      # expect 200
curl -i -u alice:<bobs-password> http://192.168.3.23:8765/api/chat/health  # expect 401
```

From **this machine**, loopback must stay open (this is what keeps local dev working):

```bash
curl -i http://127.0.0.1:8765/api/chat/health           # expect 200, no credentials
```

Unit tests for the gate's contract, including its fail-closed and anti-spoof behaviour:

```bash
cd backend && .venv/bin/python -m pytest tests/test_lan_guard.py -q
```

## 5. What everyone shares with you

This is the part to agree on *before* handing over credentials. Separate passwords, but one
identity as far as the app is concerned, so:

| Shared, not per-user | Where it lives |
|---|---|
| Provider API keys (and the spend they authorise) | `settings.api_keys`, one row |
| Google/OAuth tokens | `oauth_tokens` — `provider` is `UNIQUE`; the model's own comment says *"This is a single-user app"* |
| Projects, workflows, agents, tools, skills | no `owner_id` on any of them |
| Files, uploaded documents, agent workspaces | local disk, keyed by numeric id + slug, **absolute** paths in the DB |
| Chat history and memory | `chat_sessions`, `conversation_archives` |
| Every setting: default model, theme, workspace path, storage mode | `settings`, single row (`id=1`) |

Consequences worth naming out loud:

- **You can overwrite each other.** Two people editing one workflow is last-write-wins.
- **Attribution is nonexistent.** `audit_log.user_id` and `chat_sessions.user_id` exist but
  are `nullable` and never populated from an authenticated identity — you cannot tell who
  ran what.
- **Trust is machine trust.** The agent tools include filesystem and shell access, and
  exports write files to disk. The person with the password has your machine and your keys.
- **Plain HTTP.** Basic-auth credentials are base64, not encrypted, so anyone who can
  sniff your LAN traffic can read the password. Fine on a home/office LAN you control;
  not fine on shared or public Wi-Fi. See §8 for the fix.

## 6. Client-side things that break off-localhost

A page served over `http://192.168.x.x` is **not a secure context**. The platform hides
several APIs; the app hit this and has one fix in place:

- **`navigator.clipboard` is `undefined`** off-localhost. ~20 call sites across the UI
  called it unguarded, so every copy button threw on a LAN origin.
  `src/lib/clipboard.ts` now installs a fallback once at startup (`src/main.tsx`), backed
  by `document.execCommand('copy')`, which needs no secure context. New code should prefer
  `copyText()` from that module, which reports whether the copy happened. Reading the
  clipboard is still impossible without HTTPS, and fails loudly rather than returning `''`.
- **No HTTPS also blocks** service workers, `crypto.subtle`, geolocation, and
  camera/microphone capture. None are used by the core editor/chat flow, but a future
  feature that reaches for one will fail only for the LAN user — a bug class worth
  remembering.
- **The terminal works**, because `TerminalTab.tsx` builds its WebSocket URL from
  `window.location.host` and switches `ws:`/`wss:` with the page protocol. Any new
  `new WebSocket("ws://localhost:…")` would break on LAN — use `window.location`.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `503` and text about `LANGCONFIG_LAN_USERS` | flag on, no usable credential | set `LANGCONFIG_LAN_USERS` in `.env`, restart the backend |
| `401` on every request, browser never prompts | client not sending credentials; some fetch-only flows do not trigger the dialog | open `http://<ip>:8765/` directly first, so the document itself is challenged |
| Browser shows a login box for `192.168…` | working as intended | enter your own name and password |
| A named person suddenly gets `401` | their entry was removed or is malformed (boot log says which) | check the entry's `name:password` shape, restart |
| JSON `{"app": "LangConfig"}` at the LAN URL | you are running the backend without LAN mode (or without `dist/`) | `LANGCONFIG_LAN_ACCESS=on` **and** `npm run build`, then restart |
| `404 Not Found` JSON on a frontend path | an `/api/...`-looking path never falls through to the SPA (by design) | check the real endpoint |
| Copy buttons do nothing | stale bundle without `src/lib/clipboard.ts` | `npm run build` and hard-refresh |
| Local dev suddenly asks for a password | you opened `:8765` from another interface, not loopback | use `localhost`/`127.0.0.1`, or send credentials |
| A webhook receiver now returns 401 | external endpoint hitting a gated path | add its prefix to `LANGCONFIG_LAN_BYPASS_PATHS` — **only** if it verifies its own signatures |

## 8. If you need this beyond a trusted LAN

The password crosses the wire in base64. For anything past your own network, terminate TLS
in front of the backend and let that layer do the authentication — a reverse proxy (Caddy,
nginx, Traefik) with HTTPS and its own auth, or reach the machine over WireGuard/Tailscale
and keep it off the public internet entirely. `LANGCONFIG_LAN_BYPASS_PATHS` and the
loopback exemption are both things you would want to re-examine under that setup.

**A specific trap worth knowing.** If the reverse proxy runs on *this same machine*, every
request reaches the backend from `127.0.0.1`, so the loopback exemption applies to all of
them and LAN mode protects nothing — the backend sees only "local" traffic and cannot tell
one user from another. In that topology the proxy *is* the gate; treat
`LANGCONFIG_LAN_ACCESS` as off and make sure the proxy is the thing doing authentication.
Putting the proxy on the LAN in front of an unauthorised backend hands out the same open
door this document exists to close.

## 9. When this is not enough — separate users, separate data

LAN mode is a shared door. If two people must *not* see each other's projects, files, keys
or chat history, the work is not a patch:

- `settings` is a **single row** and `oauth_tokens.provider` is `UNIQUE` — per-user
  credentials mean rebuilding both into per-user tables.
- ~39 tables have no ownership column; every query would need a tenancy key.
- Storage is local directories with **absolute paths** in the database
  (see [`storage-map.md`](storage-map.md)) — per-user isolation means re-rooting the
  filesystem layout, not adding a column.
- Process-global singletons (`event_bus`, `chat_session_manager`, `context_window_manager`)
  are shared by construction.

[`plans/2026-02-12-langconfig-saas-design.md`](plans/2026-02-12-langconfig-saas-design.md)
reached the same conclusion for the full multi-tenant product — *"Current LangConfig has
zero multi-tenancy; retrofitting is harder than rebuilding"* — and designs a separate
`langconfig-cloud` codebase with Better Auth, orgs, RLS and Stripe instead.

**Rough shape of the intermediate step** (named users, still one shared workspace, so you
at least know who did what): add a `users` table and a signed session cookie, then populate
the `user_id` columns that already exist (`audit_log`, `chat_sessions`,
`conversation_archive`, `search_history`) from that identity. Days, not weeks — and no
schema surgery, because the nullable columns are already there.

That step is *not* what LAN mode does. LAN mode gives each person a credential, which makes
entry revocable and refuses traceable, but the application never learns who they are: after
the door, every request is anonymous. If "who deleted this workflow?" must have an answer,
the work above is the actual fix.

---

## Appendix — configuration reference

| Variable | Default | Meaning |
|---|---|---|
| `LANGCONFIG_LAN_ACCESS` | `off` | `on` enables the gate **and** SPA serving on `:8765` |
| `LANGCONFIG_LAN_USERS` | *(empty)* | comma-separated `name:password`; the per-person form. Malformed entries are dropped and reported at boot |
| `LANGCONFIG_LAN_USER` | `langconfig` | legacy single username — read only when `LANGCONFIG_LAN_USERS` is empty |
| `LANGCONFIG_LAN_PASSWORD` | *(empty)* | legacy single password; with no usable credential, every LAN request gets 503 |
| `LANGCONFIG_LAN_BYPASS_PATHS` | *(empty)* | comma-separated path prefixes that skip auth; anyone can reach these |

Code: `backend/middleware/lan_guard.py` (gate), `backend/main.py` (middleware registration
+ SPA serving), `backend/tests/test_lan_guard.py` (contract), `src/lib/clipboard.ts`
(insecure-context fallback), `env_example` (§"LAN access").
