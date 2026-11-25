#!/usr/bin/env python3
"""Phase 1: read a PostgreSQL database and print the brief an ontology is built from.

The brief is deliberately small and decision-oriented — it answers the questions the
configuration has to answer, not "what is in this database":

  * which tables are candidates for OBJECTS (a primary key, an identity)
  * which columns are LINKS (FKs), and whether a table is a many-to-one link or a
    many-to-many association that carries its own payload (it must become a class)
  * how big each table is, and whether it has a date column (a time window is only
    meaningful if the data is recent — check `date_range`, do not assume now())
  * the cardinality of candidate DIMENSIONS (a column with 800 distinct values is not a
    label; a column with 4 is a dimension)
  * NULL semantics on columns that will become definitions (a NULL is not false)

Usage:
    python introspect_db.py --dsn "host=127.0.0.1 port=5432 dbname=mydb user=me" \
        [--schema public] [--out brief.json] [--sample-nulls]
"""
from __future__ import annotations

import argparse
import json
import sys

import psycopg2

# a dimension needs few distinct values; a label needs many. These are counting hints only —
# the human still decides what a dimension means.
DIMENSION_MAX = 200


def parse_dsn(text: str) -> dict:
    out: dict = {}
    for part in text.split():
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--schema", default="public")
    ap.add_argument("--out", default="")
    ap.add_argument("--sample-nulls", action="store_true",
                    help="count NULLs per column (slower; needed for definitions)")
    args = ap.parse_args()

    conn = psycopg2.connect(**parse_dsn(args.dsn))
    conn.autocommit = True          # read-only introspection, no transaction needed
    cur = conn.cursor()

    cur.execute("""
        SELECT c.relname, c.reltuples::bigint,
               pg_size_pretty(pg_total_relation_size(c.oid))
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relkind = 'r'
        ORDER BY c.reltuples DESC
    """, (args.schema,))
    tables = cur.fetchall()
    # a freshly loaded database has no statistics yet (reltuples = -1): the brief would then
    # say "unknown" for every table, which is worse than a slow exact count. ANALYZE first.
    if tables and any(int(t[1]) < 0 for t in tables):
        print("no statistics yet (reltuples = -1): running ANALYZE", file=sys.stderr)
        for table, _rows, _size in tables:
            try:
                cur.execute(f'ANALYZE "{args.schema}"."{table}"')
            except psycopg2.Error:
                pass
        cur.execute("""
            SELECT c.relname, c.reltuples::bigint,
                   pg_size_pretty(pg_total_relation_size(c.oid))
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relkind = 'r'
            ORDER BY c.reltuples DESC
        """, (args.schema,))
        tables = cur.fetchall()

    brief: dict = {"dsn": args.dsn, "schema": args.schema, "tables": []}
    for table, est_rows, size in tables:
        cur.execute("""
            SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
                   pg_get_expr(d.adbin, d.adrelid) AS default_expr
            FROM pg_attribute a
            LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
            WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum
        """, (f"{args.schema}.{table}",))
        cols = [{"column": r[0], "type": r[1], "not_null": r[2], "default": r[3]}
                for r in cur.fetchall()]

        cur.execute("""
            SELECT a.attname FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary
            ORDER BY array_position(i.indkey, a.attnum)
        """, (f"{args.schema}.{table}",))
        pk = [r[0] for r in cur.fetchall()]

        # one row per FK, including composite keys: conkey/confkey are arrays
        cur.execute("""
            SELECT con.conname,
                   (SELECT array_agg(a.attname ORDER BY x.ord)
                      FROM unnest(con.conkey) WITH ORDINALITY AS x(attnum, ord)
                      JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = x.attnum),
                   cl.relname,
                   (SELECT array_agg(a.attname ORDER BY x.ord)
                      FROM unnest(con.confkey) WITH ORDINALITY AS x(attnum, ord)
                      JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = x.attnum)
            FROM pg_constraint con
            JOIN pg_class cl ON cl.oid = con.confrelid
            WHERE con.conrelid = %s::regclass AND con.contype = 'f'
        """, (f"{args.schema}.{table}",))
        fks = [{"name": r[0], "columns": list(r[1] or []), "references": r[2],
                "reference_columns": list(r[3] or [])} for r in cur.fetchall()]

        entry = {"table": table, "estimated_rows": int(est_rows), "size": size,
                 "primary_key": pk, "columns": cols, "foreign_keys": fks,
                 "date_columns": [], "dimensions": [], "label_candidates": []}

        # what matters for a *time window*: does this table have dates, and how recent?
        for c in cols:
            if "date" in c["type"] or "timestamp" in c["type"]:
                try:
                    cur.execute(f'SELECT min("{c["column"]}"), max("{c["column"]}") '
                                f'FROM "{args.schema}"."{table}"')
                    lo, hi = cur.fetchone()
                    entry["date_columns"].append({"column": c["column"],
                                                  "min": str(lo), "max": str(hi)})
                except psycopg2.Error:
                    entry["date_columns"].append({"column": c["column"], "min": None, "max": None})

        # dimensions vs labels: distinct count decides which questions are answerable
        for c in cols:
            if c["type"].lower().startswith(("text", "character", "boolean")):
                try:
                    cur.execute(f'SELECT count(DISTINCT "{c["column"]}") '
                                f'FROM "{args.schema}"."{table}"')
                    n = cur.fetchone()[0]
                    if n and n <= DIMENSION_MAX:
                        cur.execute(f'SELECT "{c["column"]}" FROM "{args.schema}"."{table}" '
                                    f'WHERE "{c["column"]}" IS NOT NULL '
                                    f'GROUP BY 1 ORDER BY 1 LIMIT 12')
                        entry["dimensions"].append({"column": c["column"], "distinct": n,
                                                    "values": [str(r[0]) for r in
                                                               cur.fetchall()]})
                    elif n:
                        entry["label_candidates"].append({"column": c["column"],
                                                          "distinct": n})
                except psycopg2.Error:
                    pass

        if args.sample_nulls:
            for c in cols:
                if c["not_null"]:
                    continue
                try:
                    cur.execute(f'SELECT count(*) FILTER (WHERE "{c["column"]}" IS NULL), '
                                f'count(*) FROM "{args.schema}"."{table}"')
                    nulls, total = cur.fetchone()
                    c["null_count"] = int(nulls)
                    c["null_note"] = "NULL is a state, not false" if nulls else "none"
                except psycopg2.Error:
                    pass

        # Shape is a DECISION, and the brief flags the candidates rather than deciding:
        #   · PK == the FK columns                -> a pure junction (many-to-many link)
        #   · 2+ FKs, payload, and NO date column -> probably an association that carries
        #     data (reification: it becomes a class) — but it may be an event table whose
        #     timestamps were not modelled, so it asks for confirmation
        #   · otherwise                            -> an object
        fk_cols = {c for f in fks for c in f["columns"]}
        payload = [c["column"] for c in cols
                   if c["column"] not in (pk or []) and c["column"] not in fk_cols]
        if pk and fk_cols and set(pk) == fk_cols:
            entry["shape_hint"] = "junction (PK = the FKs): a pure many-to-many link"
            entry["shape_question"] = ("does this link carry data of its own? if yes it is a "
                                       "reified class, not a junction")
        elif len(fks) >= 2 and payload and not entry["date_columns"]:
            entry["shape_hint"] = "suspect association with payload — CONFIRM with the human"
            entry["shape_question"] = ("is this an event object (it has a time, an actor, a "
                                       "result) or an association carrying data?")
        elif len(pk) > 1:
            entry["shape_hint"] = ("composite key — junction or entity with a natural key; "
                                   "CONFIRM")
            entry["shape_question"] = ("is each row a relationship between two objects "
                                       "(junction) or an entity with its own identity?")
        elif pk:
            entry["shape_hint"] = "object"
        else:
            entry["shape_hint"] = "no primary key — one is needed before it can be an object"
        brief["tables"].append(entry)

    conn.close()
    text = json.dumps(brief, indent=2, ensure_ascii=False, default=str)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text + "\n")
        print(f"wrote {args.out} ({len(brief['tables'])} tables)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
