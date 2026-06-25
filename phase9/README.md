# Phase 9 — Document Chat (DV Chat) over PageIndex + Neo4j

> Goal: a chat experience that picks **the right document** for a user query, **loads the right pages**, and answers using a single document as a KV source — without chunking or embeddings.
>
> **Base document** — this README captures the **current** knowledge/chat code in the repo so the next 3 steps (1) sample DV chat, (2) doc-index matching, (3) eval & plan can build on a shared picture.

---

## 🎯 Three Steps (planned)

| # | Step | Output |
|---|---|---|
| 1 | Develop a sample **doc-viewer chat** (DV chat) | Runnable script that uploads a PDF, lets the user ask questions, returns LLM answer grounded in the PDF |
| 2 | Build **doc index → correct doc → load full content** flow | Reuse `DocIndexClient` (TOC) + `Neo4jDocumentIndex` (routing) to auto-select the matching document, then KV-load its full text |
| 3 | **Evaluate** what in the current code (Step 1+2 base) should be promoted into the long-lived platform (SDK method, FastAPI route, UI panel) | A short diff proposal + ranked improvements |

This README is the **base for all three steps**. Read this first before editing code.

---

## 🏗️ Current Architecture (Base Map)

The "doc chat" feature is already partially implemented in the repo. The pieces that matter for Phase 9:

```
┌──────────────────────────────────────────────────────────────────────────┐
│   Frontend (src/features/knowledge/...)                                 │
│   • Upload PDF/MD/TXT → POST /api/rag/documents                          │
│   • Search bar   → POST /api/rag/search  (mode=vector|graphindex)        │
│   • "Ask AI"     → POST /api/rag/graphindex/answer                       │
└──────────┬───────────────────────────────────────────────────────────────┘
           │ FastAPI  (backend/api/knowledge/rag.py)
           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Routing layer — pick the target document                               │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  1. Try Neo4j first    (services/neo4j_document_index.py)       │    │
│  │     • :Document {project_id, name} nodes                         │    │
│  │     • Metadata scoring: name 3.0, supported_queries 3.0,        │    │
│  │       about 2.5, description/preview/tags 2.0, search 1.5,      │    │
│  │       out_of_scope -3.0                                         │    │
│  │  2. Fallback: in-memory scan of DocIndexClient._meta.json        │    │
│  │     • _score_graphindex_document() — duplicate scoring logic    │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  Loader — load full content of the chosen document              │    │
│  │  services/doc_index_service.py  (DocIndexClient.get_full_content)│   │
│  │     • PDF: PyMuPDF get_toc() + page-by-page text                │    │
│  │     • MD/TXT: heading scan + per-line pages                      │    │
│  │     • L1 _meta.json  →  L2 {doc_id}.json  →  L3 page content    │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  Answer — KV-style LLM call                                     │    │
│  │  POST /api/rag/graphindex/answer                                │    │
│  │     • System: "treat document as KV, no outside knowledge"      │    │
│  │     • User:   key + description + query + full document value   │    │
│  │     • Model:  DB default + DB fallback chain                    │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└──────────┬───────────────────────────────────────────────────────────────┘
           │
           ▼
   ┌──────────────┐    ┌────────────────┐
   │ PostgreSQL   │    │ Neo4j (HTTP)   │     File system:
   │ ContextDoc   │    │ :Document KV   │     outputs/doc_index/
   │ Project      │    │ routing only   │     _meta.json + {doc_id}.json
   └──────────────┘    └────────────────┘
```

---

## 📂 File Inventory (the moving parts)

### Core services (read these first)

| File | Role | What it owns |
|---|---|---|
| [`backend/services/doc_index_service.py`](../../backend/services/doc_index_service.py) | **PageIndex / GraphIndex** — vectorless document index | `DocIndexClient`: `index()`, `list_all()`, `get_document_structure()`, `get_page_content()`, `get_full_content()` |
| [`backend/services/neo4j_document_index.py`](../../backend/services/neo4j_document_index.py) | **Neo4j** document routing index | `Neo4jDocumentIndex`: `upsert_document()`, `find_best_document()`, scoring |
| [`backend/api/knowledge/rag.py`](../../backend/api/knowledge/rag.py) | **FastAPI** RAG/GraphIndex routes | `search` (vector\|graphindex), `graphindex/answer`, page fetch, structure fetch |
| [`backend/services/context_document_indexer.py`](../../backend/services/context_document_indexer.py) | **Vector** RAG (chunks + embeddings) | `search_context_documents()` (used in vector mode) |

