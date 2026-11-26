"""Additive tool merge must never *skip* a tool because its id is taken.

The merge shipped with `AND NOT EXISTS (SELECT 1 FROM custom_tools WHERE id = 225)`, so on a
machine that had made its own tools (the ECS: 89 rows where the library has 72) the ids 221 /
224 / 225 were already used — and `ontology_publish`, `ontology_open`, `ontology_inspect` were
silently dropped while the merge printed "0 tool(s) added". A missing tool row is invisible:
the agent simply cannot call it and reports "this failed".

The contract these tests pin down:

* the only skip condition is `tool_id` (union semantics — never touch a row that exists);
* an `id` that is already taken makes the row take a sequence value instead of being dropped.
"""
from __future__ import annotations

import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MERGE = BACKEND / "scripts/seeds/in/custom_tools_merge.sql"
GENERATOR = BACKEND / "scripts/seeds/out/export_tools_merge.py"

SKIP_BY_ID = "AND NOT EXISTS (SELECT 1 FROM custom_tools WHERE id = "
NEXT_ID = "nextval(pg_get_serial_sequence('custom_tools', 'id'))"


def test_merge_does_not_skip_a_tool_when_its_id_is_taken():
    sql = MERGE.read_text(encoding="utf-8")
    assert SKIP_BY_ID not in sql, (
        "custom_tools_merge.sql still drops a tool when its id is occupied — "
        "regenerate with scripts/seeds/out/export_tools_merge.py")
    inserts = len(re.findall(r"INSERT INTO custom_tools \(", sql))
    assert inserts > 0, "the merge file has no INSERTs at all"
    assert sql.count(NEXT_ID) >= inserts, (
        f"{inserts} INSERT(s) but only {sql.count(NEXT_ID)} sequence fallback(s): "
        "a taken id would still skip the row")


def test_generator_emits_the_sequence_fallback():
    src = GENERATOR.read_text(encoding="utf-8")
    assert "nextval(pg_get_serial_sequence('custom_tools', 'id'))" in src
    assert SKIP_BY_ID not in src, "the generator still emits the skip-by-id guard"
