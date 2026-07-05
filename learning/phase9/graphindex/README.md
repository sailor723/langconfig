# Phase 9 / graphindex scripts

These are the **Phase 9** scripts organized by complexity level.
They are preserved and actively maintained as the **ground truth** —
they work because the architecture is simple.

## Layer overview

| # | File | What it does | Agent? | LLM |
|---|------|-------------|--------|-----|
| **1** | `index_build.py` | **Index builder + CLI** — hash → dedup → copy → enrich → Neo4j upsert. Also central hub for `load_doc_context`, `load_document_content`, `--qa`, `--purge`. | ❌ No | Minimax M3 |
| **2** | `route.py` | **Legacy doc matcher** — kept for `fetch_catalog()` used by the UI and `python_agent.py`. | ❌ No | Gemma4 + Minimax M3 |
| **3** | `python_agent.py` | **Legacy REPL** — manual conversation loop, routing per turn, session caching, cost tracking. | ❌ No | Gemma4 + Minimax M3 |
| **4** | `agent.py` | **DeepAgent chat** — `create_deep_agent` with 4 tools, MemoryMiddleware (AGENTS.md), token streaming, REPL. | ✅ **Yes** | Minimax M3 (agent) + Gemma4 (via tools) |

`tools.py` is the shared tool layer for **Layer 4**. It wraps raw functions from
Layer 1 into ``StructuredTool`` objects required by ``create_deep_agent``.

## Import chain

```
index_build.py   ── raw functions (load_document_content, load_doc_context,
    │                Neo4jDocumentIndex, find_best_document, cmd_ingest_folder)
    │
    ├── route.py              ── legacy fetch_catalog()
    │
    ├── tools.py              ── wraps index_build functions into StructuredTool
    │       │                       + ContextVar helpers for backend requests
    │       │
    │       └── agent.py      ── uses tools.py + create_deep_agent
    │
    ├── backend/tools/native_tools.py   ── imports index_build directly (graphindex_search, etc.)
    │
    └── backend/api/knowledge/rag.py    ── imports index_build.cmd_ingest_folder directly
```

No wrappers, no middlemen. The backend imports the modules directly.

## Architecture

```
.env (root)          → graphindex config (NEO4J_*, GRAPHINDEX_MODEL, etc.)
                          │
graphindex/index_build.py  ← CLI + shared helpers
    ├── make_llm()                — init_chat_model (Minimax M3)
    ├── extract_document_enrichment()  — LLM structured output
    ├── load_document_content(max_chars)  — PDF / MD / TXT reader with optional truncation
    ├── load_doc_context()         — concatenate matched docs for agent
    ├── find_best_document()       — Neo4j vector match with scope support
    ├── _file_path_for()           — cached Neo4j file-path lookup
    ├── cmd_ingest() / cmd_ingest_folder() / cmd_qa() / cmd_purge()
    └── Neo4jDocumentIndex        — from backend/services
              │
              ├── neo4j_document_index.py  — Cypher CRUD
              └── backend/data/documents/project_{id}/  — file storage
```

### LLM split

Two separate LLMs, each with a different role:

| Step | Function | Default model | Provider | Role |
|---|---|---|---|---|
| **Doc matching** | `find_best_document()` | `minimax-m3` | MiniMax API | Vector routing — scores docs from embeddings |
| **Synthesis** | `cmd_qa()` | `minimax-m3` | MiniMax API | Full-power answer from loaded doc text |

