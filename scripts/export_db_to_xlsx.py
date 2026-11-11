#!/usr/bin/env python
"""Export a Postgres database to one Excel workbook: index, column catalog, one sheet per table.

Written for the ontology profile databases (``backend/features/ontology/profiles/<profile>/settings.json``
carries a `dsn` block with ``${ENV:-default}`` placeholders), but it takes any DSN.

Usage — run it with the interpreter that has psycopg2 + openpyxl (the backend venv):

    backend/.venv/bin/python scripts/export_db_to_xlsx.py --profile retail --out retail_db_export.xlsx
    backend/.venv/bin/python scripts/export_db_to_xlsx.py \
        --dsn postgresql://user:pass@127.0.0.1:15432/retail_db --out /tmp/any.xlsx
    backend/.venv/bin/python scripts/export_db_to_xlsx.py --profile retail --tables customers,orders

What it does, and what it deliberately does not:

* **Read-only**: the session is opened ``readonly=True, autocommit=True``. Nothing in
  the source database can be changed by this script, including by a typo in ``--tables``
  (it quotes every identifier and only ever runs SELECT / count(*)).
* **One sheet per table**, with the header frozen, an auto-filter and column widths sized
  from the data — a workbook someone can actually read, not a dump.
* **jsonb → compact JSON text**, timestamps → ISO-8601, NULL → empty cell. Excel has no
  JSON or timezone type; writing Python objects makes openpyxl guess, and a jsonb column
  that arrives as ``str(dict)`` (single quotes) is no longer valid JSON.
* **A `catalog` sheet** (every column, its type, nullability, default) and a **`00_index`
  sheet** (source, export time, row counts, foreign keys). Without the catalog the
  workbook is data you cannot validate; the row counts are the check that nothing was cut.

Exit codes: 0 written, 1 nothing to export or the source is unreachable, 2 bad arguments.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PROFILES_DIR = REPO / "backend" / "features" / "ontology" / "profiles"

PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_placeholders(value: Any) -> Any:
    """Resolve ``${VAR}`` / ``${VAR:-default}`` against the environment, as the ontology profiles do."""
    if not isinstance(value, str):
        return value
    return PLACEHOLDER.sub(lambda m: os.environ.get(m.group(1)) or (m.group(2) or ""), value)


def load_profile_dsn(profile: str) -> dict:
    """Build a psycopg2 kwargs dict from an ontology profile's `dsn` block."""
    path = PROFILES_DIR / profile / "settings.json"
    if not path.is_file():
        known = sorted(p.name for p in PROFILES_DIR.iterdir() if (p / "settings.json").is_file()) \
            if PROFILES_DIR.is_dir() else []
        raise SystemExit(f"unknown profile {profile!r} (no {path}); known: {', '.join(known) or 'none'}")
    settings = json.loads(path.read_text(encoding="utf-8"))
    dsn = settings.get("dsn") or {}
    if not dsn:
        raise SystemExit(f"profile {profile!r} has no `dsn` block in {path}")
    kwargs = {}
    for key in ("host", "port", "dbname", "user", "password"):
        if dsn.get(key) is not None:
            kwargs[key] = expand_placeholders(dsn[key])
    kwargs.setdefault("port", 5432)
    try:
        kwargs["port"] = int(kwargs["port"])
    except (TypeError, ValueError):
        raise SystemExit(f"profile {profile!r}: port {kwargs['port']!r} is not a number")
    return kwargs


HEADER_FONT = ("FFFFFF",)
TITLE_SIZE = 14


def _styles():
    from openpyxl.styles import Alignment, Font, PatternFill

    return (
        Font(bold=True, color=HEADER_FONT[0]),
        PatternFill("solid", fgColor="2F5597"),
        Alignment(vertical="center"),
        Font(bold=True, size=TITLE_SIZE),
    )


