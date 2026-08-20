"""PostgreSQL connection + tools for the LangGraph SQL agent.

Talks to the chinook database in your existing Postgres server (configured
through the standard Postgres env vars). Exposes the same tool surface that
sql_agent.py / sql_agent_hitl.py consume, so the graphs can keep working
unchanged. Two defaults vs. the SQLite original:

  - The connection is read-only at the transaction level (psycopg2
    `set_session(readonly=True)`), so model-generated SQL can never mutate
    the database.
  - Schema introspection uses ``information_schema`` (lower-case identifiers,
    matching the chinook tables: artist, album, track, ...).

If you ever want to point this at a *different* Postgres database, set the
same env vars the rest of the project uses (or override SQL_DATABASE_URL).
"""
import os
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Single source of truth for Postgres connection config — read from
# the project-root .env via the centralized connection module.
from langgraph.connection import (
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD,
)
from langchain.tools import tool

# Best-effort: pick up the repo-root .env so SQL_* vars flow through.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))

# Runtime override set by the studio UI (see graph_studio /databases endpoints).
# Lets the user switch the target database from the canvas without editing .env.
_DB_OVERRIDE: str | None = None


def set_target_database(name: str) -> None:
    """Point the SQL tools at a different database for this process lifetime."""
    global _DB_OVERRIDE
    _DB_OVERRIDE = name


def get_target_database() -> str:
    """Return the database the SQL tools are currently pointed at."""
    return _DB_OVERRIDE or os.getenv("SQL_POSTGRES_DB", os.getenv("POSTGRES_DB", "chinook"))


def _connection_params() -> dict[str, Any]:
    """Resolve connection params from SQL_* env vars, falling back to project defaults.

    The fallbacks reuse the existing Postgres server the LangConfig app already
    points at (see DATABASE_URL in .env), so a fresh checkout works without
    additional config — the chinook database is expected to exist.
    """
    explicit = os.getenv("SQL_DATABASE_URL")
    if explicit:
        return {"dsn": explicit}

    # Single source of truth: POSTGRES_* env vars in .env (read by
    # backend/langgraph/connection.py). No hardcoded literals here.
    return {
        "host": os.getenv("SQL_POSTGRES_HOST", os.getenv("POSTGRES_HOST", POSTGRES_HOST)),
        "port": int(os.getenv("SQL_POSTGRES_PORT", os.getenv("POSTGRES_PORT", str(POSTGRES_PORT)))),
        "dbname": get_target_database(),
        "user": os.getenv("SQL_POSTGRES_USER", os.getenv("POSTGRES_USER", POSTGRES_USER)),
        "password": os.getenv("SQL_POSTGRES_PASSWORD", os.getenv("POSTGRES_PASSWORD", POSTGRES_PASSWORD)),
    }


def _connect():
    """Open a read-only psycopg2 connection."""
    params = _connection_params()
    conn = psycopg2.connect(**params)
    # Read-only transaction: every SELECT succeeds, every DML fails.
    conn.set_session(readonly=True, autocommit=False)
    return conn


def _quote_ident(name: str) -> str:
    """Safely quote a Postgres identifier (table or column name)."""
    return '"' + name.replace('"', '""') + '"'


def ensure_chinook_db() -> dict[str, Any]:
    """Verify the Postgres chinook database is reachable.

    Returns the resolved connection params so callers can show the user where
    the workflow is reading from. Raises if the DB or any table is missing —
    mirrors the SQLite version's "download if missing" affordance.
    """
    params = _connection_params()
    dsn = params.pop("dsn", None)
    conn = psycopg2.connect(**({"dsn": dsn} if dsn else params))
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
            (n,) = cur.fetchone()
            if n == 0:
                raise RuntimeError(
                    f"Postgres database has no tables — populate it first (saw params: {params or dsn})"
                )
    finally:
        conn.close()
    return params


@tool
def sql_db_list_tables() -> str:
    """Input is an empty string, output is a comma-separated list of tables in the database."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            )
            tables = [row[0] for row in cur.fetchall()]
        return ", ".join(tables)
    finally:
        conn.close()


@tool
def sql_db_schema(table_names: str) -> str:
    """Input to this tool is a comma-separated list of tables, output is the schema and sample rows for those tables.
    Be sure that the tables actually exist by calling sql_db_list_tables first!
    Example Input: table1, table2, table3"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # Discover all tables so we can validate names + check what exists.
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
            valid_tables = {row[0] for row in cur.fetchall()}

            results: list[str] = []
            for raw in table_names.split(","):
                table = raw.strip()
                if not table:
                    continue
                if table not in valid_tables:
                    results.append(f"Error: table_names {{{table!r}}} not found in database")
                    continue

                # CREATE TABLE statement (postgres-friendly, lowercase identifiers).
                cur.execute(
                    "SELECT column_name, data_type, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = %s "
                    "ORDER BY ordinal_position",
                    (table,),
                )
                cols = cur.fetchall()
                if not cols:
                    results.append(f"-- empty schema for {table}")
                    continue
                col_lines = [
                    f"  {_quote_ident(c[0])} {c[1]}{' NOT NULL' if c[2] == 'NO' else ''}"
                    for c in cols
                ]
                create_stmt = f"CREATE TABLE {_quote_ident(table)} (\n" + ",\n".join(col_lines) + "\n);"
                results.append(create_stmt)

                # Sample rows for context.
                try:
                    cur.execute(f"SELECT * FROM {_quote_ident(table)} LIMIT 3;")
                    rows = cur.fetchall()
                    if rows:
                        col_names = [d.name for d in cur.description]
                        results.append(
                            f"/*\n3 rows from {table} table:\n"
                            + "\t".join(col_names)
                            + "\n"
                            + "\n".join(
                                "\t".join("NULL" if v is None else str(v) for v in row)
                                for row in rows
                            )
                            + "\n*/"
                        )
                except Exception as exc:  # noqa: BLE001
                    results.append(f"Error fetching sample rows: {exc}")

            return "\n\n".join(results)
    finally:
        conn.close()


@tool
def sql_db_query(query: str) -> str:
    """Input to this tool is a detailed and correct SQL query, output is a result from the database.
    If the query is not correct, an error message will be returned.
    If an error is returned, rewrite the query, check the query, and try again.
    If you encounter an issue with Unknown column 'xxxx' in 'field list', use sql_db_schema to query the correct table fields."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            # Mirror the SQLite original: str() on the full row set.
            return str(cur.fetchall())
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"
    finally:
        conn.close()


def main() -> None:
    """Quick connectivity sanity check (no LLM involved)."""
    params = ensure_chinook_db()
    print(f"Dialect: postgresql @ {params.get('host','?')}:{params.get('port','?')}/{params.get('dbname','?')}")

    print(f"Available tables: {sql_db_list_tables.invoke({})}")

    conn = _connect()
    try:
        with conn.cursor() as cur:
            for query in (
                "SELECT COUNT(*) FROM track",
                "SELECT g.name, ROUND(AVG(t.milliseconds)) AS avg_ms "
                "FROM track t JOIN genre g ON t.genreid = g.genreid "
                "GROUP BY g.name ORDER BY avg_ms DESC LIMIT 3",
            ):
                cur.execute(query)
                print(f"\nQuery: {query}\nResult: {cur.fetchall()}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()