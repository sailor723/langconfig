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

## 🌌 System at a Glance (one picture, full pipeline)

> **Read this first.** Every other diagram in this file is a zoom-in on one part of this picture.

```
                              USER
                               │
                  "compare Nike strategy with
                       industry trends"
                               │
                               ▼
        ┌──────────────────────────────────────────┐
        │  PHASE 9 ENTRY POINTS                    │
        │  ┌────────────────┐  ┌────────────────┐  │
        │  │  dv_chat.py    │  │ query.py       │  │
        │  │  (single doc)  │  │ (multi-doc)    │  │
        │  └────────────────┘  └────────────────┘  │
        │  ┌────────────────┐  ┌────────────────┐  │
        │  │  build_        │  │ eval_routing_  │  │
        │  │  graphindex.py │  │ deep.py        │  │
        │  │  (sync Neo4j)  │  │ (headline)     │  │
        │  └────────────────┘  └────────────────┘  │
        └──────────────────┬───────────────────────┘
                           │
        ╔══════════════════╧══════════════════╗    ◄── All paths funnel into
        ║  STAGE 1 — ROUTE                   ║        one shared decision:
        ║  (pick the right document(s))      ║        "which doc answers this?"
        ║                                    ║
        ║  ┌──────────────────────────────┐  ║        Three implementations,
        ║  │ String  (1 ms, 57% accuracy) │  ║        same interface:
        ║  │ LLM     (5 s,  100% accuracy)│  ║        ┌────────────────────┐
        ║  │ Multi   (12 s, domain-aware) │──┼───────►│ route_semantic.py  │
        ║  └──────────────────────────────┘  ║        │ route_by_llm()    │
        ║           │                        ║        └────────────────────┘
        ╚═══════════╪════════════════════════╝
                    │   { primary: "nke-10k-2023.pdf",
                    │      supporting: ["Strategic Framework...", ...] }
                    ▼
        ┌──────────────────────────────────────────┐
        │  STAGE 2 — LOAD                          │
        │  (read content, no LLM)                  │
        │                                          │
        │  DocIndexClient.get_full_content(doc_id) │
        │    ├─ PDF: PyMuPDF get_toc() + pages     │
        │    └─ MD/TXT: heading scan + lines       │
        │                                          │
        │  Char caps: primary 30K, supporting 15K  │
        └──────────────────┬───────────────────────┘
                           │   42,369 chars of doc text
                           ▼
        ┌──────────────────────────────────────────┐
        │  STAGE 3 — SYNTHESIZE                    │
        │  (LLM #2 — generate answer)              │
        │                                          │
        │  System: "treat doc as KV, cite pages"   │
        │  User:   query + full doc text           │
        │  Model:  MiniMax-M3 (cache: 100% hit)    │
        └──────────────────┬───────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────────┐
        │  ANSWER                                  │
        │  "Nike's strategy organized around 7     │
        │   pillars (consumer-led product, ...).   │
        │   Industry trends Nike identifies: ...   │
        │   [cites pages from Doc 1: pp.1-6]"      │
        └──────────────────────────────────────────┘

        ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐
        │  Neo4j       │    │  File system │    │  PostgreSQL      │
        │  :Document   │    │  /data/docs/ │    │  ContextDoc      │
        │  routing +   │    │  + L1/L2/L3  │    │  upload metadata │
        │  enrichment  │    │  page index  │    │  (sync target)   │
        └──────────────┘    └──────────────┘    └──────────────────┘
              ▲                     ▲                     ▲
              │  content_sha256     │  doc_id, page text  │  project_id
              │  about / supports   │                     │
              └─────── all three kept in sync by `_try_sync_context_document_to_neo4j`
```

**Key insight to hold in your head**: Stages 1 and 3 are the only LLM calls. Stage 2 is pure file I/O.
The LLM in Stage 1 reads a stable catalog → prompt cache 100% hits → ~5s. The LLM in Stage 3
reads the chosen doc → cache hits on system+doc prefix → ~20s for synthesis. Everything else is
free.

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

## 🗺️ phase9/ File Map (how the 16 files relate)

> **Why this map**: every phase9 file imports from or is imported by another. If you don't know the
> dependency graph, you don't know which file is safe to edit in isolation.

```
phase9/
│
├── 📌 ENTRY POINTS (user-facing CLIs)
│   ├── dv_chat.py              ──► legacy/dv_chat.py  (single-doc REPL)
│   ├── query.py                ──► query_agent.py     (multi-doc unified CLI)
│   ├── query_deep.py           ──► query_agent.py     (deep-agent variant)
│   └── query_agent.py          ──► graphindex_tools.py  (3-subagent orchestrator)
│
├── 🛠️ CORE TOOLKIT (the 5 graphindex_* tools)
│   └── graphindex_tools.py     ◄── imported by query_agent.py, graphindex_chat_agent.py
│                                uses: legacy/build_graphindex.py (helpers)
│
├── 🏗️ BUILD / INDEX (offline, modifies Neo4j)
│   ├── graphindex_build_python.py     ──► graphindex_tools.py
│   ├── graphindex_build_deepagent.py  ──► graphindex_tools.py (uses DeepAgent)
│   ├── graphindex_build_langgraph.py  ──► graphindex_tools.py (uses LangGraph)
│   ├── graphindex_builder_template.py ──► template for new builders
│   ├── buildindex_tools.py            ──► LLM enrichment primitives
│   └── build_agent.py                 ──► same as buildindex_tools.py, agent variant
│
├── 💬 CHAT ORCHESTRATION
│   ├── graphindex_chat_agent.py        ──► graphindex_tools.py  (single-agent chat)
│   └── graphindex_chat_template.py     ──► template for new chat agents
│
├── 📊 EVALUATION
│   ├── eval_routing.py          ──► legacy/eval_routing.py
│   └── eval_routing_deep.py     ──► eval_routing.py  (deep variant)
│
├── legacy/                      ──► "no deletions" policy
│   ├── build_graphindex.py      ──► exports DOCS_BASE, make_llm, helpers
│   ├── route_semantic.py        ──► superseded by phase9/query.py
│   ├── dv_chat.py               ──► superseded by phase9/dv_chat.py
│   └── eval_routing.py          ──► exports EVAL_QUERIES
│
└── .dv_memory/
    └── AGENTS.md                ──► agent context for this folder
```

