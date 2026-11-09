# Housekeeping audit — local repo, 2026-11-09

Scope: this working tree on the Mac (`/Users/weiping/dev/Learn/langchain-ai/langconfig`), measured on
2026-11-09. Three questions, in this order of money: **data** (bytes and dangling records), **code**
(files nothing can reach), **docs** (claims the repo no longer honours).

Nothing in this document has been deleted. Every row is a measurement plus a verdict, so the
decisions below can be taken one at a time.

---

## 1. Data

### 1.1 The headline numbers

| Area | On disk | Tracked in git | Verdict |
|---|---|---|---|
| `.git` (history) | **481 MB** | — | 414 MB of it is `backend/data/**` PDFs that were committed once and deleted since |
| `backend/data` | **794 MB** | 0 files (ignored) | 535 MB of it is documents **no index points at** |
| `backend/outputs` | 249 MB | 0 files (ignored) | agent workspaces: 25 MB of them are embedded virtualenvs |
| `node_modules` | 412 MB | 0 | normal |
| `.uv-cache` | 126 MB | 0 | regenerable cache |
| `langconfig.zip` | 42 MB | 0 (ignored) | build artifact of `scripts/make_team_zip.sh` |
| `backend/notebooks` | 34 MB | **222 files** | 22 MB of that is one file named `Arial` |
| `dist` | 12 MB | 0 (ignored) | regenerable |
| `docs` | 8 MB | 65 of 78 files | 13 files are local-only by design |

### 1.2 Documents: 535 MB nothing points at, 815 records pointing at nothing

The document store is `backend/data/documents/<project>/…`, indexed two ways: the KV catalog
`data/documents/.kvmeta/<project>.json` (1 786 entries) and the DB tables `context_documents`
(12 rows) / `session_documents` (49 rows).

| Measurement | Value |
|---|---|
| files on disk under `data/documents` | 1 491 files / 643 MB |
| distinct paths referenced by catalog or DB | 1 847 |
| **files with no reference at all** | **459 files / 535 MB** |
| **references whose file is gone** | **815 of 1 847 (44 %)** |

The orphans are not spread evenly: 297 files sit in `project_1/`, 124 in `project_chat_sessions/`,
and the biggest single offenders are four lecture PDFs that exist in the store two or three times
under different hashes:

```
178.2 MB  project_chat_sessions/2cf15bb9…/3a712a88_C4M4.pdf
 70.5 MB  project_chat_sessions/3c5cfd80…/6dd561fd_lecture-notes-7.pdf
 48.9 MB  project_chat_sessions/62eddbce…/dd2053cf_C2M3.pdf
 36.9 MB  project_chat_sessions/1e066c9d…/cdb736b2_Week1_slides.pdf   (×3 copies, same size)
```

Checked before calling them orphaned: their filenames appear in **no** catalog entry, on any path,
absolute or relative — the app resolves documents through the catalog, so these files are not
reachable from the UI. The same mechanism is healthy for knowledge bases
(`data/knowledge/.kvmeta`: 8 stale of 2 151), so this is document-specific rot, not a broken index.

Two different jobs hide in that table, and they deserve different answers:

- **535 MB of unfiled files** — nothing reads them. Deleting is safe; it is user data, so the
  decision is a retention one, not a technical one.
- **815 dangling records** — the UI can still offer a document whose file is gone. Cleanup here is
  metadata surgery on `.kvmeta/*.json` + two DB tables, and it makes the viewer stop lying. This is
  a bug to fix, not just bytes to reclaim.

### 1.3 Git history: 414 MB of PDFs

`git rev-list --objects --all` grouped by path prefix:

```
414 MB  backend/data        ← 45 blobs, no longer tracked, still in history
 35 MB  src/features
 33 MB  backend/notebooks
 21 MB  backend/scripts     (the neo4j-hr seed dumps)
 17 MB  backend/uv.lock · 17 MB backend/core · 15 MB docs/tutorial
```

Working tree is only **82 MB tracked**, so `.git` at 481 MB is mostly other people's old uploads.
Reclaiming it means rewriting history (`git filter-repo --path backend/data --invert-paths`), which
forces every clone to be re-done. That is a decision about the team, not about this folder —
see §4.

### 1.4 Residue that is simply dead

| Item | Size | Why it is dead | Action |
|---|---|---|---|
| `backend/features/ontology/profiles/*/.staging/` | 4 dirs, 5.7 MB | every one belongs to a publish the ledger records as `refused` | delete |
| `backend/features/ontology/profiles/logistics/.backup/` | 13 dirs, 1.9 MB | rollback snapshots of replaces nobody can return to; only the newest per key is a real restore point | keep newest 1 per key |
| `backend/outputs/**/site-packages` | 2 dirs, 25 MB | agents pip-installed into their own workspace | delete |
| `backend/outputs/**/__pycache__` | 64 dirs, 2 MB | regenerable | delete |
| `backend/_analysis_output`, `backend/_data_analysis_sandbox` | 4 MB | gitignored analysis scrap | delete |
| root `backups/` | 5 MB | pre-housekeeping session dumps (`agents.json`, `sessions.json`, …) | archive or delete |
| root `data/analysis_dbs` | 11 MB | generated dashboards + sqlite | delete |
| `langconfig.zip`, `dist/`, `.uv-cache/` | 180 MB | rebuildable | delete on demand |
| `.team_deploy/` | 1 MB | contains a **private ssh key** | keep, but it is a secret in the tree |

