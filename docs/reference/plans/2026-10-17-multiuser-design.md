# Real multi-user management — study and evaluation

**Date:** 2026-10-17
**Status:** Study / awaiting decisions (§14). **No code written and none planned for now** —
implementation was started on Slice 1 and then rolled back at the product owner's request (see
§0.1). The running app is single-access + the LAN gate.

**Design input from the product owner (2026-10-17), which changes the tiering below:** the
*core of the system is shared* — the code itself, built-in agents, built-in tools, built-in
skills, **and the knowledge base**. "KB shared" is a deliberate product decision, not an
oversight; it inverts what this study originally assumed and is applied throughout (§4 R2/R3,
§6.4, §9, §10, Slice 2).
**Supersedes the framing of:** [`../lan-access.md`](../lan-access.md) §9 ("when this is not enough")

Four requirements were given:

1. Each user has their **own API keys**.
2. Tools and prompts: **built-ins shared**, each user's **custom ones private**.
3. The **workspace is separated per user**.
4. "Other" — everything else that has to be decided, found and listed in §10.

---

## 0. Verdict up front

Multi-user is **substantially more tractable than the codebase's own documentation claims**, for a
reason that is easy to miss: this app went through a settings refactor that built the exact seam a
per-user design needs, and most tables already carry the ownership columns. What is missing is
*identity* — one authenticated principal threaded through — plus a handful of hard blockers.

Four things should change the plan you may already have in mind:

| # | Discovery | Consequence |
|---|---|---|
| **1** | Settings are already **one row per namespace** (`settings_documents(ns)`), secrets encrypted per document, with ~10 chokepoint call sites — not 43 routers. | Per-user settings/keys is a **schema change plus threading `user_id`**, not a rewrite. This is the single biggest de-risking. |
| **2** | **"Prompts" are not a stored entity.** The Prompt activity is a read-only projection of `deep_agent_templates.system_prompt`. | Requirement 2 cannot be met for prompts without **creating a new owned entity**. Requirements as written assume something that does not exist. |
| **3** | The **dangerous leak is not the database, it is the process cache**: `chat_session_manager.active_sessions` caches live `agent_instance` objects — already built with resolved credentials — keyed by `session_id:agent_id:agent_version`, **with no user in the key**. | Per-user keys can silently serve user A's key to user B. This must be fixed *before* per-user keys ship, not after. |
| **4** | Absolute machine paths are **baked into JSONB**: 50 of 56 agents carry `/Users/…` inside `config` (`system_prompt`/`agent_docs`), plus 1,989 knowledge-catalog records. | The path migration is a **content rewrite**, not a column update. It is small in volume (§9.4) but must be scripted and reversible. |
| **5** | **`is_builtin` is a code-execution trust boundary that any caller can rewrite.** `PUT /api/custom-tools/{id}` has no built-in guard and no owner check, and built-ins execute with a full `__builtins__` + `os`/`pathlib` namespace. | With one user this is an open exec surface; with two it is **privilege escalation** (§8.2). Fix before the second user exists, not as part of "phase 3". |

Plus one structural constraint that decides the enforcement strategy: **349 routes, 8 with any
auth-ish dependency.** Ownership cannot be enforced route-by-route. §11 addresses this.

---

### 0.1 Where implementation actually stands

Slice 1 (identity + profiles) was begun and then rolled back in the same session, deliberately, so
the repository is not left half-migrated. What was written and removed: `models/user.py`,
`core/security/{passwords,lan_auth}.py`, `core/context/current_user.py`, `services/user_service.py`,
`middleware/identity.py`, plus a rewrite of the LAN gate to verify against a `users` table.

**The current, working state:** the original single-access LAN gate (`middleware/lan_guard.py`,
env-configured, `admin:1234`), 32 passing gate tests, and no per-user anything. Local development
is password-free on loopback.

The lesson worth keeping: the gate rewrite had made *login itself* depend on the unfinished slice —
restarting the server mid-slice would have locked every LAN user out with `503`. Any future slice
must be landed atomically (schema + bootstrap + gate + tests together) or not at all.

## 1. Method

- Read-only code and schema inspection of this repository; no files modified except this document.
- Live read-only SQL against the running PostgreSQL (row counts and value shapes, §9.3/§9.4).
- Three deep dives ran in parallel: tools/skills/prompts, and workspace/storage paths, both of whose
  findings are incorporated below. The third (runtime globals and run tables) was cut short; its
  highest-risk items — the agent-instance cache, the event bus, the schema registry, per-worker
  state — were verified directly and appear in §3.4 and §7.2, but the complete per-table attribution
  checklist for run/history tables in §10 is a **plan-to-verify** list, not an exhaustively audited
  one. Treat that row set as the first task of Phase 6, not as settled fact.
- Claims carry `path:line` citations; numbers marked *(measured)* came from the live database on
  2026-10-17 and will drift.

---

## 2. What already exists (the seam)

This section matters because it converts "rewrite" into "wire up". Every item below was verified.

### 2.1 Settings are already namespaced documents

`settings_documents(ns PRIMARY KEY, document JSON, revision, updated_at)` —
`backend/core/settings/store.py:63-67`. One row per namespace, secrets Fernet-encrypted at rest per
document, optimistic `revision` for conflict detection, `mutate()`/`get_document()`/`get_revision()`
as the only accessors.

Ten namespaces (`backend/core/settings/schemas.py:354-365`): `general`, `models`, `workspace`,
`storage`, `rag`, `search`, `onboarding`, `runtime`, `agents`, `knowledge`.

Critical: **the existing design already distinguishes per-person from team settings**, in the seed
exporter's own words — `scripts/seeds/out/export_settings.py:19`, which strips `general` ("per-person
cosmetic") and `onboarding` while exporting the rest as *team* decisions. The concept exists in the
code's reasoning but has no representation in the schema. That is exactly the gap to close.

### 2.2 API keys already resolve through one function

`config.get_api_key_from_db(key_name)` (`backend/config.py:363-380`) reads the `models` namespace's
`api_keys` sub-document and is the **only** source of truth — `.env` credentials are deliberately
ignored and reported once (`backend/config.py:344-361`). Call sites are few and enumerable:
`langgraph/llm.py:117`, `tools/native_impl.py:92,93,592`, `core/tools/factory/builders.py:937,1026`,
`core/graphs/read_file.py:574`.

`ApiKeys` has ~15 provider key fields, each tagged `{"role": "secret"}`
(`backend/core/settings/schemas.py:53-78`), so "which fields are secrets" is already data, not
special-cased code.

### 2.3 Ownership and visibility columns already exist on the important tables

*(measured against the live DB)*

| Table | Existing columns | Rows |
|---|---|---|
| `custom_tools` | `created_by`, `is_public`, `is_builtin`, `project_id`, `parent_tool_id` (fork) | 67 (64 builtin, 3 custom) |
| `deep_agent_templates` | `is_public` — **defaults `true`, and no create path sets it** | 56 |
| `workflow_profiles` | `created_by` | 57 |
| `chat_sessions` | `user_id`, `project_id` | 258 |
| `conversation_archives`, `audit_logs`, `search_history` | `user_id` | — |
| `custom_output_schemas` | `is_public`, `is_builtin` | — |

