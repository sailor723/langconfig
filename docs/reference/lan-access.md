# LAN access — accounts, and what everyone still shares

**Questions this answers:** two people need to use LangConfig. How do they sign in, who can
sign in, and what does everyone still see?

**Short answer:** the app now has **accounts**. A person signs in with the browser's Basic-auth
prompt, the credential is checked against a `users` table, and every request is attributable to
that person (`audit_logs.user_id`, `chat_sessions.user_id`). Roles are `admin` and `member`;
admins manage accounts in the app under **Users**. What accounts do *not* do is isolate data:
everyone in one install still shares projects, files, chats, tools, skills, knowledge — and
provider API keys. Separate front doors, one workspace. §5 lists exactly what is shared, and §9
says what real isolation would take.

---

## 1. What LAN mode is

| | Default (`LANGCONFIG_LAN_ACCESS=off`) | LAN mode (`=on`) |
|---|---|---|
| Requests from this machine (127.0.0.1) | allowed | allowed, unchanged — resolved to the install's owner |
| Requests from the network | **allowed, unauthenticated** — no gate exists | allowed with a per-person credential from the `users` table |
| UI for other people | — | built bundle served from `:8765` |
| Local dev server (`:1421`) | works | works, and stays loopback-only |
| Who did what | unknown | `user_id` on new audit rows and chat sessions |

The default column is worth reading twice: it is not "locked down", it is "no gate at all".
LAN mode adds the gate. Off means the backend still binds `0.0.0.0:8765` (`start.sh`) and
**anything on the network can drive the whole app** — run code, read any file, spend your API
keys. Turning the flag on is a decision about *who* gets in, not about whether to protect
anything.

## 2. How it actually works

Four mechanisms, in `backend/middleware/lan_guard.py`, `backend/middleware/identity.py` and the
tail of `backend/main.py`:

1. **The gate is keyed on the source address, not the Host header.** `scope["client"]` is
   loopback (`127.0.0.0/8`, `::1`) → allowed. Anything else → HTTP Basic credentials required.
   This is why local development, the Vite dev-server proxy and the test suite needed no changes.
   It is *not* keyed on `Host:` or `X-Forwarded-For`, because both are trivially forged by exactly
   the attacker the gate exists to stop.
2. **Credentials are verified against the `users` table** (scrypt hashes, one password per
   person). A verified request carries its identity into the app through a ContextVar
   (`backend/core/context/current_user.py`), so routes and services can ask `current_user()` /
   `require_user()` / `require_admin()` without touching 349 route signatures.
3. **It fails closed.** LAN mode on with an **empty `users` table** returns **503** to every
   network request rather than opening. A database that cannot be read is also **503** — "the
   store is down" must never look like "wrong password". A misconfigured gate must never silently
   become an open one.
4. **LAN users are served the built frontend from `:8765` itself.** One origin means the browser
   answers the 401 challenge on the document once, then attaches those credentials to every
   same-origin request — fetches, SSE streams (`/api/chat/...`, workflow execution) and the
   terminal's WebSocket alike.

### Why not just point people at Vite on `:1421`?

Two independent reasons, both fatal:

- `vite.config.ts` sets `allowedHosts: [process.env.VITE_ALLOWED_HOSTS || "localhost"]`, so Vite
  answers *"Blocked request. This host is not allowed."* for the LAN IP. (`VITE_ALLOWED_HOSTS` is
  read from the **shell**, not from `.env` — it is not run through `loadEnv`. Exporting it in
  `.env` silently does nothing.)
- Even with that fixed, the dev server proxies `/api` → `127.0.0.1:8765` **from loopback**,
  which the gate exempts by design. Going through Vite would bypass the gate entirely. That is
  why LAN users get the built bundle instead.

## 3. Turn it on

```bash
# 1. In .env — switch the gate on, and seed the FIRST administrator.
LANGCONFIG_LAN_ACCESS=on
LANGCONFIG_LAN_USERS=admin:<password>
```

```bash
# 2. Build the UI people will actually load, then start as usual.
npm run build
bash start.sh
```

`start.sh` prints the URL to hand over (names only — never passwords).

### The `.env` credential is a one-time seed, not the user list

On first boot the backend imports `LANGCONFIG_LAN_USERS` into the `users` table: the **first**
entry becomes an **admin**, the rest become members. After that:

- **`.env` is never read again.** Editing `LANGCONFIG_LAN_USERS` later does **not** add, rename,
  remove or re-password anyone. This is the rule provider API keys already follow (DB only), and
  it exists so a file on disk cannot silently become a way into a database of accounts.
