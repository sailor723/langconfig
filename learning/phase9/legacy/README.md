# Phase 9 / legacy scripts

These are the **original** Phase 9 scripts that use raw `llm.invoke([messages])`
calls directly. They are preserved and actively maintained as the **ground
truth** — they work because the architecture is simple.

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

## CLI Commands

All commands accept `--project-id N` (default: 1, from `.env` `GRAPHINDEX_DEFAULT_PROJECT_ID`).

| Command | What it does | LLM needed? |
|---|---|---|
| `--list` | Scan files on disk, cross-check against Neo4j index | No |
| `--show NAME` | Show a document's full enrichment (about, queries, tags) | No |
| `--query TEXT` | LLM scores all docs → returns best match | **Yes** |
| `--ingest FILE` | Hash → dedup (Neo4j) → copy → enrich → index | **Yes** |
| `--ingest-folder DIR` | Recursively ingest all supported files in a directory | **Yes** |
| `--rebuild-one NAME` | Rebuild enrichment for one doc and upsert | **Yes** |
| `--rebuild-project` | Rebuild enrichment for every doc in the project | **Yes** |
| `--remove NAME` | Remove a doc from both Neo4j and filesystem | No |

### Examples

```bash
# List all files with index status
uv run python -m learning.phase9.legacy.build_graphindex --list --project-id 1

# Ingest a single file
uv run python -m learning.phase9.legacy.build_graphindex --ingest report.pdf --project-id 1

# Ingest an entire folder (recursive)
uv run python -m learning.phase9.legacy.build_graphindex --ingest-folder /path/to/docs --project-id 1

# Query — find best-matching doc for a question
uv run python -m learning.phase9.legacy.build_graphindex --query "tesla strategy" --project-id 1

# Show a doc's full enrichment
uv run python -m learning.phase9.legacy.build_graphindex --show 01_tesla_q3_strategy.pdf --project-id 1

# Remove a doc
uv run python -m learning.phase9.legacy.build_graphindex --remove 01_tesla_q3_strategy.pdf --project-id 1

# Rebuild single
uv run python -m learning.phase9.legacy.build_graphindex --rebuild-one 01_tesla_q3_strategy.pdf --project-id 1

# Rebuild all
uv run python -m learning.phase9.legacy.build_graphindex --rebuild-project --project-id 1
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

# GraphIndex
GRAPHINDEX_MODEL=minimax-m3
GRAPHINDEX_DEFAULT_PROJECT_ID=1
```

## Data flow — Ingest

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
```

## Files

| File | What it is | Status |
|---|---|---|
| `build_graphindex.py` | Primary CLI — ingest, query, rebuild, remove, list. Exports helper functions (`make_llm`, `extract_document_enrichment`, etc.) reused by `phase9/graphindex_*.py`. | **Active** |
| `create_mock_data.py` | Creates 3 mock .md files for testing. | **Helper** |
| `route_semantic.py` | Original semantic router (`--query`, `--show-catalog`). | **Legacy CLI** |
| `dv_chat.py` | Original DV chat REPL (route + load + answer). | **Legacy CLI** — Phase 2 migration target |
| `eval_routing.py` | Original eval suite (14 hand-labeled queries, string vs LLM). Exports `EVAL_QUERIES`. | **Utility + legacy eval** |

## What's next — Phase 2

Wrap `dv_chat.py` as a DeepAgent using `create_deep_agent` and the same
5 graphindex tools. The legacy code is the reference implementation —
the DeepAgent version will use `astream_events` for token-level streaming.