And a visibility pattern already ships: `GET /api/deepagents?public_only=true` filters
`is_public == True` (`backend/api/agents/deep_agents.py:576-584`), and the custom-tool list already
excludes built-ins (`backend/api/tools/routes.py:139`) because built-ins are served from a separate
native registry.

**But read that carefully — the filter is inert.** `deep_agent_templates.is_public` defaults `true`
and no create path sets it, so `public_only=true` filters nothing today; and for tools, `is_public`
is read in two predicates yet **written by no API path at all**. The *shape* of requirement 2 exists;
the *semantics* were never switched on. `custom_tools.created_by` is likewise written only by the
seeder and read only into an export's `metadata.author`.

One more trap: in `custom_tools`, `project_id IS NULL` means "global to everyone", and NULL is the
API default (`models/custom_tool.py:90`). So the current default for a newly created custom tool is
*shared with all users* — the opposite of what requirement 2 asks for. Any implementation must flip
that default deliberately rather than inherit it.

### 2.4 A runtime context object designed for exactly this, currently inert

`AgentRuntimeContext` carries `user_id`, `user_role`, `user_preferences`, `project_id`,
`session_id`, `thread_id` (`backend/core/context/runtime.py:93-126`) — the LangGraph v1 context
pattern. It is **never instantiated outside its own module**: every `AgentRuntimeContext(` occurrence
is a docstring or a self-test (`runtime.py:281-421`). The pipe exists, unused.

### 2.5 `audit_logs.user_id` and the audit service already accept an identity

`services/audit_service.py:74,206` take `user_id: Optional[int]`; `get_audit_logs():392` can filter
by it. No caller passes it.

**The pattern across 2.4 and 2.5 is the headline of this study: the app was built with multi-user
placeholders and then wired single-user.** The work is mostly connection, not construction — with
the four blockers in §0 and §3 as the exceptions.

---

## 3. What is missing, and what actively blocks

### 3.1 No identity at all (the root cause)

No login, no session, no token; 349 routes, 8 with any auth-ish dependency. Nothing knows who is
calling. Every ownership column above is therefore either NULL or a hardcoded stub.

**However — identity is already at the edge.** The LAN gate we built
(`backend/middleware/lan_guard.py`) authenticates a *named principal* on every non-loopback request
and then discards the name. Browsers attach Basic credentials to every same-origin request
automatically, so in LAN mode the server can know who is asking **with no frontend change**. This is
the cheapest available bootstrap for real identity, and §5 builds on it.

### 3.2 No users table, no roles

Nothing to attach keys, ownership or policy to. `user_profiles` is not it: it is
`user_id INTEGER` populated by regex-extracting a name from chat text
(`backend/api/chat/messages.py:703-745`), with no credentials and no authority.

### 3.3 Two competing settings stores

The legacy single-row `settings` table (`models/settings.py`, `id=1`) is **still read** for language
preference (`api/chat/messages.py:442-448`) and by the models routes
(`api/models/routes.py:16`). A per-user design must decide this table's fate explicitly, or it
becomes a silent second source of truth for preferences (§14 Q3).

### 3.4 The process-level credential cache (highest severity)

`services/chat_session_manager.py:86-118` caches live `agent_instance` objects under
`cache_key = session_id` (optionally `:agent_id[:agent_version]`). Agent instances are constructed
with credentials already resolved. **No user ID in the key.** With per-user keys this is a
cross-user credential leak, not merely a correctness bug.

Same class of issue in two more places:

- `services/event_bus.py:50-114` — subscribers are queued per `channel` string with no identity, so
  anyone subscribing to a channel receives every event on it.
- `models/custom_schema.py:185-190` — `OutputSchemaRegistry._custom_schemas` is a **process-wide dict
  keyed by schema name only**. Two users who both create a schema called `Invoice` overwrite each
  other, and whichever user loads first determines which definition the other one's agent silently
  uses. This is the clearest cross-user leak in the codebase: no database involved, nothing to audit,
  wrong behaviour that looks like a cache.

### 3.5 "Prompts" have no storage

`src/components/layout2/PromptBrowserSidebar.tsx:1-33` states it plainly: prompt entries are
extracted from agent `system_prompt`, and the prompt `id` **is an agent id**; the page loads via
`apiClient.listDeepAgents({ public_only: false })` (`PromptHomePage.tsx:339`). There is no prompt
write path and no prompt table. Requirement 2 for prompts needs a new entity (§8.3).

### 3.6 Ownership is not enforced on reads either

`ChatSession` is fetched by `session_id` alone in at least 12 places (e.g.
`api/chat/session.py:108,242,276,352,445`; `api/chat/documents.py:87,383,535,577,709,744`). Session
ids are UUIDs, so guessing is impractical — but there is no owner check, so any leaked or shared id
is full access. Same shape for documents and files.

### 3.7 `UNIQUE` constraints that assume one user

- `workspace_files.file_path` (`models/workspace_file.py:24`) — UNIQUE
- `storage_objects.key` (`models/storage_object.py:31`) — UNIQUE
- `oauth_tokens.provider` (`models/oauth_token.py:36`) — UNIQUE, and its model docstring says
  *"This is a single-user app, so there's one token per provider"*; six lookups filter
  `provider == X` only (`services/oauth_service.py:142,181,230,294,332`).

Each must become a composite key including the user — a real migration, though small in rows.

---

## 4. Requirements, restated as testable definitions

Ambiguity here is what produces two incompatible implementations. Proposed definitions:

**R1 — Own API keys.** Every credential lookup happens *in the context of a requesting user*; there
is no code path that reads "the" key. A user's key is never visible to another user (not in the UI,
not in logs, not through shared caches), and changing a key takes effect for that user only,
promptly.

**R2 — Shared built-ins, private customs.** Two tiers, not three:

* **Shared (the default for everything the platform ships):** the application **code** itself,
  built-in **agents**, built-in **tools**, built-in **skills**, and — explicitly — the **knowledge
  base**. Readable by everyone, writable only by an admin or through the seed/import path.
  Customising any of these means **forking**, never editing in place.
* **Private:** anything a user creates themselves — their own tools, prompts, skills, schemas,
  projects, workflows, agents-by-fork. Visible to its owner only, unless an admin publishes it.

There is no third "shared but user-owned" tier in v1. It is the most common source of accidental
leakage (it needs an owner *and* a publish flag *and* a revoke path) and nothing in the stated
requirements needs it. Add it later, if ever, as a per-asset-class opt-in.

**R3 — Separate workspaces, shared knowledge.** A user's **scratch/output** area is private: no
other user can read, list or trace their uploaded or generated files, including through exports,
the file browser, or the terminal's working directory.

