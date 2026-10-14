# Storage map — where a project's data actually lives

Two questions this answers, because both have bitten us:

1. **Where is a project's data?** One project's documents, agent workspaces and memory
   are currently spread across three directories, keyed two different ways.
2. **Why does copying or moving a tree break things silently?** Because the database
   stores *absolute* paths, so a path describes the machine it was written on rather
   than the project.

Numbers quoted below are from one reference install (56 agents / 67 tools), not
universal constants — they are there to make the shapes concrete.

---

## 1. The state today

```
~/langconfig/                                   ← code tree (git) — but the data lives inside it
│
├── .env            POSTGRES_*, API_KEY_ENCRYPTION_KEY, LANGCONFIG_WORKSPACE_ROOT
│
├── backend/
│   ├── data/                                   ← ① not configurable: "./data" relative to CWD
│   │   ├── documents/                          ← storage.documents_base_dir
│   │   │   ├── .kvmeta/project_1.json          ← CATALOG A: the sidebar panel lists from this
│   │   │   ├── project_1/…                     ← ② keyed by NUMERIC ID
│   │   │   │      └── [industry/player/sub_category/sub_department]/<uuid8>_<name>
│   │   │   ├── project_15/…  project_9876/…    ← ③ no `projects` row → INVISIBLE in the UI
│   │   │   └── (db mode lists from storage_objects instead — same bytes, other catalog)
│   │   ├── uploads/  agents_md/  storage/
│   │
│   ├── outputs/                                ← "WORKSPACE" #1: settings.workspace.base_dir
│   │   ├── langconfig-test/                    ← ④ keyed by SLUG (= project 1)
│   │   │   ├── agents/agent_212/               ← deliverables the agent wrote
│   │   │   └── workflow_None/
│   │   ├── agents/agent_223/                   ← ⑤ legacy: agent has no project_id
│   │   └── projects/default-project/           ← older layout, still on disk
│   │
│   └── .workspace_data/                        ← "WORKSPACE" #2: LANGCONFIG_WORKSPACE_ROOT
│       ├── langconfig-test/AGENTS.md           ← ⑥ SLUG again
│       ├── 999/AGENTS.md    None/AGENTS.md     ← ⑦ keys that match no project
│
└── PostgreSQL
    ├── projects(id, name, indexing_status, indexed_nodes_count, embedding_dimension)
    ├── context_documents(project_id, file_path → ABSOLUTE, industry…, indexing_status)  CATALOG B
    ├── data_context_documents_embeddings  (pgvector)
    ├── storage_objects(key = 'documents/project_<id>/…')                                CATALOG C
    ├── session_documents(project_id, file_path → ABSOLUTE)
    ├── workspace_files(project_id, file_path)   file_versions
    ├── deep_agent_templates(project_id, workspace_path → ABSOLUTE)
    ├── chat_sessions(project_id)
    └── skills(source_path → ABSOLUTE)
```

### What each marker costs

| marker | what it is | the failure it has already produced |
|---|---|---|
| ① | `backend/data/` is not configurable | a fresh clone cannot be pointed at existing data, so 695 MB gets copied by hand |
| ②④ | documents key on the **id**, workspaces on the **slug** | renaming a project moves half its data and orphans the rest |
| ③⑦ | folders with no matching database row | documents and `AGENTS.md` files that exist but appear nowhere |
| ⑤ | agents without a project keep a legacy path | two workspace layouts coexist (`outputs/agents/…` and `outputs/<slug>/agents/…`) |
| A B C | three catalogs for one body of documents | the panel can list what retrieval cannot find, and vice versa |
| → | absolute paths in the database | copying the folder yields `1779 records, 1779 DANGLING` while the UI still lists everything |

### The rules that currently apply

- **Agent workspace** — `WorkspaceManager.resolve_agent_workspace`, in priority order:
  1. `deep_agent_templates.workspace_path` (absolute used as-is; relative resolved against
     the vault root when a project is bound, else against `base_dir`);
  2. vault-scoped default `outputs/{vault_key}/agents/agent_{id}/` when a project is bound;
  3. legacy default `outputs/agents/agent_{id}/`.
