# Phase 9 / graphindex scripts

These are the **Phase 9** scripts organized by complexity level.
They are preserved and actively maintained as the **ground truth** —
they work because the architecture is simple.

## Layer overview

| # | File | What it does | Agent? | LLM |
|---|------|-------------|--------|-----|
| **1** | `build_index.py` | **Index builder** — hash → dedup → copy → enrich → Neo4j upsert. Pure Python + `llm.invoke()` for enrichment. | ❌ No | Minimax M3 |
| **2** | `route.py` | **Doc matcher** — `route_by_llm()` scores docs by metadata, returns ordered list. Also has `load_doc_context()` + `answer_from_docs()` for end-to-end. | ❌ No | Gemma4 + Minimax M3 |
| **3** | `python_agent.py` | **Legacy REPL** — manual conversation loop, routing per turn, session caching, cost tracking. | ❌ No | Gemma4 + Minimax M3 |
| **4** | `agent.py` | **DeepAgent chat** — `create_deep_agent` with 4 tools, MemoryMiddleware (AGENTS.md), token streaming, REPL. | ✅ **Yes** | Minimax M3 (agent) + Gemma4 (via tools) |

`tools.py` is the shared tool layer for **Layer 4**. It wraps raw functions from
Layers 1-2 into ``StructuredTool`` objects required by ``create_deep_agent``.

## Import chain

```
build_index.py   ── raw functions (load_document_content, Neo4jDocumentIndex)
    │
    ▼
route.py         ── raw functions (route_by_llm, load_doc_context, etc.)
    │
    ├── python_agent.py    ── calls raw functions directly
    │
    └── tools.py           ── wraps raw functions into StructuredTool for DeepAgent
            │                       + ContextVar helpers for backend requests
            │
            └── agent.py   ── uses tools.py + create_deep_agent
                                      │
                                      ▼
                              backend/api/chat/routes.py  ── imports agent.py directly
                              backend/api/knowledge/graphindex_chat.py  ── imports agent.py directly
                              backend/api/knowledge/rag.py  ── imports build_index.py directly
```

No wrappers, no middlemen. The backend imports the legacy modules directly.

## Architecture

```
.env (root)          → graphindex config (NEO4J_*, GRAPHINDEX_MODEL, etc.)
                          │
graphindex/build_index.py  ← CLI + shared helpers
    ├── make_llm()                — init_chat_model (Minimax M3)
    ├── extract_document_enrichment()  — LLM structured output
    ├── load_document_content()    — PDF / MD / TXT reader
    ├── load_graphindex_metadata() — placeholder (DocIndex client TBD)
    └── Neo4jDocumentIndex        — from backend/services
              │
              ├── neo4j_document_index.py  — Cypher CRUD
              └── backend/data/documents/project_{id}/  — file storage
```

### LLM split

Two separate LLMs, each with a different role:

| Step | Function | Default model | Provider | Role |
|---|---|---|---|---|
| **Doc matching** | `route_by_llm()` | `gemma4` | Ollama (local) | Fast routing — scores docs from metadata |
| **Synthesis** | `answer_from_docs()` | `minimax-m3` | MiniMax API | Full-power answer from loaded doc text |