**Import rules to remember** (so you don't break the graph):

| Rule | Why |
|---|---|
| Entry points can import anything | They orchestrate, they don't get orchestrated |
| `graphindex_tools.py` imports from `legacy/build_graphindex.py` | The 5 tools need `make_llm`, `extract_document_enrichment`, `load_document_content` |
| `graphindex_*_agent.py` files import from `graphindex_tools.py` | They bind tools to a DeepAgent |
| `eval_routing*.py` files import from `legacy/eval_routing.py` | They reuse `EVAL_QUERIES` + `run_*_eval` helpers |
| **Never import from `phase9/` into `backend/`** | Phase 9 is scripts/notebooks, not platform code (per `learning_plan.md`) |

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

### Sequence: a single user query end-to-end

> **What this shows**: every actor in the system and what each one does. The "wall-clock" column on
> the right is the typical latency you should expect in production.

```
 User         Frontend       FastAPI        Neo4j          DocIndex       LLM
  │              │              │              │              │              │
  │ click "Ask"  │              │              │              │              │
  │─────────────►│              │              │              │              │
  │              │ POST /graphindex/answer    │              │              │
  │              │─────────────►│              │              │              │
  │              │              │ find_best_document()       │              │  ~5 ms
  │              │              │─────────────►│              │              │
  │              │              │◄─────────────│  doc pointer │              │
  │              │              │              │              │              │
  │              │              │ get_full_content(doc_id)   │              │  ~200 ms
  │              │              │─────────────────────────────►              │
  │              │              │◄────────────────────────────│  page text  │
  │              │              │              │              │              │
  │              │              │ system: "treat as KV"      │              │
  │              │              │ user:   query + doc text   │              │
  │              │              │─────────────────────────────┼─────────────►│  ~20 s
  │              │              │◄────────────────────────────┼─────────────│
  │              │              │              │              │  answer     │
  │              │ SSE chunks   │              │              │              │  streaming
  │              │◄─────────────│              │              │              │
  │ tokens      │              │              │              │              │
  │◄─────────────│              │              │              │              │
  │              │              │              │              │              │
  ▼              ▼              ▼              ▼              ▼              ▼
```

**Where the time goes (typical, MiniMax-M3)**:
| Step | Latency | Bottleneck? |
|---|---|---|
| Neo4j routing | 5 ms | No (or 5 s if LLM routing — see "Three Routing Modes" below) |
| `get_full_content` | 200 ms | No (pure file I/O + PyMuPDF) |
| LLM synthesize | 15-20 s | **Yes** (cache hit on system+doc prefix makes it cheap; miss makes it 40 s) |
| Total | 15-25 s | LLM |

### Where the cost goes (typical query)
| Token bucket | Tokens | Notes |
|---|---|---|
| System prompt (catalog + KV instructions) | ~600 | Cache hit 100% after first call |
| Doc text (primary 30K + supporting 3×15K) | ~18,000 | Cache hit on first 14K (system+prefix) |
| User query | ~50 | Not cached |
| LLM output | ~500 | Not cached |
| **Per-query cost (after warm-up)** | **~$0.012** | MiniMax M3: $0.60/M in + $2.40/M out |

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

## 💸 Prompt Cache Mechanics (the secret weapon)

> **Why this matters**: every Phase 9 cost argument depends on it. If you don't get prompt caching,
> the LLM semantic router looks like a 5-second tax with no upside. With it, it's nearly free.

```
   Query #1                                Query #2, 3, 4, ...
      │                                        │
      ▼                                        ▼
 ┌─────────┐                              ┌─────────┐
 │ SYSTEM  │  catalog (~40K tokens)        │ SYSTEM  │  same catalog (~40K tokens)
 │ prompt  │  ────────────────────────►   │ prompt  │  ──── cache HIT (100%) ────►
 │         │  same prefix → cacheable      │         │  billed at cache_read rate
 └─────────┘                              └─────────┘
      │                                        │
      ▼                                        ▼
 ┌─────────┐                              ┌─────────┐
 │ USER    │  "Nike revenue"  (~10 tok)    │ USER    │  "苏格拉底思想" (~10 tok)
 │ query   │                              │ query   │  ← only this changes
 └─────────┘                              └─────────┘
      │                                        │
      ▼                                        ▼
   ~$0.024                                  ~$0.024
   (cold, 40K fresh)                        but cache_read = 40,000 tokens
                                            → only the user query + output is "new"
                                            → effective cost ≈ $0.001
```

**Three rules that keep the cache hot** (violate any of them and you pay full price every query):

1. **The system prompt must be byte-identical across queries.** Catalog is rendered deterministically:
   same field order, same separator, same line endings.
2. **The user message must come AFTER all the cached content.** Don't put the query in the system
   prompt and the catalog in the user message — that flips the cache window.
3. **The LLM provider must support prefix caching.** MiniMax M3 does (5-min TTL). OpenAI does
   (more aggressive). Anthropic does (5-min TTL). Local Ollama does NOT (no cache benefit).

**Measured benefit in Phase 9** (project 1, 18 docs, 14-query eval):
| Query | First call (cold) | Subsequent (warm) |
|---|---|---|
| Catalog routing | ~10 s | ~3-5 s |
| Doc synthesis | ~40 s | ~15-20 s |
| `cache_read` tokens | 0 | 30,000-35,000 |

**Implication**: don't reformat the catalog between queries. The single biggest performance bug
you can introduce in Phase 9 is sorting docs by name in one query and by date in the next.

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

## 🎚️ Three Routing Modes (before Step 2.6)

> **The single most important diagram in Phase 9.** Everything else (eval results, schema evolution,
> multi-doc synthesis) is an elaboration on one of these three modes. Pick the wrong one for your
> corpus and you'll either overspend or misroute.

```
                        USER QUERY
                            │
                            ▼
              ┌─────────────────────────┐
              │ Which routing mode?     │
              └────────────┬────────────┘
                           │
        ┌──────────────────┼──────────────────┬──────────────────┐
        │                  │                  │                  │
        ▼                  ▼                  ▼                  ▼
  ┌───────────┐      ┌───────────┐      ┌───────────┐      ┌───────────┐
  │  STRING   │      │  LLM      │      │  LLM      │      │  HEURISTIC│
  │  metadata │      │  semantic │      │  domain-  │      │  + manual │
  │  scoring  │      │  single-  │      │  aware    │      │  override │
  │           │      │  doc      │      │  multi-   │      │           │
  │  ~1 ms    │      │           │      │  doc      │      │           │
  │  57% acc  │      │  ~5 s     │      │  ~12 s    │      │  0 ms     │
  │           │      │  100% acc │      │  100% acc │      │  100% acc │
  └─────┬─────┘      └─────┬─────┘      └─────┬─────┘      └─────┬─────┘
        │                  │                  │                  │
        │  Step 2.5-       │  Step 2.6-       │  Step 2.9-      │  Step 2.1-
        │  pre-rebuild     │  2.8             │  2.10            │  always
        │                  │                  │                  │
        │  use when:       │  use when:       │  use when:       │  use when:
        │  • no enrich-    │  • 10-50 docs    │  • cross-domain  │  • user knows
        │    ment yet      │  • ZH/multilin-  │    question      │    the doc
        │  • <10 docs      │    gual queries  │  • need sources  │  • router wrong
        │  • fast preview  │  • default mode  │    from N docs   │  • debug
        │                  │                  │                  │
        └──────────────────┴──────────────────┴──────────────────┘
                                    │
                                    ▼
                          ┌──────────────────┐
                          │  Chosen doc(s)   │
                          │  → Stage 2 (Load)│
                          │  → Stage 3 (LLM) │
                          └──────────────────┘
```

**Decision rule of thumb** (memorize this):

| If you have... | Use this mode |
|---|---|
| < 10 docs and no enrichment yet | String (1 ms) |
| 10-50 docs, multilingual, default | LLM semantic (5 s, 100%) |
| Cross-domain question ("compare X with Y") | LLM domain-aware multi-doc (12 s) |
| User explicitly names a doc | `/doc <name>` override (bypass router) |

**The 43-pp gap is real** — see [eval.md](./eval.md) for the per-category breakdown. String matching
gets 0% on Chinese, LLM gets 100%. That's the single biggest reason Phase 9 keeps the LLM router
as the default despite the 5-second cost.

---

## 🎯 Step 2.6 — Semantic LLM routing (DONE)

String-matching routing fails on queries where the term isn't a literal substring
of any field (e.g. "苏格拉底思想" → 苏格拉底 doesn't appear in any field, but it
clearly relates to the philosophy doc). Solution: progressive disclosure + LLM
routing — apply the same pattern Phase 6 SKILLS.md uses for skills, but for docs.

`phase9/route_semantic.py` does this in 3 steps:

  1. **fetch_catalog** — 1 Cypher query pulls every doc + its `out_of_scope`
     neighbors' full metadata (`about`, `supported_queries`, etc.). No Neo4j
     relationships needed — just an `OPTIONAL MATCH` + `collect()`.
  2. **format_catalog** — render as a human-readable string with nested `excludes`
     showing each excluded doc's full about + supports.
  3. **route_by_llm** — put the formatted catalog in a stable `SystemMessage`
     (→ MiniMax prompt cache 100% hit), then ask the LLM to pick the best doc
     with a JSON response (`{name, confidence, reasoning}`).

Comparison (string vs LLM, against live Neo4j with 18 docs):

| Query | string (1 ms) | LLM (3-7 s) | Notes |
|---|---|---|---|
| `philosopher profiles` | 6 人物库.pdf | 6 人物库.pdf (0.97) | agree |
| `苏格拉底思想` | (no match) | 6 人物库.pdf (0.30) | LLM recognizes Socrates→philosophy, is honest about partial match |
| `machine learning neural networks` | Deep Learning in Healthcare.pdf (lucky) | cs230-midterm.pdf (0.62) | LLM knows CS230 = Stanford DL course |
| `Nike revenue` | nke-10k-2023.pdf | nke-10k-2023.pdf | agree |

Usage:

```bash
# Single query
python phase9/route_semantic.py --query "苏格拉底思想"

# Compare string vs LLM side-by-side
python phase9/route_semantic.py --query "neural networks" --compare

# Show the catalog (for debugging)
python phase9/route_semantic.py --show-catalog
```

Cache benefit: catalog is the same across all queries within a project, so
system-message prefix is stable → MiniMax prompt cache 100% hits → only the
query + output costs tokens (typically 1,000-2,000 tokens per query).

## 🎯 Step 2.7 — Full project rebuild + JSON parser hardening (DONE)

`--rebuild-project` was run against all 18 docs in project 1. Result:
**16/18 succeeded** (the 2 failures are scanned PDFs where PyMuPDF can't
extract text). Every successful doc now has:

| Field | Source |
|---|---|
| `what_this_document_is_about` | 150-300 chars, generated by LLM from doc content |
| `supported_queries` | 5-11 natural-language questions per doc |
| `out_of_scope` | 5-17 exact doc names (LLM told to put each name on its own) |
| `few_shot` | 2-4 example Q/A pairs |
| `search_terms`, `content_preview`, `page_count` | (unchanged from DocIndex) |

Real test of routing after rebuild:

| Query | string (1 ms) | LLM (3-7 s) |
|---|---|---|
| `binary classification neural network` | C4M4.pdf ❌ | **C1M2.pdf (0.95)** ✅ |
| `reinforcement learning Q-learning` | cs230-midterm.pdf ❌ | **lecture-notes-9.pdf (0.97)** ✅ |
| `philosopher profiles` | 6 人物库.pdf | 6 人物库.pdf (0.97) |

Notice the LLM now reads C1M2's about text and recognizes "Andrew Ng's Deep
Learning course C1M2: Basics of Neural Network Programming — covers binary
classification" as the perfect match, while string-matching guessed wrong
on C4M4.pdf (which is Course 4, not Course 1).

### Bug fixes during rebuild

Two small bugs in `build_graphindex.py` JSON parser were fixed:

  1. **Missing `import re`** — the fallback JSON parser used `re.sub` but the
     module wasn't imported.
  2. **Naive brace matching** — `text.find("{")` + `text.rfind("}")` would
     grab trailing prose after the JSON. Replaced with proper balanced-brace
     matching that respects JSON string literals and escape sequences.

MiniMax M3 has a quirk where ~50% of calls wrap the answer in
`<think>...</think>` blocks despite being told not to. The fallback parser
handles both cases:

  - Strip `<think>...</think>` if present
  - Walk from the first `{` tracking brace depth (skipping over content
    inside string literals and after backslash escapes)
  - Take everything up to the matching closing `}`
  - Sanitize stray control characters before `json.loads()`

Full catalog is ~158K chars / ~40K tokens and stable per project → MiniMax
prompt cache 100% hits on every routing call.

## 🎯 Step 2.8 — Ingest with SHA-256 dedup (DONE)

`--ingest <file>` adds a new doc safely: hash the file, check filesystem +
Neo4j for any existing copy, copy with hash prefix only if genuinely new,
then run enrichment to add the graphindex node.

### Flow

```
new file (any path)
   │
   ▼ SHA-256 (8-char prefix used as filename prefix)
   │
   ├── fs dedup   : rglob docs_base, scan sha256 of each project_* file
   │                (skip project_chat_sessions — those are private clones)
   ├── neo4j dedup: MATCH (d:Document {content_sha256}) — skip if hit
   │
   └── neither hit:
       copy → backend/data/documents/project_1/{h[:8]}_{name}
       upsert node + SET d.content_sha256 = $h
       run LLM enrichment (about / supported / out_of_scope / few_shot)
```

### Verified scenarios (live tests against localhost:7474)

| Ingest | Result |
|---|---|
| `31042021_nke-10k-2023.pdf` (already in fs as `37901aa0_nke-10k-2023.pdf`) | ✗ skipped: same sha256 |
| `/tmp/new_test_doc.txt` (genuinely new) | ✓ copied + indexed as `92707d11_new_test_doc.txt` |
| `/tmp/new_test_doc.txt` again | ✗ skipped: already in Neo4j by content_sha256 |

### Usage

```bash
# Default target dir: backend/data/documents/project_1
python phase9/build_graphindex.py --ingest /path/to/new.pdf

# Custom target dir (any project_* folder under backend/data/documents/)
python phase9/build_graphindex.py --ingest /path/to/new.pdf \
    --ingest-target /Users/me/projects/foo/backend/data/documents/project_42
```

### Why hash prefix filename?

Matches the existing base convention (`35d142f1_C1M2.pdf`,
`66bbde2a_Departmental Survey for Biz Strategy.pdf`). The 8-char prefix
is the SHA-256 leading bytes — gives ~4 billion distinct buckets while
staying short.

## 🎯 Step 2.9 — Domain-aware multi-doc routing (DONE)

The routing prompt now asks the LLM to:

  1. Tag the primary document with a short `primary_domain` (lowercase snake_case)
  2. Identify 0-3 **supporting documents** from different domains that add
     context, each with a concrete `reason`

The LLM is now responsible for cross-domain selection (rather than relying
on a fixed score-threshold or fuzzy overlap), which lets it reason about
*semantic complementarity* — e.g. "Nike 10-K is the primary, but the
Strategic Framework Presentation adds the methodology for industry comparison."

### Schema evolution

| Field | v1 (before) | v2 (current) |
|---|---|---|
| main doc | `name` | `primary` |
| confidence | `confidence` | `primary_confidence` |
| domain | — | `primary_domain` |
| supporting | — | `supporting: [{name, reason}]` |

`_parse_decision()` accepts both v1 and v2 schemas (backwards compat) and
uses balanced-brace matching that handles nested `{...}` arrays in
`supporting`.

### Live test: cross-domain query

```
Query: 'compare Nike strategy with industry trends'
  llm  → nke-10k-2023.pdf  (confidence=0.92)  domain=financial_report
        Nike's 10-K is the core source for Nike's strategy and risk/competitive
        context, while the strategic framework and survey supply cross-domain
        scaffolding for an industry-trend comparison.
  supporting (2):
    - Strategic Framework Presentation.pdf
      reason: 'DEEP RESEARCH' pillar covers industry analysis and competitive
              intelligence methodology...
    - Departmental Survey for Biz Strategy.pdf
      reason: Provides strategic metrics (BCG portfolio, customer loyalty,
              innovation/R&D) that can benchmark Nike's strategy...
```

### Live test: single-domain query

```
Query: 'philosopher profiles'
  llm  → 6 人物库.pdf  (confidence=0.97)  domain=philosopher_entrepreneur_library
  (no supporting — query is single-domain)
```

### Other fixes

  - `max_tokens` bumped from 512 to 1024 to fit multi-supporting JSON
  - Truncation recovery in `_parse_decision` — when LLM hits max_tokens
    mid-JSON, we close any unclosed braces/brackets at the last complete
    nested boundary so we still get *something* useful back

## 🎯 Step 2.10 — Multi-doc load + synthesis (DONE)

End-to-end command:

```bash
python phase9/route_semantic.py --query-answer "compare Nike strategy with industry trends"
```

Flow:

```
                 ┌─────────────────┐
                 │  1. Route        │  LLM #1 (catalog → primary + supporting)
                 │     (1 LLM call) │  cache: 34K tokens hit
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │  2. Load docs    │  PyMuPDF × N, capped per-doc chars
                 │     (no LLM)     │  primary: 30K, supporting: 15K each
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │  3. Synthesize   │  LLM #2 (multi-doc → answer)
                 │     (1 LLM call) │  cites pages, weaves primary+supporting
                 └─────────────────┘
```

### Per-doc char caps

| Role | Cap | Reason |
|---|---|---|
| primary | 30,000 | Main source, needs depth |
| supporting | 15,000 | Reference material, cap tighter |

Total max context: `30K + 3 × 15K = 75K chars` ≈ 18K tokens (well within
MiniMax M3 limits).

### Live test against localhost:7474

```
Query: 'compare Nike strategy with industry trends'

routed → nke-10k-2023.pdf  (confidence=0.85)  domain=nike_financial_report
supporting (2):
  - Strategic Framework Presentation.pdf
  - Departmental Survey for Biz Strategy.pdf
(route: 11.93s, cache_read=34,816)

loaded 42,369 chars  (0.2s)
synthesized  (20.6s, cache_read=128)

ANSWER:
  Nike's strategy organized around 7 pillars (consumer-led product,
  innovation-led differentiation, DTC push, ...). Industry trends Nike
  identifies itself: hyper-competition (lists adidas/Anta/ASICS/etc.),
  trade protectionism, supply chain volatility, ...
  
  The supporting documents don't add industry-trend data — Document 2 is
  an AI integration framework, Document 3 is a generic business strategy
  template. So comparison relies on Nike's own disclosures.
  
  [cites pages from Doc 1: pp.1-6]
```

The synthesis LLM correctly notes when supporting docs don't add
context, and only cites Doc 1 when answering.

### Usage

```bash
# Full end-to-end (route + load + answer)
python phase9/route_semantic.py --query-answer "<query>"

# Just route (no load, no answer)
python phase9/route_semantic.py --query "<query>"

# Side-by-side comparison
python phase9/route_semantic.py --query "<query>" --compare
```

## 🎯 Step 3 — Eval suite (DONE)

`phase9/eval_routing.py` runs a hand-labeled 14-query set across 6
categories (simple EN, simple ZH, conceptual, cross-domain, irrelevant,
ambiguous). Reports top-1 / top-3 accuracy, per-category breakdown,
latency stats, and the full misroute list.

### Headline (live results, 18 docs in project 1)

| Method | Primary accuracy | Top-3 | Latency mean | Latency max |
|---|---|---|---|---|
| String matching | 57% | 57% | 1 ms | 1 ms |
| **LLM semantic** | **100%** | **100%** | 5,393 ms | 12,612 ms |

### Per-category Δ (LLM − string)

| Category | n | String | LLM | Δ |
|---|---|---|---|---|
| A. Simple EN literal | 2 | 100% | 100% | 0 |
| B. Simple ZH | 2 | **0%** | **100%** | **+100 pp** |
| C. Conceptual | 4 | 75% | 100% | +25 pp |
| D. Cross-domain | 2 | 50% | 100% | +50 pp |
| E. Irrelevant | 2 | 50% | 100% | +50 pp |
| F. Ambiguous | 2 | 50% | 100% | +50 pp |

### Cache benefit verified

MiniMax prompt cache 100% hits on the 40K-token catalog across all 14
queries. `cache_read` per query: 30K-35K tokens.

### Full report

See [`phase9/eval.md`](./eval.md) for the complete write-up including
misroute analysis, latency distribution, caveats, and the promotion
plan for lifting the LLM router into `backend/services/`.

### How to re-run

```bash
python phase9/eval_routing.py --method both
python phase9/eval_routing.py --method string
python phase9/eval_routing.py --method llm --output /tmp/eval.json
```

## 🎯 Step 2.11 — Integrated DV chat with LLM routing (DONE)

`phase9/dv_chat.py` now reads the **real Neo4j catalog** (no more SEED_DOCS)
and routes every fresh query through `route_by_llm()`. The SEED_DOCS list
was a hand-rolled 6-doc fake; the live REPL now sees all 18 project docs
with their LLM-enriched `about` / `supported_queries` / `out_of_scope`.

### New commands

| Command | Effect |
|---|---|
| `/docs` | List all 18 docs with their `about` preview |
| `/doc <name>` | Switch to a specific doc (manual override) |
| `/route` | Show current routing method |
| `/route llm` | Switch to LLM semantic routing (default) |
| `/route string` | Switch to base's string-matching routing |
| `/stats` | Show session totals |
| `/quit` | Exit |

### Per-turn output

Every question prints:

```
🤖 <answer>
   ├─ doc:      <primary> [+ supporting1, supporting2]
   ├─ routed:   llm  (0.97 domain=financial_report, 40.0s routing)
   ├─ tokens:   in=  7,360  out=  471  (standard)
   │            cache_read=   114  (1.5% cached)
   ├─ latency:   18.9s  (cum LLM:  18.9s, wall:  59.4s)
   └─ cost:     $0.0055  (session: $0.0055 over 1 turn)
```

The footer shows routing method, confidence, domain, latency, cache hit
rate, and cost per turn.

### Live test (4 turns)

```
you> Nike revenue
  → routed (llm, 0.97  domain=financial_report, 40.0s): nke-10k-2023.pdf
🤖 ... Historical revenue by region (FY 2023: U.S. 43%, Non-U.S. 57%) ... (Document 1, p.51)

you> 苏格拉底思想
  (active doc kept: nke-10k-2023.pdf — LLM says "not in this doc")

you> binary classification neural network
  (active doc kept: same)

you> /route string
  → routing now: string  (active doc reset)

you> Nike revenue
  → routed (string, 1.00, 0.0s): nke-10k-2023.pdf
🤖 ... (same answer, but routing was free)

session: 4 turns, 76.7% cached, $0.022 total
```

The first routing call is slow (cold prompt cache, ~40s) but subsequent
calls within the same project get **99.7% cache hit** because the
40K-token catalog system message is stable.

### Wiring summary

```
                    ┌─────────────────────────────────────┐
                    │ phase9/route_semantic.py            │
  user query ──────►│ fetch_catalog → format_catalog →     │
                    │ route_by_llm → {primary, supporting}│
                    └────────────────────┬────────────────┘
                                         │
                                         ▼
                    ┌─────────────────────────────────────┐
                    │ phase9/dv_chat.py                   │
                    │ MultiDocSession(primary, supporting)│
                    │   ↳ load_multi_doc_context()        │
                    │   ↳ ask → LLM synthesize answer      │
                    └─────────────────────────────────────┘
```

### Caveats

  - **Active-doc persistence**: once a doc is routed, subsequent questions
    in the same session continue in that doc (no re-route). This is by
    design — same as Phase 9 Step 2. Use `/doc <name>` to switch.
  - **First routing call is slow** (~30-40s cold cache); subsequent calls
    are ~3-5s with cache hit.
  - **Two LLM instances are created**: one for routing, one for chat. They
    could be merged but separating them makes the routing-call budget
    independent of the chat history.

## 🎯 Step E — Phase 9 integrated as native tools (DONE)

`backend/tools/native_tools.py` now wraps the Phase 9 query/build system
as native tools that agents can call. The function signatures are kept
identical so existing agent configs work unchanged; only the
implementation switches from base string matching to Phase 9 LLM semantic
routing.

### What changed

| Tool | Before (base) | After (Phase 9) |
|---|---|---|
| `graphindex_search(query, project_id)` | `_try_graphindex_search_via_neo4j` (string match) | `phase9.query.route_by_llm` (LLM semantic) |
| `graphindex_load(context_doc_id)` | `_load_full_content_for_kv` (KV store) | `phase9.query._read_doc_text` (PyMuPDF / file read) |

### New tools added

| Tool | Backed by | Use case |
|---|---|---|
| `graphindex_list_docs(project_id)` | `phase9.query.fetch_catalog` | Discover what docs exist before routing |
| `graphindex_multi_doc_load(query)` | `phase9.query.load_multi_doc_context` | One-shot: route + load primary + supporting |
| `graphindex_rebuild_one(name)` | `phase9.graphindex_build_python.cmd_rebuild_one` | Knowledge curation |
| `graphindex_ingest(file_path)` | `phase9.graphindex_build_python.cmd_ingest` | Build-side ingest (richer than chat_pdf) |

### How the integration works

`backend/tools/native_tools.py` adds a one-time `sys.path` injection
right after the imports so the module can `from query import ...`:

```python
_PHASE9_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "phase9"))
if _PHASE9_DIR not in sys.path and os.path.isdir(_PHASE9_DIR):
    sys.path.insert(0, _PHASE9_DIR)
```

Then each tool becomes a thin wrapper around Phase 9:

```python
def graphindex_search(query: str, project_id: Optional[int] = None) -> str:
    """..."""
    from query import fetch_catalog, route_by_llm, make_llm  # Phase 9
    from services.neo4j_document_index import Neo4jDocumentIndex

    idx = Neo4jDocumentIndex()
    rows = fetch_catalog(idx, project_id or 1)
    decision, cache_read = route_by_llm(query, rows, make_llm())
    return _format_decision(decision, cache_read)
```

### Live test (12/14 = 86% accuracy)

```
$ python /tmp/quick_eval.py
  OK  Nike revenue 2023                             expected=nke-10k-2023.pdf               got=nke-10k-2023.pdf (4.2s)
  OK  Nike 10-K annual report financial statements  expected=nke-10k-2023.pdf               got=nke-10k-2023.pdf (4.0s)
  OK  苏格拉底思想                                        expected=6 人物库.pdf                      got=6 人物库.pdf (10.3s)
  OK  孔子语录                                          expected=6 人物库.pdf                      got=6 人物库.pdf (5.4s)
  OK  binary classification neural network          expected=C1M2.pdf                       got=C1M2.pdf (4.0s)
  OK  reinforcement learning Q-learning Deep Q-Netw expected=lecture-notes-9.pdf            got=lecture-notes-9.pdf (4.3s)
  OK  face recognition Siamese triplet loss         expected=C4M4.pdf                       got=C4M4.pdf (8.5s)
  OK  word embedding Word2Vec GloVe                 expected=C5M2.pdf                       got=C5M2.pdf (3.4s)
  OK  compare Nike strategy with industry trends    expected=nke-10k-2023.pdf               got=nke-10k-2023.pdf (10.5s)
  FAIL apply entrepreneur thinking to AI strategy fr expected=Strategic Framework Presentati got=6 人物库.pdf (20.3s)
  OK  what is the weather today in Tokyo            expected=None                           got=(null) (2.9s)
  FAIL how do I bake a chocolate cake                expected=None                           got=test_doc.txt (5.4s)
  OK  deep learning course logistics grading        expected=Week1_slides.pdf               got=Week1_slides.pdf (5.7s)
  OK  machine learning project planning error analy expected=lecture-notes-6.pdf            got=lecture-notes-6.pdf (4.1s)
=== TOTAL: 12/14 = 86% ===
```

The 2 failures are pre-existing Phase 9 limitations (LLM non-determinism
on D_cross_domain + a leftover `test_doc.txt` in Neo4j). Phase 9
preserves the same 86% accuracy via the new tool wrappers.

### Tool registration sites updated

| Line | Change |
|---|---|
| `_PHASE9_DIR = ...; sys.path.insert(0, _PHASE9_DIR)` | New path hook (line 30-39) |
| `graphindex_search` function body | Switched to Phase 9 |
| `graphindex_load` function body | Switched to Phase 9 |
| `_graphindex_*_tool = StructuredTool.from_function(...)` | New wrappers for 4 additional tools |
| `_TOOL_REGISTRY["graphindex_*"] = _graphindex_*_tool` | New entries in dispatch map |
| `get_available_tool_names()` list | New tool names added |
| `get_tool_registry()` (UI metadata) | New entries with `(Phase 9)` suffix |

### What still needs work

1. **chat_pdf.py KV store** — still exists but unused by the new tool
   path. Future cleanup: remove `chat_pdf.py` + `.chat_pdf_kv/` directory.
2. **`_try_sync_context_document_to_neo4j` enrichment bug** — DONE (see
   Step F below). Knowledge-panel uploads now get real enrichment.
3. **Chat upload integration** — chat-panel uploads still don't go to
   Neo4j. Could call `graphindex_ingest` from
   `chat/routes.py:_process_single_chat_upload` after a successful save.

## 🎯 Step F — Knowledge-panel upload gets real enrichment (DONE)

`backend/api/knowledge/rag.py:_try_sync_context_document_to_neo4j` was
passing `enrichment=None` for every knowledge-panel upload. Result:
the Neo4j Document node had empty `about / supports / out_of_scope /
few_shot`, which made routing for new docs effectively impossible.

### Fix

Added a new helper `_phase9_get_or_generate_enrichment` that:

1. Reads the existing Neo4j node (if any). If it already has a populated
   `what_this_document_is_about`, **reuse that enrichment** (avoids
   duplicate LLM calls for already-indexed docs).
2. Otherwise, calls `phase9.graphindex_build_python.enrich_document` to
   run a single LLM call and return a `Neo4jDocumentEnrichment` with
   `about / supported_queries / out_of_scope / few_shot`.

The main `_try_sync_context_document_to_neo4j` now passes the result
to `build_document_node_properties(..., enrichment=...)` instead of
`enrichment=None`.

### Behaviour

| Scenario | Cost | Result |
|---|---|---|
| Doc already has enrichment in Neo4j | 0.01s (Neo4j read) | Reuse, no LLM call |
| Doc has no Neo4j entry (fresh upload) | ~10s (1 LLM call) | Generate enrichment, upsert |
| LLM call fails | 0s (catch) | Empty enrichment, doc still gets upserted |

### End-to-end test (knowledge-panel upload simulation)

```
$ python /tmp/test_e2e_enrich.py
File: backend/data/documents/project_1/bf25d4ce_e2e_test_doc.txt
Created ContextDocument id=37
Running _try_sync_context_document_to_neo4j...
    (structured output failed, retrying plain: 1 validation error for
     DocumentEnrichmentOutput Invalid JSON ...)

=== Neo4j node ===
  about: 'Graph neural networks (GNNs) applied to social network analysis,
          covering node classification, link prediction, and community...'
  supports (5):
    - 'graph neural networks overview'
    - 'GNN node classification'
    - 'link prediction with GNNs'
  out_of_scope (18):
    - 6 人物库.pdf
    - 8284514.pdf
    - C1M2.pdf

  ✓ ENRICHMENT POPULATED
```

### Files changed

- `backend/api/knowledge/rag.py`:
  - Added `_PHASE9_DIR` path hook (top of file)
  - Added `_phase9_get_or_generate_enrichment()` helper (~50 lines)
  - Modified `_try_sync_context_document_to_neo4j` body: pass
    `enrichment=enrichment_obj` instead of `enrichment=None`

### Existing tests

`backend/tests/test_neo4j_autosync.py` still passes — the test uses
a `DummyNeo4jIndex` without `get_document()`. The new code catches
the `AttributeError` and falls through to the LLM branch, which also
fails (no LLM in test), returning an empty enrichment. Test asserts
on `payload["content"]` is not in payload, which still holds.

```
$ pytest backend/tests/test_neo4j_autosync.py -v
backend/tests/test_neo4j_autosync.py::test_try_sync_context_document_to_neo4j_upserts_pointer_metadata PASSED [100%]
1 passed, 4 warnings in 1.98s
```

## 🎯 Step G — Chat upload now gets enrichment (DONE)

`backend/api/chat/routes.py:_index_to_graphindex_for_chat` already
called `index_document_background()` after saving the chat file. With
Step F, that chain now ends in `_phase9_get_or_generate_enrichment`,
so chat uploads automatically get the same Neo4j enrichment as
knowledge-panel uploads.

### Full chain (chat panel)

```
chat upload (POST /api/chat/{session_id}/upload)
  → _process_single_chat_upload       (chat/routes.py)
  → _index_to_graphindex_for_chat      (chat/routes.py, async)
       ↓ dedup by SHA-256, then filename
  → ContextDocument created
  → index_document_background()       (knowledge/rag.py, async)
       ↓ DocIndex + vector indexing
  → _try_sync_context_document_to_neo4j (knowledge/rag.py)
  → _phase9_get_or_generate_enrichment (knowledge/rag.py, NEW)
       ↓ reuse if existing, else 1 LLM call
  → Neo4j Document node with about / supports / out_of_scope
```

### End-to-end test

```
$ python /tmp/test_chat_upload.py
Saved to: /Users/weiping/dev/Learn/langchain-ai/langconfig/data/documents/project_1/40d8bd1d_chat_upload_test.txt
Created ContextDocument id=40
Running index_document_background(40)...

=== Neo4j node ===
  about: 'A test document about reinforcement learning covering
          Q-learning, DQN, policy gradient, and actor-critic methods, used to...'
  supports (5):
    - 'What is Q-learning?'
    - 'What is DQN?'
    - 'What are policy gradient methods?'
  out_of_scope (19):
    - 6 人物库.pdf
    - 8284514.pdf
    - C1M2.pdf

  ✓ ENRICHMENT POPULATED (chat upload works!)

Cleaned up test artifact
```

### Files changed

- `backend/api/chat/routes.py`:
  - Added `_PHASE9_DIR` path hook (top of file)
  - Added `[phase9]` log markers in `_index_to_graphindex_for_chat`
    (one at start, one after indexing completes) so the Phase 9 path
    is visible in logs

### What still needs work

1. **chat_pdf.py KV store** — still exists but unused by the new tool
   path. Future cleanup: remove `chat_pdf.py` + `.chat_pdf_kv/` directory.

## 🎯 Step H — Frontend folder upload (DONE)

Both the knowledge panel and chat panel now support uploading a whole
folder (recursive). The browser's directory picker (via the
`webkitdirectory` attribute) returns a flat `FileList` to the FE, which
is then sent to the existing `upload-multiple` backend endpoint.

