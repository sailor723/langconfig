"""Phase 9 legacy scripts (raw `llm.invoke` style).

These scripts were the first drafts of the Phase 9 GraphIndex system,
using direct `llm.invoke([messages])` calls. They are kept for
historical reference and as the source of helper functions that the
modern (current) scripts reuse:

  - build_graphindex.py  ->  build_graphindex_clean.py, buildindex_tools.py
  - route_semantic.py    ->  graphindex_tools.py, dv_chat.py (self)
  - eval_routing.py      ->  eval_routing_deep.py (reuses EVAL_QUERIES + helpers)
  - dv_chat.py           ->  standalone REPL

Current (recommended) Phase 9 scripts live one level up in phase9/:
  - build_graphindex_clean.py  (pure Python + 1 LLM call, recommended)
  - build_graphindex_deep.py   (DeepAgent-based, 3 subagents)
  - query.py                   (aggregator CLI)
  - query_agent.py             (DeepAgent query factory)

Imports from current scripts use:
  from legacy.build_graphindex import (DOCS_BASE, make_llm, ...)
  from legacy.eval_routing      import (EVAL_QUERIES, run_string_eval, ...)
"""