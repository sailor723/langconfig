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

## 🎯 Step A — DeepAgent unified architecture (DONE)

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

---

## 🔗 Related Reading

- VectifyAI / GraphIndex (inspiration): <https://github.com/VectifyAI/GraphIndex>
- Phase 3 README on memory systems (the `SimpleMemory` two-layer pattern): `learning/phase3/README.md`
- Phase 5 README on skills (the `pdf-chat-assistant` skill): `learning/phase5/README.md`
- Phase 6 README on workflows (the KV-style `graphindex/answer` pattern): `learning/phase6/README.md`
- Phase 8 README (DeepAgent Studio — same author style, useful template): `phase8/README.md`
