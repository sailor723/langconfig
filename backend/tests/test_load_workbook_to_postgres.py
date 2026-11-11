"""`scripts/load_workbook_to_postgres.py` — the decisions that are wrong silently.

Loading needs a live Postgres, but the parts that quietly corrupt a round trip are pure:
identifier sanitising (a Chinese or duplicate header), type inference (money as BIGINT,
booleans as TEXT), and the cell coercion that has to match the inferred type. Those are
tested here; the load itself is evidenced by the row counts the script prints.
"""
import datetime as dt
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "load_workbook_to_postgres.py"


@pytest.fixture(scope="module")
def loader():
    if not SCRIPT.is_file():
        pytest.skip("loader script not present")
    spec = importlib.util.spec_from_file_location("load_workbook_to_postgres", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ── identifiers ─────────────────────────────────────────────────────────────

def test_sanitize_ident_makes_queryable_names(loader):
    assert loader.sanitize_ident("Order Lines") == "order_lines"
    assert loader.sanitize_ident("订单编号") == "c", "a non-ASCII header needs a stable fallback"
    assert loader.sanitize_ident("2026 sales") == "c_2026_sales", "a leading digit is not a legal identifier"


def test_unique_names_disambiguates_duplicate_headers(loader):
    assert loader.unique_names(["name", "Name", "name"]) == ["name", "name_2", "name_3"]
    assert loader.unique_names(["金额", ""]) == ["c1", "c2"]


# ── type inference ──────────────────────────────────────────────────────────

def test_integers_and_decimals(loader):
    assert loader.infer_type([1, 2, 3]) == "BIGINT"
    assert loader.infer_type([1, 2.5]) == "NUMERIC"
    assert loader.infer_type([1, 2, 3], name="amount") == "NUMERIC", \
        "money must not become BIGINT just because today's values are whole"


def test_booleans_do_not_become_text(loader):
    # Python bool is an int subclass; without an explicit check these were TEXT 'True'.
    assert loader.infer_type([True, False]) == "BOOLEAN"


def test_timestamps_from_cells_and_from_iso_strings(loader):
    assert loader.infer_type([dt.datetime(2026, 11, 5, 13, 21)]) == "TIMESTAMPTZ"
    assert loader.infer_type(["2026-11-05 13:21:07.519146+00:00",
                             "2026-11-04 09:00:00+00:00"]) == "TIMESTAMPTZ"


def test_json_columns_are_recognised(loader):
    assert loader.infer_type(['{"a": 1}', '{"b": [2]}']) == "JSONB"
    assert loader.infer_type(["[1, 2]", "[3]"]) == "JSONB"
    assert loader.infer_type(['{"a": 1}', "not json"]) == "TEXT"


def test_empty_and_mixed_columns_are_text(loader):
    assert loader.infer_type([None, ""]) == "TEXT"
    assert loader.infer_type([1, "x"]) == "TEXT"


# ── coercion matches the inferTypes ─────────────────────────────────────────

def test_coerce_follows_the_inferred_type(loader):
    assert loader.coerce("42", "BIGINT") == 42
    assert loader.coerce("99.5", "NUMERIC") == Decimal("99.5")
    assert loader.coerce("", "TEXT") is None, "blank cells are NULL, not empty strings"
    assert loader.coerce("true", "BOOLEAN") is True
    assert loader.coerce("false", "BOOLEAN") is False
    assert loader.coerce("garbage", "BOOLEAN") is None
    assert json.loads(loader.coerce('{"a":1}', "JSONB")) == {"a": 1}


def test_every_inferred_type_has_a_coercion(loader):
    """A type the inferrer can emit and the coercer cannot handle fails only at load time."""
    for pg_type in ("TEXT", "BIGINT", "NUMERIC", "TIMESTAMPTZ", "JSONB", "BOOLEAN", "DATE"):
        loader.coerce("2026-11-05", pg_type)  # must not raise
