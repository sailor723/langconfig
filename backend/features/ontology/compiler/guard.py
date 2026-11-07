"""SQL guardrails for a database that is not a toy.

Everything that reads the source database goes through here. The rules assume tens of
millions of rows in `orders` (and whatever else is declared big), so a query that would scan
an unbounded table, return an unbounded page, or cost more than the budget is narrowed —
and the narrowing is always *shown*, never silent.

The four promises:

1. **No free-form SQL.** Only SQL the compiler produced is run. The guard refuses anything
   that is not a single SELECT/CTE, and no HTTP route accepts SQL from the request.
2. **No unbounded page.** A missing `LIMIT` becomes `LIMIT max_rows`; a grouped metric gets
   its groups capped the same way. An existing `LIMIT` is never doubled.
3. **No unbounded scan — without changing what a number means.** There are two kinds of query
   and the guard treats them differently on purpose:

   * **listings** (`mode="rows"`, the default): "show me data". A big table with no time filter
     gets `time_col >= now() - interval 'N days'` injected, and the page is capped. Narrowing a
     listing is a scope decision, and it is shown.
   * **declared metrics** (`mode="declared"`): a metric's number IS its definition. Injecting a
     window here would silently answer a different question, so it is never injected — the
     unbounded scan is reported instead, and the plan budget decides whether it may run at all.
     A `LIMIT` is still applied: it caps rows/groups, never the aggregate.
4. **No surprise bill.** Every statement runs with `statement_timeout`, and its `EXPLAIN`
   estimate is checked first: a plan that would touch more than `max_plan_rows` rows on a big
   table is refused by name, with the numbers, instead of running for minutes.

Nothing here changes what a number *means* — the injected `LIMIT` and window are reported in
`notes`, and every caller shows them next to the SQL, so the reader can see the question was
narrowed and by how much.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time

BASE = pathlib.Path(__file__).resolve().parent
# The guard's settings come from the ACTIVE PROFILE (APP_SETTINGS); this is only the fallback for a
# process that was never pointed at one — and it points at retail's profile, the reference ontology,
# not at "whatever directory this module sits in" (a rule that made the guard read a stale file on
# every machine that was not the author's).
SETTINGS = pathlib.Path(os.environ.get("APP_SETTINGS")
                         or (BASE.parent / "profiles" / "retail" / "settings.json"))

DEFAULTS = {
    "enabled": True,
    "max_rows": 1000,            # LIMIT injected when a query has none
    "default_window_days": 90,   # time bound injected on a big table without one
    "statement_timeout_ms": 5000,
    "max_plan_rows": 2_000_000,  # refuse a plan that would scan more than this
    "big_tables": {"orders": "placed_at"},
}


class Refusal(Exception):
    """The query was refused by a guardrail, by name, before running."""


def config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        s = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return cfg
    for k, v in (s.get("guard") or {}).items():
        if v is not None:
            cfg[k] = v
    return cfg


# --------------------------------------------------------------------------- rewriting

_NOT_READ = re.compile(r"^\s*(insert|update|delete|merge|drop|alter|create|truncate|grant)\b",
                       re.I)
_HAS_LIMIT = re.compile(r"\blimit\s+\d+\s*;?\s*$", re.I)
_TIME_PRED = r"\b{p}\b\s*(>=|>|between)"


def _time_filtered(sql: str, column: str) -> bool:
    return re.search(_TIME_PRED.format(p=re.escape(column)), sql, re.I) is not None


NOT_ALIASES = {"where", "join", "on", "group", "order", "limit", "left", "right", "inner",
               "full", "cross", "union", "having", "as", "using", "when", "then", "else"}


def _qualified(table: str, column: str, sql: str) -> str:
    """Qualify with the table (or its alias) — an unqualified column is ambiguous in a JOIN."""
    m = re.search(rf"\b(?:from|join)\s+{re.escape(table)}\b\s+(?:as\s+)?([A-Za-z_][\w]*)",
                  sql, re.I)
    alias = m.group(1) if m and m.group(1).lower() not in NOT_ALIASES else None
    return f"{alias or table}.{column}"


def _where_insert(sql: str, predicate: str) -> str:
    """Add `predicate` to the statement's outermost WHERE / GROUP BY / ORDER BY / LIMIT."""
    body = sql.rstrip().rstrip(";")
    m = None
    for kw in (r"\bwhere\b", r"\bgroup\s+by\b", r"\border\s+by\b", r"\blimit\b"):
        found = list(re.finditer(kw, body, re.I))
        found = [f for f in found if not _inside_parens(body, f.start())]
        if found:
            m = found[0]
            break
    if m is None:
        return f"{body} WHERE {predicate};"
    start = m.start()
    head, tail = body[:start], body[start:]
    keyword = tail.split()[0] + ("" if not tail.lower().startswith("group") else "")
    # "WHERE ..." -> "WHERE (pred) AND ..."; anything else -> "WHERE pred <keyword> ..."
    if re.match(r"where\b", tail, re.I):
        return f"{head}WHERE ({predicate}) AND {tail[5:].lstrip()};"
    return f"{head}WHERE {predicate} {tail};"


