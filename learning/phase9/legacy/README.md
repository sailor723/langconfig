# Phase 9 / legacy scripts

These are the **original** Phase 9 scripts that use raw `llm.invoke([messages])`
calls directly. They are preserved and actively maintained as the **ground
truth** — they work because the architecture is simple.

## Pipeline

```
build_graphindex.py     1. Build graph index (ingest, enrich, manage docs)
       │
       ▼
route_semantic.py       2. Route query → matched docs (LLM routing)
       │
       ▼
dv_chat.py              3. Chat REPL (route + load + synthesize)
```

Each stage builds on the previous one. `route_semantic.py` and `dv_chat.py`
import shared helpers from `build_graphindex.py`.

## Architecture

```
.env (root)          → graphindex config (NEO4J_*, GRAPHINDEX_MODEL, etc.)
                          │
legacy/build_graphindex.py  ← CLI + shared helpers
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

### `build_graphindex.py` — Index management

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

### `route_semantic.py` — Routing + answer

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
# === build_graphindex ===

# List all files with index status
uv run python -m learning.phase9.legacy.build_graphindex --list --project-id 1

# Ingest a single file
uv run python -m learning.phase9.legacy.build_graphindex --ingest report.pdf --project-id 1

# Ingest an entire folder (recursive)
uv run python -m learning.phase9.legacy.build_graphindex --ingest-folder /path/to/docs --project-id 1

# === route_semantic ===

# Route — find matched docs (Gemma4)
uv run python -m learning.phase9.legacy.route_semantic --query "tesla strategy" --project-id 1

# Route + answer (Gemma4 routing → Minimax M3 synthesis)
uv run python -m learning.phase9.legacy.route_semantic --query-answer "how many cars byd sold in europe 2024" --project-id 1

# Show catalog
uv run python -m learning.phase9.legacy.route_semantic --show-catalog --project-id 1

# Scope to specific docs
uv run python -m learning.phase9.legacy.route_semantic --query "ev market" --project-id 1 --doc-scope "01_tesla_q3_strategy.pdf" "03_byd_vs_tesla_europe.md"

# === dv_chat ===

# Start interactive chat (Gemma4 routing + Minimax M3 per turn)
uv run python -m learning.phase9.legacy.dv_chat --project-id 1
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
│  route_semantic.py --query "how many cars byd sold in europe"  │
│    │                                                           │
│    ▼                                                           │
│  fetch_catalog(idx, pid)          — all/scoped docs from Neo4j │
│    │                                                           │
│    ▼                                                           │
│  route_by_llm(query, rows, gemma4) — LLM scores doc metadata   │
│    │                                           (cheap, local)  │
│    ▼                                                           │
│  RouteDecision.documents            — ordered list of matches  │
│    │                                                           │
│    ▼ (if --query-answer)                                       │
│  load_doc_context(idx, pid, docs)   — read full text from disk │
│    │                                                           │
│    ▼                                                           │
│  answer_from_docs(query, ctx, minimax)  — synthesize answer    │
│                                               (expensive, API) │
│    ▼                                                           │
│  Final answer with citations                                   │
└────────────────────────────────────────────────────────────────┘
```

## Files

| File | What it is | Status |
|---|---|---|
| `build_graphindex.py` | Primary CLI — ingest, query, rebuild, remove, list. Exports helper functions reused by `route_semantic.py` and `dv_chat.py`. | **Active** |
| `route_semantic.py` | Semantic router + answer pipeline. Uses `gemma4` (Ollama) for routing and `minimax-m3` (API) for synthesis. Supports doc scope. | **Active** |
| `dv_chat.py` | Interactive chat REPL (route → load → answer per turn). Pricing tracker, multi-doc session, token cost logging. | **Active** |
| `create_mock_data.py` | Creates 3 mock .md files for testing. | **Helper** |
| `eval_routing.py` | Original eval suite (14 hand-labeled queries, string vs LLM). Exports `EVAL_QUERIES`. | **Utility + legacy eval** |

## What's next — Phase 2

Wrap the legacy chat flow (`dv_chat.py`) as a DeepAgent using `create_deep_agent`
and the same 5 graphindex tools. The legacy code is the reference implementation —
the DeepAgent version will use `astream_events` for token-level streaming.