One residue item is not local-only: on the deployment (`/root/langconfig`) there are **2 orphan agent
workspaces** (`user 12/agent_355` 12 MB, `user 1/agent_355` 0.8 MB) left behind by the deleted agent
355, and `profiles/.archive/` holds five archived ontologies (8 MB).

### 1.5 Tracked bloat (these cost everyone a clone)

| Path | Size | Note |
|---|---|---|
| `backend/notebooks/module-4/Arial Unicode.ttf` | **23 MB** | tracked before `.gitignore` learned `backend/notebooks/**/*.ttf`, and a tracked file is not affected by an ignore rule — so it stayed. Untracked now (still on disk). The processed `Arial Unicode*.pkl` forms stay tracked: they are what the notebook loads |
| `backend/notebooks/module-1/.langgraph_api/*.pckl` | 7 files | **langgraph runtime state** committed as source |
| `backend/notebooks/**/.ipynb_checkpoints/` | 25 files | editor scratch |
| `backend/static/plotly.min.js` + `backend/skills/personal/1/erp-analyst/plotly.min.js` | 4.6 + 3.4 MB | the same library twice |
| `backend/scripts/seeds/in/neo4j-hr/{hr_nodes,hr_rels}.json` | 3.3 MB | seed data (the `.dump` sibling is already ignored) |
| `wsl_setup.pdf` | 1.1 MB | source is `wsl_setup.md` beside it |
| `backend/skills/personal/1/**` | 22 files | one user's **personal** skills, in the public repo |
| `my-deep-agent-fe` | symlink | committed symlink to `/Users/weiping/…/my-deep-agent/frontend` — dangles for every other machine |
| `test_graphindex_search.py`, `test_pageindex_search.py` (root) | 173 lines each, **identical** | mock-data demos, not tests, and not in `tests/` |
| `src/assets/langconfig-logo.png` (1.3 MB), `src/assets/react.svg`, `public/tauri.svg`, `public/vite.svg`, `public/reset-theme.html` | ≈1.5 MB | **0 references anywhere** (verified by grep over `src/` + `index.html`) |
| `public/GhostPeony.png` (1.6 MB) | — | referenced only by `components/layout/ModernHeader.tsx`, which is itself dead — dies with it |
| `src/i18n/locales/`, `public/images/` | empty dirs | left over (i18n dictionaries are inline in `src/i18n/index.ts`) |

### 1.6 Database

53 tables; 18 are empty; 12 have no SQLAlchemy model. The model-less ones are legitimate
(`alembic_version`, langgraph `checkpoints`/`store`, `langchain_pg_*`, and the two raw-DDL tables
`settings_documents` and `ontology_publishes`). Most empty tables are dead schema rather than orphan
rows — cheap to leave, cheap to drop — **except where an empty table meets a dead router, which is a
complete subsystem**: `classic_graphs` and `classic_graph_runs` are both empty *and* the
`api/classic_graph` router has zero callers, so router + model + tables can be removed as one unit
(see §2.3).

---

## 2. Code

### 2.1 Frontend: 49 files nothing can reach

Method: roots are `src/main.tsx` → `App.tsx`; every other module must be reachable by a static
import, a `React.lazy`, or a string-keyed map. Result: **322 files, 270 reachable, 49 unreachable
(≈15 400 LOC)**, 45 of them clean cuts; 112 exported values are imported by nobody (64 wholly dead).

Four whole subsystems are unmounted:

| Subsystem | Files | Note |
|---|---|---|
| Memory UI (`MemoryView`, `MemoryManager`) | several | no route, no import |
| workflow execution-history panels | several | superseded by the studio's own panels |
| `canvas/index.ts` barrel + its two hooks + `WorkflowSettingsDialog` | 4 | the real canvas imports the modules directly |
| the old `components/layout/` shell (`ModernHeader`) | several | replaced by `layout2/` long ago |

`pages/ProjectsPage.tsx` and `pages/PromptAssemblyPage.tsx` look like pages and are wired to nothing.

Duplicates, with the mounted one named: three agent-output renderers (live: `ContentBlockRenderer`),
two PDF viewers (live: `layout2/PdfViewer`), two cost/metrics panel families (live: `TotalCostPanel`).
29 files still call `fetch(` directly instead of the API client, two of them hardcoding
`http://localhost:8765`.