def _inside_parens(text: str, index: int) -> bool:
    depth = 0
    for ch in text[:index]:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
    return depth > 0


def apply(sql: str, cfg: dict | None = None, *, window_days: int | None = None,
          mode: str = "rows") -> dict:
    """Return the guarded SQL and what was done to it. Never executes anything."""
    cfg = cfg or config()
    notes: list[str] = []
    window = None
    out = sql.strip()
    if not cfg.get("enabled"):
        return {"sql": out, "notes": [], "changed": False, "window": None}

    if _NOT_READ.match(out):
        raise Refusal("the guard only runs reads: this statement is not a SELECT")
    if out.count(";") > 1 or (out.count(";") == 1 and not out.rstrip().endswith(";")):
        raise Refusal("the guard runs ONE statement per query")

    big = {t.lower(): c for t, c in (cfg.get("big_tables") or {}).items()}
    touched = [t for t in big if re.search(rf"\b{re.escape(t)}\b", out, re.I)]
    declared = mode == "declared"
    days = int(window_days if window_days is not None else cfg["default_window_days"])
    for table in touched:
        column = big[table]
        if _time_filtered(out, column):
            continue
        if declared:
            # the metric's definition has no window: report the scan, do not rewrite the question
            notes.append(f"unbounded scan on {table} — the definition has no {column} filter "
                         f"(bounded only by the plan budget)")
            continue
        if days <= 0:
            raise Refusal(
                f"{table} is a big table and this query has no {column} filter — refusing an "
                f"unbounded scan (add a time window, or raise guard.default_window_days)")
        out = _where_insert(out, f"{_qualified(table, column, out)} >= "
                                 f"now() - interval '{days} days'")
        notes.append(f"+ {column} >= now() - {days} days  (unbounded scan on {table})")
        window = {"table": table, "column": column, "days": days}

    if not _HAS_LIMIT.search(out):
        rows = int(cfg["max_rows"])
        out = out.rstrip().rstrip(";") + f" LIMIT {rows};"
        notes.append(f"+ LIMIT {rows}  (page capped)")
    return {"sql": out, "notes": notes, "window": window,
            "changed": out.strip() != sql.strip()}


# --------------------------------------------------------------------------- plan budget


