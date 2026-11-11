#!/usr/bin/env python
"""Review a Postgres database's tables, then (optionally) give it primary and foreign keys.

For a database loaded from a spreadsheet — `load_workbook_to_postgres.py` brings the
rows but not the model — the constraints are the part nobody wrote down. This finds them
from the data and, when asked, applies them:

    backend/.venv/bin/python scripts/review_db_constraints.py --db retail_xlsx            # report only
    backend/.venv/bin/python scripts/review_db_constraints.py --db retail_xlsx --apply     # add PKs/FKs

How a candidate is chosen (and why it is checkable rather than a guess):

* **Primary key**: a column with no NULLs and as many distinct values as rows. Tables
  without one are reported as such — a surrogate id is added only with `--add-surrogate`,
  because inventing a column changes the schema the agent will query.
* **Foreign key**: a column whose *every* value exists in another table's primary key,
  with a compatible type. The check is an anti-join count, so "looks like an FK" and "is an
  FK" are different things: `orders.amount` matches nothing, while `orders.sold_at` is an
  integer that happens to be 1 or 2 — it only becomes an FK because both values are store
  ids, which the anti-join proves and the name does not.
* Nothing is applied when integrity fails: a column with orphans is reported with the
  count, not constrained. A constraint that has to be forced is a constraint that will lie.

The report always runs before any change, and `--apply` re-checks rather than trusting the
report: the database may have moved between the two.

Exit codes: 0 ok, 1 connection/selection problem or (with --apply) a constraint that
could not be added.
"""
from __future__ import annotations

import argparse
import sys


def q(cur, sql: str, params=None):
    cur.execute(sql, params or ())
    return cur.fetchall()


def table_columns(cur, schema: str, table: str) -> list[tuple[str, str]]:
    rows = q(cur, """select column_name, data_type from information_schema.columns
                      where table_schema=%s and table_name=%s order by ordinal_position""",
             (schema, table))
    return [(r[0], r[1]) for r in rows]


def tables_in(cur, schema: str) -> list[str]:
    return [r[0] for r in q(cur, """select table_name from information_schema.tables
                                     where table_schema=%s and table_type='BASE TABLE'
                                     order by 1""", (schema,))]


def existing_keys(cur, schema: str) -> tuple[dict, list]:
    pk: dict[str, list[str]] = {}
    for table, col in q(cur, """
            select c.relname, a.attname
              from pg_index i
              join pg_class c on c.oid = i.indrelid
              join pg_namespace n on n.oid = c.relnamespace
              join pg_attribute a on a.attrelid = c.oid and a.attnum = any(i.indkey)
             where i.indisprimary and n.nspname = %s
             order by c.relname, a.attnum""", (schema,)):
        pk.setdefault(table, []).append(col)
    fks = q(cur, """
            select conrelid::regclass::text, conname, pg_get_constraintdef(oid)
              from pg_constraint
             where contype='f' and connamespace=(select oid from pg_namespace where nspname=%s)
             order by 1,2""", (schema,))
    return pk, fks


def column_stats(cur, schema: str, table: str) -> list[dict]:
    cols = table_columns(cur, schema, table)
    cur.execute(f'select count(*) from "{schema}"."{table}"')
    total = cur.fetchone()[0]
    stats = []
    for col, dtype in cols:
        # count(*) FILTER avoids a second scan per column and keeps NULLs honest.
        cur.execute(f'select count(*) filter (where "{col}" is null), count(distinct "{col}") '
                    f'from "{schema}"."{table}"')
        nulls, distinct = cur.fetchone()
        stats.append({"column": col, "type": dtype, "nulls": nulls,
                      "distinct": distinct, "total": total})
    return stats


def pk_candidates(stats: list[dict], table: str = "") -> list[str]:
    """Unique, non-null columns, ranked — because "unique" is not the same as "identifies".

    Under 4 rows of sample data, `orders.amount` and `orders.placed_at` are also unique,
    and taking the first unique column alphabetically would have made `amount` a primary
    key. Naming decides the order instead: `id` first, then `<table>_id`, then any other
    `*_id`; timestamps and money columns sink to the bottom because they are unique by
    accident rather than by design.
    """
    cand = [c["column"] for c in stats
            if c["total"] > 0 and c["nulls"] == 0 and c["distinct"] == c["total"]]

    def score(col: str) -> int:
        name = col.lower()
        if name == "id":
            return 0
        if name == f"{table.rstrip('s')}_id":
            return 1
        if name.endswith("_id"):
            return 2
        if name.endswith("_at") or name.endswith("_ts") or name in ("ts", "date"):
            return 8
        if any(k in name for k in ("amount", "price", "total", "cost", "revenue", "qty")):
            return 9
        return 5

    return sorted(cand, key=score)