Both configurable via `.env`. See [Configuration](#configuration) below.

## CLI Commands

### `build_index.py` — Index management

All commands accept `--project-id N`.

| Command | What it does | LLM needed? |
|---|---|---|
| `--list` | Scan files on disk, cross-check against Neo4j index | No |
| `--show NAME` | Show a document's full enrichment (about, queries, tags) | No |
| `--query TEXT` | (Legacy) LLM scores all docs → returns best match | **Yes** |
| `--ingest FILE` | Hash → dedup (Neo4j) → copy → enrich → index | **Yes** |
| `--ingest-folder DIR` | Recursively ingest all supported files in a directory | **Yes** |
| `--rebuild-one NAME` | Rebuild enrichment for one doc and upsert | **Yes** |
| `--rebuild-project` | Rebuild enrichment for every doc in the project | **Yes** |
| `--remove NAME` | Remove a doc from both Neo4j and filesystem | No |

### `route.py` — Routing + answer

| Flag | What it does |
|---|---|
| `--query TEXT` | Route: find matched docs (Gemma4 routing) |
| `--query-answer TEXT` | Full pipeline: route → load doc text → synthesize answer (Minimax M3) |
| `--show-catalog` | Pretty-print all docs + their supports/excludes |
| `--compare` | Run both string + LLM routing side-by-side |
| `--no-llm` | Skip LLM routing (only show catalog or string) |
| `--doc-scope NAME [NAME ...]` | Scope routing to specific docs (default: all) |
| `--project-id N` | Project ID (default: from `.env`) |

**Supported output formats:**
- `--query` returns **all matched docs** ordered by relevance, each with a confidence score and reason
- `--query-answer` returns a synthesized answer with document citations

### `dv_chat.py` — Interactive REPL

| Flag | What it does |
|---|---|
| `--route {llm,string}` | Routing method (default: llm) |
| `--project-id N` | Project ID (default: from `.env`) |

### Examples

```bash
# === build_index ===

# List all files with index status
uv run python -m learning.phase9.graphindex.build_index --list --project-id 1

# Ingest a single file
uv run python -m learning.phase9.graphindex.build_index --ingest report.pdf --project-id 1

# Ingest an entire folder (recursive)
uv run python -m learning.phase9.graphindex.build_index --ingest-folder /path/to/docs --project-id 1

# === route ===

# Route — find matched docs (Gemma4)
uv run python -m learning.phase9.graphindex.route --query "tesla strategy" --project-id 1

# Route + answer (Gemma4 routing → Minimax M3 synthesis)
uv run python -m learning.phase9.graphindex.route --query-answer "how many cars byd sold in europe 2024" --project-id 1

# Show catalog
uv run python -m learning.phase9.graphindex.route --show-catalog --project-id 1

# Scope to specific docs
uv run python -m learning.phase9.graphindex.route --query "ev market" --project-id 1 --doc-scope "01_tesla_q3_strategy.pdf" "03_byd_vs_tesla_europe.md"

# === python_agent ===

# Start interactive chat (Gemma4 routing + Minimax M3 per turn)
uv run python -m learning.phase9.graphindex.python_agent --project-id 1

# === agent ===

# Single query
uv run python -m learning.phase9.graphindex.agent --query "tesla europe market share" --project-id 1

# Interactive REPL (token streaming, conversation history)
uv run python -m learning.phase9.graphindex.agent --project-id 1
```

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

## Data flow — Ingest → Route → Answer

```
source file
    │
    ▼
sha256(content)  ──►  scan Neo4j for content_sha256  ──►  skip if exists
    │
    ▼
copy to backend/data/documents/project_{id}/{original_name}
    │
    ▼
extract_document_enrichment()  ──►  LLM structured output (about, queries, tags)
    │
    ▼
upsert Document node in Neo4j with content_sha256, enrichment, file_path
    │
    ▼
┌─ User query ───────────────────────────────────────────────────┐
│                                                                │
│  agent.py --query "how many cars byd sold in europe"      │
│    │                                                           │
│    ▼                                                           │
│  DeepAgent (create_deep_agent)                                 │
│    │                                                           │
│    ▼                                                           │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  tools.py (StructuredTool wrappers)                       │  │
│  │                                                           │  │
│  │  1. list_docs()  — list project catalog                   │  │
│  │  2. query_docs() — route: Gemma4 scores metadata           │  │
│  │  3. read_doc()   — load full text from disk               │  │
│  │  4. answer()     — synthesize: Minimax M3 reads + answers  │  │
│  └──────────────────────────────────────────────────────────┘  │
│    │                                                           │
│    ▼                                                           │
│  Final answer with citations + streaming                      │
└────────────────────────────────────────────────────────────────┘
```

## Backend integration

The legacy modules are imported **directly** by the LangConfig backend — no wrappers, no middlemen:

| Backend file | Imports |
|---|---|
| `backend/api/chat/routes.py` | `graphindex.agent.build_agent()` |
| `backend/api/knowledge/graphindex_chat.py` | `graphindex.agent.build_agent()` |
| `backend/api/knowledge/rag.py` | `graphindex.build_index.cmd_ingest()`, `extract_document_enrichment()` |

## Files

| File | What it is | Status |
|---|---|---|
| `build_index.py` | Primary CLI — ingest, query, rebuild, remove, list. Exports helper functions reused by `route.py` and `python_agent.py`. | **Active** |
| `route.py` | Semantic router + answer pipeline. Uses `gemma4` (Ollama) for routing and `minimax-m3` (API) for synthesis. Supports doc scope. | **Active** |
| `tools.py` | Tool wrappers for the DeepAgent: `list_docs`, `query_docs`, `read_doc`, `answer`. Also exports ContextVar helpers for backend request scoping. | **Active** |
| `agent.py` | DeepAgent-powered chat REPL (or single query). Token streaming, conversation history, `!reset`. The canonical chat agent used by the backend. | **Active** |
| `python_agent.py` | Legacy interactive chat REPL (route → load → answer per turn). Pricing tracker, multi-doc session, token cost logging. | **Legacy** |
| `create_mock_data.py` | Creates 3 mock .md files for testing. | **Helper** |
| `eval_routing.py` | Original eval suite (14 hand-labeled queries, string vs LLM). Exports `EVAL_QUERIES`. | **Utility + legacy eval** |
