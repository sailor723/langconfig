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
from typing import Annotated, Any, Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Single source of truth for Postgres connection config — read from
# the project-root .env via the centralized connection module.
from langgraph.connection import (
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD,
)
from langchain.tools import tool
from langgraph.prebuilt import InjectedState

# Best-effort: pick up the repo-root .env so SQL_* vars flow through.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))

# Runtime override set by the studio UI (see graph_studio /databases endpoints).
# Lets the user switch the target database from the canvas without editing .env.
_DB_OVERRIDE: str | None = None


# ── Named targets: a database on a DIFFERENT server ─────────────────────────
# Everything below assumes one Postgres instance (POSTGRES_*) and only varies the
# dbname. That breaks the moment the target lives elsewhere: TPC-H sits on its
# own instance at :5432 under another role, so "select dbname=tpch" would look
# for tpch on the platform server and 404. A target is therefore a *server +
# database* pair and is the single place a second instance is described. Picking
# one happens through the same studio dropdown as a plain dbname — `_connect()`
# and `_connection_params()` resolve the name here.
#
# Env override (merged over these defaults, same shape):
#   SQL_TARGETS='{"tpch": {"host": "10.0.0.9", "port": 5432, "user": "analyst",
#                          "dbname": "tpch", "password": "…"}}'
_BUILTIN_TARGETS: dict[str, dict[str, Any]] = {
    "tpch": {
        "host": "127.0.0.1",
        "port": 5432,
        "dbname": "tpch",
        "user": "weiping",
        # No password on purpose: local trust auth. An empty string would be
        # sent as a password and rejected, so it is omitted rather than blank.
    },
}


def _load_targets() -> dict[str, dict[str, Any]]:
    """Built-in targets merged with the SQL_TARGETS env override."""
    import json

    targets = {name: dict(cfg) for name, cfg in _BUILTIN_TARGETS.items()}
    raw = os.getenv("SQL_TARGETS")
    if raw:
        try:
            over = json.loads(raw)
        except ValueError:
            # A malformed env blob must not take the SQL graph down: the
            # built-ins still work and the bad name simply stays unrecognised.
            over = None
        if isinstance(over, dict):
            for name, cfg in over.items():
                if isinstance(cfg, dict):
                    targets.setdefault(name, {}).update(cfg)
    return targets


_TARGETS: dict[str, dict[str, Any]] = _load_targets()


def list_targets() -> dict[str, dict[str, Any]]:
    """Named targets (server + database) — the studio picker lists these too."""
    return {name: dict(cfg) for name, cfg in _TARGETS.items()}


def is_target(name: Optional[str]) -> bool:
    """True when `name` is a registered target rather than a plain dbname."""
    return bool(name) and (name or "").strip() in _TARGETS


def _target_params(name: str) -> Optional[dict[str, Any]]:
    """Connection params for a named target, or None when it is a plain dbname."""
    cfg = _TARGETS.get((name or "").strip())
    if not cfg:
        return None
    if cfg.get("dsn"):
        return {"dsn": cfg["dsn"]}
    params: dict[str, Any] = {
        "host": cfg.get("host", POSTGRES_HOST),
        "port": int(cfg.get("port", POSTGRES_PORT)),
        "dbname": cfg.get("dbname", name),
        "user": cfg.get("user", POSTGRES_USER),
    }
    password = cfg.get("password")
    if password not in (None, ""):
        params["password"] = password
    return params


def set_target_database(name: str) -> None:
    """Point the SQL tools at a different database for this process lifetime.

    `name` is either a database on the platform server (chinook, manufacturing…)
    or a named target (tpch) that carries its own host/port/role.
    """
    global _DB_OVERRIDE
    _DB_OVERRIDE = name


def get_target_database() -> str:
    """Return the database the SQL tools are currently pointed at.

    The fallback chain deliberately never lands on ``POSTGRES_DB``: that is the
    PLATFORM database (agents, skills, runs, audit) and pointing the SQL graph at
    it is exactly how a "which genre has the longest tracks" question ends up
    scanning 52 platform tables instead of Chinook's 11. SQL tools get their own
    knob (``SQL_POSTGRES_DB``) and the demo database as the built-in default.
    """
    return _DB_OVERRIDE or os.getenv("SQL_POSTGRES_DB") or "chinook"


def _resolve_database(database: Optional[str]) -> str:
    """Per-call database resolution: explicit param -> studio override -> env."""
    if database:
        return database
    return get_target_database()


def _connection_params(connection: Optional[dict] = None) -> dict[str, Any]:
    """Resolve connection params: explicit dict wins, else SQL_* env, else
    project defaults (POSTGRES_* via connection.py — no hardcoded literals).

    ``connection`` keys: dsn (full URL) OR host / port / dbname / user /
    password. ``dbname`` is filled from ``_resolve_database(None)`` when the
    explicit dict omits it, so a per-call database reaches the connection.
    """
    if connection:
        params: dict[str, Any] = {}
        if connection.get("dsn"):
            params["dsn"] = connection["dsn"]
        else:
            if connection.get("host") is not None:
                params["host"] = connection["host"]
            if connection.get("port") is not None:
                params["port"] = int(connection["port"])
            if connection.get("dbname"):
                params["dbname"] = connection["dbname"]
            if connection.get("user") is not None:
                params["user"] = connection["user"]
            if connection.get("password") is not None:
                params["password"] = connection["password"]
        if "dsn" in params:
            return params
        return {**params, "dbname": params.get("dbname") or _resolve_database(None)}

    explicit = os.getenv("SQL_DATABASE_URL")
    if explicit:
        return {"dsn": explicit}

    # A named target carries its own server, so it wins over the platform
    # defaults. This is the one branch that lets a second Postgres instance be
    # reachable from every graph and from the studio dropdown.
    target = _target_params(_resolve_database(None))
    if target:
        return target

    return _platform_params(_resolve_database(None))