- Accounts are managed **in the app**: activity bar → user icon → **Users…** (admin only).
- The boot log says which state you are in: `Bootstrapped 1 account(s) from .env` on the first
  boot, `User accounts: 3 existing (bootstrap skipped)` afterwards.

If the users table is empty and `.env` has no credential, nobody can sign in. Create the first
admin from a shell on the server:

```bash
cd backend
.venv/bin/python scripts/create_user.py admin 'a-long-password' --admin
.venv/bin/python scripts/create_user.py --list      # who exists, roles, last sign-in
```

`create_user.py` is an operator tool, not the normal workflow: creating accounts, resetting,
disabling and promoting all live in the app.

### Accounts, roles and passwords

| | Member | Admin |
|---|---|---|
| Sign in, chat, build, run | yes | yes |
| Change own display name and password | yes | yes |
| List / create / disable accounts, reset passwords | no | yes |

- **Password policy: minimum 8 characters.** No email, no reset link, no self-service signup — an
  admin sets the initial password and tells the person. A LAN app with no outbound mail has no
  honest alternative.
- **Changing your own password asks for the current one** even though the browser is already
  signed in: an unlocked laptop is not consent.
- **Two guards on the server**: an admin cannot demote or disable themselves, and the last active
  admin cannot be demoted or disabled. Locking everyone out of an install with no recovery path
  is not a feature.
- **A disabled account is refused exactly like a wrong password** (401), so nobody can probe
  which usernames exist or which are merely switched off.

### Adding or removing a person

In **Users** (admin): add an account with an initial password, or set the row to *Disabled*.
Disabling is immediate — the verifier's cache is invalidated on every change, so the person's
next request is refused rather than up to a minute later. Nothing is ever hard-deleted: the
`user_id` columns that now point at existing work keep their owner.

### Signing out, and what it can honestly promise

The user popover (**activity bar → your icon → Sign out**) really does end access from that
browser — including a reload, which shows a "Signed out" page instead of the app — because the
backend marks the browser as signed out and the gate then refuses it *before* it looks at the
credential.

That takes one extra piece of state, and it is worth understanding why:

- HTTP Basic has **no session and no logout message**. The browser keeps the credential in its own
  cache and attaches it to every request for the realm until the browser is closed.
- So signing out sets a **session cookie** (`langconfig_signed_out`, `HttpOnly`, no `Max-Age` — it
  dies with the browser session, like the credential it suppresses) and answers with **401 and no
  `WWW-Authenticate` header**. The missing challenge is the trick: a 401 *with* a challenge makes
  the browser re-prompt or silently retry with the credential it still holds, which would undo the
  sign-out one request later.
- **Sign in** (on that page) deletes the marker and redirects back into the app; the browser
  replays its remembered credential, so returning to your own account needs no typing.

What it does **not** do: forget the password the browser has saved. Anyone who presses *Sign in*
on that browser is back in as the same person. To hand a machine to someone else, **close the
browser or use a private window** — that is the only step that also clears the browser's own
credential cache. The sign-out page says exactly this, in these words.

## 4. Verify it, don't assume it

From **the other machine** (replace the IP):

```bash
curl -i http://192.168.3.23:8765/api/users/me                            # 401 + WWW-Authenticate
curl -i -u alice:<password> http://192.168.3.23:8765/api/users/me        # 200, "username":"alice"
curl -i -u alice:<bobs-password> http://192.168.3.23:8765/api/users/me   # 401
curl -i -u alice:<password> http://192.168.3.23:8765/api/users           # 403 when alice is a member
```

Sign out / sign in, as the browser does it (a cookie jar stands in for the browser):

```bash
curl -s -c jar -o page.html http://192.168.3.23:8765/api/auth/sign-out   # 200 + session cookie
grep -c "Signed out" page.html                                          # 1
curl -s -i -b jar -u alice:<password> http://192.168.3.23:8765/api/chat/health | head -1
#   401 and NO WWW-Authenticate — the credential alice still holds is not enough
curl -s -i -b jar -c jar http://192.168.3.23:8765/api/auth/sign-in | head -3   # 303 -> /
curl -s -o /dev/null -w '%{http_code}\n' -b jar -u alice:<password> \
  http://192.168.3.23:8765/api/users/me                                          # 200 again
```

From **this machine**, loopback must stay open (this is what keeps local dev working) and
resolves to the install's owner:

```bash
curl -i http://127.0.0.1:8765/api/users/me       # 200, no credentials, "via":"loopback"
```

Tests for the whole chain — gate contract, verification, roles, attribution:

```bash
cd backend && .venv/bin/python -m pytest \
  tests/test_lan_guard.py tests/test_user_service.py tests/test_user_api.py \
  tests/test_audit_attribution.py tests/test_chat_session_manager.py -q   # 107
```

