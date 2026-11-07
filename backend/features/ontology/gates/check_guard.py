#!/usr/bin/env python3
"""K1–K8: SQL guardrails for a database that is not a toy.

The promises, and how each one is proved here:

* K1  no free-form SQL — only single SELECT/CTE statements run, and no route takes SQL
* K2  a missing LIMIT is capped, an existing one is never doubled
* K3  a listing over a big table gets a time bound (and says so)
* K4  a DECLARED METRIC is never windowed — the number must stay the number its definition
      promises (this is the check that catches the honest mistake)
* K5  the plan budget refuses a scan by name, before running it
* K6  statement_timeout is applied to every guarded statement
* K7  the injected window really narrows the rows (and is reversible)
* K8  the settings page and settings.json agree with guard.config()

    $P check_guard.py
"""
from __future__ import annotations

import pathlib
import sys

# The feature's roots: the COMPILER (this gate's imports), the WORKBENCH (the static assets it
# checks) and the PROFILES (the declarations). All relative to the feature directory — a gate that
# addresses "/Users/weiping/..." only runs on one machine.
import pathlib as _pathlib
import sys as _sys
sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))       # the _paths helper
from _paths import COMPILER as BASE, PROFILES, WORKBENCH, WORKBENCH as APP, profile_dir
_sys.path.insert(0, str(BASE))
sys.path.insert(0, str(WORKBENCH))
sys.path.insert(0, str(BASE))

import psycopg2  # noqa: E402

# The compiler reads the profile from $APP_SETTINGS and applies its ns + ontology_dir + OVERLAY.
# Retail's metrics live in the overlay, so a gate that checks retail without this loaded an
# ontology with no metrics at all.
import os as _os
_os.environ["APP_SETTINGS"] = str(profile_dir("retail") / "settings.json")
import actions  # noqa: E402
import guard    # noqa: E402
import serve_ui  # noqa: E402

ok = True


def check(label: str, got, want) -> None:
    global ok
    state = "PASS" if got == want else "FAIL"
    ok = ok and got == want
    print(f"  [{state}] {label}: got {got!r}, want {want!r}")