**A defect found while auditing, not just dead weight:** `App.tsx` has `HashRouter` but **no
`<Routes>`** — routing is `ROUTE_TO_VIEW` + a `switch` in `renderCurrentPage()`. `ROUTE_TO_VIEW` maps
`/learning → 'learning'` (line 192) and `useLayout.tsx` lists Learning as a live activity (line 51),
but the switch has **no `case 'learning'`** — so the Learning activity silently renders the home
page. Verified by hand. Either finish it or remove the activity.

Do not "clean" by name: `src/lib/api/*.ts` (13 files) is imported as `./api/<domain>` from
`api-client.ts`, and `OfficeViewer` is only reachable through `React.lazy` — both are live.

Three more defects the reachability pass exposed, each cheaper to fix than to keep:

- **`DownloadProvider` is never mounted** (`contexts/DownloadContext.tsx`), so
  `useDownloadContext` always falls back to `workflowName: 'Generated'` — every downloaded artifact is
  misnamed. Mount it in `WorkflowCanvas` or delete the context.
- **`components/layout2/SearchPanel.tsx` is a mock** — it is mounted in the sidebar and says in its own
  source *"Mock search results for demo … In production this would call a backend search API"*.
- **29 files call `fetch(` directly** instead of the API client, and two hardcode the backend
  (`GoogleOAuthButton.tsx`, `usePresentationJob.ts` → `http://localhost:8765`), so they break on any
  host other than the developer's laptop.

### 2.2 Backend: four dead sub-graphs, and two files that look live and are not

The deep pass walked every module in `backend/` (excluding `outputs/`, `.venv/`) and checked each
against imports, route registration in `main.py` (49 `include_router` calls), the frontend's path
strings, the tests, and the docs. Re-verified by hand where the answer changes a decision:

| Finding | Evidence | Verdict |
|---|---|---|
| **`backend/api/schemas.py`** (1.2 KB) | `api/schemas/` is a **package**; `import api.schemas` resolves to `__init__.py`, so this module's router can never mount | delete |
| **`backend/api/mcp/config.py`** (484 lines, 7 endpoints) | no `include_router` for it anywhere in `main.py` | delete or wire it |
| **`backend/core/codegen/workflow_exporter_old.py`** (3 043 lines / 124 KB) | a test file lists it by name as *"retired exporter, unused"*; the live one is `workflow_exporter.py` | delete |
| **`backend/api/workflows/checkpoints.py`** (5 endpoints) | zero callers in frontend, tests or docs | delete |
| **`backend/orchestration/`** (package) | `__init__.py` imports `.graph_state`, which **does not exist** — importing the package raises. Its only mention anywhere is a docstring example (`core/workflows/runner.py:139`) | delete |
| **`backend/api/chat/documents.py`** | `/upload` and `/upload-multiple` are each declared **twice** (the copies at :337/:353 win), plus two shadowed helpers | merge — this is a live bug, not dead code |

Three "dead" claims from the audit that I **withdrew after checking**, because deleting them would
break working code:

- **`backend/features/ontology/workbench/serve_ui.py`** (2 420 lines) is imported as a bare
  `import serve_ui` by **5 gate files** (`check_guard`, `check_metrics`, `check_abc`, `check_nl`,
  `check_tpch`), which put `workbench/` on `sys.path` first. What is unreachable is the *HTTP* side:
  `services/ontology_workbench.py`'s `/api/ontology/workbenches` endpoints, which the UI no longer
  calls (they are the documented development tool). Keep the module; the endpoints are a separate
  question.
- **`backend/langgraph/`** shares a name with the pip package but resolves as a namespace package and
  is live (`langgraph.tool_adapters` is genuinely `backend/langgraph/tool_adapters.py`, and its graph
  siblings are dispatched by string name). Never delete this directory wholesale.
- **`backend/features/ontology/gates/check_tpch.py` etc.'s `import serve_ui`** is only "missing" to a
  naive grep — see above.

Loose scripts at `backend/` root, checked by grep for their basename across `backend/`, `docs/` and
`start.sh` — every one of these is a one-off migration or a probe somebody saved instead of running:

| Item | Lines | References | Verdict |
|---|---|---|---|
| `_debug_tool.py` | 20 | 0 | delete |
| `_fix_model.py` | 19 | 0 | delete (hardcodes agent 45 + localhost) |
| `_update_prompt.py` + `_update_agent.json` | 39 | 0 | delete — a "ticker_classifer" prompt for an agent that is long gone |
| `t.py` | 23 | 0 | delete — an httpx probe |
| `debug_template.py` | 46 | 0 | delete |
| `update_greeting_prompt.py` | 35 | 0 | delete |
| `rename_studio_tools.py`, `fix_graphindex_tool_names.py` | 98 + 103 | 0 | delete — one-shot DB renames already applied |
| `create_print_hello_tool.py`, `create_pdf_tools.py`, `create_graphindex_workflow_tools.py` | 90 + 155 + 258 | 0 / docstring / 0 | delete — tool-creation demos |
| `chat_pdf_simple.py`, `analysis_server.py` | 225 + 274 | 1 (own docstring) | delete — the second HTTP server duplicates `api/analysis` |
| `test_memory.py`, `test_structured_output.py` (backend root) | 378 + 42 | 0 | move to `tests/` or delete — loose `test_*` outside `tests/` |
| `test_graphindex_search.py`, `test_pageindex_search.py` (repo root) | 173 × 2 | 0, **byte-identical** | delete both: mock-data demos, and named `test_*` at the root so a bare `pytest` collects them |
| `titanic_analysis.png` (306 KB), `langconfig.db` (0 B) | — | 0 | delete |
| **`backend/db:`** (a directory whose literal name ends in a colon, from a shell typo) | 1 MB, 9 `SKILL.md` | 0 | delete |
| `backend/_examples/` (4 files) + `backend/examples/` (68 KB) | two parallel example trees | 0 both | delete, or keep one and name it |
| `backend/schemas/workflow_blueprint.py`, `core/utils/dynamic_prompts.py`, `core/utils/trustcall.py`, `services/data_dashboard.py`, `api/analysis/analysis_checkpoints.py`, `features/ontology/compiler/merge_ttl.py`, `langgraph/check_states.py`, `db/add_project_id_column.py` | 499 + 390 + 494 + 599 + 57 + 53 + 165 + 46 | 0 each | delete |
| `backend/notebooks/module-1/.langgraph_api/*.pckl` | 7 files | — | untrack: langgraph runtime state |
| `backend/notebooks/**/.ipynb_checkpoints/` | 25 files | — | untrack: editor scratch |

### 2.3 Endpoints nobody calls

426 route decorators were resolved to full paths and grepped against `src/`, `tests/`, `scripts/` and
`docs/`. **18 endpoint groups have zero callers**, and they are not all alike:

- **Whole routers never mounted or never called**: `api/mcp/config.py` (7 endpoints, no
  `include_router`), `api/workflows/checkpoints.py` (5 endpoints, 420 lines, no caller anywhere),
  `api/classic_graph/` (registered, `classic` appears **0 times** in `src/` and tests, **and both its
  tables `classic_graphs` / `classic_graph_runs` hold 0 rows** — router + model + tables can go
  together).
- **Orphan handlers inside live routers**: `api/analysis` `data-embedded/{filename}` and `meta/{hash}`
  (served only by the retired `analysis_server.py`), `api/memory/projects/{id}/memories*`,
  `api/agent-documents/*`, `api/graphindex/chat*`, `api/workspace/files/bulk-delete` and
  `default/files*`, `api/ontology/workbenches*`, `api/kv/tree`, `api/skills/playground/run`,
  `api/settings/embedding-models`, `api/background-tasks/stats`, `api/graph-studio/threads/{id}/runs`,
  `api/webhooks/trigger/{id}/test`, `api/debug/emit-test-subagent-events/{workflow_id}`.
- **Exception — keep**: `POST /api/workflows/{id}/export/package` is the sole entry point to the live
  `workflow_exporter.py`; the frontend does not call it, but removing it would orphan the exporter.

### 2.4 Two places to stop and ask a human

1. **`backend/scripts/manual_migrations/`** (5 files, 1 437 lines). Alembic owns `audit_log`, but
   **`workflow_version` appears in none of the 41 alembic revisions** — so
   `add_versioning_columns.py` may still be the only thing that creates columns the app writes to.
   Do not delete this directory until someone confirms it against a fresh DB.
2. **`backend/notebooks/module-6/`** (~40 `zz_*` / `fetch_*` / `run_*` scripts, most of the 34 MB).
   The notebooks API lists `.ipynb` only, so these are teaching scratch — but they are the material of
   the course that ships with the repo, so the answer is "archive", not "delete".

## 3. Docs

Method: 36 documents (`docs/**/*.md`, the root instruction files, two package READMEs), 1 369 path
tokens, 32 markdown link targets, 168 endpoint mentions checked against a route inventory built from
`APIRouter(prefix=…)` + decorators, and 5 orphan checks.

**One root cause explains most of it:** `docs/` was reorganised into `docs/system-architecture/` and
`docs/installation/`, but the links inside the docs were never updated — and `docs/reference/`, which
several docs link to, **never existed**.