## 5. What everyone shares with you

This is the part to agree on *before* handing out accounts. Accounts are separate; the workspace
is not.

| Shared, not per-user | Where it lives |
|---|---|
| Provider API keys (and the spend they authorise) | `settings.api_keys`, one row |
| Google/OAuth tokens | `oauth_tokens` — `provider` is `UNIQUE` |
| Projects, workflows, agents, tools, skills, knowledge bases | no `owner_id` on any of them |
| Files, uploaded documents, agent workspaces | local disk, keyed by numeric id + slug, **absolute** paths in the DB |
| Chat history and memory | `chat_sessions`, `conversation_archives` — visible to everyone |
| Every setting: default model, theme, workspace path, storage mode | `settings_documents`, one row per namespace |

Consequences worth naming out loud:

- **You can overwrite each other.** Two people editing one workflow is last-write-wins.
- **Attribution is real now, but forward-only.** New rows carry `user_id` (`audit_logs`,
  `chat_sessions`), so "who ran that" has an answer *from this version on*. Rows written before
  accounts existed stay `NULL`; nobody knows who made them and nothing guesses.
- **Trust is machine trust.** The agent tools include filesystem and shell access, and exports
  write files to disk. Anyone with an account has your machine and your keys.
- **Plain HTTP.** Basic-auth credentials are base64, not encrypted, so anyone who can sniff your
  LAN traffic can read the password. Fine on a home/office LAN you control; not fine on shared or
  public Wi-Fi. See §8.

## 6. Client-side things that break off-localhost

A page served over `http://192.168.x.x` is **not a secure context**. The platform hides several
APIs; the app hit this and has one fix in place:

- **`navigator.clipboard` is `undefined`** off-localhost. ~20 call sites across the UI called it
  unguarded, so every copy button threw on a LAN origin. `src/lib/clipboard.ts` now installs a
  fallback once at startup (`src/main.tsx`), backed by `document.execCommand('copy')`, which needs
  no secure context. New code should prefer `copyText()` from that module, which reports whether
  the copy happened. Reading the clipboard is still impossible without HTTPS, and fails loudly
  rather than returning `''`.
- **No HTTPS also blocks** service workers, `crypto.subtle`, geolocation, and camera/microphone
  capture. None are used by the core editor/chat flow, but a future feature that reaches for one
  will fail only for the LAN user — a bug class worth remembering.
- **The terminal works**, because `TerminalTab.tsx` builds its WebSocket URL from
  `window.location.host` and switches `ws:`/`wss:` with the page protocol. Any new
  `new WebSocket("ws://localhost:…")` would break on LAN — use `window.location`.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `503` saying no account exists | gate on, `users` table empty | create the first admin: `backend/scripts/create_user.py <name> <pw> --admin`, or seed `LANGCONFIG_LAN_USERS` |
| `503` saying the user store is unavailable | database unreachable from the backend | check PostgreSQL (`docker ps`, `DATABASE_URL`), then restart |
| `401` on every request, browser never prompts | client not sending credentials; some fetch-only flows do not trigger the dialog | open `http://<ip>:8765/` directly first, so the document itself is challenged |
| Browser shows a login box for `192.168…` | working as intended | enter your own name and password |
| A person suddenly gets `401` | their account was disabled (in **Users**), or the password was reset | re-enable, or give them the new password |
| An account added to `.env` never appears | `.env` is bootstrap-only and was already imported once | add the account in **Users** |
| `403` "Administrator role required." | that account is a member | promote it in **Users** as an admin |
| Password change rejected | wrong current password, or fewer than 8 characters | the message names which |
| JSON `{"app": "LangConfig"}` at the LAN URL | backend running without LAN mode (or without `dist/`) | `LANGCONFIG_LAN_ACCESS=on` **and** `npm run build`, then restart |
| `404 Not Found` JSON on a frontend path | an `/api/...`-looking path never falls through to the SPA (by design) | check the real endpoint |
| Copy buttons do nothing | stale bundle without `src/lib/clipboard.ts` | `npm run build` and hard-refresh |
| Local dev suddenly asks for a password | you opened `:8765` from another interface, not loopback | use `localhost`/`127.0.0.1`, or send credentials |
| A webhook receiver now returns 401 | external endpoint hitting a gated path | add its prefix to `LANGCONFIG_LAN_BYPASS_PATHS` — **only** if it verifies its own signatures |
| Everyone is locked out | the last admin's password was lost or the account was disabled | `create_user.py --reset-password` or `--enable` on the server |
| "Signed out" page reappears after signing in | the sign-in link was opened with the marker still set | use the **Sign in** button on that page (it clears the cookie); a bookmark to `/` will stay signed out until you do |
| Signed out, but clicking Sign in returns to the same person | expected — the browser replays its saved credential | close the browser or use a private window to be a different person |

