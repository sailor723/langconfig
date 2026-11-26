#!/usr/bin/env python3
"""Seed the two DB-management BUILTIN tools: `db_describe` (databases → tables → columns) and `db_execute`.

The third one, `db_list_databases`, was folded into `db_describe(db_name="")`: listing databases and
describing one are the same discovery question, and two doors onto it is what §8 of db-tools-review.md
is about.

Why builtins: they write to (or introspect) databases the platform's own client speaks to, and a seeded
builtin row runs with the full namespace while a UI-created tool does not. The LOGIC lives in
`services/db_admin.py` (`list_databases` / `describe` / `execute`) — these rows are thin adapters, so the
guards can be tested without a database (`tests/test_db_admin.py`).

What was missing before this: `pg_query` / `pg_list_tables` / `pg_describe_table` speak only to the
platform's own database, and `db_query` / `db_review` / `db_rename_column` speak to any database but only
READ. "Manage the server" needs three verbs none of them had — list the databases, describe any database,
and run ONE write statement against a named database, in two phases (plan → confirm).

Idempotent: re-running updates the rows in place.

    cd backend && .venv/bin/python scripts/seeds/in/seed_db_admin_tools.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND, REPO  # noqa: E402,F401

from db.database import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402


LIST_CODE = r'''# --- imports ---
def db_list_databases(with_objects: bool = True) -> str:
    """List every database on this PostgreSQL server: size, object count, owner, writability.

    ONE call answers "which databases are there, and how big are they" for the whole server. Do not follow
    it with one `db_query` per database to count tables: the counts are already here.
    """
    from services import db_admin

    try:
        out = db_admin.list_databases(with_objects=with_objects)
    except db_admin.DbAdminError as exc:
        return f"REFUSED: {exc}"
    except Exception as exc:                                    # noqa: BLE001
        return f"ERROR: {type(exc).__name__}: {exc}"
    lines = [f"{out['count']} database(s):", ""]
    for d in out["databases"]:
        flags = []
        if d["platform"]:
            flags.append("platform database — readable, writes refused")
        if d["template"]:
            flags.append("template")
        if not d["connectable"]:
            flags.append("no-connections")
        objs = "?" if d["objects"] is None else d["objects"]
        lines.append(f"- {d['database']:<26} {d['size']:>10}  objects={objs:<4} owner={d['owner']}"
                     + (f"  [{', '.join(flags)}]" if flags else ""))
    lines.append("")
    lines.append("next: db_describe(db_name=...) for one database's tables, then "
                 "db_describe(db_name=..., table=...) for one table's columns/keys.")
    return "\n".join(lines)
'''

DESCRIBE_CODE = r'''# --- imports ---
def db_describe(db_name: str = "", table: str = "", ontology_key: str = "") -> str:
    """Tables of any database (with row estimates), or one table's columns — and with NO database name,
    the server's databases (this absorbed `db_list_databases`: enumerating databases and describing one
    were two doors onto the same discovery question)."""
    from services import db_admin

    if not (db_name or "").strip():
        try:
            out = db_admin.list_databases(with_objects=False, ontology_key=ontology_key)
        except db_admin.DbAdminError as exc:
            return f"REFUSED: {exc}"
        except Exception as exc:                                # noqa: BLE001
            return f"ERROR: {type(exc).__name__}: {exc}"
        lines = [f"{out['count']} database(s) on this server:", ""]
        for d in out["databases"]:
            lines.append(f"- {d['database']:<32} {d['size']:>8}  owner={d['owner']}"
                         + ("" if d.get("writable", True) else "  [read-only]"))
        lines += ["", "next: db_describe(db_name=...) for one database's tables."]
        return "\n".join(lines)

    try:
        out = db_admin.describe(db_name, table, ontology_key=ontology_key)
    except db_admin.DbAdminError as exc:
        return f"REFUSED: {exc}"
    except Exception as exc:                                    # noqa: BLE001
        return f"ERROR: {type(exc).__name__}: {exc}"
    if not table:
        lines = [f"{out['database']}: {out['count']} table(s)/view(s)", ""]
        for t in out["tables"]:
            lines.append(f"- {t['schema']}.{t['table']:<32} {t['kind']:<11} "
                         f"rows~{t['rows_estimate']:<8} {t['size']}")
        return "\n".join(lines)
    lines = [f"{out['database']}.{out['table']}  ({out['rows']} rows)", "", "columns:"]
    for c in out["columns"]:
        null = "NULL" if c["nullable"] else "NOT NULL"
        dflt = f" default={c['default']}" if c["default"] else ""
        lines.append(f"- {c['column']:<24} {c['type']:<18} {null}{dflt}")
    if out["indexes"]:
        lines += ["", "indexes:"] + [f"- {i['index']}: {i['definition']}" for i in out["indexes"]]
    if out["constraints"]:
        lines += ["", "constraints:"] + [f"- {c['constraint']} ({c['kind']}): {c['definition']}"
                                          for c in out["constraints"]]
    return "\n".join(lines)
'''

EXECUTE_CODE = r'''# --- imports ---
def db_execute(db_name: str, sql: str, confirm: bool = False) -> str:
    """Run ONE write statement (DDL/DML) against a named database. Two phases: plan, then confirm.

    The platform's own database is accepted for ROW-LEVEL DML only (INSERT/UPDATE/DELETE); DDL on it is
    refused — that one belongs in psql as an administrator. This is the ONLY write tool: it absorbed
    the old `pg_execute`, which was deleted (see db-tools-review.md §B).
    """
    from services import db_admin

    try:
        out = db_admin.execute(db_name, sql, confirm=confirm)
    except db_admin.DbAdminError as exc:
        return f"REFUSED: {exc}"
    except Exception as exc:                                    # noqa: BLE001
        return f"ERROR: {type(exc).__name__}: {exc}"
    if not out.get("executed"):
        return ("NOTHING WAS EXECUTED (confirm=false).\n"
                f"database: {out['database']}\nkind: {out['kind']}\nstatement:\n  {out['statement']}\n\n"
                + str(out.get("next") or ""))
    affected = out.get("rows_affected")
    return (f"executed against {out['database']}  ({out['kind']})\n"
            f"  {out['statement']}\n"
            f"  rows_affected={affected}  ({out.get('note', '')})")
'''

TOOLS = [
    {
        "tool_id": "db_describe",
        "name": "DB describe (any database)",
        "description": ("Describe ANY database: without `table` it lists tables/views with row estimates; "
                        "with `table` it returns columns + types + nullability + defaults, indexes and "
                        "constraints, and the exact row count. Use it before writing SQL, and after a "
                        "db_execute that changed a table."),
        "fn": "db_describe",
        "code": DESCRIBE_CODE,
        "schema": {
            "db_name": {"type": "string",
                        "description": "database to describe; EMPTY lists the databases on this server "
                                       "(this absorbed the old db_list_databases)", "default": ""},
            "table": {"type": "string", "description": "one table (empty = list them all)", "default": ""},
        },
    },
    {
        "tool_id": "db_execute",
        "name": "DB execute (one write statement)",
        "description": ("【写别的库就用我】Run ONE write statement against a named database: "
                        "INSERT/UPDATE/DELETE and DDL "
                        "(CREATE/ALTER/DROP/TRUNCATE/COMMENT). TWO PHASES — confirm=false returns the plan "
                        "and executes nothing; only confirm=true runs it. Refuses, by name: stacked "
                        "statements, server-level verbs (DROP DATABASE, DROP SCHEMA, ALTER SYSTEM, roles, "
                        "grants), the platform's own database, and template0/template1/postgres. "
                        "NOT limited to business databases: row-level DML on the platform is allowed here too (this tool "
                        "refuses the platform database by its db_name argument); NOT for reading — "
                        "`db_query` / `db_describe`."),
        "fn": "db_execute",
        "code": EXECUTE_CODE,
        "schema": {
            "db_name": {"type": "string", "description": "database the statement runs against"},
            "sql": {"type": "string", "description": "ONE statement; a trailing ';' is fine"},
            "confirm": {"type": "boolean",
                        "description": "false (default) = plan only; true = execute it", "default": False},
        },
    },
]

INSERT_SQL = text("""
    INSERT INTO custom_tools
        (tool_id, name, description, tool_type, template_type, category, is_builtin,
         is_public, output_format, definition, input_schema, implementation_config,
         requires_api_key, tags, version, usage_count, error_count,
         is_template_based, is_advanced_mode, created_at, updated_at)
    VALUES
        (:tool_id, :name, :description, 'python_function', 'custom', 'database', true,
         false, 'string', CAST(:definition AS json), CAST(:input_schema AS json),
         CAST(:impl AS json), false, CAST(:tags AS json), '1.0.0', 0, 0,
         true, true, now(), now())
    ON CONFLICT (tool_id) DO UPDATE SET
        name = EXCLUDED.name,
        description = EXCLUDED.description,
        definition = EXCLUDED.definition,
        input_schema = EXCLUDED.input_schema,
        implementation_config = EXCLUDED.implementation_config,
        category = EXCLUDED.category,
        is_builtin = true,
        updated_at = now()
""")


def main() -> int:
    db = SessionLocal()
    try:
        for spec in TOOLS:
            props = {k: {kk: vv for kk, vv in v.items()} for k, v in spec["schema"].items()}
            db.execute(INSERT_SQL, {
                "tool_id": spec["tool_id"],
                "name": spec["name"],
                "description": spec["description"],
                "definition": json.dumps({"category": "database", "order": 2, "section": None,
                                          "is_concurrency_safe": False, "output_schema": None,
                                          "guard": {"approval": False, "confirmation": False},
                                          "presentation": {}}),
                "input_schema": json.dumps({"type": "object", "properties": props,
                                            "required": [k for k in props if "default" not in props[k]]},
                                           ensure_ascii=False),
                "impl": json.dumps({"function_name": spec["fn"], "code": spec["code"],
                                    "args_schema": spec["schema"]}, ensure_ascii=False),
                "tags": json.dumps(["database", "admin", "postgres", "ddl"]),
            })
            print(f"  seeded {spec['tool_id']}")
        db.commit()
        rows = db.execute(text("select tool_id, name from custom_tools where tool_id like 'db\\_%' "
                               "order by tool_id")).fetchall()
        print("db_* tools:", [r[0] for r in rows])
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
