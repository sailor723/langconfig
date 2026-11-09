# Multi-tenancy — how isolation actually works here

**Date:** 2026-10-22
**Applies to:** the five-group (one instance per group) deployment
**Companion to:** `plans/2026-10-17-multiuser-design.md` (local-only, not in this repository; same
repository, covers *users inside* one instance) and [`lan-access.md`](../installation/lan-access.md) (the gate).

---

## 0. The one thing to understand first

**There is no tenant concept in the code.** A grep for `tenant_id` / `org_id` finds nothing; the
`instance_id` hits in `core/versioning.py` are ORM row ids. The application does not know which
tenant it serves, cannot enumerate tenants, and has no cross-tenant ceiling to enforce.

Tenancy is therefore **a deployment property, not a feature**. It is built from four things that all
live outside the application:

| Boundary | Mechanism | If it is misconfigured |
|---|---|---|
| Data | one PostgreSQL **database** per instance | rows leak between tenants |
| Files | one `backend/data` + `outputs` + `.workspace_data` per instance | documents and agent deliverables leak |
| Secrets | `models.api_keys` rows inside that database | provider keys leak |
| Network | security group / VLAN / SSH tunnel | **everything leaks** — the app has no authentication of its own unless the LAN gate is enabled |

That is simultaneously the strength and the fragility: isolation cannot be bypassed by forgetting a
`WHERE` clause (as application-level tenancy can), but it also cannot be repaired in code — it is
only as good as the deployment.

## 1. Topology in use

```
        ┌──────────────┐   ┌──────────────┐        ┌──────────────┐
        │  group 1     │   │  group 2     │  ...   │  group 5     │
        │  host / ECS  │   │  host / ECS  │        │  host / ECS  │
        ├──────────────┤   ├──────────────┤        ├──────────────┤
        │ Postgres  DB │   │ Postgres  DB │        │ Postgres  DB │
        │ data/ output │   │ data/ output │        │ data/ output │
        │ .env keys    │   │ .env keys    │        │ .env keys    │
        │ Ollama       │   │ Ollama       │        │ Ollama       │
        └──────────────┘   └──────────────┘        └──────────────┘
              ▲                  ▲                       ▲
        group-1 members    group-2 members          group-5 members
        (one shared login today — see the multiuser plan for accounts)
```