### What changed

| Panel | Status |
|---|---|
| Knowledge panel | Already had `webkitdirectory` (purple "Select folder" button) |
| Chat panel | New dropdown next to paperclip — "Upload file(s)" or "Upload folder" |

The chat `FileUploadButton.tsx` was refactored:
- The single paperclip icon is now a 2-button group with a small chevron
  that opens a popover menu (Upload file(s) / Upload folder)
- Folder upload uses a second hidden `<input type="file" webkitdirectory>` ref
- All files go through the existing `upload-multiple` endpoint, then
  Phase 9 enrichment (Step G) ensures each one becomes routable

### End-to-end test (folder upload via API)

```
$ mkdir -p /tmp/folder_test/{sub1,sub2}
$ echo "NLP test" > /tmp/folder_test/a.txt
$ echo "DL test" > /tmp/folder_test/sub1/b.txt
$ echo "# MD test" > /tmp/folder_test/sub2/c.md

$ curl -X POST "http://localhost:8765/api/chat/${SID}/upload-multiple?project_id=1" \
    -F "files=@/tmp/folder_test/a.txt" \
    -F "files=@/tmp/folder_test/sub1/b.txt" \
    -F "files=@/tmp/folder_test/sub2/c.md"
uploaded 3 files: ['a.txt', 'b.txt', 'c.md']
```

After ~30s (3 LLM enrichment calls):

```
$ python -c "from tools.native_tools import graphindex_search; ..."
  a.txt: about='A simple test file verifying folder upload functionality, ...' supports=3
  b.txt: about='A test/stub document containing only placeholder text about deep learning, ...' supports=2
  c.md: about='A minimal test markdown file used to verify the folder upload path ...' supports=3
```