### Supporting

| File | Role |
|---|---|
| [`backend/api/chat/routes.py`](../../backend/api/chat/routes.py) | DeepAgent chat sessions (dual storage: PG JSON + LangGraph checkpointer) — not the doc-chat path, but shares the agent factory |
| [`backend/chat_pdf_simple.py`](../../backend/chat_pdf_simple.py) | Standalone PDF chat using DeepSeek — the **simplest possible** doc chat, good reference for Step 1 |
| [`backend/scripts/test_graphindex_pdf_chat_flow.py`](../../backend/scripts/test_graphindex_pdf_chat_flow.py) | End-to-end smoke test: sync → search → load → format |
| [`backend/scripts/test_graphindex_native_tools.py`](../../backend/scripts/test_graphindex_native_tools.py) | Same flow but exposed as native DeepAgent tools |
| [`backend/scripts/test_nike_query.py`](../../backend/scripts/test_nike_query.py) | Concrete query → matching Nike 10-K example |

### Data models

| File | Role |
|---|---|
| [`backend/models/core.py`](../../backend/models/core.py) | `ContextDocument`, `Project`, `IndexingStatus` — PG side |
| Neo4j `(:Document {project_id, name, ...})` | KV side (one node per doc, no edges) |

### Tests

| File | Covers |
|---|---|
| `backend/tests/test_neo4j_document_index.py` | Neo4j upsert/list/score |
| `backend/tests/test_neo4j_document_enrichment.py` | Enrichment field scoring |
| `backend/tests/test_neo4j_autosync.py` | Auto-sync on doc upload |
| `backend/tests/test_graphindex_search_via_neo4j.py` | Search hits Neo4j path |
| `backend/scripts/test_neo4j_document_kv_roundtrip.py` | KV roundtrip |

---

## 🔁 The Full "Doc Chat" Flow Today

1. **Upload** (`POST /api/rag/documents`)
   - File → `ContextDocument` row
   - Background `index_document_background()` runs:
     - **Vector path**: `context_document_indexer` → chunks + pgvector embeddings
     - **GraphIndex path**: `DocIndexClient.index(file_path)` → `_meta.json` + `{doc_id}.json`
     - **`_try_sync_context_document_to_neo4j()`** → upsert `:Document` node

2. **Search** (`POST /api/rag/search` with `search_mode="graphindex"`)
   ```
   request.query
     └─► _try_graphindex_search_via_neo4j()
           └─► Neo4j find_best_document(project_id, query)
                 └─► choose_best_document_match() (metadata scoring)
           └─► returns top-1 GraphIndexDocItem (structure preview)
     fallback: in-memory scan of DocIndexClient.list_all()
   ```

3. **Answer** (`POST /api/rag/graphindex/answer`)
   ```
   request.query + project_id [+ context_doc_id]
     └─► _resolve_graphindex_target_document()
           1. explicit context_doc_id?  → use it
           2. Neo4j find_best_document() → use it
           3. fallback: in-memory score over project docs
     └─► _load_full_content_for_kv()
           └─► DocIndexClient.get_full_content(doc_id)  (L2+L3)
     └─► LLM.invoke([System, Human])  with KV-style prompt
   ```

4. **Drill-down** (`GET /api/rag/documents/{id}/graphindex/pages/{pages}`)
   - `pages` format: `5-7`, `3,8`, `12`
   - Returns per-page content for the UI to highlight

---

## 🧠 What PageIndex Gives Us (vs. Vector RAG)