def main() -> int:
    cfg = guard.config()
    conn = psycopg2.connect(**actions.DSN)
    cur = conn.cursor()

    print("=== K1 only reads that the compiler produced ===")
    for bad in ("INSERT INTO orders VALUES (1, 1, 1, now())",
                "UPDATE orders SET amount = 0",
                "DROP TABLE orders"):
        try:
            guard.apply(bad, cfg)
            check(f"{bad.split()[0]} is refused", "accepted", "refused")
        except guard.Refusal:
            check(f"{bad.split()[0]} is refused", "refused", "refused")
    check("two statements at once are refused", _refused("SELECT 1; SELECT 2", cfg), True)
    # no HTTP route may accept SQL from the request: the compiler is the only source
    src = (APP / "serve_ui.py").read_text(encoding="utf-8")
    check("no route reads a 'sql' field from the request",
          'payload.get("sql")' in src or 'payload["sql"]' in src, False)

    print("=== K2 the page is capped, and never capped twice ===")
    g = guard.apply("SELECT id FROM customers ORDER BY id", cfg)
    check("a missing LIMIT is injected", f"LIMIT {cfg['max_rows']}" in g["sql"], True)
    g2 = guard.apply("SELECT id FROM customers ORDER BY id LIMIT 5", cfg)
    check("an existing LIMIT is left alone", g2["sql"].count("LIMIT"), 1)
    check("nothing is claimed when nothing changed", g2["notes"], [])

    print("=== K3 a listing over a big table is windowed ===")
    listing = guard.apply("SELECT id, amount FROM orders ORDER BY id", cfg, mode="rows")
    check("the big table gets a time bound",
          f"orders.placed_at >= now() - interval '{cfg['default_window_days']} days'"
          in listing["sql"], True)
    check("the narrowing is reported", any("placed_at" in n for n in listing["notes"]), True)
    filtered = guard.apply("SELECT id FROM orders WHERE placed_at >= '2026-01-01'", cfg,
                           mode="rows")
    check("a query that already has a window is not touched again",
          "now() - interval" in filtered["sql"], False)

    print("=== K4 a declared metric is never silently windowed ===")
    metric = guard.apply("SELECT sum(amount) AS order_revenue FROM orders;", cfg,
                         mode="declared")
    check("the metric SQL is not rewritten with a window",
          "now() - interval" in metric["sql"], False)
    check("but the scan is reported", any("unbounded scan" in n for n in metric["notes"]), True)
    val = guard.run(cur, "SELECT sum(amount) AS order_revenue FROM orders;", mode="declared")
    total = val["rows"][0][0]
    plain = psycopg2.connect(**actions.DSN)
    pcur = plain.cursor()
    pcur.execute("SELECT sum(amount) FROM orders")
    check("the guarded number equals the unguarded number", float(total),
          float(pcur.fetchone()[0]))
    plain.close()

    print("=== K5 the plan budget refuses by name, before running ===")
    tight = dict(cfg, max_plan_rows=0)
    try:
        guard.run(cur, "SELECT sum(amount) FROM orders", cfg=tight, mode="declared")
        check("an over-budget plan is refused", "ran", "refused")
    except guard.Refusal as exc:
        check("an over-budget plan is refused", "budget" in str(exc), True)
        check("and it names the estimate", "rows" in str(exc), True)
    # the same query is fine with the real budget
    guard.run(cur, "SELECT count(*) FROM orders", cfg=cfg, mode="declared")
    check("the real budget lets it through", True, True)

    print("=== K6 every guarded statement carries a timeout ===")
    cur.execute("SET statement_timeout = 0")      # start unset, not from an earlier check
    cur.execute("SHOW statement_timeout")
    before = cur.fetchone()[0]
    guard.run(cur, "SELECT count(*) FROM orders", cfg=cfg, mode="declared")
    cur.execute("SHOW statement_timeout")
    after = cur.fetchone()[0]
    # Postgres normalises 5000 -> '5s', so compare against "unset" rather than the raw number
    check("the guard sets statement_timeout", after not in ("0", "0ms", "1ms"), True)
    check("and the connection really changed", after != before, True)

    print("=== K7 the injected window really narrows the rows ===")
    wide = guard.run(cur, "SELECT count(*) FROM orders",
                     cfg=dict(cfg, default_window_days=36500), mode="rows")
    win = guard.run(cur, "SELECT count(*) FROM orders", cfg=cfg, mode="rows")
    check("the injected window returns fewer rows", win["rows"][0][0] < wide["rows"][0][0], True)
    check("and an explicit 0 days refuses instead of widening",
          _refused("SELECT count(*) FROM orders", dict(cfg, default_window_days=0)) or
          guard.apply("SELECT count(*) FROM orders", dict(cfg, default_window_days=0))["sql"],
          True)
    check("an existing window is left alone (idempotent)",
          guard.apply(win["sql"], cfg, mode="rows")["sql"], win["sql"])

    print("=== K9 the plan check obeys the config it was given (TPCH bug) ===")
    # found against the tpch database: plan_rows() read settings.json instead of the caller's
    # config, so a table declared big by the caller was never counted and the budget never bit.
    est_real = guard.plan_rows(cur, "SELECT count(*) FROM orders", cfg=cfg)
    est_none = guard.plan_rows(cur, "SELECT count(*) FROM orders", cfg=dict(cfg, big_tables={}))
    check("the caller's big_tables are counted", est_real > 0, True)
    check("a config with no big tables estimates 0", est_none, 0)

    print("=== K10 a window that matches nothing says so (TPCH bug) ===")
    # found against tpch, whose dates are 1990s: a now()-relative window returned an empty page
    # that looked like a fact. It must be reported, not silently returned.
    empty = guard.run(cur, "SELECT id FROM orders",
                      cfg=dict(cfg, default_window_days=1), mode="rows")
    check("an empty window is reported", empty["rows"], [])
    check("and the report says the window matched nothing",
          any("matched 0 rows" in n for n in empty["notes"]), True)
    check("and it explains the fix", any("default_window_days = 0" in n
                                         for n in empty["notes"]), True)

    print("=== K8 the settings and the guard agree ===")
    s = serve_ui.load_settings()
    check("settings.json carries the guard block", isinstance(s.get("guard"), dict), True)
    for key in ("max_rows", "default_window_days", "statement_timeout_ms", "max_plan_rows"):
        check(f"settings guard.{key} is what the guard reads", s["guard"].get(key),
              guard.config().get(key))
    check("the settings page renders the card", "SQL guardrails" in
          (APP / "settings.html").read_text(encoding="utf-8"), True)

    conn.rollback()
    conn.close()
    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


def _refused(sql: str, cfg: dict) -> bool:
    try:
        guard.apply(sql, cfg)
        return False
    except guard.Refusal:
        return True


if __name__ == "__main__":
    sys.exit(main())