| Class | Count | Example |
|---|---|---|
| doc → doc links in the old flat layout | 33 refs, 15 targets | `README.md:25` links `docs/system-architecture.md` (now `docs/system-architecture/system-architecture.md`) |
| links into `docs/reference/` and `plans/` | 17 | `docs/usage.md:148` → `reference/agent-practice.md` (no such tree) |
| source paths that moved | 8 | `backend/scripts/seeds/neo4j-hr` → `backend/scripts/seeds/in/neo4j-hr`; `backend/skills/erp-analyst/` → `backend/skills/personal/1/erp-analyst/` |
| **API endpoints quoted in docs that do not exist** | 4 | `AGENTS.md:47-49`: `/api/workflows/{id}/execute`, `/api/agents/{id}/chat`, `/api/knowledge/documents` — the real ones are `/api/orchestration/*`, `/api/chat/message/stream`, `/api/rag/*` |
| count claims that are wrong | 4 | "43 routers registered" (**49**); "13 activities" (**14**, `ontology` was added — and `usage.md` documents 13); seed baseline "56 agents / 67 tools" (**63 / 74**); `GOOGLE_OAUTH_SETUP.md` says the key lives in `backend/encryption.key` (**no code reads such a file**; it is `API_KEY_ENCRYPTION_KEY` from env) |
| docs nothing links to | 5 | `GOOGLE_OAUTH_SETUP.md`, `agents-audit.md`, `deepseek-vision-model.md`, `session2-data-agent-boundary.md`, `tools-audit.md` |

`CLAUDE.md` claims to mirror `AGENTS.md`; the two have drifted, and it is **`AGENTS.md` that is
stale** — it is the file agents read, so its three dead endpoints are the most expensive item in this
section.

Verified as **not** drift (do not "fix"): `REFACTORING.md`'s missing paths are `old → new` arrow
notation for finished splits; `deploy/seed/`, `data/uploads/`, `gcp-oauth.keys.json`, fenced example
trees and DSH-product references are all correct where they are.

Two more facts from the same pass, so nobody re-audits them:

- **What is healthy in the instruction files** — all 16 rows of `AGENTS.md`'s Key Paths table resolve;
  all 5 commands (`bash start.sh`, `docker-compose up -d postgres`, `uv run alembic upgrade head`,
  `uv run pytest`, `npm run build`) resolve; the stack versions (Python 3.13, deepagents 0.7.1,
  PG16+pgvector, LangChain v1) are accurate; "12-case run book" is exactly 12; `README.md`'s
  `/api/chat/health` exists. The drift is concentrated in the **endpoint trio and three counts**.
- **Two docs are load-bearing but only singly linked**, which is why link rot went unnoticed:
  `carrier_studio.md` is reachable only from `data-taxonomy.md`, and `ontology_architecture.md` only
  from `carrier_studio.md`. `tools-audit.md`'s only inbound link is *itself broken* (three code
  comments in `backend/tools/native_impl.py` point at `docs/tools-audit.md`, not
  `docs/system-architecture/tools-audit.md`).

Also worth noting: **no doc mentions any ontology profile or builder agent**, so the archiving of
v1/v2/v5 left no dangling promise — but since `profiles/` now holds only `abc, clinic, logistics,
v3, v4, v6, retail, tpch`, a future doc that names v5 will break the moment it is written.

## 4. What to do, in order

### 4.0 Already done (this pass) — and how each one is proven

| Fix | What was wrong | Proof |
|---|---|---|
| `api/chat/documents.py` | `/upload` and `/upload-multiple` declared **twice**, and `_extract_file_text` / `_index_to_graphindex_for_chat` defined twice — Python kept the *older* helper, FastAPI kept the *first* route | `test_no_route_is_declared_twice_in_one_router`, `test_no_top_level_function_is_defined_twice[...]` (875 parametrised files) |
| `case 'learning'` | the view was routable, the activity was in the bar, and the switch had no arm → home page | `test_every_route_target_has_a_render_case` (new page: `src/components/layout2/LearningHomePage.tsx`) |
| `AGENTS.md` / `CLAUDE.md` | three endpoints that no router serves, `43 routers` (真 49), `13 activities` (真 14) | `test_quoted_api_endpoints_exist` |
| `DownloadProvider` | never mounted → every artifact downloaded as `Generated_1.<ext>`; the fallback counter also reset on every call | `test_downloads_are_named_after_their_workflow` |
| `GoogleOAuthButton`, `usePresentationJob` | hardcoded `http://localhost:8765` → dead on any other host | `test_no_component_hardcodes_the_backend_origin` |
| document store | 459 unreferenced files / 535 MB, 815 dangling records | `tests/test_housekeeping_documents.py` (6 tests on a temp tree) + `scripts/housekeeping_documents.py --db` reproducing the numbers |

Still open in this step: the **mock `SearchPanel`** (needs a real search endpoint — a feature, not
housekeeping) and the mechanical **doc link rot** (33 + 17 links, no behaviour involved).



1. **Fix the live bugs the audit turned up before tidying anything** — they are cheap and each one
   makes a delete safe afterwards:
   - the **duplicate routes** in `backend/api/chat/documents.py` (`/upload` and `/upload-multiple`
     declared twice);
   - the **Learning activity** that renders the home page (`ROUTE_TO_VIEW['/learning']` with no
     `case` in the switch);
   - **`AGENTS.md`'s three dead endpoints** and its `43 routers` count (49), because that file is what
     every agent reads;
   - the **815 dangling document records**, so the viewer stops offering files that are gone.