| Concern | Vector RAG | PageIndex / GraphIndex |
|---|---|---|
| Indexing | Chunk + embed (slow, GPU) | Extract TOC + page text (CPU, fast) |
| Retrieval | Cosine similarity on embeddings | **LLM-guided** tree navigation (no vectors) |
| Cost at query | Embedding model call | None — metadata + content only |
| Multi-doc dispatch | Single similarity pool | **Metadata-first** scoring (this repo's design) |
| Citation | By chunk id | **By page** (`source_location`) |
| Chinese / mixed scripts | Works but noisy | Works (scoring includes `[\u4e00-\u9fff]`) |
| Large docs | Chunked → context window limit | Whole document KV-loaded into prompt |

The repo ships **both** modes and lets `search_mode` switch between them.

---

## 🧪 How to Run the Current Code End-to-End

```bash
# 1. Start services
docker-compose up -d postgres neo4j       # or just postgres if no neo4j
cd backend && alembic upgrade head
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8765

# 2. Upload a doc via the Knowledge UI, or via curl:
curl -X POST http://127.0.0.1:8765/api/rag/documents \
  -F "file=@./data/documents/project_1/2561d459_C2M1.pdf" \
  -F "project_id=1"

# 3. Search (graphindex mode)
curl -X POST http://127.0.0.1:8765/api/rag/search \
  -H "Content-Type: application/json" \
  -d '{"query":"which page talks about strategy","project_id":1,"search_mode":"graphindex","top_k":3}'

# 4. Answer (KV style)
curl -X POST http://127.0.0.1:8765/api/rag/graphindex/answer \
  -H "Content-Type: application/json" \
  -d '{"query":"summarize the strategy section","project_id":1}'

# 5. Smoke test
cd backend && python scripts/test_graphindex_pdf_chat_flow.py
```

---

## 🧩 The Scoring Function (and its duplicate)

Two near-identical scoring functions exist. Phase 9 should reconcile them.

### A. Neo4j side — [`services/neo4j_document_index.py`](../../backend/services/neo4j_document_index.py)

```python
def choose_best_document_match(query, documents):
    # weights: name 3.0, supported_queries 3.0, about 2.5,
    #          description/preview/tags 2.0, search_terms 1.5,
    #          out_of_scope -3.0
    # also has Chinese-token handling via re.split(r'[^a-z0-9\u4e00-\u9fff]+', ...)
```

### B. In-memory side — [`api/knowledge/rag.py`](../../backend/api/knowledge/rag.py)

```python
def _score_graphindex_document(query, meta, context_doc):
    # weights: filename 3.0, tags 2.5, description/preview 2.0, search_terms 1.0
    # NO out_of_scope penalty, NO about/supported_queries fields
```

**Differences**:
- Neo4j version has `out_of_scope` (negative) and `supported_queries` / `what_this_document_is_about` fields
- In-memory version is simpler and ignores the enrichment fields
- Tokenization is similar but the Neo4j version handles Chinese more carefully

→ Phase 9 Step 2 (build doc-index matching) should make these call **one** shared function.

---

## ⚠️ Known Gaps (gaps to fill in Steps 1–3)

| Gap | Where | What we want |
|---|---|---|
| **No standalone DV chat script** | — | `phase9/dv_chat.py`: upload PDF → chat loop, no UI, no FastAPI |
| **Scoring duplicated in 2 places** | neo4j vs. rag.py | One function, one weight table |
| **Neo4j is best-effort** (silent `except Exception`) | `_try_*_via_neo4j` everywhere | Explicit fallback path, observability |
| **`_load_full_content_for_kv` returns raw text** | rag.py | Needs a token-budget guard before stuffing into LLM |
| **No citation in KV answer** | `graphindex/answer` | Should echo the page range actually used |
| **No multi-doc answer mode** | — | Optional: answer from N top docs, not just 1 |
| **No native tool wrapper** for DeepAgent | `native_tools.py` has it partially; should be one canonical `pdf_chat_assistant` tool | Phase 5 already has a `pdf-chat-assistant` skill — should be the single source |
| **Inconsistent env names** | `DOC_INDEX_BASE`, `NEO4J_URL` etc. | A single `config.py` section |
| **No `--serve` variant for the DV chat** | `chat_pdf_simple.py` has one | Should reuse for Phase 9 |

---

## 📁 Where Phase 9 Code Will Live

```
phase9/
├── README.md                            ← this file (base)
├── dv_chat.py                           ← Step 1: simple KV doc chat (pypdf + langchain init_chat_model)
├── doc_index_match.py                   ← Step 2: routing helper (planned)
└── eval.md                              ← Step 3: findings + promotion plan (planned)
```

Everything in this folder is **scripts/notebooks** — no FastAPI changes yet. Promotion into the platform is Step 3's output.

## How to Run Step 1

```bash
cd <repo>

# Auto-detect first PDF in backend/data/documents/
# Avoids auto-running on the "scanned" PDF — will warn if text is empty
backend/.venv/bin/python phase9/dv_chat.py

# Recommended first doc — Nike 10-K (real text, 107 pages)
backend/.venv/bin/python phase9/dv_chat.py backend/data/documents/project_1/31042021_nke-10k-2023.pdf

# Strategic deck (English)
backend/.venv/bin/python phase9/dv_chat.py backend/data/documents/project_1/66bbde2a_Departmental\ Survey\ for\ Biz\ Strategy.pdf

# Chinese document
backend/.venv/bin/python phase9/dv_chat.py backend/data/documents/project_1/5cc12ddf_6\ 人物库\ 2.pdf

```

---

## 🎯 Step 1 — Sample DV chat (DONE)

- [x] Single-file script: `python phase9/dv_chat.py /path/to/file.pdf`
- [x] Supports PDF (PyMuPDF/fitz), MD, TXT
- [x] **No truncation, no chunking, no embeddings** — full doc text loaded into LLM context
- [x] Uses `init_chat_model` from langchain (project standard, not raw OpenAI client)
- [x] Hardcoded `DEFAULT_DOC` so `python phase9/dv_chat.py` works from any cwd
- [x] `__file__`-free `.env` resolution — works as script AND in REPL/import
- [x] Interactive REPL: `you:` → `assistant:` grounded in the document
- [x] LLM instructed to cite page numbers, e.g. `(page 3)`
- [x] **Conversation meta per turn**: doc name, in/out tokens, cache_read, latency, cost
- [x] **Session summary** on `/stats` and `/quit`: cumulative tokens, time, throughput (tok/s), total cost
- [x] MiniMax M3 pricing: $0.60/M in + $2.40/M out (standard ≤512K), $1.20/M in + $4.80/M out (long-ctx >512K)
- [x] No FastAPI, no Neo4j, no DB — pure local file + langchain

## 🎯 Step 2 — Multi-doc multi-round chat (DONE)

- [x] Reuses base's `choose_best_document_match` (no live Neo4j needed)
- [x] 6 seed docs (3 EN + 3 ZH) covering finance, philosophy, strategy, agreement, course, sports
- [x] Auto-routes each query to the most relevant doc (EN + ZH verified)
- [x] Manual `/doc <name>` override for cases where routing picks wrong doc
- [x] **Per-doc session isolation**: switching docs suspends old history, resumes new
- [x] Cache benefit preserved: same doc across multiple turns → cache hit on system+doc prefix
- [x] Negative cases handled: unrelated query → "no match, use /doc"
- [x] 16/16 routing tests pass (11 auto + 3 manual + 2 negative)

## 🎯 Step 2.5 — Complete GraphIndex builder (DONE)

The production sync (`_try_sync_context_document_to_neo4j` in `api/knowledge/rag.py:444`)
passes `enrichment=None` — so 14/18 production nodes have empty `what_this_document_is_about`
and `supported_queries`. The enrichment generator existed as a dead nested function inside
`scripts/test_neo4j_document_kv_roundtrip.py` but was never called from production.

`phase9/build_graphindex.py` lifts that generator to a module-level function and exposes
4 commands that operate on the live Neo4j:

| Command | What |
|---|---|
| `--show <name>` | Dump one node's full state (enrichment + raw) |
| `--rebuild-one <name>` | Run LLM enrichment on one doc, upsert to Neo4j |
| `--rebuild-project` | Run enrichment on every doc in project 1 |
| `--query <text>` | Route a query using current enrichment state |

Verified end-to-end against localhost:7474:

- `--show "nke-10k-2023.pdf"` — 217 chars about, 8 supported queries, 7 out_of_scope
- `--rebuild-one "6 人物库.pdf"` — generates 367 chars about + 6 supported + 8 out_of_scope;
  `out_of_scope` **explicitly excludes** `cs230-*.pdf`, `lecture-notes-*.pdf`, `nke-10k-2023.pdf`,
  `Deep Learning in Healthcare.pdf`
- `--query "philosopher profiles"` → routes to `6 人物库.pdf`
- `--query "Nike revenue"` → routes to `nke-10k-2023.pdf`

Robustness: structured output sometimes wraps answer in `<think>...</think>` (MiniMax M3
quirk). The script auto-falls-back to a plain text call + manual JSON extraction.

## 🎯 Step 3 — Eval (TODO)

Run a 5-10 query suite against the seed docs, measure:
- top-1 routing accuracy
- answer page-citation accuracy
- per-doc cache hit rate
- total latency / cost

Decide which of: SDK method, FastAPI route, UI panel, native tool, skill — to promote the pieces into.

---

## 🔗 Related Reading

- VectifyAI / GraphIndex (inspiration): <https://github.com/VectifyAI/GraphIndex>
- Phase 3 README on memory systems (the `SimpleMemory` two-layer pattern): `learning/phase3/README.md`
- Phase 5 README on skills (the `pdf-chat-assistant` skill): `learning/phase5/README.md`
- Phase 6 README on workflows (the KV-style `graphindex/answer` pattern): `learning/phase6/README.md`
- Phase 8 README (DeepAgent Studio — same author style, useful template): `phase8/README.md`
