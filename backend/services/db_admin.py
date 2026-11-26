"""Managing the PostgreSQL server from inside an agent: list databases, describe anything, run DDL/DML.

What already existed (and is NOT duplicated here): `pg_query` / `pg_list_tables` / `pg_describe_table`
speak only to the platform's own database, and `db_query` / `db_review` / `db_rename_column` speak to any
database but only READ. So the three verbs a person actually needs to *manage* a server were missing:

    list databases      which databases exist, how big, how many tables, is it a template
    describe anything   schemas, tables, columns, indexes, keys — for any database, one call
    execute             CREATE / ALTER / DROP / TRUNCATE / INSERT / UPDATE / DELETE — on any database

Guards, because these are write verbs on a shared server:

* **two phases.** `execute(confirm=False)` returns the plan and touches nothing. Only `confirm=True` runs,
  after a human (or the agent's user) said yes. This is the same shape as `db_build_from_file`.
* **one statement.** A `;` that is not the trailing terminator is refused, so a stacked
  `UPDATE …; DROP TABLE …` cannot ride along.
* **a blocklist that is about the SERVER, not about judgement.** `DROP DATABASE`, `DROP SCHEMA … CASCADE`,
  `ALTER SYSTEM`, `CREATE/ALTER/DROP ROLE`, `REVOKE/GRANT … ON DATABASE`, `pg_terminate_backend`,
  `TRUNCATE` of the platform's own database, DDL on the platform's own database, and anything against
  template databases are refused by name. Row-level DML on the platform IS allowed — operators do it.
  Everything else in the caller's own databases is allowed — that is what "manage" means, and pretending
  otherwise just pushes people back to psql.
* **the target is named.** The database is an argument, never parsed out of the SQL, so "which server was
  that?" always has an answer in the tool call.

The password is never an argument: it arrives as PGPASSWORD from the agent's own Database section
(`services/agent_database.py`), exactly like `db_query`.
"""
from __future__ import annotations

import os
import re

#: Statements that act on the SERVER or on other accounts. Their blast radius is not "one database", so
#: they are refused by name instead of being run with a timeout and a rowcount.
SERVER_LEVEL = (
    "drop database", "drop schema", "alter system", "create role", "alter role", "drop role",
    "create user", "alter user", "drop user", "grant ", "revoke ", "pg_terminate_backend",
    "pg_cancel_backend", "pg_reload_conf", "pg_drop_replication_slot", "create database",
    "alter database", "create tablespace", "drop tablespace", "vacuum full",
)
#: Databases that must never be written: the ones PostgreSQL itself owns, and whatever the platform
#: runs on (its own schema lives there).
NEVER_WRITE = ("template0", "template1", "postgres")

_WRITE = ("insert", "update", "delete", "create", "alter", "drop", "truncate", "comment", "copy")
_READ = ("select", "with", "explain", "show", "values")


class DbAdminError(ValueError):
    """A request that will not be carried out — the message says what to fix."""


def _conn_kwargs(db_name: str = "", ontology_key: str = "") -> dict:
    """The agent's own connection (host/port/user/password) plus the requested database.

    `ontology_key` lets a caller name an ontology whose profile declares a DIFFERENT server (TPC-H
    lives on :5432 while the platform's own database is :5433) — the declaration is the fact.
    """
    from tools.native_impl import _pg_conn_kwargs  # the one place that precedence lives

    kw = _pg_conn_kwargs(dbname=db_name, ontology_key=ontology_key)
    kw.setdefault("connect_timeout", 8)
    return kw


def _platform_db() -> str:
    return str(os.environ.get("POSTGRES_DB") or "").strip()


def validate_statement(sql: str, *, platform_db: str | None = None) -> str:
    """The single statement to run, or a refusal. Pure — this is the part worth testing.

    Returns the statement with its trailing `;` removed. Raises `DbAdminError` naming the reason.
    """
    text = (sql or "").strip()
    if not text:
        raise DbAdminError("empty SQL")
    stripped = text[:-1].rstrip() if text.endswith(";") else text
    trailing = [i for i, ch in enumerate(stripped) if ch == ";"]
    if trailing:
        raise DbAdminError(
            "multiple statements in one call — a write tool runs ONE statement, so a stacked "
            "`UPDATE …; DROP TABLE …` cannot ride along. Split it.")
    low = re.sub(r"\s+", " ", stripped.lower())
    for term in SERVER_LEVEL:
        if low.startswith(term) or re.search(rf"\b{re.escape(term)}", low):
            raise DbAdminError(
                f"refused: `{term.strip()}` acts on the SERVER (or on other accounts), not on one "
                f"database. Run it in psql as an administrator if that is really intended.")
    if not low.startswith(_WRITE) and not low.startswith(_READ):
        raise DbAdminError(
            "refused: only INSERT/UPDATE/DELETE and DDL (CREATE/ALTER/DROP/TRUNCATE/COMMENT) may be "
            f"executed here, plus read-only SELECT/WITH. Got: {stripped[:60]!r}")
    plat = (platform_db or _platform_db()).strip()
    if plat and re.search(rf"\b{re.escape(plat.lower())}\b", low) and low.startswith(("drop ", "truncate ")):
        raise DbAdminError(
            f"refused: this statement names the platform's own database {plat!r}. Dropping or truncating "
            f"the database the app runs on is not something an agent does.")
    return stripped