2. **Delete the dead code**, in this order of confidence: `workflow_exporter_old.py` (3 043 lines),
   `api/schemas.py`, `api/mcp/config.py`, `api/workflows/checkpoints.py`, `backend/orchestration/`,
   the root `test_*_search.py` pair, and the four zero-reference `_`-prefixed scripts. Then the four
   unmounted frontend subsystems (49 files, ≈15 400 LOC).
3. **Delete the residue in §1.4** (535 MB of unfiled documents, 25 MB of embedded venvs,
   `__pycache__`, refused `.staging` trees, old `.backup` snapshots, `backups/`, `data/analysis_dbs`,
   and on demand `langconfig.zip` / `dist/` / `.uv-cache/`) — one script, `--dry-run` first, every
   path logged.
4. **Untrack the bloat in §1.5**, extend `.gitignore` (`Arial`, `.langgraph_api/`, `*.pckl`,
   `*.ipynb_checkpoints/` is already there but not applied to notebooks, `backend/skills/personal/`),
   drop the dangling `my-deep-agent-fe` symlink, and stop tracking one user's personal skills.
5. **Repair the docs link rot**: 33 old-flat-layout links + 17 `docs/reference/`·`plans/` links + 8
   moved source paths — mechanical, and it is the cheapest way to make `docs/` trustworthy again.
6. **Decide on history**: rewriting `.git` from 481 MB to roughly 70 MB is the only way to reclaim
   that space, and the price is a re-clone on every machine including the deployment. Not urgent —
   but note the working tree is only 82 MB tracked, so 85 % of what `.git` holds is old uploads.

## 5. How to verify any of this yourself

```bash
# data
git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)' \
  | awk '$1=="blob" && $3 ~ /^backend\/data\// {s+=$2; n++} END {printf "%.0f MB in %d blobs\n", s/1048576, n}'
# code (backend): is a module reachable?
grep -rn "import <module_name>\|from <module_name>" backend --include=*.py --exclude-dir=.venv
# code (frontend): is a file reachable from the entry point?
grep -rn "from '.*<Basename>'" src
# docs: does a quoted path exist?
git ls-files --error-unmatch <path>
```


## 6. How to test any of this

One command, and it exits non-zero if anything is wrong:

```bash
./scripts/housekeeping_verify.sh          # guards + typecheck + build + store report (~30 s)
./scripts/housekeeping_verify.sh --quick  # skip the frontend build
./scripts/housekeeping_verify.sh --full-suite   # also run the 1 000-test backend suite
```

What each part proves, and why it is a test rather than a checklist:

| Check | Command it runs | What it would have caught |
|---|---|---|
| route collisions | `pytest tests/test_housekeeping_guards.py -k twice` | the `/upload` pair — the second handler was unreachable and editing it changed nothing |
| redefined functions | `pytest tests/test_housekeeping_guards.py -k defined_twice` | the two `_extract_file_text` — Python keeps the last binding, so the older helper ran |
| views that render nothing | `pytest … -k render_case` | Learning: routable, in the ActivityBar, no `case` → showed the home page |
| doc endpoints | `pytest … -k quoted_api_endpoints` | `POST /api/workflows/{id}/execute` in `AGENTS.md`, which every agent read |
| hardcoded origin | `pytest … -k hardcodes_the_backend_origin` | `http://localhost:8765` in two components |
| download naming | `pytest … -k downloads_are_named` | `DownloadProvider` never mounted → `Generated_1.png` |
| document classifier | `pytest tests/test_housekeeping_documents.py` | deleting a *referenced* file, or calling a dangling record an orphan |

The guards are static (they read source with `ast` and grep), so they need **no database, no app
import, and run in ~6 s** — which is what makes them worth running on every change rather than once.

**The 20-failure baseline.** The backend suite is not green and was not green before this pass:
`pytest tests` reports **20 failed / 1 004 passed** on a clean checkout (mostly
`test_user_workspace_path`, `test_ontology_build`, `test_user_api`). Two files fail at *collection*
(`test_neo4j_document_enrichment`, `test_pageindex_full_content_loader` — missing optional deps), so
the suite is run with those ignored. Compare against the baseline rather than expecting green:

```bash
cd backend && .venv/bin/python -m pytest tests -q \
  --ignore=tests/test_neo4j_document_enrichment.py \
  --ignore=tests/test_pageindex_full_content_loader.py 2>&1 | grep -E '^(FAILED|ERROR)' | sort
```

**Manual checks** (things no static test can see — do these in the browser once):

1. **Learning** — click `Learning` in the ActivityBar: it must show the notebook list (28 notebooks
   here), grouped by module, and clicking one must open it as a workspace tab. Before the fix it showed
   the home page.
2. **Download naming** — run any workflow that emits an image, download it from the results panel: the
   file must be named after the workflow, not `Generated_1`.
3. **Documents** — open a document viewer and confirm it does not offer an entry whose file is gone
   (815 of those exist today; they disappear only after `--prune-refs --apply`).

**When you are ready to clean the store** (§1.2), the script moves rather than deletes — run it, read
the manifest, then decide:

```bash
cd backend
.venv/bin/python ../scripts/housekeeping_documents.py                  # report (this is what I ran)
.venv/bin/python ../scripts/housekeeping_documents.py --quarantine --apply
.venv/bin/python ../scripts/housekeeping_documents.py --prune-refs --apply
# to undo:  mv data/documents/.quarantine/<stamp>/* data/documents/
```


## 7. Execution log — what was actually done

> **Commit hashes in §7 changed on 2026-11-09**: the history was rewritten (§7.7), so every hash that
> existed before it is gone. Identify commits by their message, not their sha.

Three batches, each verified before moving on. Nothing here is a proposal; it is what ran.

### 7.1 The fixes and the guards (commit `d65ae5c`)

`api/chat/documents.py` de-duplicated (route pair + two helper pairs) · `case 'learning'` added with
`LearningHomePage` · `AGENTS.md`/`CLAUDE.md`/`README.md`/`docs/usage.md` endpoints and counts corrected
· `DownloadProvider` mounted in `WorkflowCanvas`, fallback counter fixed · both hardcoded
`http://localhost:8765` replaced by `API_BASE_URL` · guards + document classifier + verify script added.

Proven by: `./scripts/housekeeping_verify.sh` → **842 guards pass, tsc clean, build clean**, and the
backend suite at exactly the 20-failure baseline.

### 7.2 The deletions (commit `e647b5e`, 162 files, −40 469 lines)

| Batch | Removed | Verified by |
|---|---|---|
| backend modules | `workflow_exporter_old.py` (3 043 L), `api/schemas.py` (shadowed), `api/mcp/config.py` (never mounted), `api/workflows/checkpoints.py` (5 endpoints, 0 callers) **and its `include_router`**, `backend/orchestration/` (broken package), 6 zero-reference modules | `import main` builds 423 routes; full suite unchanged at 20 failures |
| backend root | 15 loose one-off scripts, 2 loose `test_*.py`, `titanic_analysis.png`, `langconfig.db`, two parallel example trees, the directory literally named `db:` | same |
| frontend | 44 files: memory UI, execution-history panels, canvas barrel + hooks + dialog, old `components/layout` shell, 2 page-shaped orphans, plus the 5 files that only those referenced | `tsc` + `vite build` clean |
| untracked (kept on disk) | `Arial Unicode.ttf` (23 MB), 7 langgraph `.pckl` blobs, 25 `.ipynb_checkpoints` files, `backend/skills/personal/` | `git ls-files` counts to 0; `.gitignore` extended so they cannot come back |
| deleted assets | 6 unreferenced images, the dangling `my-deep-agent-fe` symlink | grep for each basename |

### 7.3 The document store (no commit — it is gitignored runtime data)

```
cd backend
.venv/bin/python ../scripts/housekeeping_documents.py --db --quarantine --prune-refs --apply
```

Result, measured by the same script immediately afterwards:

| | before | after |
|---|---|---|
| files in the store | 1 491 | **1 032** |
| distinct references | 1 847 | **1 032** |
| healthy pairs | 1 032 | **1 032** |
| unreferenced files | 459 (535 MB) | **0** |
| dangling references | 815 | **0** |

The 459 files were **moved**, not deleted: `backend/data/documents/.quarantine/20261109-213814/` keeps
their original relative paths plus a `MANIFEST.txt`, and the pruned catalog files were copied to
`kvmeta-backup/` beside it. To undo:

```bash
mv backend/data/documents/.quarantine/20261109-213814/project_* backend/data/documents/
cp backend/data/documents/.quarantine/20261109-213814/kvmeta-backup/*.json backend/data/documents/.kvmeta/
```

Nothing was reclaimed on disk yet — the quarantine sits inside the store (537 MB) so the move stays a
one-liner. To actually free the space, move it off the checkout:

```bash
mv backend/data/documents/.quarantine/20261109-213814 ~/langconfig-quarantine-2026-11-09
```

### 7.4 The docs link rot (commit follows 7.3)

`docs/` was reorganised and the links inside it were not. New tool: `scripts/docs_link_check.py`
(report / `--fix` / `--check`), guarded by `backend/tests/test_docs_links.py`.

| | before | after |
|---|---|---|
| broken relative links between our own docs | 32 | **0** |
| stale source paths quoted in docs | 8 | **0** |

The fixer only rewrites a link when **exactly one file in the repository** has the target's basename —
a rename is followed, a deletion is not guessed at. It ignores anything inside fenced code blocks (an
illustrative directory tree in a design note is not a link) and skips external URLs and anchors.
The five links whose targets are genuinely absent (4 × `plans/*.md`, 1 × `reference/agent-practice.md`)
were unlinked in prose with the reason, rather than pointed at a wrong file. Code comments in
`backend/tools/native_impl.py` that named `docs/tools-audit.md` now name its real path.

### 7.5 Zero-caller endpoints (commit follows)