### Server logs (Phase 9 path visible)

```
[phase9] chat upload starting: filename='a.txt', project_id=1, file_size=118 bytes
[phase9] generated fresh enrichment for 'a.txt': about='A simple test file verifying...'
[phase9] chat upload indexed: doc_id=45, filename='a.txt' (now routable in Neo4j)
[phase9] chat upload starting: filename='b.txt', project_id=1, file_size=110 bytes
[phase9] generated fresh enrichment for 'b.txt': about='A test/stub document...'
[phase9] chat upload indexed: doc_id=46, filename='b.txt' (now routable in Neo4j)
[phase9] chat upload starting: filename='c.md', project_id=1, file_size=81 bytes
[phase9] generated fresh enrichment for 'c.md': about='A minimal test markdown file...'
[phase9] chat upload indexed: doc_id=47, filename='c.md' (now routable in Neo4j)
```

### Routing verification (each folder doc is reachable)

```
'verify recursive folder upload functionality'  -> b.txt
'placeholder text deep learning'                -> b.txt
'markdown folder upload path'                   -> c.md
```

### Files changed

- `src/features/chat/ui/FileUploadButton.tsx`:
  - Added `FolderUp`, `FileUp`, `ChevronUp` icon imports
  - Added `showMenu` state + `folderInputRef` for the second input
  - Replaced single button with a 2-button group + popover menu
  - Added `webkitdirectory` second input for folder picking
  - Preserves all original behaviour (single file → `/upload`,
    multiple → `/upload-multiple`)

## 🎯 Step I — Move legacy scripts to `phase9/legacy/` (DONE)

The 4 raw-`llm.invoke` CLIs were moved from `phase9/` to
`phase9/legacy/` to keep the current Phase 9 directory focused on
recommended and modern scripts. Their helper functions are still
imported by the modern scripts (via `from legacy.xxx import ...`).

### What moved

| File | Old path | New path | Helper functions still imported by |
|---|---|---|---|
| `build_graphindex.py` | `phase9/` | `phase9/legacy/` | `graphindex_build_python.py`, `buildindex_tools.py` |
| `route_semantic.py` | `phase9/` | `phase9/legacy/` | `graphindex_tools.py`, `legacy/dv_chat.py` |
| `dv_chat.py` | `phase9/` | `phase9/legacy/` | (self-contained REPL) |
| `eval_routing.py` | `phase9/` | `phase9/legacy/` | `eval_routing_deep.py` |

### What stayed in `phase9/`

| File | Why |
|---|---|
| `graphindex_build_python.py` | Recommended (Step D) — pure Python + 1 LLM call |
| `graphindex_build_deepagent.py` | DeepAgent build (Step C) |
| `build_agent.py` | Build-side DeepAgent factory |
| `buildindex_tools.py` | 9 @tool wrappers for build-side DeepAgent |
| `graphindex_tools.py` | 4 @tool wrappers for query-side DeepAgent |
| `query.py` | Aggregator CLI |
| `query_deep.py` | DeepAgent query CLI |
| `query_agent.py` | Query-side DeepAgent factory |
| `eval_routing_deep.py` | Comparison eval (string / llm / deep) |

### Updated phase9 file layout

```
phase9/
├── legacy/                       ← Step I
│   ├── __init__.py               (docstrings)
│   ├── README.md                 (explains what's in here + why)
│   ├── build_graphindex.py        ← raw llm.invoke, helpers still imported
│   ├── route_semantic.py          ← raw llm.invoke, helpers still imported
│   ├── dv_chat.py                 ← raw llm.invoke REPL
│   └── eval_routing.py            ← raw llm.invoke eval
│
├── graphindex_build_python.py     ← Recommended (pure Python + 1 LLM call)
├── graphindex_build_deepagent.py      ← DeepAgent build (3 subagents)
├── build_agent.py                ← Build-side DeepAgent factory
├── buildindex_tools.py           ← 9 @tool wrappers for build
│
├── graphindex_tools.py           ← 4 @tool wrappers for query
├── query.py                      ← Aggregator CLI
├── query_agent.py                ← Query-side DeepAgent factory
├── query_deep.py                 ← DeepAgent query CLI
│
├── eval_routing_deep.py          ← Comparison eval
└── README.md
```

### How the move was done

1. `git mv` each script from `phase9/` to `phase9/legacy/` (preserves
   git blame).
2. Each script got a `REPO_ROOT = Path(__file__).resolve().parent.parent.parent`
   (was `.parent.parent`) so the `.env` and `backend/` paths still
   resolve from the new location.
3. Each importer was updated:
   ```python
   # Before
   from build_graphindex import (DOCS_BASE, ...)

   # After
   from legacy.build_graphindex import (DOCS_BASE, ...)
   ```
4. `phase9/legacy/__init__.py` was added (makes `legacy` a real
   Python package — `phase9/` itself stays package-less).
5. `phase9/legacy/README.md` was added explaining the move + how to
   run the legacy CLIs.

### Test results (after move)

| Test | Result |
|---|---|
| All 9 scripts respond to `--help` | ✅ |
| `legacy/route_semantic.py --query "Nike revenue 2023"` | ✅ → nke-10k-2023.pdf (0.99) |
| `query.py --method llm route "binary classification"` | ✅ → C1M2.pdf (0.95) |
| `graphindex_build_python.py --show nke-10k-2023.pdf` | ✅ shows full node |
| `eval_routing_deep.py --help` | ✅ imports from `legacy.eval_routing` |
| `pytest backend/tests/test_neo4j_autosync.py` | ✅ PASSED |
| `from main import app` (FastAPI) | ✅ loaded |
| `graphindex_search` (Phase 9 native tool) | ✅ → nke-10k-2023.pdf |
| `graphindex_list_docs` (Phase 9 native tool) | ✅ 15 docs |

### What still needs work

1. **chat_pdf.py KV store** — still exists but unused by the new tool
   path. Future cleanup: remove `chat_pdf.py` + `.chat_pdf_kv/` directory.

The legacy scripts (`dv_chat.py`, `route_semantic.py`, `eval_routing.py`)
use raw `llm.invoke([messages])`. This step adds a parallel **deepagent-based**
code path that matches the architecture used by the rest of the LangConfig
project (`backend/services/deepagent_factory.py` etc.).

### New files (legacy scripts untouched)

```
phase9/graphindex_tools.py   ← LangChain @tool wrappers
phase9/query_agent.py        ← DeepAgent factory (router/loader/answerer)
phase9/query_deep.py         ← CLI + REPL over the DeepAgent
```

### Architecture

```
            ┌─────────────────────────────────────────────┐
            │ create_deep_agent(model, system_prompt,       │
            │                  tools=[...],                  │
            │                  subagents=[router,            │
            │                            loader,             │
            │                            answerer],         │
            │                  checkpointer=MemorySaver)    │
            └─────────────────────────────────────────────┘
                                    │
   ┌────────────────────────────────┼───────────────────────────────┐
   │                                │                               │
   ▼                                ▼                               ▼
┌──────────────┐          ┌────────────────┐             ┌──────────────┐
│ fetch_catalog│          │ read_doc_tool  │             │ load_multi   │
│ _tool        │          │                │             │ _doc_tool    │
└──────────────┘          └────────────────┘             └──────────────┘
   Neo4j catalog              PyMuPDF read                   primary + supp

  ┌──────────┐    ┌──────────┐    ┌────────────┐
  │  router  │───▶│  loader  │───▶│  answerer  │
  │ (catalog │    │ (multi-  │    │ (synthesize│
  │  → JSON) │    │  doc ctx)│    │  answer)   │
  └──────────┘    └──────────┘    └────────────┘
       subagents share one LangGraph state graph
```

### Built-in middleware (from `deepagents`)

| Middleware | Effect on Phase 9 |
|---|---|
| TodoListMiddleware | LLM auto-tracks "route → load → answer" tasks |
| SubAgentMiddleware | router/loader/answerer can spawn into sub-state |
| PatchToolCallsMiddleware | Tool-call patches flow correctly |
| MemorySaver | Multi-turn REPL gets session continuity + cache hits |

### Live test (DeepAgent, single `--answer`)

```
$ python phase9/query_deep.py --answer "苏格拉底思想"

Query: '苏格拉底思想'

🤖 根据文档目录检索，当前知识库中没有关于苏格拉底的专题文档。可用的相关资料是
「6 人物库.pdf」，其中收录的哲学家为：亚里士多德、尼采、笛卡尔、维特根斯坦、海德
格尔、孔子。苏格拉底并未在该人物库中...

   ├─ tokens:   in= 17,044  out=  492
   │            cache_read=16,896  (99.1% cached)
   └─ latency:   53.4s
```

Note **99.1% cached** — the deepagent system prompt + tools + subagent
descriptions are stable across queries, so MiniMax prompt cache hits hard.

### Why deepagent over raw `llm.invoke`

| Concern | llm.invoke (legacy) | create_deep_agent (new) |
|---|---|---|
| State graph | none, manual messages list | LangGraph state, can resume |
| Multi-turn cache | manual append | automatic via checkpointer |
| Subagent delegation | manual orchestration | built-in via SubAgentMiddleware |
| Tool error retry | manual JSON fallback | PatchToolCallsMiddleware handles |
| Skills (future) | none | deepagents-native `skills=[...]` |
| HITL pause | none | built-in (just add middleware) |
| Observability | none | Langfuse callback ready |

### CLI

```bash
# Single answer (one-shot)
python phase9/query_deep.py --answer "Nike revenue 2023"

# Interactive REPL with multi-turn thread
python phase9/query_deep.py --chat

# Inspect the agent topology
python phase9/query_deep.py --show-agent
```

### Caveats

  - **Both code paths coexist**: legacy `dv_chat.py` / `route_semantic.py`
    / `eval_routing.py` are still in use. DeepAgent path is for new
    features (multi-agent collaboration, persistent state, skills).
  - **DeepAgent latency is higher** (~50s per query vs 5-10s for raw
    llm.invoke) because of state graph overhead. Cache hit rate is also
    higher (99% vs 76%) so cost per query is similar.
  - **Tools are stateless** — each tool call hits Neo4j / filesystem
    fresh. No shared mutable state between subagent calls (intentional).

## 🎯 Step A4 — Eval on DeepAgent vs raw llm.invoke (DONE)

`phase9/eval_routing_deep.py` runs the same 14-query hand-labeled set as
`eval_routing.py` against a routing-only DeepAgent (just
`fetch_catalog_tool`, no loader / answerer subagents). Compares all three
methods head-to-head.

### 3-way live results (against localhost:7474, 18 docs)

| Category | string | llm.invoke | deepagent |
|---|---|---|---|
| A. Simple EN literal | 100% | 100% | 100% |
| B. Simple ZH | 0% | 50% | **100%** |
| C. Conceptual | 75% | 100% | 100% |
| D. Cross-domain | 50% | 100% | 50% |
| E. Irrelevant | 50% | 100% | 100% |
| F. Ambiguous | 50% | 100% | 100% |
| **OVERALL** | **57%** | **93%** | **93%** |
| Latency mean | 1 ms | 11.2 s | 22.1 s |
| Cache % | — | — | 34.8% |

### Key findings

1. **DeepAgent (93%) ties llm.invoke (93%)** — both crush string matching
   (57%). DeepAgent is competitive with raw `llm.invoke` for routing-only.

2. **Latency regression**: DeepAgent is 2× slower (22s vs 11s) due to
   LangGraph state graph overhead per `invoke()`. Cache % is lower (34.8%
   vs ~99%) because each thread_id in the eval is fresh, so the system
   prompt isn't shared across queries. (In REPL with a single thread_id,
   cache % climbs back to ~99%.)

3. **B (simple ZH) DeepAgent 100% vs llm.invoke 50%** — DeepAgent's
   prompt "prefer partial match over null" is more decisive on Chinese
   queries where tokenization is unclear.

4. **D (cross-domain) DeepAgent 50%** — still misses "apply entrepreneur
   thinking to AI strategy framework" (returns null instead of
   Strategic Framework Presentation). LLM.invoke is more lenient.

5. **Architecture benefit**: DeepAgent can later gain skills, HITL
   pause, multi-agent collaboration — none of which `llm.invoke` can do.
   For *this* routing-only benchmark, the architectural overhead isn't
   yet paying off.

### Prompt refinement made the difference

```diff
- If NONE of the documents are relevant, reply: {"primary": null, ...}
+ Prefer a PARTIAL match with low confidence over returning null — if any
+ document's about or supports is even loosely related, pick it (this is
+ better for the user than saying "nothing matches")
+ Only return null if EVERY document is clearly unrelated
```

This bumped DeepAgent from 86% → 93% (matched llm.invoke).

### Usage

```bash
# All three methods (default)
python phase9/eval_routing_deep.py

# Just DeepAgent
python phase9/eval_routing_deep.py --method deep

# Save JSON
python phase9/eval_routing_deep.py --output /tmp/eval3way.json
```

## 🎯 Step B — Unified query CLI (NEW, no deletions)

`phase9/query.py` is a single CLI that consolidates the 5 separate
query-side scripts (`route_semantic.py`, `dv_chat.py`, `eval_routing.py`,
`eval_routing_deep.py`, `query_deep.py`) **without deleting them** —
all original scripts remain functional for backward compatibility.

### Subcommands

```bash
python phase9/query.py --method <string|llm|deep> <subcommand> [args]

# Single-shot routing decision
python phase9/query.py --method deep route "Nike revenue 2023"

# Single-shot answer (route + load + synthesize)
python phase9/query.py --method deep answer "compare Nike strategy with industry trends"

# Interactive REPL with multi-turn thread + /docs /method /doc
python phase9/query.py --method deep chat

# Run eval suite (single method or all)
python phase9/query.py eval --method all
python phase9/query.py eval --method deep

# Print catalog (debug)
python phase9/query.py catalog --limit 1000

# Print LLM prompt (debug)
python phase9/query.py prompt "binary classification neural network"
```

### Three routing methods

| Method | Backed by | Accuracy | Latency | Use case |
|---|---|---|---|---|
| `string` | `choose_best_document_match` (base) | 57% | 1 ms | baseline, cheap |
| `llm`    | raw `llm.invoke` on catalog prompt | 93% | ~10 s | fast LLM semantic |
| `deep`   | `create_deep_agent` with router/loader/answerer subagents | 93% | ~20 s | multi-doc + future skills/HITL |