def cell_value(value):
    """Excel-safe scalar for a DB value."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, (dt.timedelta, bytes, memoryview)):
        return str(value)
    return value


def style_header(ws, ncols: int) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill  # noqa: F401  (kept local: import cost)

    header_font, header_fill, align, _ = _styles()
    for col in range(1, ncols + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align
    from openpyxl.utils import get_column_letter

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(max(ncols, 1))}1"


def autosize(ws, widths: list[int]) -> None:
    from openpyxl.utils import get_column_letter

    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = min(max(width, 10), 60)


def main() -> int:
    ap = argparse.ArgumentParser(description="Export a Postgres database to one Excel workbook.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--profile", help="ontology profile name (reads backend/features/ontology/profiles/<name>/settings.json)")
    src.add_argument("--dsn", help="full DSN, e.g. postgresql://user:pass@host:5432/dbname")
    ap.add_argument("--out", default="db_export.xlsx", help="output .xlsx path")
    ap.add_argument("--tables", help="comma-separated table names (default: every table in the public schema)")
    ap.add_argument("--schema", default="public", help="schema to read (default: public)")
    args = ap.parse_args()

    try:
        import psycopg2
        import psycopg2.extras
        from openpyxl import Workbook
    except ImportError as exc:  # pragma: no cover - depends on the interpreter used
        print(f"missing dependency ({exc}); run this with the backend venv:\n"
              f"  backend/.venv/bin/python {Path(__file__).relative_to(REPO)} --profile … --out …",
              file=sys.stderr)
        return 2

    if args.profile:
        kwargs = load_profile_dsn(args.profile)
        source_label = f"{args.profile} ({kwargs.get('user')}@{kwargs.get('host')}:{kwargs.get('port')}/{kwargs.get('dbname')})"
    else:
        kwargs = {"dsn": args.dsn}
        source_label = args.dsn

    try:
        conn = psycopg2.connect(**kwargs)
    except Exception as exc:
        print(f"cannot connect to {source_label}: {exc}", file=sys.stderr)
        return 1
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(
        """select table_name from information_schema.tables
            where table_schema = %s and table_type = 'BASE TABLE'
            order by 1""",
        (args.schema,),
    )
    tables = [r["table_name"] for r in cur.fetchall()]
    if args.tables:
        wanted = [t.strip() for t in args.tables.split(",") if t.strip()]
        missing = [t for t in wanted if t not in tables]
        if missing:
            print(f"not found in schema {args.schema!r}: {', '.join(missing)}", file=sys.stderr)
            print(f"available: {', '.join(tables)}", file=sys.stderr)
            return 1
        tables = wanted
    if not tables:
        print(f"no tables in schema {args.schema!r}", file=sys.stderr)
        return 1

    cur.execute(
        """select table_name, column_name, data_type, is_nullable,
                  coalesce(column_default, '') as column_default, ordinal_position
             from information_schema.columns
            where table_schema = %s order by table_name, ordinal_position""",
        (args.schema,),
    )
    catalog = cur.fetchall()

    cur.execute(
        """select conrelid::regclass::text as tbl, conname, pg_get_constraintdef(oid) as definition
             from pg_constraint
            where contype = 'f' and connamespace = (select oid from pg_namespace where nspname = %s)
            order by 1, 2""",
        (args.schema,),
    )
    fks = cur.fetchall()

    counts: dict[str, int] = {}
    for table in tables:
        cur.execute(f'select count(*) as n from "{table}"')  # identifier quoted, never user SQL
        counts[table] = cur.fetchone()["n"]

    wb = Workbook()
    _, _, _, title_font = _styles()

    ws = wb.active
    ws.title = "00_index"
    ws["A1"] = f"{kwargs.get('dbname') or args.dsn} — Postgres 导出"
    ws["A1"].font = title_font
    meta: list[tuple[Any, Any]] = [
        ("源库", source_label),
        ("schema", args.schema),
        ("导出时间", dt.datetime.now().isoformat(sep=" ", timespec="seconds")),
        ("表数量", len(tables)),
        ("总行数", sum(counts.values())),
        ("", ""),
        ("表", "行数"),
    ]
    for row in meta:
        ws.append(list(row))
    for table in tables:
        ws.append([table, counts[table]])
    ws.append(["", ""])
    ws.append(["外键", "定义"])
    for fk in fks:
        ws.append([f"{fk['tbl']}.{fk['conname']}", fk["definition"]])
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 70

    ws = wb.create_sheet("catalog")
    ws.append(["表", "列", "类型", "可空", "默认值", "位置"])
    for row in catalog:
        ws.append([row["table_name"], row["column_name"], row["data_type"],
                   row["is_nullable"], row["column_default"], row["ordinal_position"]])
    style_header(ws, 6)
    autosize(ws, [22, 22, 24, 8, 16, 8])

    for table in tables:
        ws = wb.create_sheet(table[:31])
        cur.execute(f'select * from "{table}"')  # identifier quoted, never user SQL
        records = cur.fetchall()
        columns = [d.name for d in cur.description]
        ws.append(columns)
        for record in records:
            ws.append([cell_value(record[c]) for c in columns])
        style_header(ws, len(columns))
        widths = []
        for c in columns:
            longest = len(c)
            for record in records[:200]:
                value = cell_value(record[c])
                longest = max(longest, len(str(value)) if value is not None else 0)
            widths.append(longest + 2)
        autosize(ws, widths)

    out = Path(args.out).expanduser().resolve()
    wb.save(out)
    conn.close()

    print(f"wrote {out}")
    print(f"  sheets: 00_index, catalog, {', '.join(tables)}")
    for table in tables:
        print(f"  {table:24} {counts[table]:>6} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