Both configurable via `.env`. See [Configuration](#configuration) below.

## CLI Commands

### `index_build.py` — Index management

All commands accept `--project-id N`.

| Command | What it does | LLM needed? |
|---|---|---|
| `--list` | Scan files on disk, cross-check against Neo4j index | No |
| `--show NAME` | Show a document's full enrichment (about, queries, tags) | No |
| `--ingest FILE` | Hash → dedup (Neo4j) → copy → enrich → index | **Yes** |
| `--ingest-folder DIR` | Recursively ingest all supported files in a directory | **Yes** |
| `--rebuild-one NAME` | Rebuild enrichment for one doc and upsert | **Yes** |
| `--rebuild-project` | Rebuild enrichment for every doc in the project | **Yes** |
| `--remove NAME` | Remove a doc from both Neo4j and filesystem | No |
| `--qa TEXT` | Route → load docs → synthesize answer (replaces old `route.py --query-answer`) | **Yes** |
| `--doc-scope NAME [NAME ...]` | Scope routing to specific docs (used with `--qa`) | No |
| `--purge` | Remove ALL docs for a project from Neo4j + PostgreSQL + Disk | No |

### `route.py` — Legacy routing (still provides `fetch_catalog`)

| Flag | What it does |
|---|---|
| `--query TEXT` | Route: find matched docs (Gemma4 routing) |
| `--query-answer TEXT` | Full pipeline: route → load doc text → synthesize answer (Minimax M3) |
| `--show-catalog` | Pretty-print all docs + their supports/excludes |
| `--project-id N` | Project ID (default: from `.env`) |

**Note:** `--qa`, `--doc-scope`, `--purge`, `--ingest`, `--ingest-folder` are now handled by `index_build.py`.

### `dv_chat.py` — Interactive REPL

| Flag | What it does |
|---|---|
| `--route {llm,string}` | Routing method (default: llm) |
| `--project-id N` | Project ID (default: from `.env`) |

### Examples

```bash
# === index_build ===

# List all files with index status
uv run python -m learning.phase9.graphindex.index_build --list --project-id 1

# Ingest a single file
uv run python -m learning.phase9.graphindex.index_build --ingest report.pdf --project-id 1

# Ingest an entire folder (recursive)
uv run python -m learning.phase9.graphindex.index_build --ingest-folder /path/to/docs --project-id 1

# QA — route + load + synthesize answer
uv run python index_build.py --qa "Blade Battery specs" --project-id 2 --doc-scope blade-battery-analysis.md

# Purge entire project
uv run python index_build.py --purge --project-id 2
```

## Data flow — 3 Workflows

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        LANG CONFIG — 3 Workflows                            │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  ╔══════════════════════════════════════════════════════════════════════╗  │
│  ║  1. CLI  — index_build.py (terminal, no backend needed)             ║  │
│  ╚══════════════════════════════════════════════════════════════════════╝  │
│                                                                            │
│   ┌──────────────────────────┐                                            
│   │  index_build.py --ingest  │── sha256 ──► Neo4j dedup check             
│   │  --ingest-folder         │── copy   ──► Disk (backend/data/)           
│   │  --purge / --list        │── INSERT ──► PostgreSQL (context_doc)       
│   │  --qa / --doc-scope      │── enrich ──► Neo4j (LLM enrichment)         
│   └──────────────────────────┘                                            
│         ▲                               ┌──────────┐                       
│         │   consistent naming           │ index    │     ┌──────────┐       
│         │   across PG + Neo4j + Disk    │ build.py │     │ route.py │       
│         └───────────────────────────────│ = CLI    │     │= legacy  │       
│                                         └──────────┘     └──────────┘       
│                                                                            │
│  ╔══════════════════════════════════════════════════════════════════════╗  │
│  ║  2. CHAT  — User talks to AI about documents                        ║  │
│  ║     (Frontend → API → DeepAgent → Tools → LLM → Answer)             ║  │
│  ╚══════════════════════════════════════════════════════════════════════╝  │
│                                                                            │
│   User types message                                                       
│      ↓                                                                     
│   POST /api/chat/message/stream                                             
│      ↓                                                                     
│   create_deep_agent() — binds GraphIndex tools                             
│      ↓              ┌─────────────────────────────────────┐                
│   Agent decides ──► │ graphindex_search(query, pid)       │                
│   which tool to     │  → choose_best_document_match (Neo4j)               
│   call              │  → returns best match doc names    │                
│                     ├─────────────────────────────────────┤                
│                     │ graphindex_load(name, pid, scope)   │                
│                     │  → load_document_content (disk)     │                
│                     │  → scope check enforced            │                
│                     ├─────────────────────────────────────┤                
│                     │ graphindex_list_docs(pid, scope)    │                
│                     │  → list_documents (Neo4j)           │                
│                     └─────────────────────────────────────┘                
│      ↓                                                                     
│   LLM assembles answer from tool results                                   
│      ↓                                                                     
│   SSE stream back to frontend                                              
│                                                                            │
│  ╔══════════════════════════════════════════════════════════════════════╗  │
│  ║  3. KNOWLEDGE  — Upload & manage docs in Knowledge Panel            ║  │
│  ║     (Frontend → API → Same CLI code path → All stores)              ║  │
│  ╚══════════════════════════════════════════════════════════════════════╝  │
│                                                                            │
│   User uploads file / folder in UI                                          
│      ↓                                                                     
│   POST /api/rag/ingest-folder  (or /upload /upload-bulk)                    
│      ↓                                                                     
│   ┌─► NEW PATH (fixed):                                                    
│   │   calls index_build.cmd_ingest_folder()  ←── SAME CODE AS CLI          
│   │      ├── sha256 → Neo4j dedup                                          
│   │      ├── copy → Disk (original name)                                   
│   │      ├── INSERT → PostgreSQL (same name)                               
│   │      └── LLM enrich → Neo4j Document node (same name)                 
│   │    Result: PG=4 docs, Neo4j=4 docs, Disk=4 files (all same name)       
│   │                                                                        
│   └─► OLD broken path (removed):                                           
│       rag.py wrote PG with original name (blade.md)                        
│       _queue_graphindex_ingest wrote Neo4j with hash name (a3c8_blade.md)  
│       ──→ PG=9 + Neo4j=4 = DUPLICATE IN UI                                
│                                                                            │
│   FE refreshes → GET /api/rag/documents → tree view shows 4 docs ✅         
│                                                                            │
│  ═════════════════════════════════════════════════════════════════════════  │
│                     STORAGE LAYER (shared)                                 │
│                                                                            │
│   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────────┐  │
│   │   PostgreSQL      │   │   Neo4j           │   │   Disk                │
│   │   context_docs    │   │   Document nodes  │   │   backend/data/       │
│   ├──────────────────┤   ├──────────────────┤   ├──────────────────────┤  │
│   │   id              │   │   name           │   │   project_2/           │
│   │   project_id      │   │   content_hash   │   │     byd/               │
│   │   filename        │   │   file_path      │   │       blade.md         │
│   │   indexing_status │   │   industry/player│   │     tesla/             │
│   │   industry/player │   │   embedding      │   │       ads.md           │
│   │   content_hash    │   │   relationships  │   │       specs.md         │
│   └──────────────────┘   └──────────────────┘   └──────────────────────┘  │
│                                                                            │
│   Core principle: Every write (CLI / API upload) goes through              │
│   index_build.cmd_ingest_folder → same naming → zero duplicates.           │
│                                                                            │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Backend integration

The legacy modules are imported **directly** by the LangConfig backend — no wrappers, no middlemen:

| Backend file | Imports |
|---|---|
| `backend/api/chat/routes.py` | `graphindex.agent.build_agent()` |
| `backend/api/knowledge/graphindex_chat.py` | `graphindex.agent.build_agent()` |
| `backend/api/knowledge/rag.py` | `graphindex.index_build.cmd_ingest_folder()` (ingest-folder endpoint) |
| `backend/tools/native_tools.py` | `graphindex.index_build.*` (graphindex_search, graphindex_load, etc.) |

## Files

| File | What it is | Status |
|---|---|---|
| `index_build.py` | Primary CLI + shared library — ingest, query, rebuild, remove, list, QA, purge. Exports `load_doc_context`, `load_document_content`, `find_best_document`, `cmd_ingest_folder` etc. | **Active** |
| `route.py` | Legacy routing. Only `fetch_catalog()` still used by UI and `tools.py`. | **Legacy** |
| `tools.py` | Tool wrappers for the DeepAgent: `list_docs`, `query_docs`, `read_doc`, `answer`. Also exports ContextVar helpers for backend request scoping. | **Active** |
| `agent.py` | DeepAgent-powered chat REPL (or single query). Token streaming, conversation history, `!reset`. The canonical chat agent used by the backend. | **Active** |
| `python_agent.py` | Legacy interactive chat REPL (route → load → answer per turn). Pricing tracker, multi-doc session, token cost logging. | **Legacy** |
| `create_mock_data.py` | Creates 3 mock .md files for testing. | **Helper** |
| `eval_routing.py` | Original eval suite (14 hand-labeled queries, string vs LLM). Exports `EVAL_QUERIES`. | **Utility + legacy eval** |

## Configuration (`.env`)

```env
# MiniMax
MINIMAX_API_KEY=sk-...
MINIMAX_BASE_URL=https://api.minimax.chat/v1

# Neo4j
NEO4J_URL=http://localhost:7474
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# GraphIndex — general
GRAPHINDEX_MODEL=minimax-m3
GRAPHINDEX_DEFAULT_PROJECT_ID=1

# GraphIndex — routing (doc matching via LLM)
GRAPHINDEX_ROUTING_MODEL=gemma4
GRAPHINDEX_ROUTING_MAX_TOKENS=2048

# GraphIndex — answer (synthesis)
GRAPHINDEX_ANSWER_MAX_TOKENS=8192

# GraphIndex — pricing (cost per 1M tokens, USD)
GRAPHINDEX_PRICING_STANDARD_INPUT=0.60
GRAPHINDEX_PRICING_STANDARD_OUTPUT=2.40
GRAPHINDEX_PRICING_LONG_CTX_INPUT=1.20
GRAPHINDEX_PRICING_LONG_CTX_OUTPUT=4.80
GRAPHINDEX_TIER_THRESHOLD=512000

# GraphIndex — safety caps
GRAPHINDEX_PRIMARY_MAX_CHARS=10000000
GRAPHINDEX_SUPPORTING_MAX_CHARS=10000000
```