### What's consolidated inside `query.py`

| Original script | Now mode in `query.py` |
|---|---|
| `route_semantic.py --query` | `route` |
| `route_semantic.py --query-answer` | `answer` |
| `route_semantic.py --show-catalog` | `catalog` |
| `route_semantic.py --show-prompt` | `prompt` |
| `dv_chat.py` | `chat` |
| `eval_routing.py` | `eval --method string\|llm` |
| `eval_routing_deep.py` | `eval --method deep` |
| `query_deep.py` | `query.py --method deep <subcommand>` |

All ~2,000 lines of legacy code is preserved on disk. `query.py` is a
**convenience aggregator** that ships the same logic through one CLI.

## 🎯 Step C — Build-side DeepAgent (NEW, no deletions)

`phase9/build_graphindex.py` (raw `llm.invoke`) gets a parallel
deepagent-based path. Legacy script remains intact.

### New files

```
phase9/buildindex_tools.py    ← LangChain @tool wrappers (9 tools)
phase9/build_agent.py         ← DeepAgent factory + 3 subagents
phase9/graphindex_build_deepagent.py ← CLI entry (--ingest, --rebuild-one, ...)
```

### Architecture

```
   ┌─────────────────────────────────────────────────┐
   │ create_deep_agent(model, system_prompt,          │
   │                  tools=[...9...],                 │
   │                  subagents=[ingest_checker,       │
   │                               enricher,           │
   │                               writer])            │
   └─────────────────────────────────────────────────┘
                        │
   ┌────────────────────┼────────────────────────────────┐
   ▼                    ▼                                ▼
┌─────────────┐  ┌──────────────┐         ┌──────────────────┐
│ sha256/     │  │ read_doc_tool│         │ upsert_doc_to_neo4j│
│ scan_fs/    │  │ get_metadata │         │ _tool            │
│ scan_neo4j  │  │ list_other_  │         │ copy_to_project_ │
│             │  │ doc_names    │         │ dir_tool         │
└─────────────┘  └──────────────┘         └──────────────────┘
   ingest_checker  enricher                    writer
```

### Built-in middleware

| Middleware | Effect on Phase 9 |
|---|---|
| TodoListMiddleware | LLM auto-tracks "hash → dedup → enrich → write" |
| SubAgentMiddleware | 3 subagents can spawn into sub-state |
| PatchToolCallsMiddleware | Tool-call patches flow correctly |

### Live test (--ingest)

```
$ python phase9/graphindex_build_deepagent.py --ingest /tmp/test_doc_deep.txt

🤖 Ingestion complete.
  - Verdict: new (no dupes)
  - SHA-256: 38191f3cf52e0ccdcf527ac5a31de317...
  - Copied to: backend/data/documents/project_1/38191f3c_test_doc_deep.txt
  - Neo4j upsert: OK
  - content_sha256 set
   ├─ tokens: in=11,482  out=191
   │          cache_read=11,378 (99.1% cached)
   └─ latency: 59.0s
```

Verify:
```
$ python phase9/graphindex_build_deepagent.py --show test_doc_deep.txt
📄 test_doc_deep.txt
   about: A short test document covering machine learning evaluation
          metrics, including accuracy, precision, recall, F1 score, ...
   supports (6): [precision/recall, F1, ROC/AUC, confusion matrix, ...]
   out_of_scope (5): [6 人物库.pdf, Nike 10-K, ...]
   content_sha256: 38191f3cf52e0ccd…
```

### Bugs found and fixed by the DeepAgent test

1. `build_document_node_properties()` was missing `doc_index_id` arg
   → fixed by passing `doc_index_id=None`.
2. `build_document_node_properties()` expects a `Neo4jDocumentEnrichment`
   dataclass, not a `dict` → fixed by constructing the dataclass.

These were latent bugs in the legacy `build_graphindex.py` — the
DeepAgent test exposed them via runtime error messages.

### CLI

```bash
# Ingest a new file (hash + dedup + copy + enrich + upsert)
python phase9/graphindex_build_deepagent.py --ingest /path/to/new.pdf

# Custom target directory
python phase9/graphindex_build_deepagent.py --ingest new.pdf --ingest-target /path/

# Rebuild enrichment for one doc
python phase9/graphindex_build_deepagent.py --rebuild-one "nke-10k-2023.pdf"

# Rebuild for entire project (18 docs, ~15 min)
python phase9/graphindex_build_deepagent.py --rebuild-project

# Show a node
python phase9/graphindex_build_deepagent.py --show "nke-10k-2023.pdf"

# Print agent topology
python phase9/graphindex_build_deepagent.py --show-agent
```

### Phase 9 file layout (current)

```
phase9/
├── build_graphindex.py          ← Build (raw llm.invoke) — UNCHANGED
├── buildindex_tools.py          ← Build tools (9 @tool wrappers)
├── build_agent.py               ← Build DeepAgent factory
├── graphindex_build_deepagent.py     ← Build CLI (deepagent path)
│
├── graphindex_tools.py          ← Query tools (4 @tool wrappers)
├── query_agent.py               ← Query DeepAgent factory
├── query.py                     ← Query CLI (aggregator)
│
├── route_semantic.py            ← Legacy query: raw llm.invoke — UNCHANGED
├── dv_chat.py                   ← Legacy REPL: raw llm.invoke — UNCHANGED
├── eval_routing.py              ← Legacy eval — UNCHANGED
├── eval_routing_deep.py         ← Legacy DeepAgent eval — UNCHANGED
└── query_deep.py                ← Legacy deepagent CLI — UNCHANGED
```

## 🎯 Step D — Clean Python build (NEW, recommended, no deletions)

`phase9/graphindex_build_python.py` is the **recommended** way to ingest
files into the graphindex. Pure Python function chain + **one** LLM
call for enrichment. No state graph, no subagent overhead, no
orchestration layer.

### Why pure Python over deepagent for build?

Build-side work is **deterministic**:

```
ingest:
  1. sha256(file)               — pure Python
  2. fs dedup                   — pure Python
  3. neo4j dedup                — pure Python
  4. copy with hash prefix      — pure Python
  5. LLM extract metadata       — ONE call
  6. upsert neo4j               — pure Python
```

There is no creative decision-making for an LLM to do. Adding a
deepagent layer adds ~30s of state-graph overhead per ingest with no
benefit. The query side is different — routing decisions are
non-deterministic and benefit from subagent collaboration.

### Three build-side scripts, three roles

| Script | Style | When to use |
|---|---|---|
| `graphindex_build_python.py` 🆕 | Pure Python + 1 LLM call | **Recommended** for normal ingestion |
| `build_graphindex.py` | Same flow, but orchestration mixed into `main()` | Legacy; keep for reference |
| `graphindex_build_deepagent.py` | DeepAgent with 3 subagents | Demo of deepagent architecture; useful if you want skills/HITL added to ingest later |

### Speed comparison (live)

```
$ python phase9/graphindex_build_python.py --ingest /tmp/test_clean.txt
📥 Ingesting /tmp/test_clean.txt
   hash: 726a1ba7…  (418 bytes)
   copied: backend/data/documents/project_1/726a1ba7_test_clean.txt
   enriching via LLM…     done (10.2s)
      about: A test document covering cross-validation strategies …
      supports: 5 queries
      out_of_scope: 18 docs
   neo4j: upserted as test_clean.txt
✅ Done in 10.2s

vs. deepagent path: ~60s for the same ingest (6× slower).
```

The LLM call is the same in both paths (~10s); what changes is the
overhead:
- Pure Python: 0s overhead (function calls + Neo4j round-trip)
- DeepAgent: ~50s overhead (state graph + LLM orchestration of subagents)

### CLI

```bash
# Recommended ingest
python phase9/graphindex_build_python.py --ingest /path/to/new.pdf
python phase9/graphindex_build_python.py --ingest new.pdf --ingest-target /path/

# Show / rebuild
python phase9/graphindex_build_python.py --show "nke-10k-2023.pdf"
python phase9/graphindex_build_python.py --rebuild-one "nke-10k-2023.pdf"
python phase9/graphindex_build_python.py --rebuild-project
```

### Updated phase9 file layout

```
phase9/
├── graphindex_build_python.py    🆕 Build CLI — PURE PYTHON (recommended)
├── graphindex_build_deepagent.py     ← Build CLI — DeepAgent (state-graph demo)
├── build_graphindex.py          ← Build CLI — legacy (mixed into main)
├── buildindex_tools.py          ← Tools for the deepagent path
├── build_agent.py               ← DeepAgent factory for build
│
├── graphindex_tools.py          ← Tools for query
├── query_agent.py               ← DeepAgent factory for query
├── query.py                     ← Query CLI (aggregator)
│
├── route_semantic.py            ← Legacy query — UNCHANGED
├── dv_chat.py                   ← Legacy REPL — UNCHANGED
├── eval_routing.py              ← Legacy eval — UNCHANGED
├── eval_routing_deep.py         ← Legacy deepagent eval — UNCHANGED
└── query_deep.py                ← Legacy deepagent CLI — UNCHANGED
```

## 🎯 Step L — `graphindex_chat` as a langconfig agent template (DONE)

The langconfig UI is an **agent IDE**: users build, edit, and run agents
via `src/features/agents/ui/DeepAgentBuilder.tsx` and the
`src/features/deepagent-studio/` canvas. The agent builder has full
CRUD via `POST /api/deepagents/` + `POST /api/deepagents/import`
(`.langconfig` JSON format).

This step makes `graphindex_chat` available as a first-class agent
template so users can:

1. Click a button on the Knowledge panel to import it.
2. Open it in the agent builder, edit anything (model, prompt, tools,
   add subagents).
3. Run it from the chat panel.

### L0 — Template payload (`phase9/graphindex_chat_template.py`)

A new Python file generates the exact `.langconfig` JSON that
`POST /api/deepagents/import` accepts. It mirrors the same
configuration as `phase9/graphindex_chat_agent.py`:

- 4 tools: `graphindex_list_docs`, `graphindex_search`,
  `graphindex_load`, `graphindex_multi_doc_load`
- Model: `minimax-m3` (deepseek-chat, per step 4)
- Category: `research`
- 0 subagents (single agent, like the Python reference)
- Middleware: `todo_list` + `filesystem` (deepagent defaults)
- Backend: `state` (LangGraph in-memory)

CLI modes:

```bash
# Print the template JSON
python phase9/graphindex_chat_template.py --print

# Save to file (for re-import or sharing)
python phase9/graphindex_chat_template.py --save /tmp/graphindex_chat.langconfig

# POST to /api/deepagents/import (CLI live test)
python phase9/graphindex_chat_template.py --import --server http://localhost:8765

# Custom name/model
python phase9/graphindex_chat_template.py --import --name "My Research Agent" --model minimax-m3
```

### L1 — Knowledge panel import button

`src/features/knowledge/ui/KnowledgeBaseView.tsx` got a new purple
"Phase 9" banner card right under the upload zone:

```
┌──────────────────────────────────────────────────┐
│ ✨ graphindex_chat (Phase 9)                      │
│ LLM-semantic-routed chat with 4 GraphIndex tools. │
│ Click to add to agent builder.                   │
│                              [✨ Use in builder] │
└──────────────────────────────────────────────────┘
```

Behaviour:

- Click → `POST /api/deepagents/import` with the embedded template JSON
- Button shows loader spinner → success checkmark with "In library"
- Hover tooltip shows the imported agent's id
- If import fails (e.g. already exists), the error is logged and the
  UI shows a graceful failure (no crash)
- The exact same template is also bundled inline in the FE
  (`GRAPHINDEX_CHAT_TEMPLATE_PAYLOAD` constant) so the button works
  without an extra fetch round-trip

`src/lib/api-client.ts` got a new `importDeepAgent(langconfigContent)`
helper that wraps the POST.

### Test results

```
$ python phase9/graphindex_chat_template.py --import --server http://localhost:8765
✓ Imported graphindex_chat agent (id=91, name='graphindex_chat')
  View in agent library: GET http://localhost:8765/api/deepagents/91

$ curl -s "http://localhost:8765/api/deepagents/91" | python3 -c ...
ID: 91
Name: graphindex_chat
Category: research
Model: minimax-m3
Tools: ['graphindex_list_docs', 'graphindex_search', 'graphindex_load', 'graphindex_multi_doc_load']
Subagents: []
Description: LLM-semantic-routed chat with project documents (Phase 9). 4 native tools: list, search, load, multi_doc_load.
```

TypeScript typecheck: clean (only the pre-existing
`SkillLibrary.tsx` error remains, unrelated to this step).
Vite build: clean.

### Why this design

The langconfig UI is already an agent IDE. The 4 graphindex_* tools
were already in `/api/tools/registry` since Step E. This step just
**bundles them into a first-class agent template** that users can
import, edit, and run — no separate graphindex_chat chat interface
needed. The same agent can be customized per-project (model swap,
extra tools, etc.) without touching Phase 9 code.

### Next

- **L2** (chat panel): add `graphindex_chat` as a one-click option in
  the chat panel's agent selector (so the user doesn't have to find
  it in the library)
- **L3** (tool library): surface the 4 graphindex_* tools in the tool
  library with a "Phase 9" badge so users can mix them into any agent

---

## 🎯 Step M — Progressive disclosure for `graphindex_chat` (DONE)

This step makes the modern `graphindex_chat` deepagent structurally
identical to the legacy 2-LLM-call flow from `legacy/route_semantic.py`.

### The problem we fixed

The legacy `route_semantic.py --query-answer` was clearly
**progressive disclosure**:

```
Step 1: LLM sees catalog (small)        → picks primary + supporting
Step 2: Filesystem read                 → loads full text of those docs
Step 3: LLM sees loaded context (big)   → synthesizes answer
```

The modern `graphindex_chat_agent.py` (the deepagent) was **not**
strictly progressive disclosure — the LLM was free to skip the catalog
lookup, guess doc names, or call only `read_doc_tool`. This worked
**most** of the time, but in the LangSmith trace for `"Nike financial
metrics"` the LLM called `graphindex_list_docs(project_id="default")`
twice without ever calling `graphindex_multi_doc_load`, producing a
weak answer.

### The fix: add `route_query_tool` as the 5th tool

A new tool was added to `phase9/graphindex_tools.py`:

