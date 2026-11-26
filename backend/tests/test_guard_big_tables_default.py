"""The guard's defaults must not name another profile's schema.

`guard.DEFAULTS` used to carry `"big_tables": {"orders": "placed_at"}` — retail's schema
baked into the house default. On a *fresh* ontology that also happens to have a table called
`orders` (measured on orders_demo_v1, whose date column is 订单日期) the listing path then
injected `placed_at >= now() - interval '90 days'` and the query died with
`column orders.placed_at does not exist`.

The rule these tests hold:

* the DEFAULT big_tables is empty — one profile's table/column pair is not a house rule;
* a profile that declares `guard.big_tables` still gets exactly what it declared (retail
  keeps its window, so nothing was traded away by emptying the default).

Measured run: `cd backend && uv run pytest tests/test_guard_big_tables_default.py -q`.
"""
from __future__ import annotations

import json
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
COMPILER = BACKEND / "features" / "ontology" / "compiler"
sys.path.insert(0, str(COMPILER))

import guard  # noqa: E402  (the module under test, imported the way the gates import it)


def _use_profile(tmp_path, guard_block):
    """Point the guard at a throwaway profile that carries exactly `guard_block`."""
    profile = tmp_path / "probe_settings.json"
    profile.write_text(json.dumps({"guard": guard_block}, ensure_ascii=False), encoding="utf-8")
    guard.SETTINGS = profile
    return guard.config()


def test_default_big_tables_is_empty():
    assert guard.DEFAULTS["big_tables"] == {}, (
        "a default that names a table and its date column only means something to one "
        "profile's schema; declaring it globally breaks every other `orders` table"
    )


def test_profile_without_guard_block_gets_no_window_on_orders(tmp_path):
    cfg = _use_profile(tmp_path, {})
    assert cfg["big_tables"] == {}
    out = guard.apply("SELECT 订单号, 金额 FROM orders", cfg)
    assert "placed_at" not in out["sql"], (
        "the empty default must not inject another profile's column: " + out["sql"]
    )
    assert out["window"] is None


def test_profile_that_declares_big_tables_keeps_them(tmp_path):
    cfg = _use_profile(tmp_path, {"big_tables": {"orders": "placed_at"},
                                 "default_window_days": 90})
    assert cfg["big_tables"] == {"orders": "placed_at"}
    out = guard.apply("SELECT 订单号 FROM orders ORDER BY 订单号", cfg)
    assert "placed_at" in out["sql"], "a declared window must still be injected: " + out["sql"]
    assert out["window"] == {"table": "orders", "column": "placed_at", "days": 90}


def test_retail_still_declares_its_own_big_tables():
    """Retail relied on the default; it must now declare the same pair itself."""
    retail = BACKEND / "features" / "ontology" / "profiles" / "retail" / "settings.json"
    settings = json.loads(retail.read_text(encoding="utf-8"))
    assert (settings.get("guard") or {}).get("big_tables") == {"orders": "placed_at"}