The **knowledge base is shared by design** (product decision, §0). Anyone may read and query every
KB document. "Isolation" therefore applies to the *working* tree, not the corporate memory — and
this deliberately narrows R3 compared with the study's first draft, which had proposed per-user KB
roots. The remaining per-user question for KB is **authorship and deletion** (who may remove a
document, and whether a contributor's name is recorded), not visibility (§14 Q9).

**R4 — Everything else** is enumerated in §10 and decided in §14.

---

## 5. Identity and authentication — options

The choice here drives everything else, because "who is the current user" must be answerable from
*every* code path, including background threads and background jobs.

### Option A — Keep Basic auth, move the user registry into the DB *(recommended first step)*

`users(id, username, password_hash, role, is_active, created_at)`. The LAN guard verifies against the
DB instead of `.env`, injects the resolved user into the ASGI scope, and a tiny middleware publishes
it as a request-scoped value (ContextVar) plus FastAPI dependency.

- **Effort:** small (~1–2 days). No frontend change at all: the browser's own auth prompt keeps working.
- **Gains:** identity everywhere, per-user credentials, revocation, roles, audit attribution.
- **Limits:** credentials are base64 over plain HTTP (§ lan-access §8); no logout, no expiry, no
  "sign in as" UX; every request re-verifies (a DB lookup; cacheable).
- **Risk:** ContextVar propagation into `run_in_threadpool`/LangGraph worker threads must be
  verified — this is the one thing that can silently fail open, so it needs a test that asserts the
  current user is present inside an agent run.

### Option B — Real login page with a signed session cookie

Adds `POST /auth/login`, an HttpOnly `SameSite=Lax` cookie, CSRF tokens on state-changing routes,
logout, expiry and a user menu. Basic auth retained as a fallback for scripts.

- **Effort:** medium (~3–5 days, frontend included).
- **Gains:** proper UX, HTTPS-deployable, no password prompt per browser profile.
- **Costs:** CSRF handling on 349 routes (mitigable with a single middleware checking
  `Origin`/`Sec-Fetch-Site` rather than per-route tokens); SSE and WebSocket need cookie auth to
  work — both already same-origin, so viable.

### Option C — External IdP / OIDC (Google, Entra, Keycloak)

- **Effort:** high. **Gains:** SSO, offloaded credential handling.
- **Verdict:** defer. Note that Google OAuth **already** exists in this repo but for a different
  purpose (Slides/Docs export, `api/auth/google.py`), and conflating the two would be a mistake.

### Recommendation

**A now, B when the UI matters.** A delivers every capability in requirements 1–3 with no frontend
work and no new attack surface; B is a UX upgrade on top of the same `users` table and the same
request-scoped identity, so it does not invalidate A's plumbing. Critically, **A is a prerequisite
for nothing and a foundation for everything** — the identity plumbing is identical.

Loopback (local development, tests) needs a defined identity: use a designated `owner` user (the
first user row) so local work is attributed rather than anonymous. Do **not** make loopback
"unowned", or half the code paths will keep their single-user special cases forever.

---

## 6. Data model

### 6.1 New core tables

```
users
  id            PK
  username      UNIQUE          -- what the LAN gate / login accepts
  password_hash                 -- argon2id (not the Fernet app key; different job)
  display_name
  role          'admin' | 'member'   -- admin: manage users, publish globals, see everything
  is_active                     -- disable without deleting
  created_at, last_login_at
```

Roles: start with two. Anything more granular should be deferred until a concrete need appears —
`admin`/`member` covers every requirement stated. Add `viewer` only if a read-only auditor is real.

### 6.2 Settings: scope, not a new table

`settings_documents` gains a scope dimension. Two workable encodings:

- **(a) `user_id INTEGER NOT NULL DEFAULT 0`** with PK `(user_id, ns)`, where `0` is the team/global
  layer. Simple, no NULL-in-PK problem, and the existing 9 rows migrate as `user_id = 0` in one
  statement.
- **(b) `scope TEXT`** (`'team'`, `'user:3'`) — flexible, but every query must parse.

**Recommendation: (a)**. It keeps integer joins clean and lets a per-user row be found with an index
on the PK.

Resolution becomes a **three-layer chain**: `schema defaults → team document (user_id=0) → user
document`. That is a natural extension of the existing `resolve()` (`core/settings/resolve.py:54-70`),
which today merges only two layers. This is also precisely how the seed exporter already *thinks*
(`scripts/seeds/out/export_settings.py:19`), so the team layer already has a meaning: it is what
`seed_in` writes and what `seed_out` exports.

**Which namespaces are per-user?** The classification the code already implies, made explicit:

| Namespace | Scope | Why |
|---|---|---|
| `models` (`api_keys`) | **per-user** (team fallback optional) | R1 |
| `general` (theme, language) | **per-user** | cosmetic, already called "per-person" |
| `onboarding` (`setup_complete`) | **per-user** | each person completes their own wizard |
| `workspace`, `storage` | **per-user** | R3 — these are paths/folders |
| `rag`, `search`, `runtime`, `agents`, `knowledge` | **team default + per-user override** | sensible shared defaults, individual overrides |

The `models` case needs one extra decision: **when a user has no key configured, may their run fall
back to the team key?** Recommended: yes, but *visibly* (say so in the UI and in the audit record),
because silent fallback means one person's spend paying for another's work with no trace. This is
§14 Q1.

### 6.3 Ownership columns (additive, mostly)

Add `owner_id INTEGER REFERENCES users(id)` to the tables that carry user data. Prefer `owner_id`
over reusing `created_by VARCHAR(100)` (`models/custom_tool.py:88`, `models/workflow.py:201`), which
is an untyped string with no FK — keep it for display, add `owner_id` for enforcement.

Per table (▲ = new column, ● = already there):

| Table | Change | Enforce |
|---|---|---|
| `projects` | ▲ `owner_id` | list/get/update/delete; the container for nearly everything else |
| `workflow_profiles` | ▲ `owner_id` (keep `created_by`) | as above |
| `custom_tools` | ▲ `owner_id`; ● `is_builtin`, `is_public` | R2 |
| `custom_output_schemas` | ▲ `owner_id`; ● `is_builtin`, `is_public` | R2 |
| `deep_agent_templates` | ▲ `owner_id`; ● `is_public` (currently inert — see §2.3) | R2 |
| `prompts` *(new)* | whole table | R2 |
| `skills` | ▲ `owner_id` | R2 (see §8.4) |
| `chat_sessions` | ● `user_id` → make NOT NULL, index with `project_id` | read paths §3.6 |
| `conversation_archives` | ● `user_id` | archive reads |
| `context_documents` | ▲ `owner_id` (or inherit from project) | R3 |
| `workspace_files`, `storage_objects` | ▲ `owner_id`; **UNIQUE becomes composite** | R3, §3.7 |
| `oauth_tokens` | ▲ `owner_id`; **UNIQUE becomes `(owner_id, provider)`** | R1-adjacent: Google tokens are personal |
| `workflow_schedules`, `workflow_triggers` | ▲ `owner_id` | §10 |
| `background_tasks`, `presentation_jobs` | ▲ `owner_id` | §10 |
| `audit_logs`, `search_history` | ● `user_id` | populate it |

### 6.4 What deliberately stays shared

Per the product decision in §0, sharing is the *default*, not the exception. Deliberately shared:

| Shared thing | Where it lives | Note |
|---|---|---|
| **Application code** | the repo | obviously shared; the point is that it is not per-user *configurable* either |
| **Built-in tools** | `backend/core/tools/registry.py`, `tools/native_tools.py`, seeded `custom_tools` rows with `is_builtin` | one global row per tool, keyed by globally-unique `tool_id`; agent configs reference tools by that bare string, so per-user seeding would break every agent |
| **Built-in skills** | `backend/skills/builtin/**/SKILL.md` | git-tracked; must become read-only through the API (today it is editable — see §8.4) |
| **Built-in agents** | seeded `deep_agent_templates` rows | shared templates people start from |
| **Knowledge base** | `.kvmeta` catalogs + `context_documents` + embeddings | **shared by product decision** — see §9.1 |
| Model catalog, `STRUCTURED_OUTPUT_SCHEMAS`, `DEFAULT_AGENT_GUARDRAILS` | code | application content |
| `API_KEY_ENCRYPTION_KEY` | `.env` | one key encrypts all users' secrets at rest; fine, and worth stating so nobody "improves" it into a per-user headache |

What is **per-user** is therefore narrower than this study first assumed: credentials and keys,
private assets, the scratch workspace, chat/memory/history, and costs. That is a smaller project
than §12 originally priced — and it is also fewer places to leak.

---

## 7. Requirement 1 — per-user API keys

### 7.1 Mechanism

1. `models.api_keys` becomes per-user (`settings_documents` row with `user_id = <user>`), resolved as
   `user → team → none`.
2. `get_api_key_from_db(key)` becomes `get_api_key(key, *, user)` — or, better, **reads the
   request-scoped current user** so the ~7 call sites need no signature change. Prefer the latter:
   fewer edits, and it cannot be forgotten at a new call site. The ContextVar must be set by the
   middleware and must survive into threadpool execution (test this explicitly, §5 Option A).
3. `POST /api/settings/api-keys/test` must test **the caller's** key, and say whose it tested —
   otherwise a user tests the team key and believes their own works.

### 7.2 The cache problem (do this first)

`chat_session_manager.active_sessions` caches built agents; agents bind credentials at build time.
Required:
- include `user` in `cache_key`;
- **invalidate a user's cached sessions when their key changes** (otherwise a rotated key keeps
  being used by a warm instance — a security and a support-ticket generator alike);