One instance serves one group. The knowledge base is **shared inside a group and private to it** —
which is exactly the product decision recorded in the multiuser plan (§0: "the core of the system,
including code, built-in agents, tools, skills and the KB, is shared").

## 2. Isolation matrix

### Genuinely isolated per tenant

| Asset | Where it lives |
|---|---|
| Projects, workflows, agents, tools, skills, chat history, settings documents | that instance's database |
| Uploaded documents and knowledge bases | `backend/data` |
| Agent deliverables and workspaces | `backend/outputs` |
| Provider API keys, Google OAuth tokens, local-model keys | `models.api_keys`, `oauth_tokens` — encrypted, in that database |
| In-process state (caches, `active_sessions`, event bus) | that instance's Python process |
| Ollama models, `.venv`, `node_modules`, `dist/` | that host |

Because each tenant is a separate process, the cross-user cache problems that plague
*single-process* multi-user designs (shared `active_sessions`, name-keyed schema registries,
per-channel event buses) simply do not arise here. That is a real advantage of this topology.

### Shared across tenants — by design or by accident

| Shared | Why | Consequence |
|---|---|---|
| **The code** | same git checkout everywhere | one bug is five bugs; patch five times or none |
| **The seed baseline** (`scripts/seeds/in`) | this *is* the "shared core": identical agents/tools/skills for every group | deliberate; but it means the baseline has an owner (§5) |
| **`API_KEY_ENCRYPTION_KEY`** | must be identical so dumps/seeds are portable | ⚠️ see §3 — this is the weakest link |
| **Provider accounts** | if a group shares one key, spend is commingled | per-group key visibility, not per-person |
| **External services with defaults** | `NEO4J_URI=bolt://localhost:7687`, `LITELLM_PROXY_URL=http://litellm-proxy:4000`, `LANGSMITH_PROJECT=langconfig` | point one instance at a central service and you have created a shared datastore without deciding to |
| **Ollama model cache** | per host, not per tenant | only matters if two tenants ever share a host |

## 3. The encryption key decision

`API_KEY_ENCRYPTION_KEY` is a passphrase from which the Fernet key is derived (PBKDF2-SHA256,
fixed salt — `services/encryption.py:86-94`), so **one string reproduces one key on every machine**.
That is why all hosts must carry the same value: it is what lets a dump from one host open on
another, and what makes seeding never have to move secrets.

The cost: the passphrase is a **master key across all tenants**. Anyone holding it — every host's
`.env`, plus every backup — can decrypt any tenant's stored provider keys and OAuth tokens from a
database dump.

Three coherent policies:

| Policy | At-rest protection | Portability | Cost to change |
|---|---|---|---|
| **A. One shared passphrase** (current) | weak if the value is guessable or published | best | zero |
| **B. One *strong* shared passphrase**, generated once (`openssl rand -hex 32`), same on all five, stored out of band | real, against someone who obtains only a dump | same as A | one `sed` per host + restart, **before** any secrets are stored |
| **C. Per-tenant passphrase** | strongest: a dump is useless without that host's key | breaks cross-host restore and secret migration | real work; changes the seed story |

**Recommendation: B.** It costs no operational change and removes the "guessable master key"
problem. Verify agreement without printing the secret:

```bash
grep '^API_KEY_ENCRYPTION_KEY=' .env | cut -d= -f2- | tr -d '\r\n' | sha256sum | cut -c1-12
```

Identical 12 characters on every host = identical key. (`e3b0c44298fc` means the value is **empty**,
i.e. the app is on its built-in dev fallback; a different hash means a real mismatch.)

## 4. Strengths and weaknesses of instance-per-tenant

### Strengths

- **Blast radius is minimal.** A compromised, corrupted or half-migrated instance cannot reach
  another tenant's data. This was demonstrated concretely: the encryption-key failure on one host
  stayed on that host.
- **Failure isolation.** One host down = one group down.
- **No ownership code to forget.** No `WHERE owner_id` to miss, no row-level security to misconfigure.
- **Upgrade freedom** per tenant; a group can hold a version for a specific agent.
- **Cost attribution per group** falls out of per-instance keys.

### Weaknesses

| Weakness | Detail | Mitigation |
|---|---|---|
| **No authentication inside a tenant** unless the LAN gate is enabled | the gate (`backend/middleware/lan_guard.py`) is implemented and tested but was not in `origin/main` at the time of writing; without it, anyone who reaches `:8765` is inside — and instances run as **root** with shell/file tools | enable the gate per instance, and restrict the port |
| **No identity of the instance itself** | no instance name, no tenant id, no banner; two hosts on `:8765` look identical | name them (`lc-g1`…`g5`), set `LANGSMITH_PROJECT` per host |
| **Content governance is implicit** | `seed_out` run on any host exports that tenant's content, and pushing it feeds the other four | designate one content owner (§5) |
| **Credential hygiene is manual** | five `.env` files, five Postgres passwords, five UI passwords | one register, distinct per host |
| **Ops cost multiplies** | 5 × backups, 5 × patches, 5 × Postgres and Ollama upgrades | version pin + fixed upgrade window |
| **Shared KB cannot span tenants** | a group's KB is private to it | if cross-group knowledge is ever needed, that is a new service, not a config change |
| **Resource floor** | ~1–2 GB per instance with Ollama | size accordingly (2 vCPU / 4 GB comfortable) |

## 5. Content governance — the part that is usually skipped

Because the seed baseline *is* the shared core, someone must own it. Without a rule, any tenant's
local edits can leak into everyone else's next seed.

- **One content owner.** Exactly one host (call it `lc-source`) is allowed to run
  `scripts/seeds/out/*` and push the result.
- **Everyone else is read-only for the baseline** — they run `seed_in` and make runtime changes in
  the app, but do not export.
- **`seed_out` never publishes credentials** (it strips them; `settings_seed.json` records which
  keys it removed). It *does* publish agents, tools, skills and team settings — that is the point.
- **Skills are their own artefact**: the `SKILL.md` files are the data, so a skill change is a git
  change.

## 6. Per-host checklist

Copy this for each new tenant:

```bash
# identity
hostnamectl set-hostname lc-g1                 # so nobody types into the wrong box
LANGSMITH_PROJECT=lc-g1                        # in .env — keep traces separate

# data isolation (must be unique per host)
POSTGRES_DB=langconfig                         # fine on a dedicated host
POSTGRES_PASSWORD=<unique per host>
API_KEY_ENCRYPTION_KEY=<the one shared strong passphrase>   # fingerprint identical on all hosts

# access (do not skip)
LANGCONFIG_LAN_ACCESS=on
LANGCONFIG_LAN_USER=<admin>
LANGCONFIG_LAN_PASSWORD=<unique per host>
# and in the cloud: security group allows 8765 only from the group's CIDR, or not at all (SSH tunnel)

# embeddings (chat needs them; the fallback path is broken — see installation notes)
ollama pull nomic-embed-text
```

Verification after each install:

```bash
curl -s -o /dev/null -w "describe -> %{http_code}\n" http://127.0.0.1:8765/api/settings/describe   # 200
grep '^API_KEY_ENCRYPTION_KEY=' .env | cut -d= -f2- | tr -d '\r\n' | sha256sum | cut -c1-12       # same on all hosts
sudo -u postgres psql -d langconfig -tAc "select count(*) from deep_agent_templates"              # ~56
```

## 7. Backups, restores, and the trap in both

Per host: a `pg_dump` of the database **and** a tar of `backend/data` + `backend/outputs`. A database
restore without the matching files gives an instance that looks healthy and is missing every
document and deliverable.

**Restore on the same host, at the same paths.** This codebase stores absolute paths in several
places (settings documents, `.kvmeta` catalogs, and the identity block baked into ~50 agents'
prompts). A restore into a different directory tree can succeed and still be broken — files
"missing" while the DB insists they exist.

Prove the restore once, into a scratch database and a scratch directory, before you need it for real.

## 8. When to add multi-user *inside* a tenant

Instance-per-tenant answers "how do groups stay apart". It does not answer "how do four people in
one group share an instance". That is the other axis, and its design is in
`plans/2026-10-17-multiuser-design.md` (local-only, not in this repository).

The deciding question, in one line:

> **Do the people need a shared knowledge base and shared agents?**
>
> - **Yes** → multi-user code is the only way to get sharing with separate logins, files and chat
>   history. Expect vertical slices: identity → workspace → keys (§12 of that plan).
> - **No** → give each person their own instance. It is cheaper, cannot leak, and takes about an hour
>   per instance.

Before either, close the two live defects that make a second person on one instance unsafe
(builtin-tool write → trusted-namespace code execution; cached agent instances keyed without a user).

## 9. Summary

| Question | Answer |
|---|---|
| Is LangConfig multi-tenant? | Not in code. Yes in deployment: one instance, database and filesystem per group |
| Is tenant data isolated? | Yes, strongly — by Postgres and the filesystem, not by filters |
| Is anything shared? | Code, seed baseline, the encryption passphrase, and any external service defaults |
| Biggest risk? | No authentication inside an instance unless the LAN gate is enabled; instances run as root |
| Cheapest improvement? | Enable the gate; one strong shared passphrase; name every host |
| What breaks the model? | Pointing two tenants at one database or one Neo4j/LiteLLM, or restoring a backup onto the wrong host |
