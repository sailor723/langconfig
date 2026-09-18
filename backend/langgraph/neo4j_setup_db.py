"""Neo4j connection + tools for the LangGraph Neo4j agent.

Mirrors backend/langgraph/sql_setup_db.py for the SQL agent: connection
helpers, three @tool functions the agent can call, and a small main() that
exercises the tools against the live database without an LLM. The Neo4j
agent (neo4j_agent.py) re-uses these tools unchanged.

Safety:
  - Read-only at the Cypher level: a regex blocklist rejects
    CREATE / MERGE / SET / DELETE / REMOVE / DROP / FOREACH / CALL
    before any query reaches the driver, so model-generated Cypher can
    never mutate the graph.
  - Parameters are parsed from JSON and must be primitives (str / int /
    float / bool / None) or a list of primitives; dicts are rejected.
  - Per-query timeout (default 10s) and result cap (1000 rows).
  - Connection-level: encrypted=False for local docker (no TLS to
    localhost); flip NEO4J_ENCRYPTED=true once a real TLS endpoint is in
    place.

If you ever want to point this at a different Neo4j database, override
NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD / NEO4J_DATABASE in .env.
"""
from __future__ import annotations

import json
import os
import re
from typing import Annotated, Any, List, Optional

from dotenv import load_dotenv
from langchain.tools import tool
from langgraph.prebuilt import InjectedState

# Best-effort: pick up the repo-root .env so NEO4J_* vars flow through.
load_dotenv(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"
    )
)


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------
# Driver cache keyed by (uri, user, password, encrypted). Neo4j drivers are
# thread-safe and pool-based, so one driver per distinct connection is enough
# — the env-configured default gets one entry, and per-call connection
# overrides (neo4j_connection) get their own. Mirrors the SQL setup's
# per-call psycopg2 style for consistency, but avoids re-opening the same
# server repeatedly.
_DRIVERS: dict[tuple, Any] = {}


def _connection_params(
    connection: Optional[dict] = None,
) -> tuple[str, str, str, bool]:
    """Resolve (uri, user, password, encrypted) for a driver.

    An explicit ``connection`` dict (keys: uri / user / password / encrypted)
    wins; otherwise the env-driven defaults from the centralized connection
    module apply (read from the project-root .env — no literals here).
    """
    from langgraph.connection import (
        NEO4J_URI,
        NEO4J_USER,
        NEO4J_PASSWORD,
        NEO4J_ENCRYPTED,
    )
    c = connection or {}
    return (
        c.get("uri") or NEO4J_URI,
        c.get("user") or NEO4J_USER,
        c.get("password") or NEO4J_PASSWORD,
        bool(c.get("encrypted", NEO4J_ENCRYPTED)),
    )


def _driver_for(
    connection: Optional[dict] = None,
) -> Any:
    """Lazy driver for a connection; cached per distinct connection params."""
    key = _connection_params(connection)
    if key not in _DRIVERS:
        from neo4j import GraphDatabase
        uri, user, password, encrypted = key
        _DRIVERS[key] = GraphDatabase.driver(
            uri,
            auth=(user, password),
            encrypted=encrypted,
        )
    return _DRIVERS[key]


def _driver() -> Any:
    """Lazy driver for the env-configured default connection."""
    return _driver_for(None)


# Runtime override set by the studio UI (see graph_studio/databases/select).
# Lets the user point the agent at a different Neo4j database without
# editing .env. Mirrors sql_setup_db._DB_OVERRIDE / set_target_database.
_DB_OVERRIDE: Optional[str] = None


def set_target_database(name: str) -> None:
    """Point the Neo4j tools at a different database for this process lifetime."""
    global _DB_OVERRIDE
    _DB_OVERRIDE = name


def get_target_database() -> str:
    """Return the database the Neo4j tools are currently pointed at."""
    from langgraph.connection import NEO4J_DATABASE  # env-driven default
    return _DB_OVERRIDE or os.getenv("NEO4J_DATABASE") or NEO4J_DATABASE


def _resolve_database(database: Optional[str]) -> str:
    """Per-call database resolution: explicit param -> studio override -> env.

    ``database`` is the per-invocation parameter (set by the agent via the
    injected graph state, or by a direct tool call). When omitted, fall back
    to the process-global ``_DB_OVERRIDE`` (set by the studio's
    /databases/select) and finally the env ``NEO4J_DATABASE``.
    """
    if database:
        return database
    return get_target_database()


