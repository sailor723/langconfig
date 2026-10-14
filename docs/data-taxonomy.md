# Data taxonomy — Registry · Knowledge · Workspace

**Status:** the three class names are agreed. Sub-levels are proposed. Open items are listed
in §7 — nothing here is implemented yet.

This is the naming authority for the platform's data model. [`storage-map.md`](storage-map.md)
describes where things live today and the shape they should take; this file says what each
thing is *called* and which class it belongs to. When the two disagree, fix whichever is wrong
and note it here.

---

## 1. Why three classes, and only three

Every kind of state in the platform answers one of three questions:

| class | answers | the test |
|---|---|---|
| **Registry** | what the system **is** | you *author* it — would you put it in git? |
| **Knowledge** | what the system **knows** | you *curate* it — would you back the file up? |
| **Workspace** | what the system **does** | it *accumulates* while working — would you miss it after a reinstall? |

Why the classes matter at all — measured on one reference install:

```
Registry (agents, tools, skills, settings, models)   ~2.2 MB      0.04% of the database
Knowledge (documents and their index)                690 MB on disk, 125 MB in the database (db mode)
Workspace                                            6.0 GB DB     97%
    of which run machinery (checkpoints)             5.8 GB of the 6.1 GB total
```

One class holds 0.04% of the bytes and is the only portable one; another holds 97% and is
deliberately per-machine. Treating them as one collection of "data" is what produced the
confusion this taxonomy replaces.

---

## 2. The classes, against what exists

### Registry — 7 tables, 5 artifacts

| database | git (the portable form) | notes |
|---|---|---|
| `deep_agent_templates` | `agents.sql` | additive union; a name clash keeps the teammate's version |
| `custom_tools` | `tools.sql` | additive union on `tool_id` |
| `skills` | `skills/**` | the `SKILL.md` file **is** the artifact |
| `settings_documents` | `settings.json` | **three-way merge, not union** — see §6 |
| `models` | `models.csv` | hand-maintained; no export path |
| `workflow_profiles`, `directives` | — | not currently exported |

Grows with **authoring**. Canonical home is Postgres; the git snapshots exist because
definitions otherwise cannot travel between machines.

### Knowledge — 5 tables

| database | disk |
|---|---|
| `context_documents` (catalog, hierarchy, indexing state) | `data/documents/<project_id>/documents/files/[industry/player/sub_category/sub_department]/<uuid8>_<name>` |
| `data_context_documents_embeddings` (vectors) | `.kvmeta/<project_id>.json` (the listing the sidebar reads, local mode) |
| `storage_objects` (the bytes, `storage.mode=db` only) | — |
| `agent_documents`, `session_documents` | — |

Grows with **what you curate**. The catalog is currently split three ways — `.kvmeta`,
`context_documents`, `storage_objects` — which is why a document can be listed but not
retrievable, or present but invisible.

### Workspace — 11 tables

| sub-kind | tables | disk | retention |
|---|---|---|---|
| session record | `chat_sessions`, `conversation_archives` | — | keep (5.5 MB here) |
| run machinery | `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` | — | **ephemeral (6.0 GB here)** |
| generated files | `workspace_files`, `file_versions` | `outputs/<project>/agents/<agent_id>/`, `outputs/<project>/runs/<workflow_id>/<task_id>/` | keep until promoted or expired |
| staging | — | `data/uploads/` | expire quickly |
| traces | `tool_execution_logs`, `search_history`, `agent_memories` | — | prune |
| scope | `projects` | `.workspace_data/<project>/AGENTS.md` | see §7.1 |

Grows with **usage, steps and work produced** — three different growth laws inside one class,
which is why the sub-kinds above must not blur.

---

## 3. The names, and what was rejected

Chosen: **Registry · Knowledge · Workspace.** All three are place-or-collection nouns, so they
read as one family, and each survives being a folder name, a UI label, a doc heading and a
sentence.

Rejected, with the reason — recorded so it isn't re-litigated:

| candidate | why not |
|---|---|
| **config** | `.env` and the Settings UI already own that word; and it is the *envelope* of the platform, not its definitions |
| **definitions** | accurate, and already the code's word (`ToolDefinition`, `list_definitions`), but it reads as an abstract plural rather than a place, and does not sit naturally beside Knowledge and Workspace |
| **harness** | **already a fixed product term**: `docs/carrier_studio.md` opens with "the three terms (runtime, framework, harness)" and defines it as "the prompt, the tools, and any middleware" — i.e. it deliberately spans code *and* part of this class. Reusing it would blur the boundary this taxonomy draws |
| **fleet** | it is **LangChain's product name** — `docs/carrier_studio.md` compares Carrier Studio against "LangSmith Fleet" in a table. Putting a competitor's brand on an internal class is a factual clash |
| **hangar** | metaphor-consistent, declined |
| **artifacts** | inverted industry meaning: Google ADK calls **agent-produced files** artifacts, i.e. this class's opposite |
| **assistants** | LangGraph's term for a configured graph, with versions — good precedent, but it covers agents only, not tools, skills or settings |
| **catalog** | strong fit; reserved instead for the documents' listing, which this taxonomy renames to **index** to keep the words apart |
| **library**, **assets** | plausible (the UI already says "Tool Library"; Aliyun's handbook says "AI assets") but both are also shaped like Knowledge |

Industry precedent that supports the choice:

- **Registry** — model / prompt / agent / tool registries are the established pattern:
  [Nacos AI Registry](https://nacos-group.github.io/en/docs/next/manual/user/ai/ai-registry-overview/),
  [COMPEL: "Agent, Prompt, Tool, and Memory Registries"](https://www.compelframework.org/articles/agent-prompt-tool-memory-registries).
  The codebase already agrees: `core/tools/registry.py`, `ToolRegistry.list_definitions()`, and
  the UI's "Tool Library".
- **Knowledge** — the sidebar already names the surface *Knowledge* (`nav_knowledge`, 知识库).
- **Workspace** — already the code's word for the agent's working area
  (`settings.workspace.base_dir`, `workspace_path`, `WorkspaceManager`, `workspace_files`).
- The **control-plane / data-plane** split used elsewhere in the industry
  ([AgentScope Service](https://java.agentscope.io/v2/en/blogs/agentscope-service-release-tech))
  is the same instinct; this taxonomy just names the planes in product language.

So two of the three names were already in the product, and the third was already in the code.
Nothing new was imported.

---

## 4. Rules

1. **One name per class, everywhere** — UI label, code, path, doc. Two names for one class is
   how the previous confusion started.
2. **Scope is an axis, not a class.** `project` is not a fourth class: it is *whose* the thing
   is, and it applies to all three (`knowledge/<project_id>/…`,
   `workspace/<project_id>/agents/<agent_id>/…`, project-scoped registry rows).
3. **Retire these as top-level names** — each is ambiguous today: `data`, `storage`, `outputs`,
   `documents`, `vault`, `seeds`, `files`, and `workspace` for anything that is not class 3.
4. **Class membership is decided by the test in §1**, not by where a thing happens to sit
   today. A file an agent wrote is Workspace; the same file promoted for the model to consult
   becomes Knowledge.

---

## 5. Sub-levels (proposed)

```
registry/                                  ← git: the portable form of the Registry
    agents.sql          agents.baseline.sql      (today deep_agents_merge.sql / _dump.sql)
    tools.sql           tools.baseline.sql       (today custom_tools_merge.sql / _dump.sql)
    settings.json                                (today settings_seed.json)
    models.csv                                   (today models_seed.csv)
    skills/**                                    (today backend/skills/**)

knowledge/<project_id>/                    ← curated documents and their catalog
    documents/files/[industry/player/sub_category/sub_department]/<uuid8>_<name>
    documents/index.json                         (today data/documents/.kvmeta/<project_id>.json)

workspace/<project_id>/                    ← what accumulates while working
    agents/<agent_id>/                           scratch + generated files
    runs/<workflow_id>/<task_id>/                (today outputs/<slug>/workflow_<id>/task_<id>/)
    staging/                                     uploads in flight (today data/uploads/)
```

Sub-vocabulary: an upload is **staged** in Workspace and **promoted** into Knowledge;
*promotion* is an action, not a location. **Prompts** are not a sub-level — they are a
`system_prompt` field inside an agent row, so there is no prompt registry to name.

---

## 6. Things that do not fit cleanly

1. **`settings` merges; everything else unions.** The seed treats Registry entries as an
   additive union (a clash keeps the teammate's version) and settings as a three-way merge (a
   key they changed themselves is never overwritten). Same class, different sharing semantics
   — the name should not imply that all Registry objects propagate the same way.
2. **Run machinery inside Workspace is 1000× the rest.** `checkpoints`/`checkpoint_blobs` are
   transient execution state, not history, and they dominate the database (5.8 GB of 6.1 GB).
   Keeping them in Workspace is right by the test — but their retention cannot be shared with
   the session record.
3. **Knowledge has three catalogs today** (`.kvmeta`, `context_documents`, `storage_objects`).
   The taxonomy does not fix that; it only makes the intended shape stateable — one catalog,
   one payload.
4. **`agent_documents` and `session_documents`** are Knowledge by content but Workspace by
   scope. Left in Knowledge for now; worth revisiting if promotion semantics get built.

---

## 7. Open decisions

1. **Does `projects` belong in Registry?** Proposed: **yes** — it is authored, named, and you
   would want it to travel with the team. It cannot be both, and today it sits in Workspace's
   list only because it is per-machine data.
2. **Promotion rule** — copy or move, and does promoting a generated file index it (embeddings)
   immediately?
3. **Retention** — checkpoints aggressive, staging short, session record and generated files
   kept. Where is the retention configured, and is it per-project?
4. **The two `*_dump.sql` baselines** — rename to `*.baseline.sql`, or retire them? They are the
   empty-table path only, and a stale row in one of them shipped a duplicate `write_file` tool
   to every teammate.
5. **Data root** — external (`LANGCONFIG_DATA_ROOT`) with today's layout as the default, or stay
   in-tree?
6. **Rename now or only for new code?** Renaming artifact filenames and settings keys is cheap;
   renaming paths that the database records is a migration (see `storage-map.md` §4).

Answers to 1–3 would let the sub-levels be finalised; 4–6 are scheduling questions.