## 8. If you need this beyond a trusted LAN

The password crosses the wire in base64. For anything past your own network, terminate TLS in
front of the backend and let that layer do the authentication — a reverse proxy (Caddy, nginx,
Traefik) with HTTPS and its own auth, or reach the machine over WireGuard/Tailscale and keep it
off the public internet entirely. `LANGCONFIG_LAN_BYPASS_PATHS` and the loopback exemption are
both things you would want to re-examine under that setup.

**A specific trap worth knowing.** If the reverse proxy runs on *this same machine*, every request
reaches the backend from `127.0.0.1`, so the loopback exemption applies to all of them and LAN
mode protects nothing — the backend sees only "local" traffic, which resolves to the install's
owner. In that topology the proxy *is* the gate; treat `LANGCONFIG_LAN_ACCESS` as off and make
sure the proxy is the thing doing authentication. If you need per-person attribution *through* a
proxy, the proxy must pass the credential through (an `Authorization` header it does not consume)
rather than authenticate on the backend's behalf.

## 9. When this is not enough — separate data per person

Accounts give each person a credential, an audit trail and individual revocation. They do not give
anyone a private workspace. If two people must *not* see each other's projects, files, keys or
chat history, the work is a rebuild:

- `settings_documents` is **one row per namespace** with no owner column, and
  `oauth_tokens.provider` is `UNIQUE` — per-user credentials mean an owner key on both, not a new
  table.
- ~39 tables have no ownership column; every query would need a tenancy key and a read-path guard.
- Storage is local directories with **absolute paths** in the database (see
  [`storage-map.md`](storage-map.md)) — per-user isolation means re-rooting the filesystem layout.
- Process-global caches already carry the caller in their keys (`chat_session_manager` uses
  `u<id>:<session>:<agent>:<version>`, so a cached agent built with one person's credentials can
  never be served to another) — but the *content* they read is still shared.

[`plans/2026-10-17-multiuser-design.md`](plans/2026-10-17-multiuser-design.md) is the plan for the
rest: per-user provider keys, private custom tools/skills/prompts and per-user workspaces, on top
of the identity layer this document describes; its §2 lists what already exists to build on.
[`plans/2026-02-12-langconfig-saas-design.md`](plans/2026-02-12-langconfig-saas-design.md) reached
the same conclusion for the full multi-tenant product — *"Current LangConfig has zero
multi-tenancy; retrofitting is harder than rebuilding"* — and designs a separate
`langconfig-cloud` codebase with Better Auth, orgs, RLS and Stripe instead.

---

## Appendix — configuration reference

| Variable | Default | Meaning |
|---|---|---|
| `LANGCONFIG_LAN_ACCESS` | `off` | `on` enables the gate **and** SPA serving on `:8765` |
| `LANGCONFIG_LAN_USERS` | *(empty)* | comma-separated `name:password` — **imported once into the `users` table on first boot**, then ignored. Malformed entries are dropped and reported at boot |
| `LANGCONFIG_LAN_USER` | `langconfig` | legacy single username — read only when `LANGCONFIG_LAN_USERS` is empty |
| `LANGCONFIG_LAN_PASSWORD` | *(empty)* | legacy single password, same bootstrap-only rule |
| `LANGCONFIG_LAN_BYPASS_PATHS` | *(empty)* | comma-separated path prefixes that skip auth; anyone can reach these |
| *(no setting)* | — | `/api/auth/` is **always** reachable, signed out or not: it serves the sign-out/sign-in pages. The marker cookie is `langconfig_signed_out` |

Code: `backend/middleware/lan_guard.py` (gate), `backend/middleware/identity.py` (identity from
the verified scope), `backend/core/security/{passwords,lan_auth}.py` (scrypt hashes, verifier +
cache), `backend/core/context/current_user.py` (request identity), `backend/services/user_service.py`
(accounts, bootstrap, guards), `backend/api/users/routes.py` (self-service + admin API),
`backend/models/user.py`, `alembic/versions/032_add_users.py`, `backend/scripts/create_user.py`
(operator tool), `backend/api/auth/signout.py` (sign out/in pages and the marker cookie), and in
the UI `src/components/layout2/{UserPopover,UserAccountDialogs}.tsx`.

Tests: `backend/tests/test_lan_guard.py`, `test_user_service.py`, `test_user_api.py`,
`test_audit_attribution.py`, `test_chat_session_manager.py`.