- decide worker affinity: with `UVICORN_WORKERS > 1` this cache is per-process, and the existing
  warning in `start.sh:225-241` already documents that Graph threads break across workers. Adding
  identity makes the correctness requirement stricter, not looser.

### 7.3 Non-key credentials that are also personal

- **Google OAuth tokens** (`oauth_tokens`) — a Slides/Docs export is made *as a person*; a shared
  token means user A creates documents in user B's Google Drive. Must become per-user.
- **Search provider keys** (`search_providers`, and `tavily_api_key`/`serper_api_key` in `api_keys`)
  — these are per-user spend; treat like model keys.
- **LangSmith key** (`config.py:66`) — a tracing key can attribute one user's runs to another's
  account. Per-user, or explicitly team-only and disclosed.

### 7.4 What per-user keys do *not* buy

Cost/usage reporting across users, quotas, and "who spent what" need the *run* records to be
attributed (§10) — keys alone only change which account is billed.

---

## 8. Requirement 2 — built-ins shared, customs private

### 8.1 The visibility rule (one rule, four asset classes)

An asset is visible to a user iff:

```
is_builtin = true            -- shipped, readable by all, writable only by admin
OR is_public = true          -- published by owner (or admin)
OR owner_id = current_user   -- private
```

And writable iff `owner_id = current_user`, or the caller is an admin editing a non-builtin asset.
Builtin rows are **immutable to everyone** including admins at runtime — changes to built-ins travel
through code/seeds so they stay reproducible across installs (`docs/installation.md`'s
seed-out → push → pull → seed loop).

### 8.2 Tools — closest to done

`custom_tools` already has `is_builtin`, `is_public`, `created_by`, `project_id`,
`parent_tool_id` (`models/custom_tool.py:88-104`). Work: add `owner_id`, apply the rule in the list
query (`api/tools/routes.py:139`) and to get/update/delete/execute, and implement "**fork to
customise**" using `parent_tool_id` (which exists and is currently unused for this purpose).

**⚠ Blocker — `is_builtin` is a security boundary, and it is writable.** In
`core/tools/factory/builders.py:1812-1830`, `is_builtin` decides the exec namespace: built-ins get
full `__builtins__` plus `os`, `pathlib`, `io`, `re`; everything else gets an AST-validated restricted
namespace. And `PUT /api/custom-tools/{tool_id}` (`api/tools/routes.py:304-340`) looks the tool up by
`tool_id` alone and writes `implementation_config` with **no `is_builtin` guard and no ownership
check** — as does the `POST /{id}/test` path that immediately executes that code.

With one user this is "just" an unauthenticated code-execution surface. With two users it is
**privilege escalation**: a member edits a builtin tool's code and gets trusted-namespace execution.
This must be closed *before* the second user exists, independently of the rest of this plan:
built-in rows must be immutable through the API (verify `is_builtin` server-side, never from the
request body), tool writes must be owner-scoped, and `POST /{id}/test` must be treated as the
code-execution endpoint it is.

**Seeding constraint.** Built-in seeding is a global union on the globally-unique `tool_id`
(`backend/scripts/seeds/` + `core/tools/seed.py`), and agent configs reference tools **by `tool_id`**.
So per-user seeding is not an option: built-ins must stay one global set, seeded once. Per-user rows
must be *copies with new ids* (a fork), or agent configs will resolve to the wrong row.

### 8.3 Prompts — needs a new entity

There is nothing to add an owner column to (§3.5). Proposed:

```
prompts
  id, owner_id, is_builtin, is_public, parent_id (fork source)
  name, content, category, tags, version
  created_at, updated_at
```

Then:
- seed built-in prompts (a small, curated set: assistant/reviewer/planner/refactor patterns);
- repoint `PromptBrowserSidebar`/`PromptHomePage` at `GET /api/prompts` instead of
  `listDeepAgents`;
- provide "insert this prompt into an agent" (the current implicit flow) as an explicit action, so
  editing a prompt never silently mutates a shared agent;
- optionally offer one-way **import** of the existing agent-derived prompts, creating private
  prompt rows owned by the importing user — otherwise the Prompts activity is empty on first run and
  looks broken.

This is the largest single *new* piece of work in requirement 2, and it is a UX-visible change, so it
needs sign-off rather than drift.

### 8.4 Skills — filesystem-backed, so ownership is a directory

`skills` is an index over `SKILL.md` directories with `source_type` ∈ {`builtin`, `personal`,
`project`} (`models/skill.py:20-24`) and an **absolute** `source_path`. 43 indexed rows, all under
`backend/skills/builtin/` *(measured)*.

The model anticipates `personal` — but `backend/skills/personal/` is **one flat directory shared by
everyone**, not a per-person area, and three defects make it worse than it looks:

1. **Personal skills are copied wholesale into every run's workspace**
   (`services/skill_agent_demo.py:171-174`), so one user's personal skills land in another user's
   workspace the moment they share the agent.
2. **Built-in `SKILL.md` files are editable through the API** — the same immutability gap as tools.
3. **The indexer scans one level deep over the parent directory**, so a `personal/<user>/SKILL.md`
   layout — the obvious target — would not be found at all without changing the scan.

Target: `<user root>/skills/` for `personal`, `<project>/skills/` for `project`, repo-resident for
`builtin`; the indexer records `owner_id`; sync is per-user and must never rewrite another user's rows.