- **vault_key** — `_slugify(project.name)`, falling back to `project_<id>`
  (`WorkspaceManager.project_vault_key`). This is why a project rename moves directories.
- **Project workspace** — `get_project_workspace` → `base_dir / slug`, created on demand.
- **Project memory** — `services/agents_md_service.py`: `{WORKSPACE_ROOT}/{project_id}/AGENTS.md`
  according to its docstring, while the disk shows slugs and stray keys (`langconfig-test/`,
  `999/`, `None/`). The docstring and the on-disk reality disagree.
- **Documents** — `data/documents/project_<id>/…` plus `.kvmeta/project_<id>.json`; in
  `storage.mode=db` the listing comes from `storage_objects` keys instead.
- **Path anchors differ** — `./data/documents` resolves against `backend/` (the process CWD)
  while `backend/outputs` resolves against the repo root. Same file, two conventions.

---

## 2. The identity mismatch, at a glance

```
project  slug                documents (id-keyed)       agent workspace (slug-keyed)         memory (slug-keyed)
──────────────────────────────────────────────────────────────────────────────────────────────────────────────
1        langconfig-test     data/documents/project_1   outputs/langconfig-test/…            .workspace_data/langconfig-test/AGENTS.md
18       my-project          —                          outputs/my-project/…                 .workspace_data/my-project/AGENTS.md
19       My Second Project   —                          outputs/my-second-project/…          …
20       default-project     —                          outputs/projects/default-project/    …
9876     (no row)            data/documents/project_9876  —                                   —
```

Every row where the middle columns disagree is a rename that cannot be done safely. The
last row is data nothing points at.

---

## 3. The proposed shape

```
~/langconfig/                       ← code only (git). Recloning or deleting touches no data.
~/langconfig-data/                  ← LANGCONFIG_DATA_ROOT (bootstrap var, like DB credentials)
│
└── projects/
    └── <project_id>/               ← ② ONE key everywhere: the immutable id
        ├── documents/
        │   ├── files/[industry/player/sub_category/sub_department]/<uuid8>_<name>
        │   └── catalog.json        ← A|B|C merged: the database is the catalog, this mirrors it
        ├── memory/AGENTS.md        ← "WORKSPACE" #2, named for what it is
        └── workspaces/
            ├── agents/<agent_id>/          ← "WORKSPACE" #1
            └── workflows/<workflow_id>/<task_id>/
│
└── storage/                        ← db-mode blob spill

PostgreSQL
    projects(id, name, …)                    ← the ONLY identity; the slug is a display label
    context_documents(project_id, path RELATIVE, …)   e.g. projects/7/documents/files/a/b/report.md
    data_context_documents_embeddings
    deep_agent_templates(project_id, workspace_path RELATIVE)
    skills(source_path RELATIVE)   workspace_files(file_path RELATIVE)   …
```

In one line: **the stored path stops describing this machine and starts describing the
project** — which is what makes data portable, copyable and renamable.

### The six rules

1. **Code and data never share a tree.** One `LANGCONFIG_DATA_ROOT`; the repo holds code only.
2. **One identity: the immutable project id.** Folders key on the id; the slug is a label.
3. **One path convention: relative to the data root.** Absolute paths in the database are
   the bug class that made a folder copy produce thousands of dangling records.
4. **Two roots, two names** — never "workspace" for both:
   `workspaces/<project_id>/agents/<agent_id>/` (deliverables) and
   `memory/<project_id>/AGENTS.md` (project memory).
5. **One catalog, one payload.** The database is the catalog, the disk is the payload.
   Today the catalog is split across `.kvmeta`, `context_documents` and `storage_objects`.
   The genuine fork: if the database owns the listing, an upload is visible only once its row
   is committed; if the disk owns it, a dropped file appears but the database can lag.
6. **Make drift loud.** A doctor command reports dirs with no project row, rows with no file,
   files with no row, and mode mismatches — each with a safe repair.

---

## 4. Migration, in four independently shippable phases

