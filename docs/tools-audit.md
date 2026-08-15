# Tools Audit — LangConfig native tools vs DeepSeek Harness

Status: **review (2026-08-15)** — full inventory of every LangConfig native tool,
the DSH tool catalog, and an add/revise recommendation per tool. See
`docs/tools-refactor.md` for the architectural plan this feeds.

## 1. LangConfig native tools (52 = 43 DB-seeded + 9 legacy) — reviewed

### Web (3 + browser)
| Tool | What it does | Verdict |
|---|---|---|
| `web_search` | DDG search + Yahoo fallback (no key) | **Revise** — no Serper/Tavily in the main path; DSH has pluggable backends (exa/perplexity/deepseek-search) |
| `tavily_search` | Tavily (needs `TAVILY_API_KEY`) | Keep |
| `web_fetch` | HTTP fetch, **SSRF-guarded** | Keep |
| `browser` (legacy) | Playwright toolkit → 6 tools (navigate/click/extract_text/extract_hyperlinks/get_elements/current_webpage) | Keep — heavy but real |

### Filesystem (6)
| `ls` · `read_file` (PDF/docx/pptx text extraction) · `write_file` (md/html/pdf/docx render) · `edit_file` (old_string→new_string, unique match) · `glob` · `grep` | | **Revise** — `glob`/`grep` are pure-Python (O(n) scans); DSH uses **ripgrep**. **Missing**: `delete_file`/`rename_file`/`move_file`/`mkdir` (neither LangConfig nor DSH has them — an enhancement beyond DSH). `read_file` has no image support (no `read_image`). |

### Virtual FS (3 legacy — state-based, notebook-2.2 parity)
| ~~`vfs_ls` · `vfs_read_file` · `vfs_write_file`~~ | files in agent state, not disk | **Removed** — duplicated the disk `read_file`/`write_file` concept and confused models; the disk fs tools + `save_document` + workspace roots cover file work. State `files` field kept for schema stability. |

### Reasoning / Todo / Memory (2 + 2 + 2)
| `think_tool` · `reasoning_chain` | strategic reflection | Keep |
| `write_todos` · `read_todos` | state TODO list (notebook-2.1 parity) | Keep |
| `memory_store` · `memory_recall` | **fallback stubs** returning "unavailable" | **Revise** — the real `SimpleMemory` exists (routed when `enable_memory`); the stubs should be removed or become thin delegates, never surface "unavailable" to the model |

### Skills (4) / Agents (2)
| `create_skill` · `update_skill` · `delete_skill` · `search_skills` | skill CRUD | Keep |
| `create_deepagent` · `task` (subagent delegation) | agent creation + delegation | Keep |

### Database (11)
| `pg_list_tables` · `pg_describe_table` · `pg_query` (SELECT) · `pg_execute` (INSERT/UPDATE/DELETE) · `pg_list_agents` · `pg_get_agent` · `pg_list_skills` · `search_skills` · `pg_list_projects` · `pg_list_documents` · `pg_list_custom_tools` | Postgres read/write + catalog | **Revise** — 11 is a lot; `pg_list_skills` vs `search_skills` overlap; several are rare. Consolidate the catalog read-only tools (list tables/agents/skills/projects/documents/tools → one `pg_list` with a `kind` arg or keep the split but prune the rarely-used ones). Keep `pg_query` read-only default, `pg_execute` guarded. |

### Analysis (3)
| `sqlite_execute` (read-only, path-validated) · `sqlite_load_csv` (**defined but NOT seeded**) · `python_execute` (sandboxed) · `save_analysis_result` | data analysis | **Revise** — seed `sqlite_load_csv`; `python_execute` is the pre-Code-Mode sandbox (Phase C replaces it with `run_code`). |

### Graph / retrieval (12)
| `neo4j_list_docs` · `neo4j_get_doc` · `neo4j_query` · `neo4j_upsert_doc` · `neo4j_delete_doc` · `doc_index_list` · `doc_index_structure` · `doc_index_pages` · `graphindex_search` · `graphindex_load` · `graphindex_list_docs` · `graphindex_multi_doc_load` | Neo4j + doc-index + Phase-9 graphindex hybrid | **Revise** — heavy overlap across three families; consolidate or clearly document which stack is canonical. |

### Document / Presentation (2)
| `save_document` (agent_documents library, DB mode) · `gen_pptx` | final deliverables | Keep |

### Runtime-only (not in the 52)
| SimpleMemory real tools (when `enable_memory`) · RAG search tool (when `enable_rag`) · injected `save_document` (workspace agents) · browser Playwright 6-pack | | Keep |

### Custom tool templates
API (webhook) · notification (slack/discord/wordpress) · image/video (DALL·E, Sora, GPT-Image, Imagen, Veo, Nano Banana) · database (postgres/mysql/mongodb) · data-transform (JSON) — user-created via the UI.

## 2. DeepSeek Harness tool catalog

