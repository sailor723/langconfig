"""Smoke tests for the ER / Neo4j network diagram helpers in
backend/api/graph_studio/routes.py.

Run while Postgres (with chinook) and Neo4j (with docker seed) are reachable.
Tests skip gracefully when the corresponding DB is unavailable — same
pattern as test_sql_agent.py and test_neo4j_agent.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `config` (backend/) and the langgraph setup modules importable when
# this script runs standalone.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "langgraph"))

import pytest

from api.graph_studio import routes as gs

try:
    import sql_setup_db  # noqa: F401 - imported for connectivity check
except Exception:
    sql_setup_db = None

try:
    import neo4j_setup_db  # noqa: F401 - imported for connectivity check
except Exception:
    neo4j_setup_db = None


def _pg_ok() -> bool:
    """True when the SQL helper can introspect at least one table."""
    if sql_setup_db is None:
        return False
    try:
        conn = sql_setup_db._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_type='BASE TABLE'"
                )
                return cur.fetchone()[0] > 0
        finally:
            conn.close()
    except Exception:
        return False


def _neo4j_ok() -> bool:
    """True when the Neo4j driver can reach a populated database."""
    if neo4j_setup_db is None:
        return False
    try:
        meta = neo4j_setup_db.ensure_neo4j_db()
        return bool(meta.get("labels"))
    except Exception:
        return False


# ── SQL / ER diagram ────────────────────────────────────────────────────


def test_er_diagram_sql_payload():
    if not _pg_ok():
        pytest.skip("Postgres / chinook unreachable")
    dbname = sql_setup_db.get_target_database()
    payload = gs._er_diagram_payload(dbname, "public")
    assert payload is not None, "ER diagram payload should not be None"
    assert payload["schema"] == "public"
    assert isinstance(payload["tables"], list)
    assert len(payload["tables"]) > 0, "expected tables in the active DB"
    # Tables have name + columns + row_count; at least one table should
    # have a non-empty column list.
    assert any(t["columns"] for t in payload["tables"]), (
        "expected at least one table with columns"
    )
    # FKs list is allowed to be empty (not all DBs have FKs).
    assert isinstance(payload["foreign_keys"], list)
    # Column shape: each column must carry the four fields the renderer needs.
    for t in payload["tables"]:
        for c in t["columns"]:
            assert {"name", "type", "nullable", "pk"} <= set(c.keys), (
                f"column {t['name']}.{c['name']} missing fields: {c}"
            )
    # FK shape: each FK must carry the seven fields the renderer needs.
    for fk in payload["foreign_keys"]:
        assert {
            "from_table", "from_column",
            "to_table", "to_column",
            "constraint_name", "on_update", "on_delete",
        } <= set(fk.keys), f"FK {fk.get('constraint_name')} missing fields: {fk}"


def test_er_diagram_caching():
    """Second call should hit the cache (same dict instance)."""
    if not _pg_ok():
        pytest.skip("Postgres / chinook unreachable")
    dbname = sql_setup_db.get_target_database()
    p1 = gs._er_diagram_payload(dbname, "public")
    p2 = gs._er_diagram_payload(dbname, "public")
    assert p1 is p2


def test_er_diagram_invalid_schema():
    """An unknown schema should yield an empty payload (or None) — never raise."""
    if not _pg_ok():
        pytest.skip("Postgres / chinook unreachable")
    dbname = sql_setup_db.get_target_database()
    payload = gs._er_diagram_payload(
        dbname, "this_schema_definitely_does_not_exist_xyz"
    )
    # Either None (connection failed) or an empty payload (queried ok, empty).
    assert payload is None or (
        payload["tables"] == [] and payload["foreign_keys"] == []
    )


# ── Neo4j / network diagram ────────────────────────────────────────────


def test_neo4j_network_payload():
    if not _neo4j_ok():
        pytest.skip("Neo4j unreachable")
    dbname = neo4j_setup_db.get_target_database()
    payload = gs._neo4j_network_payload(dbname)
    assert payload is not None, "Neo4j network payload should not be None"
    assert isinstance(payload["label_nodes"], list)
    assert isinstance(payload["rel_edges"], list)
    # Every label_node has the three fields the renderer needs.
    for l in payload["label_nodes"]:
        assert {"name", "count", "properties"} <= set(l.keys), (
            f"label_node {l.get('name')} missing fields: {l}"
        )
    # Every rel_edge references a label that exists in label_nodes.
    labels = {l["name"] for l in payload["label_nodes"]}
    for e in payload["rel_edges"]:
        assert {"type", "from_label", "to_label", "count"} <= set(e.keys), (
            f"rel_edge {e.get('type')} missing fields: {e}"
        )
        assert e["from_label"] in labels, (
            f"rel_edge {e['type']} references unknown from_label '{e['from_label']}'"
        )
        assert e["to_label"] in labels, (
            f"rel_edge {e['type']} references unknown to_label '{e['to_label']}'"
        )


def test_neo4j_network_caching():
    if not _neo4j_ok():
        pytest.skip("Neo4j unreachable")
    dbname = neo4j_setup_db.get_target_database()
    p1 = gs._neo4j_network_payload(dbname)
    p2 = gs._neo4j_network_payload(dbname)
    assert p1 is p2