MISLEADING_NAME = __import__("re").compile(r"(_at|_by|_code|_no|_num|_key|_ref)$")


def looks_like_fk(col: str) -> bool:
    """A reference column by convention. `id` itself is never a foreign key."""
    return col.lower().endswith("_id") and col.lower() != "id"


def natural_targets(col: str, tables: list[str]) -> list[str]:
    """`customer_id` names the table it points at: customers.

    Without this, value containment alone proposed nonsense in a 4-row database —
    `customer_categories.customer_id → order_lines.id` "passed" because every customer
    id also happens to be an order-line id. A reference is a column *and* a target, and
    only the name can say which target.
    """
    if not looks_like_fk(col):
        return []
    base = col.lower()[:-3]
    return [t for t in tables
            if t.lower() in (base, f"{base}s", f"{base}es") or t.lower().rstrip("s") == base]


def orphan_count(cur, schema: str, table: str, col: str, ref_table: str, ref_col: str) -> int:
    cur.execute(f'''select count(*) from "{schema}"."{table}" t
                     where t."{col}" is not null
                       and not exists (select 1 from "{schema}"."{ref_table}" r where r."{ref_col}" = t."{col}")''')
    return cur.fetchone()[0]


TYPE_FAMILY = {
    "smallint": "int", "integer": "int", "bigint": "int", "numeric": "num",
    "real": "num", "double precision": "num", "text": "txt", "character varying": "txt",
    "character": "txt", "boolean": "bool", "timestamp with time zone": "ts",
    "timestamp without time zone": "ts", "date": "date", "jsonb": "json", "json": "json",
}