def _platform_params(dbname: Optional[str] = None) -> dict[str, Any]:
    """Params for the PLATFORM Postgres (:5433), never for a named target.

    The studio picker enumerates databases with this: it must list what the
    platform server holds regardless of which target is currently active, or
    switching to a remote target would hide every local database (measured: with
    tpch selected, a picker built from `_connection_params()` reported the TPCH
    server's list and "chinook" became unreachable — 404 unknown database).
    """
    return {
        "host": os.getenv("SQL_POSTGRES_HOST", os.getenv("POSTGRES_HOST", POSTGRES_HOST)),
        "port": int(os.getenv("SQL_POSTGRES_PORT", os.getenv("POSTGRES_PORT", str(POSTGRES_PORT)))),
        # Default to the PLATFORM database, not the active SQL target: with
        # "tpch" selected, `_resolve_database(None)` returns a name that lives on
        # another server, and connecting to it here failed with
        # `database "tpch" does not exist` — which took the whole picker down.
        "dbname": dbname or POSTGRES_DB,
        "user": os.getenv("SQL_POSTGRES_USER", os.getenv("POSTGRES_USER", POSTGRES_USER)),
        "password": os.getenv("SQL_POSTGRES_PASSWORD", os.getenv("POSTGRES_PASSWORD", POSTGRES_PASSWORD)),
    }


def platform_params() -> dict[str, Any]:
    """Public alias: platform-server params (used to enumerate its databases)."""
    return _platform_params()


def _connect(database: Optional[str] = None, connection: Optional[dict] = None):
    """Open a read-only psycopg2 connection to the resolved database.

    Resolution order — explicit per-call `connection` dict, then a named
    `database` target (host/port/role included), then the platform server with
    `database` as the dbname.
    """
    if connection:
        params = _connection_params(connection)
        if database and "dsn" not in params:
            params["dbname"] = database
    elif database:
        # An explicit name is honoured even when another target is active:
        # asking for "chinook" while "tpch" is selected must reach :5433, not
        # the TPCH server with a chinook dbname on it.
        target = _target_params(database)
        params = dict(target) if target else {**_platform_params(database)}
    else:
        params = _connection_params(None)
    conn = psycopg2.connect(**params)
    # Read-only transaction: every SELECT succeeds, every DML fails.
    conn.set_session(readonly=True, autocommit=False)
    return conn


def _quote_ident(name: str) -> str:
    """Safely quote a Postgres identifier (table or column name)."""
    return '"' + name.replace('"', '""') + '"'


def ensure_chinook_db(
    database: Optional[str] = None,
    connection: Optional[dict] = None,
) -> dict[str, Any]:
    """Verify the Postgres database is reachable.

    Returns the resolved connection params so callers can show the user where
    the workflow is reading from. Raises if the DB or any table is missing —
    mirrors the SQLite version's "download if missing" affordance.
    """
    params = _connection_params(connection)
    if database and "dsn" not in params:
        params["dbname"] = database
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
def sql_db_list_tables(
    database: Annotated[Optional[str], InjectedState("sql_database")] = None,
    connection: Annotated[Optional[dict], InjectedState("sql_connection")] = None,
) -> str:
    """Input is an empty string, output is a comma-separated list of tables in the database."""
    try:
        conn = _connect(database, connection)
    except Exception as exc:  # noqa: BLE001 — surface connection errors to the model
        return f"Error: {exc}"
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
def sql_db_schema(
    table_names: str,
    database: Annotated[Optional[str], InjectedState("sql_database")] = None,
    connection: Annotated[Optional[dict], InjectedState("sql_connection")] = None,
) -> str:
    """Input to this tool is a comma-separated list of tables, output is the schema and sample rows for those tables.
    Be sure that the tables actually exist by calling sql_db_list_tables first!
    Example Input: table1, table2, table3"""
    try:
        conn = _connect(database, connection)
    except Exception as exc:  # noqa: BLE001 — surface connection errors to the model
        return f"Error: {exc}"
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
def sql_db_query(
    query: str,
    database: Annotated[Optional[str], InjectedState("sql_database")] = None,
    connection: Annotated[Optional[dict], InjectedState("sql_connection")] = None,
) -> str:
    """Input to this tool is a detailed and correct SQL query, output is a result from the database.
    If the query is not correct, an error message will be returned.
    If an error is returned, rewrite the query, check the query, and try again.
    If you encounter an issue with Unknown column 'xxxx' in 'field list', use sql_db_schema to query the correct table fields."""
    try:
        conn = _connect(database, connection)
    except Exception as exc:  # noqa: BLE001 — surface connection errors to the model
        return f"Error: {exc}"
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