33 route decorators removed across 14 files; 2 whole routers deregistered (48 → 46), plus the
`agent_documents` package and `api/knowledge/graphindex_chat.py` (684 lines) deleted outright.

**Every route was re-verified here before deletion**, by grepping a distinctive fragment of its path
across `src/`, `backend/tests/`, `scripts/` and `docs/` — and the audit was wrong about one of them:
`GET /api/graph-studio/threads/{id}/runs` **is called** (`src/features/graph-studio/api.ts:397`), so it
was kept. Two other "dead" items were left alone for the same reason: `POST
/api/workflows/{id}/export/package` (the only entry point to the live `workflow_exporter.py`) and
`GET /api/settings/embedding-models` (still described in `settings-refactor.md`).

| Router | Removed |
|---|---|
| `api/memory/routes.py` | all 5 `/projects/{id}/memories*` endpoints (the memory UI was deleted in `e647b5e`) |
| `api/workspace/files_routes.py` | `/files/bulk-delete` + the whole `/default/files*` family (6) |
| `api/workflows/exports.py` | `/export/config`, `/export/config/preview`, `/import` |
| `api/analysis/routes.py` | `/data-embedded/{filename}`, `/meta/{hash_id}` (served only by the retired `analysis_server.py`) |
| `api/ontology/routes.py` | `/workbenches`, `/workbenches/{key}/stop` (the dev-only supervisors; the service stays — `ontology_publish` reloads through it) |
| `api/knowledge/kv.py`, `api/skills/routes.py`, `api/system/background_tasks.py`, `api/system/debug.py`, `api/webhooks/routes.py` | `/tree`, `/playground/run`, `/stats`, `/emit-test-subagent-events/{workflow_id}`, `/trigger/{id}/test` |
| whole routers | `api/knowledge/graphindex_chat.py` (684 L, registered but never called), `api/agent_documents/` (3 GETs; the **table** stays — `tools/native_impl.py` writes it) |

`import main` now builds **390 routes**; the backend suite still reports exactly the 20 pre-existing
failures.

### 7.6 The history rewrite (2026-11-09)

`backend/data/**` had been committed before it was gitignored, so `.git` carried **414 MB of PDFs that
no longer exist in any working tree**. Rehearsed on a bare mirror first, then done for real:

```
git clone --mirror --no-hardlinks . /tmp/rehearsal.git     # 482 MB, 1 882 commits
python -m git_filter_repo --path backend/data --invert-paths \
                          --path "backend/notebooks/module-4/Arial Unicode.ttf" --invert-paths
```

| | before | after |
|---|---|---|
| `.git` (object store) | 460 MB pack / 482 MB dir | **39.6 MiB pack** |
| commits | 1 622 on `main` | 1 581 (43 became empty and were pruned) |
| **HEAD tree** | `cc5005d2…` | **`cc5005d2…` — identical** |
| `git fsck` | — | clean |

The HEAD tree hashing the same is the proof that **no working file changed**: only history did.
Safety net: `.git/backups/pre-rewrite-20261109.bundle` (461 MB, a full `--all` bundle; restore with
`git clone <bundle>`). Delete it once you are satisfied — it is the only thing keeping the old bytes on
this disk. All 20 branches and the `main-history-backup` tag were force-pushed (the tag deleted, since it
was the one ref that kept the old commits alive on the remote), and the deployment was moved onto the
rewritten history with `git reset --hard github/main`.

**A close call worth recording.** That `reset --hard` deleted the `new_coldchain_v5` profile on the
deployment: it had been published at 16:25 but never committed — the publish's own `git commit` had
failed with "Author identity unknown" (§ the publish-commit fix), so its 9 files existed **only in that
checkout**, staged-but-uncommitted, and a hard reset removes exactly that. It was recovered
byte-for-byte from the publish ledger: `ontology_publishes.files` (jsonb) holds the full text of every
staged file, so the applied publish id `1794212541-6afcb2` still contained all nine. After restoring
them the gates re-ran green (84 metrics compiled, 0 refused) and `/api/ontology/installed` lists v5
again with its publish time.

Two lessons, both actionable:

1. **A published ontology that is not committed exists in exactly one checkout.** The ledger can rebuild
   it, but only because `stage()` records the file bodies — that is a backup, not a plan.
2. **Before any `git reset --hard` on a deployment, ask what is untracked there.** Untracked survives;
   staged-and-uncommitted does not.

### 7.7 Still open

- **ECS** has the code (`d65ae5c` + `e647b5e`); its **document store is untouched** — run the same two
  script commands there when convenient (report first).
- **git history** (414 MB of `backend/data` PDFs) — untouched by design: it needs a rewrite and a
  re-clone on every machine.
- **Mock `SearchPanel`** — needs a real search endpoint; a feature, not housekeeping.
- **Dead endpoints inside live routers** (18 groups, §2.3) and **the doc link rot** (33 + 17 links).
- **`scripts/manual_migrations/`** — still needs a human decision (§2.4).
