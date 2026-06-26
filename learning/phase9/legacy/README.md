# Phase 9 / legacy scripts

These are the **original** Phase 9 scripts that use raw `llm.invoke([messages])`
calls directly. They are preserved for:

1. **Reference** — shows the evolution from raw-LLM to DeepAgent to
   native-tool architecture.
2. **Helper functions** — many helper functions (e.g. `make_llm`,
   `extract_document_enrichment`, `load_document_content`) are reused
   by the current scripts in `phase9/`.

## Files

| File | What it is | Status |
|---|---|---|
| `build_graphindex.py` | Original GraphIndex builder CLI (`--ingest`, `--rebuild-one`, `--rebuild-project`). **Also exports helper functions** (DOCS_BASE, make_llm, extract_document_enrichment, load_document_content, load_graphindex_metadata, SUPPORTED_EXTS) reused by the modern scripts. | **Utility module** — kept here but the helper functions are still used. |
| `route_semantic.py` | Original LLM semantic router (`--query`, `--show-catalog`, `--compare`). | **Legacy CLI** — superseded by `phase9/query.py`. |
| `dv_chat.py` | Original DV chat REPL (read one PDF, then chat). | **Legacy CLI** — superseded by Phase 9 native tools. |
| `eval_routing.py` | Original eval suite (14 hand-labeled queries, string vs LLM). **Also exports** `EVAL_QUERIES` reused by `eval_routing_deep.py`. | **Utility + legacy eval**. |

## How current scripts use these

```python
# phase9/build_graphindex_clean.py
from legacy.build_graphindex import (
    DOCS_BASE,
    SUPPORTED_EXTS,
    extract_document_enrichment,
    load_document_content,
    load_graphindex_metadata,
    make_llm,
)

# phase9/buildindex_tools.py
from legacy.build_graphindex import (
    DOCS_BASE,
    SUPPORTED_EXTS,
    make_llm,
    extract_document_enrichment,
    load_document_content,
)

# phase9/eval_routing_deep.py
from legacy.eval_routing import (
    EVAL_QUERIES,
    run_string_eval,
    run_llm_eval,
    summarize as summarize_results,
    render_report as render_legacy_report,
    Neo4jDocumentIndex,
    fetch_catalog,
)
```

## Running legacy CLIs

They are still runnable from the new location:

```bash
# All paths must be from project root so the `from legacy.xxx` import works
cd /Users/weiping/dev/Learn/langchain-ai/langconfig

# Original build CLI (deprecated — use build_graphindex_clean.py instead)
python phase9/legacy/build_graphindex.py --show nke-10k-2023.pdf

# Original semantic router (deprecated — use query.py instead)
python phase9/legacy/route_semantic.py --query "Nike revenue 2023"

# Original eval (deprecated — use eval_routing_deep.py instead)
python phase9/legacy/eval_routing.py

# Original chat REPL (deprecated — use query.py chat instead)
python phase9/legacy/dv_chat.py
```

## Why are these still here?

We promised "no deletions" — these scripts have been the foundation of
Phase 9 development, and their helper functions are still imported.
Moving them to `legacy/` keeps `phase9/` clean while preserving the
historical record.

## When to delete

Once `phase9/build_graphindex_clean.py` and friends have fully replaced
the `legacy/` functions, the legacy scripts can be deleted. For now,
they're the source of helpers we don't want to duplicate.