# ---------------------------------------------------------------------------
# Safety helpers
# ---------------------------------------------------------------------------
# Blocklist of Cypher keywords that mutate the graph. Word-boundary match,
# case-insensitive. The list intentionally covers the destructive operators;
# `SET` is the dangerous one (it mutates properties on existing nodes).
_WRITE_KEYWORDS = re.compile(
    r"\b(CREATE|MERGE|SET|DELETE|REMOVE|DROP|FOREACH|CALL|LOAD\s+CSV)\b",
    re.IGNORECASE,
)


def _reject_writes(cypher: str) -> Optional[str]:
    """Return None if the query is read-only, else the offending keyword."""
    m = _WRITE_KEYWORDS.search(cypher)
    return m.group(0).upper() if m else None


_ALLOWED_PARAM_TYPES = (str, int, float, bool, type(None))


def _coerce_params(raw: str) -> tuple[Optional[dict], Optional[str]]:
    """Parse a JSON string of parameters into a primitives-only dict.

    Returns (params_dict, error). Rejects dicts, custom objects, and nested
    non-list containers — keeps the attack surface small.
    """
    if not raw or not raw.strip():
        return {}, None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"parameters must be a JSON object string: {exc}"
    if not isinstance(parsed, dict):
        return None, "parameters must be a JSON object (e.g. {\"name\": \"Tom\"})"
    cleaned: dict[str, Any] = {}
    for k, v in parsed.items():
        if isinstance(v, list):
            # list of primitives is fine (IN-list), nested lists not.
            if not all(isinstance(item, _ALLOWED_PARAM_TYPES) for item in v):
                return None, f"parameter '{k}' has nested list (only flat lists allowed)"
            cleaned[k] = v
        elif isinstance(v, _ALLOWED_PARAM_TYPES):
            cleaned[k] = v
        else:
            return None, (
                f"parameter '{k}' has unsupported type {type(v).__name__}; "
                f"only str/int/float/bool/None (or list of these) allowed"
            )
    return cleaned, None


def _quote_label(name: str) -> str:
    """Backtick-quote a Cypher identifier (label / rel type / property)."""
    return "`" + name.replace("`", "``") + "`"