### 8.5 Output schemas — same as tools, smaller

`custom_output_schemas` already has `is_public`/`is_builtin` (`models/custom_schema.py:43-44`), but
both are misleading today: **`is_builtin` is never set `True`** (the real built-ins are Python classes
registered in code), the create path **hard-codes `is_public=True`**, and the list endpoint filters
*to* public (`api/schemas/routes.py:176`). Every custom schema is therefore global by construction —
requirement 2 is precisely inverted for this asset class.

Work: add `owner_id`, honour `is_builtin` from the registry rather than the row, stop hard-coding
`is_public=True`, and **key the process-wide `_custom_schemas` cache by `(owner, name)`** (§3.4) or
two users' same-named schemas will silently collide.

---

## 9. Requirement 3 — separate workspaces

### 9.1 The current shape (verified, and the repo's own doc is stale)

`docs/reference/storage-map.md` describes three roots. There are now **four**, anchored three
different ways:

| Root | Configured by | Keyed by | Portable? |
|---|---|---|---|
| `backend/data/knowledge` | `services/kb_discovery.py:64-92` | project **slug** + `.kvmeta/<slug>.json` | catalogs store **absolute** `storage_path` |
| `backend/outputs` | `settings.workspace.workspace_path` — **an absolute path inside a settings document** *(measured: `/Users/…/backend/outputs`)* | project slug, agent id | no |
| `backend/.workspace_data` | `LANGCONFIG_WORKSPACE_ROOT` | slug / numeric id | no |
| `storage_objects` (DB mode) | `settings.storage.mode = 'db'` *(measured)* | **relative** keys (`outputs/<slug>/agents/…`) | **yes** |

Two findings worth acting on independently of multi-user:
- `backend/data/uploads` and `backend/data/agents_md` are **orphans** — no code references.
- DB storage mode already uses **relative keys** and is therefore the portable design. Per-user
  isolation should follow that pattern rather than inventing a second one.

### 9.2 Target layout

```
<root>/
    knowledge/              -- SHARED (product decision, §0): one KB for everyone
    shared/                 -- builtin skills, templates (read-only)
    users/<user_id>/
        outputs/            -- was backend/outputs      (private)
        workspace_data/     -- was .workspace_data      (private)
        skills/             -- personal skills (§8.4)   (private)
```

Only the **private working tree** moves under `users/<user_id>/`. The knowledge base keeps a single
global root because it is shared by design — which removes the largest and most delicate part of the
migration that this study originally proposed (per-user `data/knowledge`, its 1,989 `.kvmeta`
records, and a per-user KB name-space where two people's `analysis/` folder would collide).

Built-ins stay in the repo (`backend/skills/builtin/`). Resolution becomes
`root_for(user) = <root>/users/<user_id>/` for the private tree and `shared_root()` for everything
shared, each computed in **one** function that every writer calls — the current code computes paths
in several places, which is how the slug/numeric-id divergence happened in the first place.

### 9.3 Absolute paths in the database (the real work)

*(measured, live DB)*

| Where | Rows | Note |
|---|---|---|
| `deep_agent_templates.config` JSONB (`system_prompt`, `agent_docs`) | **50 of 56** | the root is *interpolated into prompt text* |
| `.kvmeta` knowledge catalogs | **1,989** | 1,989 total; only 454 also carry the new relative `key` |
| `workspace_files.file_path` | 180 of 210 | **includes pytest temp-dir residue** — test data in the real DB |
| `session_documents` | 28 of 28 | |
| `context_documents` | 8 of 8 | |
| `skills.source_path` | 43 of 43 | all `backend/skills/builtin/…` |
| `deep_agent_templates.workspace_path` | **0 of 56** | good news: agents do not store their root |

Volume is small; **shape** is the problem. Two of these are not path columns at all:

1. **`deep_agent_templates.config`** has the root pasted into prompt text
   (`core/agents/identity.py:45-56`). Rewriting 50 JSONB documents requires a content rewrite with a
   marker (e.g. `${WORKSPACE_ROOT}`) so the value stops being machine-specific — or at least a
   versioned rewrite script. This also means **new agents must never bake the root again**, or every
   new agent re-creates the problem.
2. **`.kvmeta` catalogs** store `storage_path` absolutely while `storage_objects` already stores
   relative `key`s. Unify on relative; the mismatch is a latent bug even single-user.

A migration script of the right shape already exists:
`backend/scripts/relocate_knowledge_paths.py` (dry-run + rollback journal) — extend rather than
reinvent.

### 9.4 Composite uniqueness

`workspace_files.file_path` and `storage_objects.key` are UNIQUE (§3.7). With per-user roots they must
become `UNIQUE(owner_id, path)`, otherwise two users' identically-named files collide — which will
first appear as a mysterious upload failure, not as an obvious schema error.

### 9.5 Adoption problem (the practical one)

There is existing single-user data: 12 projects, 57 workflows, 258 chat sessions, 1,989 knowledge
records. It must land somewhere. Options:

- **Adopt into an `owner` user** (recommended): create the first user (the admin), assign all existing
  rows to it, and either move the directories once or point that user's root at the *old* locations
  via symlinks so no bytes move. The symlink path makes migration instant and reversible, which
  matters because it is the step where a mistake is most expensive.
- Leave legacy rows ownerless and visible to all: rejected — it reproduces today's leak forever.

---

## 10. Requirement 4 — the rest, inventoried

Everything that touches user data, with its required treatment. This table *is* the "other" of the
requirement.

| Area | Today | Needed | Severity if skipped |
|---|---|---|---|
| **Knowledge base / RAG** (`context_documents`, embeddings, `.kvmeta`) | one catalog set | per-user root + owner column; embeddings filtered by owner | **high** — reads another person's documents |
| **Agent memory** (`agent_memories`) | 0 rows, no owner | scope per (user, agent); decide whether memory is personal or shared-with-agent | **high** — accumulated context leakage |
| **Chat sessions / archives** | `user_id` nullable, never filtered | populate + filter all 12+ read paths; unpickable session ids | **high** |
| **OAuth (Google Slides/Docs)** | one token per provider | per-user token; export creates files in the caller's Drive | **high** — writes into the wrong person's Google account |
| **Schedules / triggers / webhooks** | no owner | owner column; **define which identity a scheduled run uses** (its owner's keys, obviously — but say so) | **high** — a scheduled run could execute with the wrong credentials or on another user's files |
| **Workflow executions / events / tool & skill execution logs** | no owner | attribute to the initiating user; needed for cost, quota and "who ran this" | medium (reporting) → high once keys are per-user |
| **Presentations / notebooks / background tasks** | no owner | owner column; per-user output dirs | medium |
| **Search providers** | global config | per-user keys (§7.3) | medium |
| **Local models config** (`local_models`) | global | per-user endpoint/model choice, or explicitly team | low–medium |
| **Terminal / shell** (`api/debug/terminal`) | cwd = process cwd | per-user cwd = their workspace root | **high** — shell access to another user's tree |
| **File editor / workspace files** | absolute paths, no owner | per-user root + owner | **high** |
| **Exports / codegen** | writes files as a GET side effect, unauthenticated | per-user output dir + auth | **high** — documented earlier as an RCE-adjacent surface |
| **Rate limiting** | per IP | per user (and keep per-IP) | medium — one user can exhaust another's budget |
| **Audit log** | `user_id` never passed | populate everywhere; make it append-only | medium → high for compliance |
| **Seed out/in** | team-level by design | must skip per-user settings and per-user assets; must not copy ownership | medium — could republish a colleague's private asset |
| **`settings` legacy table** | still read in 2 places | retire or explicitly designate owner | medium — silent second source of truth |
| **Frontend** | single implicit user | user menu, "Shared"/"Mine" badges in Tools/Prompts/Skills/Agents, admin → Users page, honest empty states | medium but **user-visible** |
| **Docs** | describes single-user | update `lan-access.md` §9, `storage-map.md` (stale), this doc | low |

### 10.1 The one that will surprise you

**Schedules, triggers and webhooks** are where multi-user systems fail quietly. A cron job or a file
watcher runs with no request context; if its credential lookup falls back to "the" key it will
happily run as whoever is convenient. Decide explicitly: **a scheduled run executes as its owner**,
using the owner's keys and the owner's workspace, and it stops (with a visible error) if the owner
is deactivated or their key is missing. Do not let it fall back silently.

---

## 11. Enforcement strategy — the decisive architectural choice

349 routes; 8 with any auth dependency. Three viable approaches:

### (a) Middleware identity + repository/service helpers *(recommended)*
One middleware resolves the current user; a small set of scoping helpers
(`owned(query, model)`, `assert_visible(obj, user)`, `owner_id_for(user)`) is used in the ~30–50
queries that list or fetch user data.

- **Pros:** no route churn; testable; keeps SQL portable; explicit in review.
- **Cons:** relies on discipline — a new query that forgets the helper leaks. Mitigate with a test
  that greps for `db.query(Project)` outside the helper layer, and by making the helper the only
  sanctioned way in.

### (b) FastAPI dependency on every router
`APIRouter(dependencies=[Depends(current_user)])` per router — 43 edits, gives "identity exists"
guarantees but **not** row-level filtering. A useful *complement* to (a), not a substitute.

### (c) PostgreSQL Row-Level Security
`SET LOCAL app.user_id = …` per transaction plus `USING (owner_id = current_app_user())` policies.

- **Pros:** the only enforcement that cannot be bypassed by a forgotten `WHERE` — an institutional
  guarantee. The repo's own SaaS plan chose this (`plans/2026-02-12-langconfig-saas-design.md` §Tenant
  Isolation).
- **Cons:** every connection must carry the GUC (a pooled connection leaking a GUC between requests is
  a **silent catastrophic leak**); background jobs and migrations need an explicit bypass role; SQLite
  test paths and any raw SQL must be audited; debugging "why did I get 0 rows" gets harder.
- **Verdict:** not first. Ship (a) + (b), keep the `owner_id` columns clean and uniform, and RLS
  becomes a later hardening step that requires no data redesign — which is exactly why the columns
  must be uniform now.

### Recommendation
(a) + (b) now, (c) as an optional hardening pass. The uniform `owner_id` naming in §6.3 is what keeps
(c) cheap later; inconsistent names would foreclose it.

---

## 12. Delivery: vertical slices

**Decision (2026-10-17): deliver vertically, not horizontally.** The layer-by-layer ordering below was
replaced because a horizontal slice (e.g. "add `owner_id` to 8 tables") leaves the app in a half-broken
state — new columns written by nobody, filtered by nothing — for days at a time, with no user-visible
change and no safe place to stop.

Each slice below is a **thin end-to-end cut**: database → service → API → UI → tests, independently
shippable, demoable in the running app, and reversible on its own. A slice is *done* when a second
person can see the behaviour and nothing from a later slice is required to make it work.

### Rules that make slicing work here

1. **Each slice owns its schema migration.** No slice adds columns that the next slice is expected to
   use "soon". A column arrives with the code that filters on it.
2. **No slice makes a privacy promise it does not fully keep.** "Per-user workspace" means uploads,
   outputs, knowledge *and* the terminal cwd; if one is left out, the slice is not done — it is
   deferred.
3. **Every slice leaves single-user behaviour working.** The app must run with one user at all times;
   a slice that breaks the solo case is a bad slice.
4. **Every slice has a two-user test.** Not a unit test of a helper — an integration test that signs in
   as A and B and asserts B cannot see A's thing (or, where relevant, that A's key was used).