def list_databases(*, with_objects: bool = True, max_connections: int = 40,
                   ontology_key: str = "") -> dict:
    """Every database on the server, and (optionally) how many tables each one holds.

    The object count CANNOT come from one query: `pg_class` belongs to the database you are connected to,
    so counting another database's tables from `postgres` returns 0 for every row — measured, and the first
    version of this function did exactly that: it reported `objects=0` for nineteen databases, and the agent
    (correctly not believing it) then measured each one separately, one connection per database, until it
    hit its step limit. So the count is obtained the only way it can be: one connection per database, in this
    same call, capped at `max_connections`.
    """
    import psycopg2

    conn = psycopg2.connect(**_conn_kwargs("postgres"))
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            cur.execute("""
                select d.datname,
                       pg_catalog.pg_get_userbyid(d.datdba) as owner,
                       pg_catalog.pg_size_pretty(pg_catalog.pg_database_size(d.datname)) as size,
                       pg_catalog.pg_database_size(d.datname) as size_bytes,
                       d.datistemplate,
                       d.datallowconn,
                       pg_catalog.pg_encoding_to_char(d.encoding) as encoding,
                       pg_catalog.pg_get_userbyid(d.datdba) = current_user as owned_by_me
                  from pg_catalog.pg_database d
                 order by d.datname
            """)
            rows = cur.fetchall()
    finally:
        conn.close()

    out = []
    counted = 0
    for name, owner, size, size_bytes, is_tmpl, allow, enc, mine in rows:
        platform = bool(_platform_db()) and name == _platform_db()
        entry = {"database": name, "owner": owner, "size": size, "size_bytes": size_bytes,
                 "template": bool(is_tmpl), "connectable": bool(allow), "encoding": enc,
                 # `writable` is what THIS TOOL SET will accept, not what the server would allow.
                 # The platform's own database IS writable now — `db_execute` takes row-level DML there and
                 # refuses DDL — so the flag is true with `write_scope = "dml-only"`. (It used to be false
                 # with the note "row-level DML has its own door, pg_execute"; that door is gone.)
                 "writable": bool(allow) and not is_tmpl and name not in NEVER_WRITE,
                 "write_scope": ("dml-only" if platform else ("full" if (bool(allow) and not is_tmpl and name not in NEVER_WRITE) else "none")),
                 "platform": platform, "objects": None}
        if with_objects and entry["connectable"] and counted < max_connections:
            counted += 1
            try:
                c2 = psycopg2.connect(**_conn_kwargs(name))
                try:
                    c2.set_session(readonly=True, autocommit=True)
                    with c2.cursor() as cur2:
                        cur2.execute("""
                            select count(*) from pg_catalog.pg_class c
                              join pg_catalog.pg_namespace n on n.oid = c.relnamespace
                             where c.relkind in ('r','p','v','m')
                               and n.nspname not in ('pg_catalog','information_schema')
                        """)
                        entry["objects"] = cur2.fetchone()[0]
                finally:
                    c2.close()
            except Exception as exc:                            # noqa: BLE001
                entry["objects_error"] = str(exc).strip().splitlines()[0][:120]
        out.append(entry)
    return {"ok": True, "databases": out, "count": len(out),
            "objects_counted": counted, "objects_requested": with_objects}