| phase | change | risk |
|---|---|---|
| 0 | promote `scripts/audit_local_data.py` into a real doctor (orphans, dangling, inconsistencies) | none — reporting only |
| 1 | introduce `DATA_ROOT`, defaulting to today's layout so nothing moves; new writes use relative paths, reads resolve relative-then-legacy-absolute | low |
| 2 | one-time converter: existing rows and `.kvmeta` records go absolute → relative; dry-run first, idempotent | moderate, reversible |
| 3 | optional `--relocate` to move data out of the tree, and switch agent workspaces to id keys, leaving readable symlinks if wanted | deferred |

Phases 0–1 carry most of the value; 2 makes the database portable; 3 is cleanup.

### What deliberately does not change

- **Postgres stays the catalog** — no new datastore.
- **The two-layer document model stays** (bytes vs index); only naming and the single-catalog
  rule change.
- **`.env` keeps bootstrap only** (DB parts, `API_KEY_ENCRYPTION_KEY`, `DATA_ROOT`); runtime
  configuration stays in the settings document, which is already the app's stated direction
  for API keys ("a value in `.env` is no longer read").
- **`checkpoint_writes.task_path`** belongs to LangGraph; leave it alone.

### Surface area

Roughly **20 files** build these paths (workspace manager, identity, file storage, the
knowledge API, `agents_md_service`, the seeds and several repair scripts) and **10 columns**
hold them: `context_documents.file_path`, `deep_agent_templates.workspace_path`,
`presentation_jobs.result_file_path`, `session_documents.file_path`, `settings.storage_path`,
`settings.workspace_path`, `skills.source_path`, `workflow_profiles.custom_output_path`,
`workspace_files.file_path`, plus the `.kvmeta` JSON store. `project_id` appears on twelve
tables, which is what makes it the right key to standardise on.

The existence of `tools/migrate_storage.py`, `tools/migrate_project_folders.py`,
`scripts/rescue_stranded_workspace_files.py` and `scripts/clean_projects.py` is itself
evidence: each patched a symptom of the missing rules above.

---

## 5. Inspecting the current state

```bash
cd <tree>/backend
.venv/bin/python scripts/audit_local_data.py        # mode, roots, DB rows, on-disk sizes
```

Do the recorded document paths resolve?

```bash
python3 - <<'EOF'
import glob, json, os
recs = [v["storage_path"] for f in glob.glob("data/documents/.kvmeta/*.json")
        for v in json.load(open(f)).values() if v.get("storage_path")]
missing = [p for p in recs if not os.path.exists(p)]
print(f"{len(recs)} records, {len(missing)} DANGLING")
EOF
```

Which projects exist as rows, and which exist only as folders — i.e. which documents the
sidebar can never show?

```bash
.venv/bin/python - <<'EOF'
import os
from db.database import engine
from sqlalchemy import text
with engine.connect() as c:
    rows = {r[0] for r in c.execute(text("SELECT id FROM projects"))}
dirs = {int(d.split("_")[1]) for d in os.listdir("data/documents")
        if d.startswith("project_") and d.split("_")[1].isdigit()}
print("  projects in the database :", sorted(rows))
print("  document folders on disk :", sorted(dirs))
print("  INVISIBLE (folder, no row):", sorted(dirs - rows))
print("  EMPTY (row, no folder)   :", sorted(rows - dirs))
EOF
```

On the reference install this prints:

```
  projects in the database : [1, 18, 19, 20]
  document folders on disk : [1, 2, 6, 8, 12, 15, 16, 17, 9876]
  INVISIBLE (folder, no row): [2, 6, 8, 12, 15, 16, 17, 9876]
  EMPTY (row, no folder)   : [18, 19, 20]
```

**Eight of nine sets of documents cannot be shown in the sidebar**: the panel lists projects
from the `projects` table, and those ids have no row. The bytes are on disk, the `.kvmeta`
records are present and every path resolves — nothing points at them. `18/19/20` are simply
projects created after the documents were, so they have no folder yet; that direction is
normal and harmless.