5. **Stop at any slice boundary.** Work can pause forever after any slice and the product is coherent.

### Slice 0 — Close what is open (0.5–1 d)

Not a feature; a prerequisite that has nothing to do with multi-user and everything to do with
shipping the second user safely.

- Built-in tool rows immutable through the API; `PUT` and `POST /{id}/test` verify `is_builtin`
  server-side and never trust the request body (§8.2).
- `_custom_schemas` keyed by `(owner, name)` (§3.4).
- `skills`: built-in `SKILL.md` not writable through the API.
- **Done when:** as a non-admin, writing a builtin tool returns 403 and no code executes.

### Slice 1 — User profile management  ▶ *your item 1*

The identity cut. Nothing else works without it, and on its own it already gives revocation,
attribution and a real "who am I".

| Layer | Content |
|---|---|
| DB | `users(id, username, password_hash, display_name, role, is_active, created_at, last_login_at)`; migration `032` |
| Auth | LAN gate verifies the credential against the DB (hashed, argon2id) instead of `.env`; loopback resolves to the designated `owner` row; credential name becomes a real principal |
| Plumbing | request-scoped current user (ContextVar + `Depends`); injected by middleware so 349 routes need no edits |
| API | `GET/PATCH /api/users/me` (display name, password change); admin: `GET /api/users`, `POST /api/users`, `PATCH /api/users/{id}` (role, active), `POST /api/users/{id}/password-reset` |
| UI | user menu in `ActivityBar`; **Profile** page (name, password); **Admin → Users** page (list, create, disable, role) visible to admins only |
| Tests | two-user integration test: A creates, B cannot read A's profile; admin can; wrong password rejected; deactivated user rejected |
| Retirement | `user_profiles` (chat-extracted) becomes *derived metadata attached to a real user*, not a fake identity |

**Deferred to later slices, deliberately:** per-user API keys (slice 3), per-user workspace (slice 2),
ownership of projects/agents/tools (slices 4–5). Slice 1 changes *who you are*, not what you own.

**Done when:** a second person signs in as themselves, edits their own name and password, cannot touch
another's profile, and an admin can disable them.

### Slice 2 — User workspace management  ▶ *your item 2*

The storage cut: make "my files" true.

| Layer | Content |
|---|---|
| Config | one `root_for(user)` resolver for the private tree; `<root>/users/<user_id>/{outputs,workspace_data,skills}`. **Knowledge stays shared** — no per-user KB root (§9.2) |
| Data | `owner_id` on `workspace_files`, `storage_objects`, `context_documents`; **composite `UNIQUE(owner_id, path)`** (§9.4) |
| Services | `workspace_manager` + file storage scoped to the caller; `kb_discovery` left global |
| Terminal | shell cwd = caller's workspace root (`api/debug/terminal`) |
| Adoption | existing data assigned to `owner`; directories either moved once or symlinked (no bytes moved — §9.5) |
| UI | workspace/files panel shows only mine; path shown as user-relative, not machine-absolute |
| Tests | A uploads → B's list and B's download are empty/404; **and** the reverse: both users still see the same shared knowledge base |

