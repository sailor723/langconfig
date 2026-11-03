"""The one definition of "which blocks does this SEMANTICS.md have".

Split out of `langgraph_semantic.py` because two callers need it:

* the graph's `load_semantics` node, which decides what the model is shown, and
* the semantics editor (`api/semantics/routes.py`), which tells the author which
  blocks the loader will find.

They must agree. When the API kept its own copy, the two disagreed immediately —
the editor reported `['semantic']` for a file the loader split into
`['schema', 'semantic', 'examples']`, because the copies matched different
headings. Importing this module is cheap: it has no model, no database and no
graph, unlike `langgraph_semantic` (whose import compiles the graph and connects
to Chinook).
"""
from __future__ import annotations

import re

# A section heading: two or more '#', then the title.
_HEADING = re.compile(r"^#{2,6}\s+\S")

# Which heading keywords land in which block. Anything else is dropped rather
# than guessed at — a section the loader cannot classify must not silently become
# business rules.
BLOCK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "schema": ("schema", "表", "table", "column", "列"),
    "semantic": ("业务", "指标", "过滤", "规则", "business", "kpi", "rule", "口径"),
    "examples": ("示例", "example", "sql", "few"),
}


def semantic_blocks(text: str) -> dict[str, str]:
    """Split a SEMANTICS.md into the three blocks a SQL prompt can use.

    Deliberately dumb: heading keywords, no LLM. A file whose headings say
    "Schema / 业务逻辑 / 示例" lands in schema / semantic / examples; anything else is
    dropped.
    """
    blocks: dict[str, list[str]] = {"schema": [], "semantic": [], "examples": []}
    current: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if current and buf:
            body = "\n".join(buf).strip()
            if body:
                blocks[current].append(body)

    for line in text.splitlines():
        # "##" and deeper. `startswith("## ")` missed "### 口径规则", which silently
        # emptied every block for a whole file — the failure the editor now shows.
        if _HEADING.match(line):
            flush()
            title = line.lstrip("#").strip().lower()
            current = None
            for name, keys in BLOCK_KEYWORDS.items():
                if any(k in title for k in keys):
                    current = name
                    break
            buf = [line]
            continue
        if current is not None:
            buf.append(line)
    flush()
    return {k: "\n\n".join(v) for k, v in blocks.items()}


def present_blocks(text: str) -> list[str]:
    """Names of the blocks that actually carry text, in canonical order."""
    found = semantic_blocks(text)
    return [name for name in ("schema", "semantic", "examples") if found.get(name)]