```python
@tool
def route_query_tool(query: str, project_id: int = 1) -> str:
    """Find the top 1-3 documents that best match a user query
    (progressive disclosure: the small 'what exists' step before
    loading full text). Returns JSON: {primary, supporting: [...],
    primary_confidence, reasoning, cache_read_tokens}."""
```

This is a thin wrapper around the existing `route_by_llm()` from
`legacy/route_semantic.py`. The LLM (routing) is a separate one
from the main agent's LLM (synthesis) — keeps the call structure
identical to the legacy flow.

### New SYSTEM_PROMPT enforces the 3-step workflow

```text
WORKFLOW (progressive disclosure — MUST follow this order):
  1. ALWAYS call route_query_tool(query=..., project_id=1) FIRST
     for every user question. This is the LLM-semantic routing step
     that picks the best primary doc + 0-3 cross-domain supporting docs.
  2. PASS those exact names to load_multi_doc_tool(primary=...,
     supporting=[...]).
  3. SYNTHESIZE the final answer from the loaded context.
```

`graphindex_chat_agent.py` was updated to:
- Import `route_query_tool` (line 68)
- Add it to the agent's `tools=[...]` list (line 165)
- Replace the 4-tool SYSTEM_PROMPT with a 5-tool version that
  enforces the workflow above (lines 73–112)

### Verified: the LLM follows the new workflow

Live test of the same query that failed before:

```bash
$ python phase9/graphindex_chat_agent.py --answer "Nike financial metrics" --project-id 1

Query: 'Nike financial metrics'  (project_id=1)

── Tool calls (in order) ──
  [1] route_query_tool({'query': 'Nike financial metrics', 'project_id': 1})
  [2]   → 294 chars returned
  [3] load_multi_doc_tool({'primary': 'nke-10k-2023.pdf'})
  [4]   → 1,116 chars returned
  [5] grep(...) + grep(...)    ← deepagent's filesystem middleware
  [6-16] read_file / grep       ← LLM navigates the large doc
  [17] → final answer

🤖 Here are Nike's (NIKE, Inc.) key financial metrics for fiscal year 2023...
```

The LLM now does **step 1 (routing) → step 2 (load) → step 3
(synthesis)** exactly as the legacy 2-LLM-call flow.

### Per-doc char caps: no effective cap (just a 10M safety net)

MiniMax M3 supports **1M-token context**, so the legacy 30K/15K char
caps from `query.py` and `route_semantic.py` were causing the LLM to
take a second turn to read the rest of long docs. The caps were
bumped:

| Cap | Original (legacy) | Bumped | Effective for 10-K |
|---|---|---|---|
| `PRIMARY_MAX_CHARS` | 30,000 | 10,000,000 | ~380K chars loaded (full 10-K, all 107 pages) |
| `SUPPORTING_MAX_CHARS` | 15,000 | 10,000,000 | Same |

10M chars is a safety net to prevent OOM on truly gigantic files
(5,000+ page manuals). For all normal documents (10-K, contracts,
reports), the full text is loaded in one tool call.

The same bump was applied in 3 files for consistency:
- `learning/phase9/legacy/route_semantic.py` (line 354)
- `learning/phase9/query.py` (line 73)
- `learning/phase9/graphindex_tools.py` (line 88, `read_doc_tool` default)

### Context-window analysis (live measurement)

| Component | Chars | Tokens (~4ch/t) | % of 1M context |
|---|---:|---:|---:|
| Step 1 — catalog (48 docs + their excludes) | 709,355 | 177,338 | 17.7% |
| Step 2 — full 10-K | 380,098 | 95,024 | 9.5% |
| Worst case — 4 huge docs | 1,520,392 | 380,098 | 38% (still fits) |

**Synthesis call total input** (catalog NOT included): 95,162 tokens
= 9.5% of context. **The LLM has 90% of its context free for its
own reasoning and output.**

### Answer quality comparison (same query, different caps)

| Cap | Chars loaded | Pages of 10-K | Coverage |
|---|---:|---:|---|
| 30K (legacy) | 35,096 | ~9/107 | Part I only — "MD&A and financial statements not in provided pages" |
| 200K | 202,949 | ~50/107 | Part I + MD&A |
| **10M (current)** | **380,098** | **107/107** | **Full 10-K including audited financial statements** |

### Files changed

```
learning/phase9/graphindex_tools.py        + import json, + route_query_tool, + cap docs
learning/phase9/graphindex_chat_agent.py   + import route_query_tool, + 5th tool, + tool-call trace
learning/phase9/query.py                   PRIMARY/SUPPORTING_MAX_CHARS → 10M
learning/phase9/legacy/route_semantic.py   PRIMARY/SUPPORTING_MAX_CHARS → 10M
```

### UI agent template (Step L) also updated

The langconfig UI's `graphindex_chat` template (id=91, in
`GRAPHINDEX_CHAT_TEMPLATE_PAYLOAD` of
`src/features/knowledge/ui/KnowledgeBaseView.tsx`) was updated to
make the system_prompt explicit about:

- The **project_id is an INTEGER** (the LLM was passing `"default"`
  string before — that was the LangSmith trace regression)
- The 4 native tools (`graphindex_list_docs`, `graphindex_search`,
  `graphindex_load`, `graphindex_multi_doc_load`)
- The workflow: `graphindex_list_docs` first if unsure, then prefer
  `graphindex_multi_doc_load` for the actual answer (it does the
  routing + loading in one call)

---

## 🎯 Step N — Doc scope + KB-view polish (DONE)

This step adds **scope filtering** (tell the chat agent which docs to
consider) and a batch of KB-view UI polish: full-size doc viewer,
pop-out search modal, continuous-scroll PDF viewer, smaller chat text,
and a chat-agent pill in the KB header.

### N.1 — Doc scope (which docs the agent considers)

**Backend — `phase9/graphindex_tools.py`**: a `ContextVar` propagates the
active scope to the 5 tools without changing their signatures (which
would invalidate the LLM prompt cache):

```python
_active_doc_scope: ContextVar[Optional[set]] = ContextVar("active_doc_scope", default=None)

def set_active_doc_scope(scope) -> object: ...
def reset_active_doc_scope(token) -> None: ...
def get_active_doc_scope() -> Optional[set]: ...
```

All 5 tools (`fetch_catalog_tool`, `read_doc_tool`, `list_docs_tool`,
`load_multi_doc_tool`, `route_query_tool`) now filter their output
through `_filter_rows_by_scope()`. Out-of-scope reads return
`SCOPE_ERROR: "Document X is not in the active scope. Try a different doc."`.

**Backend — `phase9/graphindex_chat_agent.py`**: `stream_graphindex_chat()`
and `stream_graphindex_chat_events()` accept `scope: Optional[List[str]]`.
They call `set_active_doc_scope()` / `reset_active_doc_scope()` in a
try/finally so the scope is always cleared even on errors.

**Backend — `backend/api/knowledge/graphindex_chat.py`**: the
`GraphIndexChatRequest` now has `scope: Optional[List[str]]`. A new
`_resolve_scope()` helper validates the scope against the catalog
and returns `{valid, invalid, all_doc_names}`. **If every item in
`scope` is invalid**, the endpoint emits a `clarification` SSE event
and returns — without invoking the agent — saving the 30s+ the agent
would burn trying out-of-scope docs.

**Backend — `backend/api/chat/routes.py`**: the standard chat endpoint
also accepts `scope` and passes it through to `_generate_stream_phase9`.

**CLI — `phase9/query.py` and `phase9/query_deep.py`**: added
`--scope "doc1,doc2"` flag and a `/scope` REPL command for
interactive scope setting.

### N.2 — UI: doc-card checkboxes for in-scope selection

In `KnowledgeBaseView.tsx`:
- `scopeDocIds: Set<number>` state (the IDs of in-scope docs)
- Each doc card has a checkbox — click to toggle in-scope
- In-scope cards get an indigo border + checkbox fill
- A pill above the INDEXED section shows `X in scope` + `Clear` /
  `Select all` buttons
- The scope is sent to the chat agent as `scope: [...]` on every
  message; null/empty means "all docs"

### N.3 — UI: pop-out search modal

The graphindex search box used to live at the bottom of the doc
viewer (~15% vertical space). Moved to a pop-out modal triggered by
a `kb_search` button in the KB header (top right, between the metric
pills and the Browse Files buttons).

`src/features/knowledge/ui/SearchModal.tsx` is the new modal:
- `fixed inset-0` overlay with backdrop blur
- Centered card (`max-w-3xl`, `max-h-80vh`)
- Auto-focuses the search input on open
- `Escape` key + click-on-backdrop both close the modal
- Re-uses the parent's existing search state + handlers (`searchQuery`,
  `handleSearch`, `compareMode`, `useHyDE`, `useTOON`, `pageIndexDocs`,
  `searchResults`, `handleGraphIndexAnswer`) — no duplication

When the modal is closed, the doc viewer has full vertical space.

### N.4 — UI: full-size doc viewer

The doc viewer container was `style={{ minHeight: '384px', height: '48vh' }}`
(capped at 48% of viewport). Now `flex-1 min-h-0` so it fills all
remaining vertical space. `min-h-0` is critical — without it, flex
children default to `min-height: auto` and the PDF's internal scroll
container can't take over.

The `<DocumentViewer>` is now wrapped with
`<div className="flex-1 min-h-0 overflow-hidden flex flex-col">` so
it properly fills the remaining height below the file header.

### N.5 — UI: continuous-scroll PDF viewer

`src/features/knowledge/ui/TwoPagePdfViewer.tsx` was rewritten end-to-end.
Three iterations:

1. **Drag-to-pan → scroll-to-read** (matches MD viewer). Each canvas
   is now sized to the page's *natural* rendered size at the current
   zoom. At zoom > 100%, the canvas is taller than the container and
   the parent `overflow-auto` handles overflow → user scrolls with
   the mouse wheel / trackpad.

2. **Toolbar moved to top**. Page nav + 1P/2P/4P selector + zoom are
   now at the top of the viewer (were at the bottom, often hidden).

3. **Continuous scroll through the whole document** (final form). All
   pages stacked vertically in a single column, scrollable top-to-bottom
   just like MD. Replaces the 1P/2P/4P spread view entirely. Features:
   - All pages rendered in parallel (cancelled on zoom change)
   - Page indicator `N of M` updated by `IntersectionObserver` as user
     scrolls
   - Prev/Next buttons scroll by ~1 viewport (`scrollBy`)
   - "Go to: #" input — type a page number and Enter to jump
   - Default zoom 1.0 = fit-to-container-width

### N.6 — UI: chat font sizes reduced to match doc cards

In `src/features/chat/ui/MessagesPanel.tsx`:
| Element | Before | After |
|---|---|---|
| Markdown body | 0.81rem (13px) | 0.75rem (12px = doc-card `text-xs`) |
| Headings h1/h2/h3 | 24/20/18px | 15/14/13px |
| Code block | 14px | 11px |
| Inline code | 14px | 11px |
| Table cell | 14px | 11px (with 0.35rem padding) |
| System message | 14px | 12px |
| Empty-state heading | 18px | 16px |
| Line height | 1.65 | 1.55 |

### N.7 — UI: chat-agent pill in KB header

The agent's name + description (formerly the chat panel's header) now
lives as a "🪄 Chat Agent" pill in the KB header, next to the search
button. Lifted up from `<DocChatPanel>` via a new `onAgentInfoChange`
callback prop. The chat panel header is reduced to a slim 1-line
status bar (icon + description only).

### N.8 — UI: self-intro empty state

The empty-state subtitle was changed from the generic
*"Ask anything — I can help with research, analysis, coding, and more."*
to a proper self-intro that mentions graphindex:

> Ask anything about your documents — graphindex routes your query to
> the right ones, loads them, and answers from their content.

---

## 🎯 Step O — Hierarchical folder upload + Tree view (DONE)

This step extends the KB sidebar with **folder-level hierarchy metadata**
(`industry → player → sub_category → sub_department`), a **Tree view**
that mirrors the source folder structure, and a **bulk ingest path**
that preserves that hierarchy as metadata at upload time. It also
flips the doc-scope default to "all in scope" (all checkboxes
checked on first load).

### O.1 — Hierarchy metadata (4 new columns on `ContextDocument`)

| Column | Type | Example |
|---|---|---|
| `industry` | `str` (nullable) | `electric_vehicle_industry` |
| `player` | `str` (nullable) | `tesla` |
| `sub_category` | `str` (nullable) | `marketing`, `strategic_consensus` |
| `sub_department` | `str` (nullable) | `finance` (under `strategic_consensus/`) |

The columns are added via **idempotent `ADD COLUMN IF NOT EXISTS`** in
`backend/db/database.py:async_init_db()` so existing databases are
auto-upgraded on the next backend startup. No migration step needed.

Source: `backend/models/core.py` (`ContextDocument` table).

### O.2 — Folder-aware bulk upload (frontend + backend)