**Deferred:** rewriting the 1,989 `kvmeta` + 50 agent-JSONB absolute paths can be done *incrementally*
here — the resolver makes new writes correct first, then a background/one-shot rewriter cleans history.
Keep the rewriter dry-run + rollback (§9.3).

**Done when:** A uploads a file; B cannot see it, list it, download it, or reach it from the terminal.

### Slice 3 — Agent running with per-user keys  ▶ *your item 3*

The execution cut: whose key runs, and whose money.

| Layer | Content |
|---|---|
| Settings | `settings_documents` → `(user_id, ns)` (§6.2); 3-layer resolve `defaults → team → user`; `models` namespace per-user |
| Keys | `get_api_key(key)` resolves the **current user**, falling back to team only if Q1 says so — and records which was used |
| Safety | `chat_session_manager` cache key includes user; **invalidate on key change** (§7.2) |
| Ownership | `chat_sessions.user_id` populated + filtered on all 12+ read paths (§3.6) |
| Honesty | `POST /api/settings/api-keys/test` tests the caller's key and says whose it tested |
| UI | Settings → API Keys is *my* keys; badge when inherited from team |
| Tests | two users, one agent: assert the key used matches the caller; rotate A's key → A's next run uses the new one, B unaffected |

**Done when:** A and B chat with the same agent simultaneously, each billed to their own key, with
separate session lists and no shared memory.

### Slice 4 — Shared built-ins vs private customs (one asset class per sub-slice)

R2, delivered as four small slices rather than one large one — each is independently useful:

| Sub-slice | Content | Est. |
|---|---|---|
| **4a. Tools** | `owner_id`; visibility rule (§8.1); fork-to-customise via `parent_tool_id`; flip the `project_id IS NULL` global default (§8.2) | 2–3 d |
| **4b. Output schemas** | `owner_id`; stop hard-coding `is_public=True`; built-in from the registry, not the row | 1–2 d |
| **4c. Prompts** | **new entity** (§8.3): table + API + seeded built-ins + repoint `Prompt{BrowserSidebar,HomePage}` + import of existing agent-derived prompts | 3–5 d |
| **4d. Skills** | per-user skills dir; fix the one-level scan; stop copying everyone's `personal/` into every run | 2–3 d |

**Done when (each):** A creates a custom asset; B does not see it; A can fork a builtin; admin can
publish one A sees as shared.

### Slice 5 — Chat, memory and history ownership (2–3 d)

`conversation_archives`, `agent_memories`, `analysis_chat_messages` attributed and filtered; "memory"
defined as per-(user, agent) per Q6.

### Slice 6 — Runs, schedules, triggers, background work (3–5 d)

Attribute `workflow_executions`, `execution_events`, `tool_execution_logs`, `background_tasks`,
`presentation_jobs`. **Scheduled runs execute as their owner** and fail loudly if that owner is
disabled or keyless (§10.1) — never silently as someone else. Per-user rate limiting alongside per-IP.

### Slice 7 — Integrations per user (2–3 d)

Google OAuth tokens per user (`UNIQUE(owner_id, provider)`), search providers per user. Until this
slice ships, **OAuth stays admin-only** — a shared Drive token is worse than no Drive export.

### Slice 8 — Audit, quotas and admin polish (2–4 d)

`audit_logs.user_id` populated everywhere; usage/cost per user; admin dashboard; docs updated
(including correcting the stale `storage-map.md`).

### Order and why

```
0 (safety) → 1 (identity) → 2 (workspace) → 3 (agent running)
                                          ├→ 4a tools → 4b schemas → 4c prompts → 4d skills
                                          └→ 5 history → 6 runs/schedules → 7 integrations → 8 audit
```

Slices 1–3 are the spine and reproduce your ordering exactly. 4a–4d and 5–8 are independent after
slice 3 and can be reordered or dropped without leaving anything broken.

**Total ≈ 20–35 developer-days** — lower than the earlier horizontal estimate, because slicing removes
the "wire everything then discover the mismatch" tax and because each slice's tests are scoped.

### What is *not* included
Billing/quota enforcement, orgs as a grouping level, SSO, cross-instance sync, RLS hardening (§11c).
Each is additive; none blocks slices 1–6.

---

## 13. Risks, ranked by how badly they fail

0. **Privilege escalation through a builtin tool.** A member rewrites a builtin tool's
   `implementation_config` and it executes in the trusted namespace (`builders.py:1812-1830`), i.e.
   arbitrary code with `os` — as the server. This exists *today* and only looks benign because there is
   one user. It is the reason §12 starts with a safety phase. **Test:** attempt to PUT a builtin tool
   as a member; expect 403.
1. **Silent credential crossover.** A cached agent instance built with A's key serving B. Detected only
   by audit; fix is cheap (§7.2) and must precede per-user keys. **Test:** two users, one agent, assert
   the key used matches the caller.
2. **ContextVar loss in thread pools.** Identity resolves in the request but is `None` inside a
   LangGraph worker thread; the key lookup then either fails (loud, fine) or falls back to a team key
   (silent, bad). **Test:** assert current user inside an agent run, not just inside a route.
3. **Half-migrated paths.** Some rows point at the old root, some at the new; users see missing files
   and "regenerate" — quietly duplicating knowledge. Script + counts + rollback journal.
4. **A new query with no ownership filter.** Only mitigated by convention + a lint-style test (§11a).
5. **Composite-unique collisions** appearing as data loss during upload (§9.4).
6. **Scheduled jobs running as the wrong identity** (§10.1).
7. **Seeding re-publishing private assets** across installs — `seed_out` must exclude per-user data by
   construction, not by remembering.
8. **Test pollution of production data** — the DB already contains pytest temp paths (§9.3); a
   per-user migration must not faithfully migrate junk into a user's workspace.

---

## 14. Decisions needed before any code

| # | Question | Recommended | Why it blocks |
|---|---|---|---|
| Q1 | If a user has no API key, does their run fall back to a team key? | Yes, but always disclosed per run | silent fallback hides both spend and failure (§6.2) |
| Q2 | Is `admin` allowed to read other users' private projects/files? | Metadata yes, content no by default, with an explicit audited "break glass" | determines whether enforcement can be a simple owner check |
| Q3 | What happens to the legacy single-row `settings` table? | Freeze reads (migrate the 2 sites), drop after a release | second source of truth (§3.3) |
| Q4 | Are **agents** personal or team? | Team-owned by default, with per-user copies possible (fork) | requirement 2 says "tools, prompts" — agents are unstated, and it changes §8.2 scope |
| Q5 | Are **projects** personal or shareable? | Personal, with an explicit "share project" permission later | R3 hinges on it; sharing is a much bigger feature |
| Q6 | Do memories belong to a person or to an agent? | Person, scoped per agent | two people on one agent else share memories (§10) |
| Q7 | Auth: A (Basic→DB) now, B (login page) later? | Yes | §5; changes phase 1 only |
| Q8 | Do you want the old single-user data adopted into the admin user, or start clean? | Adopt via symlinked roots | determines phase 5 migration design (§9.5) |