def compatible(a: str, b: str) -> bool:
    return TYPE_FAMILY.get(a, a) == TYPE_FAMILY.get(b, b)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=15432)
    ap.add_argument("--user", default="postgres")
    ap.add_argument("--password", default="postgres")
    ap.add_argument("--schema", default="public")
    ap.add_argument("--apply", action="store_true", help="add the primary and foreign keys")
    ap.add_argument("--samples", type=int, default=3, help="sample rows per table in the report")
    args = ap.parse_args()

    try:
        import psycopg2
    except ImportError as exc:
        print(f"missing psycopg2 ({exc}); run with backend/.venv/bin/python", file=sys.stderr)
        return 1

    conn = psycopg2.connect(host=args.host, port=args.port, user=args.user,
                            password=args.password, dbname=args.db)
    cur = conn.cursor()
    schema = args.schema
    tables = tables_in(cur, schema)
    if not tables:
        print(f"no tables in {args.db}.{schema}", file=sys.stderr)
        return 1

    print(f"# 数据库体检：{args.db}  (schema {schema})")
    print(f"表数量：{len(tables)}\n")

    pk_existing, fk_existing = existing_keys(cur, schema)
    report = {}
    for table in tables:
        stats = column_stats(cur, schema, table)
        total = stats[0]["total"] if stats else 0
        print(f"## {table}  ({total} 行, {len(stats)} 列)")
        for c in stats:
            print(f"  - {c['column']:<22} {c['type']:<26} null={c['nulls']:<5} distinct={c['distinct']}")
        if total and args.samples:
            cur.execute(f'select * from "{schema}"."{table}" limit %s', (args.samples,))
            for row in cur.fetchall():
                print(f"    {row}")
        cand = pk_candidates(stats, table)
        report[table] = {"stats": stats, "pk": cand, "total": total}
        print(f"  PK 候选：{', '.join(cand) if cand else '（无：没有列同时满足 无空 且 唯一）'}")
        print()

    # ── foreign keys: every value must exist in a target PK ──────────────────
    # The chosen key, not every candidate: `customers` has both `id` and `name` unique, and
    # a target with two "primary keys" is a target no foreign key can point at.
    pk_map = {t: (pk_existing.get(t) or report[t]["pk"][:1]) for t in tables}
    print("## 外键候选（列名 + 取值双向核对）")
    fks: list[tuple[str, str, str, str]] = []
    value_only: list[tuple[str, str, str, str, int]] = []
    for table in tables:
        total = report[table]["total"]
        if total == 0:
            continue
        for c in report[table]["stats"]:
            col, dtype = c["column"], c["type"]
            if c["distinct"] == 0:
                continue
            targets = natural_targets(col, tables)
            if targets:
                for ref in targets:
                    if ref == table or not pk_map[ref] or len(pk_map[ref]) != 1:
                        continue
                    ref_col = pk_map[ref][0]
                    ref_type = next((s["type"] for s in report[ref]["stats"] if s["column"] == ref_col), "")
                    if not compatible(dtype, ref_type):
                        continue
                    orphans = orphan_count(cur, schema, table, col, ref, ref_col)
                    if orphans == 0:
                        print(f"  {table}.{col} → {ref}.{ref_col}   ✓ 列名指向该表，取值 0 孤儿（{c['distinct']} 种）")
                        fks.append((table, col, ref, ref_col))
                    else:
                        print(f"  {table}.{col} → {ref}.{ref_col}   ✗ {orphans} 行悬空（不建）")
                continue
            # Not a `*_id` column. Value containment alone is worthless in a database whose
            # ids are 1, 2, 3 — every small integer "fits" some table. Only a name that
            # *promises something else* (`_at`, `_code`, `_no` …) while holding integers that
            # land inside one table's key is worth reporting: that is a naming bug, and it
            # is exactly how `orders.sold_at` (a store id) hides in plain sight.
            if MISLEADING_NAME.search(col) and TYPE_FAMILY.get(dtype) == "int":
                matches = []
                for ref in tables:
                    if ref == table or not pk_map[ref] or len(pk_map[ref]) != 1:
                        continue
                    ref_col = pk_map[ref][0]
                    ref_type = next((r["type"] for r in report[ref]["stats"] if r["column"] == ref_col), "")
                    if TYPE_FAMILY.get(ref_type) != "int":
                        continue
                    if orphan_count(cur, schema, table, col, ref, ref_col) == 0:
                        matches.append((ref, ref_col, c["distinct"]))
                if matches:
                    value_only.append((table, col, matches))
    if not fks:
        print("  （无）")
    if value_only:
        print("\n  名字承诺的是时间/编码，取值却落在某张表的整数主键里（命名问题，不建约束）：")
        for table, col, matches in value_only:
            where = "、".join(f"{ref}.{ref_col}" for ref, ref_col, _ in matches)
            print(f"    {table}.{col}  取值 ⊆ {where}  ← 建议改名（如 store_id）后再建外键")

    if not args.apply:
        print("\n报告模式：没有改动数据库。加 --apply 才会建约束。")
        conn.close()
        return 0

    print("\n## 应用约束")
    failures = []
    for table in tables:
        if pk_existing.get(table):
            print(f"  {table}: 已有主键 ({', '.join(pk_existing[table])})，跳过")
            continue
        cand = report[table]["pk"]   # already ranked by name
        if not cand:
            print(f"  {table}: 无主键候选，跳过（不造替代键）")
            continue
        primary = cand[0]
        print(f"  {table}: 选 {primary} 作主键（候选 {', '.join(cand)}）")
        try:
            cur.execute(f'ALTER TABLE "{schema}"."{table}" ADD CONSTRAINT "{table}_pkey" PRIMARY KEY ("{primary}")')
            conn.commit()
            print(f"  {table}: PK ({primary}) ✓")
        except Exception as exc:
            conn.rollback()
            failures.append(f"{table} PK: {exc}")
            print(f"  {table}: PK 失败 — {exc}")

    taken = {(row[0].split(".")[-1], row[1]) for row in fk_existing}
    for table, col, ref, ref_col in fks:
        if (table, col) in taken:
            continue
        name = f"{table}_{col}_fkey"
        try:
            cur.execute(f'ALTER TABLE "{schema}"."{table}" ADD CONSTRAINT "{name}" '
                        f'FOREIGN KEY ("{col}") REFERENCES "{schema}"."{ref}" ("{ref_col}")')
            conn.commit()
            print(f"  {table}.{col} → {ref}.{ref_col}: FK ✓")
        except Exception as exc:
            conn.rollback()
            failures.append(f"{table}.{col} FK: {exc}")
            print(f"  {table}.{col} → {ref}.{ref_col}: FK 失败 — {exc}")

    print("\n## 结果")
    pk_after, fk_after = existing_keys(cur, schema)
    for table in tables:
        print(f"  {table:<22} PK={pk_after.get(table) or '-'}")
    print(f"  FK 数量：{len(fk_after)}")
    conn.close()
    if failures:
        print(f"\n{len(failures)} 个约束未能建立：")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