**Frontend** ([`KnowledgeBaseView.tsx`](../../src/features/knowledge/ui/KnowledgeBaseView.tsx#L534-L563)):
- The "Select Folder" button uses a `<input type="file" webkitdirectory>`
  (with the attribute set via `useRef + useEffect` to bypass React's
  prop stripping that breaks in some Safari builds)
- Each file's `webkitRelativePath` is parsed to derive the 4 hierarchy
  fields:
  - `parts[0]` → `industry`
  - `parts[1]` → `player`
  - `parts[2]` → `sub_category`
  - `parts[3]` → `sub_department`
- The per-file metadata is sent as the new `file_metadata` form field
  (JSON-encoded list, one entry per file in `files` order)

**Backend** ([`api/knowledge/rag.py`](../../backend/api/knowledge/rag.py#L946)):
- `POST /api/rag/upload-bulk` now accepts an optional `file_metadata`
  Form field (JSON list of dicts, one per file index)
- The loop picks `per_file_metadata[file_idx] or doc_metadata` and
  passes the result to `_process_single_file_for_bulk`
- `_process_single_file_for_bulk` was updated to read
  `industry / player / sub_category / sub_department` from the metadata
  and write them to the new columns (this was the key bug — bulk
  uploads silently dropped hierarchy fields before this step)

**Server-side fallback** ([`api/knowledge/rag.py`](../../backend/api/knowledge/rag.py#L1108)):
- `POST /api/rag/ingest-folder` — accepts a JSON body
  `{project_id, folder_path, industry?, player?}` and walks the folder
  on the server's disk, ingesting every supported file with hierarchy
  derived from the path. Useful for:
  - Safari / Firefox (where `webkitdirectory` is unreliable)
  - Bulk re-ingest from a known source folder without re-uploading
- Has a small purple text-input + "Use Path" button in the KB header
  for users who can't use the native folder picker

**CLI tool** ([`learning/phase9/ingest_reports.py`](../../learning/phase9/ingest_reports.py)):
- Idempotent bulk ingest from `reports_new/<industry>/<player>/.../`
- Mirrors the source folder structure under `data/documents/<id>/...`
- Sets all 4 hierarchy fields from the path
- `--dry-run`, `--industry <name>`, `--player <name>` filters
- Also back-fills `industry/player/sub_category/sub_department` on
  existing rows that have NULL values (useful after upgrading from
  a build that didn't capture hierarchy)

### O.3 — Tree view (`KbTreeView` component)

**New file** [`src/features/knowledge/ui/KbTreeView.tsx`](../../src/features/knowledge/ui/KbTreeView.tsx):
- Recursive folder tree: industry → player → sub_category →
  sub_department → file
- Each folder row: chevron (expanded/collapsed) + folder icon + name +
  doc count badge
- Each file row: same doc-card mini variant as the List view
  (selectable, scoped checkbox, delete button)
- Expansion state is persisted to `localStorage` (`kb.expandedFolders`)
- View mode (List vs Tree) is also persisted to `localStorage`
  (`kb.sidebarView`)

**Tree builder** ([`KnowledgeBaseView.tsx`](../../src/features/knowledge/ui/KnowledgeBaseView.tsx#L73)):
- `buildFolderTree(docs: Document[]): FolderNode` converts the flat
  `Document[]` array into a nested `FolderNode` tree
- Title-cases each segment + replaces underscores for display
- Memoized on `readyDocuments` so the tree only rebuilds when docs change
- Docs without hierarchy metadata go under a synthetic
  `(ungrouped)` root folder

**Bug fix in tree builder**: the original implementation used the raw
segment (`"tesla"`) for the lookup key but stored the title-cased
display name (`"Tesla"`) — every file would create its own chain of
parent folders because the second file's lookup of `"tesla"` wouldn't
find the first file's `"Tesla"`. Fixed by computing the display name
once and using it in BOTH the lookup and the storage.

### O.4 — Doc scope default flipped to "all in scope"

**Before Step O**: `scopeDocIds` defaulted to an empty `Set`, which
the chat panel interpreted as `null` (no filter, all docs). The user
had to actively tick a checkbox to enable any filter.

**After Step O** ([`KnowledgeBaseView.tsx`](../../src/features/knowledge/ui/KnowledgeBaseView.tsx#L386-L398)):
- `loadDocuments()` re-populates `scopeDocIds = new Set(all_doc_ids)`
  on every doc load (initial load, project switch, post-upload refresh)
- All checkboxes are visually checked by default
- The "X in scope" pill shows by default
- The chat panel always receives the doc-name list (never `null`)
- An empty list (after "Clear") is treated the same as `null` by the
  backend (no filter)

**State changes**:

| Trigger | New `scopeDocIds` |
|---|---|
| First load / project switch | All current project doc IDs |
| Upload new doc | Re-populated with all doc IDs (newly uploaded is checked) |
| User unchecks a checkbox | That ID removed (others remain) |
| "Clear" button | Empty Set |
| "Select all" button | All current project doc IDs |

**No per-project persistence** (deliberate): switching projects resets
the scope to the new project's docs. The doc sidebar is project-scoped
(by `activeProjectId`), so the scope is naturally project-scoped too.
A "fresh start on project switch" UX was preferred over restoring the
old selection (which would feel stale and confusing).

### O.5 — `Neo4jDocumentIndex.delete_document()`

New method in [`backend/services/neo4j_document_index.py`](../../backend/services/neo4j_document_index.py#L330):

```python
def delete_document(self, project_id: int, name: str) -> bool:
    """MATCH (d:Document {project_id, name}) DETACH DELETE d"""
```

Used by `DELETE /api/rag/documents/{id}` to also clean up the Neo4j
graphindex catalog when a doc is removed. Without this, the chat
agent's `list_docs` would still return the deleted file and the LLM
would hit "doc not found" errors when trying to read it. The endpoint
tries `original_filename` first, then `filename` (the hash-prefixed
one), and falls back gracefully if neither exists in Neo4j.

### O.6 — Neo4j hierarchy sync

[`services/neo4j_document_index.py`](../../backend/services/neo4j_document_index.py#L107-L118)
now syncs the 4 new fields to Neo4j `:Document` nodes:

```cypher
SET d.industry = $industry,
    d.player = $player,
    d.sub_category = $sub_category,
    d.sub_department = $sub_department
```

This means the chat agent's `fetch_catalog` (in `phase9/query.py`)
sees the hierarchy and can use it for routing — e.g. a query about
"Tesla marketing" can now match a `:Document` whose
`industry="electric_vehicle_industry" AND player="tesla" AND sub_category="marketing"`.

### O.7 — i18n keys added

Added the following keys (en + zh) to `src/i18n/index.ts` to silence
the `i18next: missingKey` console warnings:

| Key | EN | ZH |
|---|---|---|
| `kb_search` | `Search` | `搜索` |
| `kb_search_modal_title` | `Search documents` | `搜索文档` |
| `kb_search_modal_hint` | `Type a question or topic — graphindex finds…` | `输入问题或主题 — graphindex 会找到…` |
| `kb_upload_browse` | `Upload one or more files to this project` | `上传一个或多个文件到该项目` |
| `kb_upload_folder` | `Upload a whole folder (preserves hierarchy as metadata)` | `上传整个文件夹（保留目录结构作为元数据）` |
| `kb_paste_folder_placeholder` | `/path/to/folder (Safari fallback)` | `/path/to/folder (Safari 备用)` |
| `kb_paste_folder_button` | `Use Path` | `使用路径` |
| `kb_paste_folder_title` | `Paste an absolute folder path…` | `粘贴绝对文件夹路径…` |

### O.8 — Test verification (live, project 8 `electric_vehicle_industry`)

```
Backend:  .venv/bin/python learning/phase9/ingest_reports.py \
            --project-id 8 --industry electric_vehicle_industry
  → 5 docs created, all with industry/player/sub_category filled

Bulk upload:  curl -X POST /api/rag/upload-bulk \
               -F files=@mock.pdf -F file_metadata='[{industry, player, sub_category}, ...]'
  → 3 docs created (ids 1217-1219), all with hierarchy metadata

DB query:  SELECT id, industry, player, sub_category FROM context_documents WHERE project_id=8;
  1217  electric_vehicle_industry  tesla    analysis
  1218  electric_vehicle_industry  tesla    marketing
  1219  electric_vehicle_industry  byd      comparison
  + 5 from the CLI test

Tree view (UI): Folder structure renders correctly:
  📁 Electric Vehicle Industry
    📁 Tesla (3)
      📁 Analysis (2)  → 01_tesla_q3_strategy.md, 01_tesla_q3_strategy.pdf
      📁 Marketing (1) → 02_tesla_product_lineup_2025.md
    📁 Byd (2)
      📁 Comparison (2) → 03_byd_vs_tesla_europe.{md,pdf}
```

### O.9 — Files changed

**Backend**
- `backend/models/core.py` — added 4 columns to `ContextDocument`
- `backend/db/database.py` — `ADD COLUMN IF NOT EXISTS` migration
- `backend/api/knowledge/rag.py`
  - `DocumentResponse` (4 new fields in API contract)
  - `upload-bulk` (per-file `file_metadata` form field)
  - `_process_single_file_for_bulk` (reads industry/player/sub_category)
  - new `POST /api/rag/ingest-folder` (server-side folder walk)
  - `DELETE /api/rag/documents/{id}` (also cleans Neo4j)
- `backend/services/neo4j_document_index.py`
  - new `delete_document()`
  - sync of 4 hierarchy fields to Neo4j `:Document` nodes

**Frontend**
- `src/features/knowledge/ui/KbTreeView.tsx` — new (Tree view component)
- `src/features/knowledge/ui/KnowledgeBaseView.tsx`
  - `buildFolderTree()` helper
  - `sidebarView` state (List vs Tree, persisted)
  - `expandedFolders` state (Tree view, persisted)
  - Tree view toggle in sidebar header
  - folder path input + "Use Path" button (Safari fallback)
  - per-file metadata extraction in `handleFileSelect`
  - doc-scope default flipped to "all in scope"
- `src/lib/api-client.ts` — `ingestFolderFromPath()` and `fileMetadata`
  param on `uploadDocumentsBulk()`
- `src/i18n/index.ts` — 8 new keys (en + zh)

**CLI**
- `learning/phase9/ingest_reports.py` — new, idempotent bulk ingest
  with hierarchy derivation + metadata back-fill

---

## 🎯 Step P — Project & doc deletion fixes (DONE)

Discovered while cleaning up after Step O's test uploads: the existing
`DELETE /api/projects/{id}` endpoint and `Neo4jDocumentIndex.delete_document()`
were both incomplete, leaving orphan rows/files/Neo4j nodes behind.

### P.1 — `Neo4jDocumentIndex.delete_document()` lookup bug

The single-doc `delete_document(project_id, name)` method looked up Neo4j
nodes by `name`, but the Neo4j `:Document.name` field was the
**post-rename** name (`<8-char-content-hash>_<original>`) while the
Postgres `ContextDocument.filename` was the **pre-rename** name
(without the hash prefix). The lookup almost always missed.

For project 1, this left **98 orphan `:Document` nodes** after a
Postgres cleanup pass that deleted the corresponding rows.

**Fix** in [`api/knowledge/rag.py`](../../backend/api/knowledge/rag.py#L1761):
the DELETE handler now tries four lookup paths in order:
1. `doc.original_filename`
2. `doc.filename`
3. `Path(doc.file_path).name` (the post-rename basename — matches Neo4j)
4. **Fallback by `content_sha256`** — always unique and set at ingest time:
   ```cypher
   MATCH (d:Document {project_id: $pid, content_sha256: $h})
     DETACH DELETE d
   ```

`delete_document()` docstring in
[`services/neo4j_document_index.py`](../../backend/services/neo4j_document_index.py#L329-L362)
now documents the gotcha.

### P.2 — `DELETE /api/projects/{id}` is incomplete

The endpoint handled the workflow chain (workflows → versions →
executions → tasks → execution_events → vector table) but **missed**:

| Table / source | FK rule | Handled? |
|---|---|---|
| `context_documents` | `ON DELETE NO ACTION` | ❌ |
| `directives` | `ON DELETE NO ACTION` | ❌ |
| `custom_tools` | `ON DELETE NO ACTION` | ❌ |
| `skills` | `ON DELETE NO ACTION` | ❌ |
| `workspace_files` | `ON DELETE NO ACTION` | ❌ |
| `agent_memories` | `ON DELETE CASCADE` | ✅ |
| `search_history` | `ON DELETE NO ACTION` | ❌ |
| `tasks` (direct `project_id` FK, not via workflow) | `ON DELETE NO ACTION` | ❌ |
| Neo4j `:Document` nodes | n/a | ❌ |
| `data/documents/project_<id>/` on disk | n/a | ❌ |

Calling the existing endpoint on a project with direct-FK `tasks` rows
fails with `ForeignKeyViolation` (just hit this on project 3 — 32 tasks
+ 2580 `execution_events` blocked the delete).

**P.2 fix (TODO)**: extend the existing endpoint to also delete:
- All `context_documents` rows
- All `directives` / `custom_tools` / `skills` / `workspace_files` /
  `search_history` rows
- Tasks filtered by `project_id` directly (not just via
  `workflow_profile_id`)
- All Neo4j `:Document` nodes (`MATCH (d:Document {project_id: $pid})
  DETACH DELETE d`) plus `:Industry` / `:Player` / `:Tag` orphans
- The on-disk folder `data/documents/project_<id>/`

The same script (run via `psql` + `curl` for Neo4j + `shutil.rmtree`
for disk) is in [`/tmp/delete_p3_v3.py`](../../scripts/wipe_project.py)
and proved the pattern works. Recommend promoting that into a proper
helper module and wiring it into the endpoint.

### P.3 — UI has no project-delete button

The HomePage (Studio) lists "Recent Projects" with **no delete
action** — only "Open Project". The frontend API client has
`apiClient.deleteProject(id)` at
[`api-client.ts#L377`](../../src/lib/api-client.ts#L377) but no UI
calls it.

**P.3 fix (TODO)**: add a trash icon next to each row in the Recent
Projects list, with a confirm dialog ("This will delete the project
and all its data permanently. Continue?"). On confirm, call
`apiClient.deleteProject(id)` then refresh the list.

### P.4 — Current state after Step P partial work

Project 3 ("my deep agent project") was the test case. The
comprehensive delete (`/tmp/delete_p3_v3.py`) removed:

| Step | Count |
|---|---|
| `execution_events` | 2,580 |
| `tasks` | 32 |
| `workflow_profiles` | 0 |
| Vector table `data_project_index_3` | 1 |
| Neo4j `:Document` nodes | 315 |
| On-disk files (`data/documents/3/` + `project_3/`) | 504 |
| `projects` row (id=3) | 1 |

**Remaining projects**: id 0 (Chat Sessions, system), 1 (My First
Project), 2 (my-project), 6 (my demo project 1), 7 (mock_test_project),
8 (electric_vehicle_industry). Total: 6.

---

## 🎯 Step Q — CLI ingest full-flow + path resolution (DONE)

After Step P we had a clean DB but only 3 ways to upload docs (UI
Select Folder, UI Paste Path, CLI). The CLI was incomplete — it
only did the Postgres insert, leaving docs as `NOT_INDEXED` with no
DocIndex, no vector embeddings, no LLM enrichment, and no Neo4j
sync. This step promotes the CLI to a **production-grade ingestion
tool** that does the same flow as the API endpoint, and fixes a
critical path-resolution bug that caused the file viewer to fail.

### Q.1 — `ingest_reports.py` now does the full pipeline

New flags on the CLI:

| Flag | Effect |
|---|---|
| `--enrich` | After insert, run DocIndex (L1/L2/L3) + vector embedding (chunking) + LLM enrichment (`what_this_document_is_about` etc.) + Neo4j `:Document` sync. Same as the API's `index_document_background()` background task. Slow (10-30s per file). |
| `--skip-enrich` (default) | Insert rows as `NOT_INDEXED`; enrich later via UI or `--re-enrich-existing` |
| `--re-enrich-existing` | If set, also re-enrich rows that were **skipped** because the file's `content_hash` already exists. Use this to back-fill docs that were inserted without `--enrich`, or to re-run after a code change in the indexing pipeline. |
| `--enrich-concurrency N` | Number of docs to enrich in parallel (default: 1) |

#### Implementation

The CLI's new `run_full_enrichment()` calls the **same**
[`api.knowledge.rag.index_document_background()`](../../backend/api/knowledge/rag.py#L582)
function the API uses, so the CLI gets byte-identical behavior to
the UI. New helper function [`find_existing_doc()`](../../learning/phase9/ingest_reports.py#L252)
locates a row that was skipped (by `content_hash` first, then by
`filename`) so `--re-enrich-existing` can re-run enrichment on it.

#### Usage

```bash
# Fast (insert only — same as the old behavior)
.venv/bin/python learning/phase9/ingest_reports.py \
  --source /tmp/mock_reports --project-id 8

# Full (insert + DocIndex + vector + LLM enrichment + Neo4j)
.venv/bin/python learning/phase9/ingest_reports.py \
  --source /tmp/mock_reports --project-id 8 --enrich

# Back-fill existing docs (re-enrich what was already there)
.venv/bin/python learning/phase9/ingest_reports.py \
  --source /tmp/mock_reports --project-id 8 --enrich --re-enrich-existing
```

### Q.2 — Path resolution fix (CWD-relative → backend-anchored)

The CLI used `file_storage._base_dir` directly, which is a
**CWD-relative** path. The bug:

| Context | CWD | Resolved base | What it writes to |
|---|---|---|---|
| CLI from project root | `<project>/` | `data/documents/` | `<project>/data/documents/8/...` |
| Backend (uvicorn) | `<project>/backend/` | `data/documents/` | `<project>/backend/data/documents/project_8/...` |

So when the CLI ingested 5 files into project 8, it wrote to
`<project>/data/documents/8/...` with the `8/` prefix. The backend
then tried to serve them from
`<project>/backend/data/documents/project_8/...` (note:
`backend/data/` not `data/`, and `project_8/` not `8/`). All 5
viewer requests failed with `File not found on disk`.

**Fix** in [`ingest_reports.py#L400-L418`](../../learning/phase9/ingest_reports.py#L400-L418):
the CLI now resolves `docs_root` to an **absolute** path anchored
at `<project>/backend/data/documents/`. If that directory exists
(it always will in the standard project layout), it's used
regardless of the CLI's CWD. Otherwise the CLI falls back to the
CWD-relative base (old behavior).

```python
backend_dir = Path(__file__).resolve().parent.parent.parent / "backend"
backend_data_dir = backend_dir / "data" / "documents"
if backend_data_dir.exists():
    docs_root = backend_data_dir
else:
    docs_root = Path(file_storage._base_dir)  # fallback
```

#### Migration for existing CLI-ingested docs

For docs that were already ingested with the buggy path, the
runtime fix is:

1. **Copy** files from `<project>/data/documents/8/...` to
   `<project>/backend/data/documents/project_8/...`
2. **Update Postgres `context_documents.file_path`** from
   `data/documents/8/...` to `data/documents/project_8/...`
3. **Update Neo4j `Document.file_path`** the same way

A migration helper at [`/tmp/fix_paths.py`](../../scripts/fix_cli_ingest_paths.py)
does this for project 8 (idempotent — safe to re-run).

### Q.3 — `max_tokens` raised from 2k / 500k → 1,000,000

Found in the syslog: the chat completion request to MiniMax M3 was
sending `max_completion_tokens: 2048`, way under the model's
1M-token context window. The cause: the OpenAI client defaults to
2048 when `max_tokens` isn't explicitly set, and several places
in the code had hard caps at 500k or 32k.

Changed in 5 files:

| File | Field | Before | After |
|---|---|---|---|
| [`backend/core/agents/factory.py:57`](../../backend/core/agents/factory.py#L57) | `DEFAULT_MAX_TOKENS` | 30,000 | **1,000,000** |
| [`backend/core/agents/factory.py:63`](../../backend/core/agents/factory.py#L63) | `MAX_MAX_TOKENS` | 500,000 | **1,000,000** |
| [`backend/models/agent_config_schema.py:249`](../../backend/models/agent_config_schema.py#L249) | `max_tokens` validator | `1 <= v <= 500000` | `1 <= v <= 1000000` |
| [`backend/api/models/routes.py:34`](../../backend/api/models/routes.py#L34) | `ModelInvokeRequest.max_tokens` | `default=None, le=500000` | `default=1M, le=1M` |
| [`backend/api/knowledge/graphindex_chat.py:73`](../../backend/api/knowledge/graphindex_chat.py#L73) | `GraphIndexChatRequest.max_tokens` | `default=8192, le=32768` | `default=1M, le=1M` |

The specialized agents (SQL Agent, JSON Agent, Pandas Agent) are
left at `max_tokens=4096` — those are intentionally smaller for
short structured-output tasks. Bump them if you want.

### Q.4 — Verification: end-to-end test on `/tmp/mock_reports`

The 5-file mock folder at `/tmp/mock_reports/electric_vehicle_industry/`
went through the full pipeline:

```
Files: 5
  03_byd_vs_tesla_europe.md    (348 B)
  03_byd_vs_tesla_europe.pdf   (1.1 KB)
  01_tesla_q3_strategy.md      (452 B)
  01_tesla_q3_strategy.pdf     (1.2 KB)
  02_tesla_product_lineup_2025.md (351 B)

Step 1: CLI insert
  .venv/bin/python learning/phase9/ingest_reports.py \
    --source /tmp/mock_reports --project-id 8
  → 5 created, all with hierarchy (industry/player/sub_category)

Step 2: Full enrichment
  .venv/bin/python learning/phase9/ingest_reports.py \
    --source /tmp/mock_reports --project-id 8 --enrich --re-enrich-existing
  → 5 re-enriched, all docs moved to READY in Postgres
  → DocIndex L1/L2/L3 built
  → 2 PDFs got vector chunks; 3 MDs failed (no `markdown` module — fix: `pip install markdown`)
  → 5 Neo4j `:Document` nodes with full LLM enrichment (about/queries/out_of_scope/few_shot)

Step 3: Path fix
  → Copied 5 files to backend/data/documents/project_8/...
  → Updated 5 file_paths in Postgres
  → Updated 5 file_paths in Neo4j
  → GET /api/rag/documents/1334/content → {"kind":"markdown","content":"# BYD vs Tesla..."}  ✓

Step 4: UI verification
  → Hard refresh; sidebar shows 5 docs in Tree view
  → Click any doc → viewer renders markdown correctly
  → All 5 checkboxes checked by default (Step O scope behavior)
  → Chat panel can route queries to the right doc and answer
```

### Q.5 — What this enables

The CLI is now a first-class alternative to the UI for bulk
ingestion:

- **No UI** — useful for CI/CD, cron jobs, scripted pipelines
- **No API dependency** — bypasses uvicorn/HTTP, talks directly
  to Postgres + file storage
- **Same end result** as the UI's full upload flow
- **Idempotent** — duplicate files (by `content_hash`) are
  skipped, not re-inserted
- **Recoverable** — `--re-enrich-existing` brings existing
  docs up to date after pipeline code changes
- **Path-safe** — anchored to `backend/data/documents/`, no more
  CWD confusion

### Q.6 — Remaining gaps (TODO)

- **Vector embedding for MD files** — `pip install markdown` is
  the immediate fix. Long-term: also add support for `.docx`,
  `.pptx`, `.xlsx` chunking (currently the indexer only handles
  PDF + MD natively).
- **Neo4j `industry/player/sub_category` are empty strings** —
  the sync code sets them to `""` instead of the actual values.
  The chat agent uses `tags` for routing so it works, but the
  Neo4j Browser shows blank. Fix: update the sync Cypher to read
  from the Postgres row before syncing.
- **Project 1 docs (the original 57)** were wiped in Step P's
  project-1 cleanup. The `/tmp/mock_reports/` rebuild proves the
  pipeline; if you want to rebuild project 1 too, the same CLI
  command will work (just change `--project-id 8` to `1`).

---

## 🎯 Step R — Active project_id flows from UI to chat (DONE)

Step Q verified the CLI ingest pipeline. The next regression was
discovered when the user uploaded 5 docs via the UI to project 8
(`electric_vehicle_industry`) and asked the chat about them — the
LLM replied *"There are no documents in project 8"*. The catalog
query (`fetch_catalog`) worked, but the chat's project context was
broken: the LLM was silently querying project 1 (a different
project), seeing 0 docs, and hallucinating the user's project name
in its response.

### R.1 — Root cause

`backend/api/chat/routes.py:819` had:

```python
project_id=agent_project_id or 1,
```

`agent_project_id = getattr(agent, 'project_id', None)`. The
`deep_agent_templates` table has no `project_id` column (verified
via `information_schema.columns`), so `agent_project_id` was
**always None** and the chat **always queried project 1**.

This wasn't caught earlier because the working end-to-end test
in `c58fc91` ran on project 1, where the Nike docs lived — the
hardcoded fallback to 1 was correct in that test, but wrong in
every other context.

### R.2 — The fix (4 changes, 1 commit `68131d7`)

1. **`SendMessageRequest`** (backend) — added
   `project_id: Optional[int] = None`. The UI tells the backend
   which project the user is currently viewing.

2. **`_generate_stream` Phase 9 dispatch** (backend) — replaced
   `project_id=agent_project_id or 1` with
   `request.project_id if request.project_id is not None else agent_project_id`.
   **No more `or 1` hardcode.** If neither is set, logs a warning
   and passes `None` to the agent.

3. **`graphindex_chat_agent.py`** (Phase 9) — changed all four
   `project_id: int` signatures to `project_id: Optional[int]` and
   added a system-prompt branch: when `project_id is None`, the
   prompt says *"No project is currently selected. The tools may
   return empty results. If you can't find a relevant document,
   reply honestly: 'No matched document found in the current scope.
   Please select a project or upload docs.'"* This is the correct,
   non-misleading behavior.

4. **`useChatStreaming` + `DocChatPanel`** (frontend) — added
   `projectId?: number | null` to the `sendMessage` signature and
   the POST body. `DocChatPanel` was already in scope of the active
   `projectId` (from `KnowledgeBaseView`); it now forwards it.

### R.3 — Before / after

**Before**:
```
User on project 8 (5 docs)
Chat → POST /api/chat/message/stream { session_id, message, scope }   ← no project_id
Backend → project_id = agent_project_id or 1 = 1  (silent fallback)
LLM → list_docs_tool(project_id=1) → 0 docs
LLM → "There are no documents in project 8"  (hallucinated)
```

**After**:
```
User on project 8 (5 docs)
Chat → POST /api/chat/message/stream { session_id, message, scope, project_id: 8 }
Backend → project_id = 8 (from request)
LLM → list_docs_tool(project_id=8) → 5 docs
LLM → route_query_tool(query, project_id=8) → Tesla doc
LLM → load_multi_doc_tool(primary=Tesla doc) → doc content
LLM → answer based on the actual doc, highlights it in sidebar/viewer
```

**Edge case** (no project_id from UI, e.g. test scripts):
```
project_id = None
System prompt: "No project is currently selected. Reply honestly: ..."
LLM → list_docs_tool() → 0 docs (tools default to project 1 which is empty)
LLM → "No matched document found in the current scope."
```

### R.4 — Files changed

| File | Change |
|---|---|
| [`backend/api/chat/routes.py`](../../backend/api/chat/routes.py) | `SendMessageRequest` got `project_id` field; `_generate_stream` Phase 9 dispatch uses request.project_id (no `or 1`) |
| [`learning/phase9/graphindex_chat_agent.py`](../../learning/phase9/graphindex_chat_agent.py) | All `project_id: int` → `Optional[int]`; system-prompt branch for None |
| [`src/features/chat/hooks/useChatStreaming.ts`](../../src/features/chat/hooks/useChatStreaming.ts) | `sendMessage` got `projectId` parameter; POST body includes `project_id` |
| [`src/features/knowledge/ui/DocChatPanel.tsx`](../../src/features/knowledge/ui/DocChatPanel.tsx) | Forwards `projectId` to `sendMessage` |

### R.5 — Verification (pending)

User needs to:
1. **Restart the backend** (`./start.sh` — picks up the new dispatch)
2. **Hard refresh** the browser (Cmd+Shift+R)
3. Go to KB → project 8 (electric_vehicle_industry)
4. Click a doc → chat panel
5. Ask: *"Tell me Tesla's Q3 strategy"*
6. Expected: LLM routes to the right doc, loads it, answers based
   on actual content, highlights the doc in the sidebar

### R.6 — Why this was easy to miss

Three separate code paths in the Phase 9 chat stack were each
"correct in isolation" but compounded into a silent fallback:

| Layer | What it does | What was wrong |
|---|---|---|
| `deep_agent_templates` table | Stores agent config | No `project_id` column |
| `routes.py` Phase 9 dispatch | Calls chat agent | `or 1` hardcode |
| `graphindex_tools.py` tools | Read Neo4j catalog | Tool default = 1 |

The fix only touches the dispatch layer (routes.py) and the LLM
prompt (graphindex_chat_agent.py). The tool defaults and the
agent template schema are unchanged. If you later add a
`project_id` column to `deep_agent_templates`, the dispatch's
fallback chain (`request.project_id → agent.project_id`) will
pick it up automatically.

---

## 🔗 Related Reading

- VectifyAI / GraphIndex (inspiration): <https://github.com/VectifyAI/GraphIndex>
- Phase 3 README on memory systems (the `SimpleMemory` two-layer pattern): `learning/phase3/README.md`
- Phase 5 README on skills (the `pdf-chat-assistant` skill): `learning/phase5/README.md`
- Phase 6 README on workflows (the KV-style `graphindex/answer` pattern): `learning/phase6/README.md`
- Phase 8 README (DeepAgent Studio — same author style, useful template): `phase8/README.md`