**Which decision blocks which slice** (only these are urgent, in this order):

| Slice | Needs |
|---|---|
| **1 — profile** | **Q7** (auth mechanism) — the only true blocker for starting |
| **2 — workspace** | **Q8** (adopt old data or start clean) |
| **3 — agent running** | **Q1** (team-key fallback), **Q3** (legacy `settings` table) |
| **4a — tools** | **Q4** (are agents personal or team) |
| **5 — history** | **Q6** (memory belongs to a person or an agent) |
| **8 — audit/admin** | **Q2** (admin break-glass), **Q5** (are projects shareable) |

Q2 and Q5 change nothing before slice 8 and can be deferred until then without losing work.

---

## 14.1 Decisions taken on 2026-10-26 (scope A — identity only)

The four open questions were answered, and the scope was narrowed to **A**:

| # | Question | Decision |
|---|---|---|
| Q7 | Auth mechanism | **Keep the browser Basic prompt, but verify against the `users` table** instead of `.env`. No login page, no cookie, no CSRF surface. |
| — | Roles | **`admin` + `member`** only. |
| — | Existing accounts | **Bootstrap from `.env` on first boot**, then `.env` stops being read (same rule provider API keys already follow). |
| — | Password policy | **Minimum 8 characters.** |

**Scope A means: identities, not isolation.** Every person gets a login, an audit
trail and individual revocation — and keeps seeing and editing every agent,
workflow, chat and knowledge base in the tenant. Private files (Slice 2) and
per-user provider keys (Slice 3) are explicitly out of scope.

### Three constraints this scope creates

1. **`.env` stops being a user list.** Editing `LANGCONFIG_LAN_USERS` after the
   first boot has no effect; users are managed in the app. This must be documented
   or a team will believe they added someone.
2. **Data stays shared.** "Has an account" ≠ "data is isolated". Say it twice in
   training.
3. **The first credential must satisfy the policy.** The bootstrap imports the
   `.env` account as the first admin; if its password is shorter than 8 characters
   it must be changed at first login.

### Slice 1 execution checklist — **shipped 2026-10-26**

| Step | Files | Acceptance | State |
|---|---|---|---|
| 1 | `models/user.py` (new) — username/password_hash/role/is_active | `users` table, scrypt hash, unique username | ✅ `032_add_users` |
| 2 | `core/security/passwords.py` (new) — `hashlib.scrypt`, no new dependency | hash/verify round-trip; malformed hash = wrong password, never an exception | ✅ |
| 3 | `services/user_service.py` (new) — CRUD, `authenticate`, `bootstrap_from_env` | `admin` imported as the first admin; idempotent on re-run | ✅ |
| 4 | `core/context/current_user.py` (new) — ContextVar + `require_user` / `require_admin` | available inside route handlers and threadpool work | ✅ |
| 5 | `middleware/lan_guard.py` — verify against the DB; loopback → owner; no users → 503 | existing gate behaviour preserved (401/503/websocket/bypass) | ✅ + `middleware/identity.py` |
| 6 | `api/users/routes.py` (new) — `/me`, password change, admin list/create/disable/role/reset | a member cannot read another profile; admin can | ✅ |
| 7 | `api/chat/session.py`, `services/audit_service.py` — write `user_id` | new sessions and audit rows carry the caller | ✅ (chokepoint, not 40 call sites) |
| 8 | `services/chat_session_manager.py` — cache key includes the user | two users on one agent never share a cached instance | ✅ — see 14.2 for the schema registry |
| 9 | Frontend — `UserPopover`, `AccountDialog`, `UsersDialog` + `lib/api/users.ts` | change own name/password; admin creates, promotes, disables, resets | ✅ |
| 10 | Tests | two users sign in; disabled user is refused; audit names the caller; loopback stays password-free | ✅ 71 new/updated tests |

Landed **atomically**, which is the lesson of §0.1: schema + bootstrap + gate + API + UI +
tests together. The previous attempt had made login itself depend on the unfinished slice, so
restarting mid-work would have refused every LAN user with `503`.

Ops tool: `backend/scripts/create_user.py` (first admin, resets, `--enable`, `--list`) — the
recovery path that does not require the app to be usable.

### 14.2 The two Slice 0 leftovers, decided

- **Agent-instance cache key — done.** `services/chat_session_manager.py` keys entries as
  `u<id>:<session>:<agent>:<version>` (`u~` outside a request), so a cached agent built with
  resolved credentials and a resolved workspace can never be handed to another person.
  `remove_session` matches the session as a key *segment*, since the id is no longer first.
- **`OutputSchemaRegistry` — deliberately not changed.** It is a process cache of
  `name → schema class` over `custom_output_schemas`, whose names are globally unique in one
  shared database. Keying it by owner now would *break* structured output (user A registers a
  schema, user B's agent assembly asks for it by name and would miss), which is a regression
  with no threat model behind it while all schemas are shared. It becomes the right change in
  Slice 3, when custom schemas acquire owners — at which point `get()` must also fall back to
  the shared namespace rather than only the caller's.

### Already done before Slice 1

- **Slice 0, the urgent part:** built-in tools and skills are now read-only
  through the API (`3e70b58`). `PUT`/`DELETE /api/custom-tools/{id}` and
  `PUT /api/skills/{id}` return 403, because `is_builtin` selects the *trusted*
  exec namespace — rewriting a built-in and calling `POST /{id}/test` was
  unauthenticated code execution.
- The two remaining Slice 0 items need a notion of "who is asking", so they moved
  into Slice 1: the agent-instance cache key and `OutputSchemaRegistry`.

---

## 15. Appendix — files a first implementation touches

| Concern | Files |
|---|---|
| Identity | `backend/middleware/lan_guard.py`, new `backend/middleware/identity.py`, new `backend/models/user.py`, `alembic/versions/032_*` |
| Settings scope | `backend/core/settings/store.py:63-67`, `resolve.py:54-70`, `config.py:318-380`, `api/system/settings.py:274,342`, `api/system/settings_documents.py:65`, `main.py:106` |
| Cache/credential safety | `backend/services/chat_session_manager.py:86-118`, `services/event_bus.py:50-114` |
| Ownership | `models/{core,custom_tool,custom_schema,deep_agent,skill,workflow*},workspace_file,storage_object,oauth_token}.py` |
| Visibility | `api/tools/routes.py:139`, `api/agents/deep_agents.py:576-584`, `api/schemas/routes.py:176` |
| Prompts (new) | new `models/prompt.py`, new `api/prompts/`, `src/components/layout2/Prompt{BrowserSidebar,HomePage,DetailTab}.tsx` |
| Workspace | `services/workspace_manager.py` (esp. `list_all_files:890-923`), `services/kb_discovery.py:64-92`, `core/agents/identity.py:45-56`, `scripts/relocate_knowledge_paths.py` |
| Read-path ownership | `api/chat/session.py:108,242,276,352,445`, `api/chat/documents.py:87,383,535,577,709,744` |
| Docs to correct | `docs/reference/lan-access.md` §9, `docs/reference/storage-map.md` (stale roots) |