def plan_rows(cur, sql: str, params=None, cfg: dict | None = None) -> int:
    """EXPLAIN the statement and return the largest estimated row count it will produce.

    Two corrections over the first version, both measured on the clinic ontology:

    * **A fan-out lives on the top node, not on a scan.** `treatment_lines × invoices` scanned
      2,493 rows from a big table but its Nested Loop's estimate was 20,849,548 — the budget
      only looked at scan nodes, so a 20M-row plan was admitted and really returned 15.9M rows
      in 309 ms. If the statement touches a budgeted table, the ROOT estimate counts too.
    * **"Big" is not the same as "has a time column".** A table can be the largest one in the
      database and still have no timestamp to window on (`treatment_lines`: 6,443 rows, no date
      column). It belongs in the plan budget, not in `big_tables` (which also injects windows).
      Profiles list those in `large_tables`; they count for the budget only.
    """
    cfg = cfg or config()
    cur.execute("EXPLAIN (FORMAT JSON) " + sql, params)
    row = cur.fetchone()
    plan = row[0] if row else None
    if isinstance(plan, str):
        plan = json.loads(plan)
    big = {t.lower() for t in (cfg.get("big_tables") or {})}
    large = {t.lower() for t in (cfg.get("large_tables") or [])}
    budget = big | large
    worst = 0

    # Every node's estimate matters, not just the scan's: a cartesian join's cost is stated on
    # its Nested Loop (7.5M) while the root Aggregate says 1 and the scan says 3,236. A node
    # inside the plan is work the database has to do.
    worst_budget = 0
    worst_any = 0

    def walk(node: dict) -> None:
        nonlocal worst_budget, worst_any
        if not isinstance(node, dict):
            return
        rows = int(node.get("Plan Rows") or 0)
        worst_any = max(worst_any, rows)
        rel = (node.get("Relation Name") or "").lower()
        if rel in budget:
            worst_budget = max(worst_budget, rows)
        for child in node.get("Plans") or []:
            walk(child)

    for p in (plan if isinstance(plan, list) else [plan]):
        walk((p or {}).get("Plan") or {})
    touches = bool(budget) and any(re.search(rf"\b{re.escape(t)}\b", sql, re.I) for t in budget)
    return max(worst_budget, worst_any) if touches else worst_budget


# --------------------------------------------------------------------------- running


def run(cur, sql: str, params=None, cfg: dict | None = None, *,
        window_days: int | None = None, mode: str = "rows") -> dict:
    """Guard, budget-check, execute — in one place. Returns rows + the report to show."""
    cfg = cfg or config()
    g = apply(sql, cfg, window_days=window_days, mode=mode)
    started = time.perf_counter()
    ms = 0
    if cfg.get("enabled"):
        # Always SET, never SET LOCAL. `SET LOCAL` outside a transaction block is a no-op
        # with a warning, and psycopg2 reports STATUS_IN_TRANSACTION for a connection that
        # is not in one (measured: status == 1 right after connect, `SET LOCAL` then did
        # nothing, and a `pg_sleep(3)` ran to completion against a 400 ms timeout — the
        # timeout gate could not fail, so it proved nothing). A plain SET always applies;
        # it is re-issued before every statement, so a rollback cannot leave it missing.
        cur.execute(f"SET statement_timeout = {int(cfg['statement_timeout_ms'])}")
        estimate = plan_rows(cur, g["sql"], params, cfg)
        if estimate > int(cfg["max_plan_rows"]):
            raise Refusal(
                f"the plan would read ~{estimate:,} rows from a big table, over the "
                f"{int(cfg['max_plan_rows']):,} budget — narrow the window or add a filter")
        g["plan_rows"] = estimate
    cur.execute(g["sql"], params)
    ms = int((time.perf_counter() - started) * 1000)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description] if cur.description else []
    if g.get("window") and not rows:
        # the window we invented matched nothing: the data is probably not relative to today.
        # Report it as a guard effect instead of letting an empty page look like a fact.
        w = g["window"]
        g["notes"] = [n for n in g["notes"] if "now() - " not in n]
        g["notes"].append(
            f"the injected window ({w['column']} >= now() - {w['days']} days) matched 0 rows — "
            f"this table's dates may not be now-relative "
            f"(set guard.default_window_days = 0 to refuse instead of narrowing)")
    g["rows"] = rows
    g["cols"] = cols
    g["ms"] = ms
    return g


def report(g: dict) -> str:
    """One line for the UI/CLI: what the guard did, in the same terms as the SQL."""
    bits = []
    if g.get("plan_rows"):
        bits.append(f"plan ≈ {int(g['plan_rows']):,} rows")
    bits.extend(g.get("notes") or [])
    return " · ".join(bits) if bits else "no guardrail applied"
