#!/usr/bin/env python
"""Load an Excel workbook into a new Postgres database: one sheet per table, types inferred.

The companion of `export_db_to_xlsx.py` — that one takes a database apart into sheets,
this one puts sheets back together as a database. Written for the Excel/CSV chat agents
(they query a real database, so the spreadsheet has to become one first).

    backend/.venv/bin/python scripts/load_workbook_to_postgres.py \
        --file retail_db_export.xlsx --db retail_xlsx

What it decides, and why:

* **Which sheets are data.** Meta sheets produced by the exporter (`00_index`,
  `catalog`) are skipped by default — they describe the export, they are not tables.
  `--sheets` and `--skip-sheets` override that.
* **Column types** are inferred from the values, not from Excel's formatting: a column
  of whole numbers is `BIGINT`, decimals are `NUMERIC`, ISO-8601 strings are
  `TIMESTAMPTZ`, values that all parse as JSON objects/arrays are `JSONB`, everything
  else is `TEXT`. The inferred type is printed per column, so a wrong guess is visible
  in the transcript instead of surprising someone mid-query.
* **Identifiers are sanitised to ASCII** (`订单编号` style headers keep a stable
  `c1`, `c2` … fallback; spaces/punctuation become `_`) because a chat agent writes SQL
  by hand and quoted-Chinese identifiers are where that goes wrong.
* `--dry-run` prints the DDL and touches nothing; `--recreate` drops an existing
  target database, and is refused unless the name ends in `_xlsx`/`_csv`/`_test` — a
  typo must not drop `retail_db`.

Exit codes: 0 loaded, 1 nothing to load / connect failure, 2 bad arguments.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

IDENT_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
DEFAULT_SKIP = {"00_index", "catalog"}


# ── pure helpers (unit-tested) ───────────────────────────────────────────────

def sanitize_ident(name: str, fallback: str = "c") -> str:
    """ASCII identifier from an arbitrary header."""
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", str(name or "").strip()).strip("_").lower()
    if not cleaned:
        return fallback
    if cleaned[0].isdigit():
        cleaned = f"{fallback}_{cleaned}"
    return cleaned[:60]


def unique_names(headers: list[str]) -> list[str]:
    """Sanitised headers with duplicates disambiguated (`name`, `name_2`, …)."""
    out: list[str] = []
    seen: dict[str, int] = {}
    for i, header in enumerate(headers, start=1):
        base = sanitize_ident(header, fallback=f"c{i}")
        count = seen.get(base, 0) + 1
        seen[base] = count
        out.append(base if count == 1 else f"{base}_{count}")
    return out


def _is_int(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return value.is_integer()
    return False


def _is_number(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float, Decimal)):
        return True
    return False


MONEY_HINT = re.compile(r"(amount|price|total|cost|revenue|fee|balance|tax|discount|salary|budget)")


def infer_type(values: list, name: str = "") -> str:
    """Postgres type for one column, from its non-empty values (and its name, for money).

    Two deliberate deviations from "look only at the values":

    * ``price``/``amount``-like columns stay NUMERIC even when every value happens to be
      whole — storing money as BIGINT is a model that breaks the first time someone
      writes 99.5, and the exported ``products.price`` was 3 whole numbers.
    * booleans stay BOOLEAN. They arrive from Excel as Python bools, which are neither
      numbers nor strings, so a value-only classifier files them under TEXT and the
      database ends up with the literal strings "True"/"False".
    """
    vals = [v for v in values if v is not None and not (isinstance(v, str) and v.strip() == "")]
    if not vals:
        return "TEXT"
    if all(isinstance(v, bool) for v in vals):
        return "BOOLEAN"
    if all(_is_number(v) for v in vals) and MONEY_HINT.search(name or ""):
        return "NUMERIC"
    if all(isinstance(v, dt.datetime) for v in vals):
        return "TIMESTAMPTZ"
    if all(isinstance(v, dt.date) for v in vals):
        return "DATE"
    if all(_is_int(v) for v in vals):
        return "BIGINT"
    if all(_is_number(v) for v in vals):
        return "NUMERIC"
    if all(isinstance(v, str) for v in vals):
        if all(ISO_TS.match(v.strip()) for v in vals):
            return "TIMESTAMPTZ"
        if all(v.strip().startswith(("{", "[")) for v in vals):
            try:
                for v in vals[:50]:
                    json.loads(v)
                return "JSONB"
            except (ValueError, TypeError):
                return "TEXT"
    return "TEXT"


def coerce(value, pg_type: str):
    """Turn a cell into something psycopg2 will accept for `pg_type`.

    A cell that does not fit the inferred type becomes NULL instead of aborting the
    load: one stray "N/A" in a column of numbers should cost one value, not the whole
    table. The loader counts those conversions and prints them, so a column whose type
    was inferred wrong is visible rather than silent — `test_every_inferred_type_has_a_coercion`
    exists because this path raised `decimal.InvalidOperation` before it was guarded.
    """
    try:
        return _coerce(value, pg_type)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _coerce(value, pg_type: str):
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    if pg_type == "TEXT":
        return value if isinstance(value, str) else str(value)
    if pg_type == "BOOLEAN":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "t", "1", "yes", "y"):
            return True
        if text in ("false", "f", "0", "no", "n"):
            return False
        return None
    if pg_type == "BIGINT":
        if isinstance(value, str):
            value = value.strip()
        return int(Decimal(str(value)))
    if pg_type == "NUMERIC":
        try:
            return Decimal(str(value).strip())
        except InvalidOperation:
            return None
    if pg_type == "TIMESTAMPTZ":
        if isinstance(value, dt.datetime):
            return value
        return value.strip() if isinstance(value, str) else str(value)
    if pg_type == "JSONB":
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return value


# ── main ────────────────────────────────────────────────────────────────────

def read_sheet(ws) -> tuple[list[str], list[list]]:
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []
    headers = [("" if c is None else str(c)) for c in rows[0]]
    data = [list(r) for r in rows[1:] if any(c is not None and str(c).strip() != "" for c in r)]
    return headers, data


def main() -> int:
    ap = argparse.ArgumentParser(description="Load an Excel workbook into a new Postgres database.")
    ap.add_argument("--file", required=True, help="path to .xlsx")
    ap.add_argument("--db", required=True, help="target database name (created if missing)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=15432)
    ap.add_argument("--user", default="postgres")
    ap.add_argument("--password", default="postgres")
    ap.add_argument("--schema", default="public")
    ap.add_argument("--sheets", help="comma-separated sheets to load (default: all data sheets)")
    ap.add_argument("--skip-sheets", help="comma-separated sheets to skip (default: 00_index,catalog)")
    ap.add_argument("--recreate", action="store_true", help="drop the target database first (name must end _xlsx/_csv/_test)")
    ap.add_argument("--dry-run", action="store_true", help="print the DDL and load nothing")
    args = ap.parse_args()

    try:
        from openpyxl import load_workbook
        import psycopg2
        from psycopg2.extras import execute_values
    except ImportError as exc:
        print(f"missing dependency ({exc}); run with the backend venv: backend/.venv/bin/python …",
              file=sys.stderr)
        return 2

    src = Path(args.file).expanduser()
    if not src.is_file():
        print(f"no such file: {src}", file=sys.stderr)
        return 1

    if args.recreate and not re.search(r"_(xlsx|csv|test)$", args.db):
        print(f"refusing --recreate on {args.db!r}: the name must end in _xlsx/_csv/_test", file=sys.stderr)
        return 2

    wb = load_workbook(src, data_only=True, read_only=True)
    skip = set(DEFAULT_SKIP if args.skip_sheets is None else
               {s.strip() for s in args.skip_sheets.split(",") if s.strip()})
    wanted = ({s.strip() for s in args.sheets.split(",") if s.strip()} if args.sheets else None)

    sheets = []
    for name in wb.sheetnames:
        if wanted is not None:
            if name not in wanted:
                continue
        elif name in skip:
            continue
        headers, data = read_sheet(wb[name])
        if not headers or not data:
            print(f"skip {name!r}: empty")
            continue
        cols = unique_names(headers)
        types = [infer_type([row[i] if i < len(row) else None for row in data], name=cols[i])
                 for i in range(len(headers))]
        sheets.append({"name": name, "table": sanitize_ident(name, fallback="sheet"), "cols": cols,
                       "types": types, "rows": data})
    wb.close()

    if not sheets:
        print("nothing to load (no data sheets matched)", file=sys.stderr)
        return 1

    print(f"source: {src}")
    for s in sheets:
        print(f"\n[{s['name']}] -> {s['table']}  ({len(s['rows'])} rows)")
        for col, pg in zip(s["cols"], s["types"]):
            print(f"   {col:<24} {pg}")
        if args.dry_run:
            ddl = ", ".join(f'"{c}" {t}' for c, t in zip(s["cols"], s["types"]))
            print(f"   CREATE TABLE \"{args.schema}\".\"{s['table']}\" ({ddl});")

    if args.dry_run:
        print("\ndry run: nothing created")
        return 0

    admin = dict(host=args.host, port=args.port, user=args.user, password=args.password, dbname="postgres")
    try:
        conn = psycopg2.connect(**admin)
    except Exception as exc:
        print(f"cannot connect to {args.host}:{args.port} as {args.user}: {exc}", file=sys.stderr)
        return 1
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("select 1 from pg_database where datname = %s", (args.db,))
        exists = cur.fetchone() is not None
        if exists and args.recreate:
            cur.execute(f'DROP DATABASE "{args.db}" with (force)')
            exists = False
            print(f"\ndropped {args.db}")
        if not exists:
            cur.execute(f'CREATE DATABASE "{args.db}"')
            print(f"created database {args.db}")
    conn.close()

    conn = psycopg2.connect(host=args.host, port=args.port, user=args.user,
                            password=args.password, dbname=args.db)
    conn.autocommit = False
    loaded = []
    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{args.schema}"')
        for s in sheets:
            ddl_cols = ", ".join(f'"{c}" {t}' for c, t in zip(s["cols"], s["types"]))
            cur.execute(f'DROP TABLE IF EXISTS "{args.schema}"."{s["table"]}"')
            cur.execute(f'CREATE TABLE "{args.schema}"."{s["table"]}" ({ddl_cols})')
            payload = []
            rejected = 0
            for row in s["rows"]:
                out = []
                for i, t in enumerate(s["types"]):
                    raw = row[i] if i < len(row) else None
                    value = coerce(raw, t)
                    if value is None and raw is not None and str(raw).strip() != "":
                        rejected += 1
                    out.append(value)
                payload.append(out)
            cols_sql = ", ".join(f'"{c}"' for c in s["cols"])
            execute_values(cur, f'INSERT INTO "{args.schema}"."{s["table"]}" ({cols_sql}) VALUES %s',
                           payload, page_size=500)
            cur.execute(f'SELECT count(*) FROM "{args.schema}"."{s["table"]}"')
            actual = cur.fetchone()[0]
            ok = actual == len(s["rows"])
            loaded.append((s["table"], actual, len(s["rows"]), ok))
            note = f" ({rejected} cell(s) kept as NULL — type may not fit)" if rejected else ""
            print(f"  {s['table']:<24} {actual:>6} rows {'✓' if ok else '✗ MISMATCH'}{note}")
    conn.commit()
    conn.close()

    bad = [x for x in loaded if not x[3]]
    print(f"\nloaded {len(loaded)} tables into {args.db}"
          + (f" — {len(bad)} row-count mismatches!" if bad else " — row counts match the workbook"))
    print(f"  DSN: postgresql://{args.user}@{args.host}:{args.port}/{args.db}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