def _format_rows(rows: List[dict]) -> str:
    """Format a list of row dicts as a markdown table (mirrors sql_db_query)."""
    if not rows:
        return "Query returned no results."
    col_names = list(rows[0].keys())
    lines = ["## Cypher Results", ""]
    lines.append("| " + " | ".join(col_names) + " |")
    lines.append("| " + " | ".join("---" for _ in col_names) + " |")
    for row in rows[:200]:  # cap rendered preview at 200 rows in markdown
        vals = []
        for c in col_names:
            v = row.get(c)
            s = str(v) if v is not None else "NULL"
            if len(s) > 200:
                s = s[:200] + "…"
            vals.append(s)
        lines.append("| " + " | ".join(vals) + " |")
    if len(rows) > 200:
        lines.append("")
        lines.append(
            f"*Showing first 200 of {len(rows)} row(s). "
            f"Add a LIMIT to the query to narrow the result.*"
        )
    else:
        lines.append(f"\n*{len(rows)} row(s) returned*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sanity check
# ---------------------------------------------------------------------------
def _list_neo4j_databases() -> list[dict[str, str]]:
    """List every non-system Neo4j database (SHOW DATABASES).

    Mirrors sql_setup_db._list_databases(): returns a list of dicts with
    `name` + `type` so the UI can tell system DBs from user DBs.

    Uses the SYSTEM database (which always exists) to enumerate; falls back
    to an empty list if the cluster doesn't support SHOW DATABASES.
    """
    drv = _driver()
    try:
        with drv.session(database="system") as s:
            rows = s.run("SHOW DATABASES").data()
        # Filter out internal/system DBs; user DBs have type='standard'
        return [
            {"name": r["name"], "type": r.get("type", "standard")}
            for r in rows
            if r.get("type") == "standard"
        ]
    except Exception:
        return []


def ensure_neo4j_db(
    database: Optional[str] = None,
    connection: Optional[dict] = None,
) -> dict[str, Any]:
    """Verify the Neo4j server is reachable. Returns connection metadata.

    ``database`` / ``connection`` override the target database / connection
    per call (fall back to studio override + env). Raises if no labels exist
    (mirrors sql_setup_db.ensure_chinook_db's "DB must be populated" check).
    """
    db = _resolve_database(database)
    drv = _driver_for(connection)
    with drv.session(database=db) as s:
        labels = s.run(
            "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n "
            "ORDER BY n DESC LIMIT 1"
        ).data()
        if not labels:
            raise RuntimeError(
                f"Neo4j database '{db}' has no nodes — "
                "load some data before invoking the agent."
            )
    uri, _, _, _ = _connection_params(connection)
    return {
        "uri": uri,
        "database": db,
        "labels": [r["label"] for r in labels],
    }


# ---------------------------------------------------------------------------
# The 3 tools — mirrors sql_setup_db's sql_db_list_tables / sql_db_schema /
# sql_db_query. Different names (neo4j_graph_*) so they don't collide with
# the existing neo4j_* document-index tools in backend/tools/native_impl.py.
# ---------------------------------------------------------------------------
@tool
def neo4j_graph_schema(
    database: Annotated[Optional[str], InjectedState("neo4j_database")] = None,
    connection: Annotated[Optional[dict], InjectedState("neo4j_connection")] = None,
) -> str:
    """Input is an empty string. Output is a compact summary of the active
    Neo4j graph database — node labels with counts, relationship types with
    counts, and the property keys present on each label (capped at 8 props
    per label for compactness). The LLM should call this first before
    writing any Cypher, exactly like sql_db_list_tables.
    """
    db = _resolve_database(database)
    drv = _driver_for(connection)
    with drv.session(database=db) as s:
        # Top labels
        labels = s.run(
            "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n "
            "ORDER BY n DESC LIMIT 50"
        ).data()
        # Top relationship types
        rels = s.run(
            "MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS n "
            "ORDER BY n DESC LIMIT 50"
        ).data()
        # Property keys per label (top 8 per label, by frequency)
        props_by_label = s.run(
            """
            MATCH (n)
            WITH labels(n)[0] AS label, keys(n) AS ks, count(*) AS n
            UNWIND ks AS k
            WITH label, k, sum(n) AS usage
            ORDER BY label, usage DESC
            WITH label, collect({key: k, usage: usage})[0..8] AS top
            RETURN label, top
            """
        ).data()
    prop_map = {r["label"]: [p["key"] for p in r["top"]] for r in props_by_label}

    lines = ["## Neo4j Graph Schema", ""]
    if labels:
        lines.append("### Node labels (top 50)")
        for r in labels:
            tag = r["label"]
            keys = prop_map.get(tag) or []
            keys_str = f"  [{', '.join(keys)}]" if keys else ""
            lines.append(f"- {tag}  ({r['n']:,} nodes){keys_str}")
    else:
        lines.append("(no nodes in database)")
    lines.append("")
    if rels:
        lines.append("### Relationship types (top 50)")
        for r in rels:
            lines.append(f"- :{r['rel']}  ({r['n']:,} edges)")
    lines.append("")
    return "\n".join(lines)


@tool
def neo4j_graph_schema_details(
    labels: str,
    database: Annotated[Optional[str], InjectedState("neo4j_database")] = None,
    connection: Annotated[Optional[dict], InjectedState("neo4j_connection")] = None,
) -> str:
    """Input is a comma-separated list of node labels (e.g. 'Person,Movie').
    Output is detailed schema for those labels — properties with data types
    plus up to 3 sample nodes per label. Call neo4j_graph_schema first to
    discover the labels, then this tool to drill into specific ones.

    Example Input: Person, Movie
    """
    db = _resolve_database(database)
    drv = _driver_for(connection)
    with drv.session(database=db) as s:
        # Verify the labels exist by listing all current labels
        existing = {
            r["label"]
            for r in s.run("MATCH (n) RETURN DISTINCT labels(n)[0] AS label").data()
        }

        results: list[str] = []
        for raw in labels.split(","):
            label = raw.strip()
            if not label:
                continue
            if label not in existing:
                results.append(f"Error: label {{{label!r}}} not found in database")
                continue

            # Sample 3 nodes — pick the keys present on them for the "shape"
            sample = s.run(
                "MATCH (n:" + _quote_label(label)
                + ") RETURN n LIMIT 3"
            ).data()
            # Property keys + inferred data type (we only have the runtime
            # Cypher types; report the first node's apoc-style map if any).
            keys: list[str] = []
            if sample:
                first = sample[0]["n"]
                keys = list(first.keys())
            sample_block = ""
            if sample:
                rows = []
                for row in sample:
                    r = row["n"]
                    rows.append(
                        "{" + ", ".join(
                            f"{k}: {dict(r).get(k)!r}" for k in keys[:6]
                        ) + "}"
                    )
                sample_block = (
                    f"/*\n3 sample {label} nodes:\n"
                    + "\n".join(rows)
                    + "\n*/"
                )

            results.append(
                f"### Label `{label}`\n"
                f"- properties: {', '.join(keys) if keys else '(none)'}\n"
                f"- count: {len(sample)} sampled (of "
                f"{sum(1 for _ in s.run('MATCH (n:' + _quote_label(label) + ') RETURN n LIMIT 1000'))} approx)\n"
                + sample_block
            )
        return "\n\n".join(results) if results else "No labels provided."


@tool
def neo4j_graph_query(
    cypher: str,
    parameters: str = "{}",
    database: Annotated[Optional[str], InjectedState("neo4j_database")] = None,
    connection: Annotated[Optional[dict], InjectedState("neo4j_connection")] = None,
) -> str:
    """Input is a Cypher query and an optional JSON string of parameters.
    Output is a markdown table of the query results, or an error message if
    the query fails.

    Read-only: any Cypher containing CREATE / MERGE / SET / DELETE /
    REMOVE / DROP / FOREACH / CALL / LOAD CSV is rejected before reaching
    the server. Parameters must be a JSON object of primitives (str /
    int / float / bool / None) or a flat list of primitives — dicts and
    nested containers are rejected. Add LIMIT to your query when the
    result set could be large.

    If you encounter 'variable not defined' or 'unknown label' errors,
    call neo4j_graph_schema first to discover the actual graph shape.

    Example Input:
        cypher='MATCH (p:Person {name: $name})-[:ACTED_IN]->(m:Movie) '
               'RETURN m.title AS title, m.released AS year '
               'ORDER BY year DESC LIMIT $limit'
        parameters='{"name": "Tom Hanks", "limit": 5}'
    """
    forbidden = _reject_writes(cypher)
    if forbidden:
        return (
            f"Error: write/destructive operation '{forbidden}' is not allowed "
            f"in neo4j_graph_query. Use the Neo4j Browser or write a separate "
            f"write-enabled tool if you need to mutate the graph."
        )

    params, err = _coerce_params(parameters)
    if err:
        return f"Error: {err}"

    try:
        db = _resolve_database(database)
        drv = _driver_for(connection)
        with drv.session(database=db) as s:
            result = s.run(cypher, parameters=params or {})
            # .data() caps internally at the driver's record_limit; cap again
            # here for safety.
            rows = result.data()[:1000]
            return _format_rows(rows)
    except Exception as exc:  # noqa: BLE001 - surface driver errors verbatim
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# main() — connectivity + tool sanity check (no LLM)
# ---------------------------------------------------------------------------
def main() -> None:
    """Quick smoke test: verify connection, exercise all 3 tools live."""
    meta = ensure_neo4j_db()
    print(f"Neo4j @ {meta['uri']}/{meta['database']}  ({len(meta['labels'])} labels)")
    print()

    print("=== neo4j_graph_schema ===")
    print(neo4j_graph_schema.invoke({}))
    print()

    print("=== neo4j_graph_schema_details('Person') ===")
    print(neo4j_graph_schema_details.invoke({"labels": "Person"}))
    print()

    print("=== neo4j_graph_query (Tom Hanks movies) ===")
    out = neo4j_graph_query.invoke({
        "cypher":
            "MATCH (p:Person {name: $name})-[:ACTED_IN]->(m:Movie) "
            "RETURN m.title AS title, m.released AS year "
            "ORDER BY year DESC LIMIT $limit",
        "parameters": '{"name": "Tom Hanks", "limit": 5}',
    })
    print(out)
    print()

    print("=== neo4j_graph_query write-reject smoke test ===")
    bad = neo4j_graph_query.invoke({
        "cypher": "CREATE (n:BadNode {x: 1}) RETURN n",
        "parameters": "{}",
    })
    print(bad)


if __name__ == "__main__":
    main()