| DSH tool | Package | Notes |
|---|---|---|
| `read` · `write` · `edit` · `read_image` | `packages/fs/tool-fs` | sandboxed (`FsSandboxController`), read windowing/streaming, observation events, **`read_image`** (PNG/JPEG/WebP/GIF) |
| `glob` · `grep` | `packages/fs/tool-fs-search` | **ripgrep-backed** |
| `str_replace_editor` | `packages/fs/tool-str-replace-editor` | Claude-Code-style surgical replace |
| `web_search` · `web_fetch` | `packages/web/tool-web` | **pluggable backends**: `web-search-deepseek` / `-exa` / `-perplexity`; `web-fetch-http` |
| `bash` · `bash_persistent` · `pwsh` | `packages/shell/tool-bash*`, `tool-pwsh` | **sandboxed shell with persistent sessions** |
| `skill` | `packages/skill/tool-skill` | progressive-disclosure skill reader |
| `run_code` | `packages/core/tools` (code-mode) | generated TS/Python SDK over the registry |
| MCP tools | `packages/mcp` | external MCP servers |
| subagent delegation | agent-presets / subagent packages | nested agents |
| core seam | `packages/core/tools` | `defineTool`, schema validation, guards (approval), timeouts, concurrency, presentation, ordered prompt assembly |

## 3. Gap analysis — ADD to LangConfig

| # | Tool | DSH basis | Why |
|---|---|---|---|
| 1 | **`bash` (sandboxed, optional persistent)** | tool-bash / tool-bash-persistent | **The biggest gap** — LangConfig has a terminal UI but no agent shell tool; agents can't run commands |
| 2 | **`read_image`** | tool-fs | multimodal input exists; add image reading (OCR via the multimodal model or tesseract) |
| 3 | **ripgrep-backed `glob`/`grep`** | tool-fs-search | speed + richer search (submodule: `rg` binary; pure-Python fallback) |
| 4 | **`run_code` + Python SDK** | code-mode | already planned as Phase C — the flagship |
| 5 | **`skill` read-on-demand tool** | tool-skill | unify progressive disclosure for normal agents (deep agents already have it) |
| 6 | **pluggable web-search backends** | web-search-* | Serper/Tavily already present; add exa/perplexity-style providers later |
| 7 | **`delete_file` / `rename_file` / `move_file` / `mkdir`** | beyond DSH | agents can't manage files beyond read/write/edit — a real usability gap |

## 4. Gap analysis — REVISE current LangConfig tools

| # | Tool(s) | Revision |
|---|---|---|
| 1 | `memory_store` / `memory_recall` stubs | remove the "unavailable" stubs or delegate to `SimpleMemory` directly (never fake-fail) |
| 2 | `web_search` | keep DDG no-key default; let the definition declare `requires_api_key` and prefer a configured provider when set |
| 3 | `glob` / `grep` | ripgrep backend (see ADD #3) |
| 4 | `vfs_*` vs disk `read_file`/`write_file` | decide the split; keep VFS only as a scoped memory FS or fold into the sandbox |
| 5 | `pg_*` family (11) | prune/consolidate the rarely-used catalog tools; keep read-only `pg_query` + guarded `pg_execute` |
| 6 | retrieval family (neo4j + doc_index + graphindex = 12) | document which stack is canonical; prune dead ones |
| 7 | `sqlite_load_csv` | seed it (defined but missing from the seed) |
| 8 | `python_execute` | superseded by `run_code` in Phase C; keep as the sandboxed fallback |

### Retrieval-stack canonical choice (audit finding #6 resolved)

Three overlapping retrieval families exist — their intended split:

| Family | Canonical role | Keep / prune |
|---|---|---|
| `graphindex_*` (Phase 9) | **Canonical RAG doc search/load** (PG with optional Neo4j hybrid) | Keep all 4 |
| `doc_index_*` | Document structure/page viewer (PageIndex) | Keep 3 (list/structure/pages) |
| `neo4j_*` | Graph Studio native graph ops (create/query docs in Neo4j) | Keep 5 — graph work, not RAG |

No consolidation needed once this split is documented; the model guidance
(Phase D) should say which to prefer for "search my documents" vs "graph".

## 5. Execution status

> **Batch 1 (quick wins) ✅** — seeded `sqlite_load_csv`; added `delete_file`/`rename_file`/`move_file`/`mkdir`; memory stubs route to SimpleMemory; retrieval split documented.
> **Batch 2 (bash) ✅** — sandboxed `bash` tool (bounded timeout, sandbox cwd, capped output).
> **Batch 3 (read_image + ripgrep) ✅** — `read_image` (tesseract OCR), `glob`/`grep` prefer ripgrep when installed (Python fallback).
> **Batch 4 (Code Mode) ✅** — `run_code` + generated Python SDK (Phase C, see tools-refactor.md).
> **Batch 5 (skill + search backends) ✅** — on-demand `skill` reader; `web_search` prefers a configured Tavily/Serper key (settings documents) over DDG.

## 6. Suggested next steps — seeded `sqlite_load_csv`; added
> `delete_file`/`rename_file`/`move_file`/`mkdir`; memory stubs now route to
> SimpleMemory (never fake-fail); retrieval-stack split documented above.


1. **Quick wins (no infra)**: seed `sqlite_load_csv`; make `memory_store`/`memory_recall` real delegates; add `delete_file`/`rename_file`/`move_file`/`mkdir` to `native_impl` + seed; document the retrieval-stack canonical choice.
2. **Shell (biggest capability win)**: sandboxed `bash` tool (reuse the analysis sandbox machinery) — worth doing before/with Phase C.
3. **read_image + ripgrep**: moderate effort, high model-usefulness.
4. **Phase C `run_code`** (already planned) absorbs `python_execute`.
5. **`skill` tool + search backends**: after Phase D (prompt assembly) lands.