def describe(db_name: str, table: str = "", ontology_key: str = "") -> dict:
    """Schemas and tables for a database (row counts), or one table's columns, indexes and keys."""
    import psycopg2

    name = (db_name or "").strip()
    if not name:
        raise DbAdminError("db_name is required (see db_list_databases)")
    kw = _conn_kwargs(name, ontology_key)
    try:
        conn = psycopg2.connect(**kw)
    except Exception as exc:                                   # noqa: BLE001
        raise DbAdminError(f"cannot connect to {name!r}: {str(exc).strip().splitlines()[0]}") from exc
    try:
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor()
        if not table:
            cur.execute("""
                select n.nspname, c.relname,
                       case c.relkind when 'r' then 'table' when 'p' then 'partitioned'
                            when 'v' then 'view' when 'm' then 'matview' else c.relkind::text end,
                       c.reltuples::bigint,
                       pg_catalog.pg_size_pretty(pg_catalog.pg_total_relation_size(c.oid))
                  from pg_catalog.pg_class c
                  join pg_catalog.pg_namespace n on n.oid = c.relnamespace
                 where c.relkind in ('r','p','v','m')
                   and n.nspname not in ('pg_catalog','information_schema')
                 order by n.nspname, c.relname
            """)
            tables = [{"schema": s, "table": t, "kind": k, "rows_estimate": max(0, est), "size": sz}
                      for s, t, k, est, sz in cur.fetchall()]
            return {"ok": True, "database": name, "tables": tables, "count": len(tables)}
        cur.execute("""
            select column_name, data_type, is_nullable, column_default, character_maximum_length,
                   numeric_precision, numeric_scale, ordinal_position
              from information_schema.columns
             where table_name = %s
             order by ordinal_position
        """, (table,))
        cols = [{"column": c, "type": t, "nullable": (n == "YES"), "default": d, "max_len": ml,
                 "precision": p, "scale": s, "position": pos}
                for c, t, n, d, ml, p, s, pos in cur.fetchall()]
        if not cols:
            raise DbAdminError(f"{table!r} has no columns in {name!r} — check the name with db_describe "
                               f"(no table argument lists them all)")
        cur.execute("""
            select indexname, indexdef from pg_indexes where tablename = %s order by 1
        """, (table,))
        idx = [{"index": i, "definition": d} for i, d in cur.fetchall()]
        cur.execute("""
            select con.conname, con.contype,
                   pg_catalog.pg_get_constraintdef(con.oid)
              from pg_catalog.pg_constraint con
              join pg_catalog.pg_class rel on rel.oid = con.conrelid
             where rel.relname = %s
             order by 1
        """, (table,))
        cons = [{"constraint": c, "kind": {"p": "primary", "f": "foreign", "u": "unique", "c": "check"}
                 .get(k, k), "definition": d} for c, k, d in cur.fetchall()]
        cur.execute("select count(*) from " + _quote(table))
        rows_exact = cur.fetchone()[0]
        return {"ok": True, "database": name, "table": table, "rows": rows_exact,
                "columns": cols, "indexes": idx, "constraints": cons}
    finally:
        conn.close()


def execute(db_name: str, sql: str, *, confirm: bool = False, timeout_ms: int = 15000) -> dict:
    """Run ONE write statement against `db_name`. Phase 1 (confirm=False) returns the plan only."""
    import psycopg2

    name = (db_name or "").strip()
    if not name:
        raise DbAdminError("db_name is required (see db_list_databases)")
    if name in NEVER_WRITE:
        raise DbAdminError(f"refused: {name!r} is a database PostgreSQL (or this platform) owns; "
                           f"writes belong in a database that holds the caller's data")
    platform = _platform_db()
    statement = validate_statement(sql)
    low = statement.lower()
    if platform and name == platform:
        # The target database is an ARGUMENT, so the guard has to look at the ARGUMENT: a
        # `DROP TABLE deep_agent_templates` never mentions the database name in its text.
        #
        # TWO verbs, ONE door. Row-level DML on the platform is a thing operators really do (fix a
        # tool's `is_deprecated` flag, a settings row, an agent's config), so it is allowed here;
        # DDL on it is not an agent's job and stays refused. This used to be split across two tools
        # (`db_execute` refused the platform by argument, `pg_execute` served it) — a caller had to
        # know which database was "the platform's" before choosing a tool, and `pg_execute` was
        # never bound by anything or ever called.
        if not low.startswith(("insert", "update", "delete")):
            raise DbAdminError(
                f"refused: {name!r} is THIS PLATFORM's own database, where only row-level DML "
                f"(INSERT/UPDATE/DELETE) is allowed. DDL on the database this app runs on is not an "
                f"agent's job — that one belongs in psql as an administrator.")
    plan = {"ok": True, "database": name, "statement": statement,
            "kind": "ddl" if low.startswith(("create", "alter", "drop", "truncate", "comment")) else "dml",
            "confirmed": bool(confirm)}
    if not confirm:
        plan["next"] = (f"Nothing was executed. Show this to the user; then call again with "
                        f"confirm=true to run it against {name!r}.")
        return plan

    kw = _conn_kwargs(name, ontology_key)
    try:
        conn = psycopg2.connect(**kw)
    except Exception as exc:                                   # noqa: BLE001
        raise DbAdminError(f"cannot connect to {name!r}: {str(exc).strip().splitlines()[0]}") from exc
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = " + str(max(100, min(int(timeout_ms), 120000))))
            cur.execute(statement)
            affected = cur.rowcount
            notice = ""
            try:
                conn.notices and None
            except Exception:                                   # noqa: BLE001
                pass
        plan.update({"executed": True, "rows_affected": affected,
                     "note": "rowcount is -1 for statements that do not report one (most DDL)"})
        return plan
    except Exception as exc:                                   # noqa: BLE001
        raise DbAdminError(f"{name}: {str(exc).strip().splitlines()[0]}") from exc
    finally:
        conn.close()


def _quote(ident: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", ident or ""):
        return '"' + (ident or "").replace('"', '""') + '"'
    return '"' + ident + '"'
