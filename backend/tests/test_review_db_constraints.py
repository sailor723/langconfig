"""`scripts/review_db_constraints.py` — where a wrong key decision would be invisible.

Every decision this script makes is a guess from data, so the guesses are tested rather
than trusted: which unique column gets to be the primary key, which column names name a
table, and what counts as the same type across tables.
"""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "review_db_constraints.py"


@pytest.fixture(scope="module")
def review():
    if not SCRIPT.is_file():
        pytest.skip("review script not present")
    spec = importlib.util.spec_from_file_location("review_db_constraints", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _stats(*rows):
    """(column, type, nulls, distinct, total) tuples -> the stats shape the script builds."""
    return [{"column": c, "type": t, "nulls": n, "distinct": d, "total": tot}
            for c, t, n, d, tot in rows]


# ── primary key choice ──────────────────────────────────────────────────────

def test_id_wins_over_other_unique_columns(review):
    """Under 4 rows `amount` and `placed_at` are unique too — that is an accident."""
    stats = _stats(("id", "bigint", 0, 4, 4),
                   ("customer_id", "bigint", 0, 4, 4),
                   ("amount", "numeric", 0, 4, 4),
                   ("placed_at", "timestamp with time zone", 0, 4, 4))
    assert review.pk_candidates(stats, "orders")[0] == "id"


def test_a_table_named_key_beats_an_incidental_one(review):
    stats = _stats(("name", "text", 0, 4, 4),
                   ("customer_id", "bigint", 0, 4, 4))
    assert review.pk_candidates(stats, "customers")[0] == "customer_id"


def test_columns_with_nulls_or_duplicates_are_not_keys(review):
    stats = _stats(("id", "bigint", 1, 3, 4), ("code", "text", 0, 2, 4))
    assert review.pk_candidates(stats, "t") == []


# ── foreign key direction ───────────────────────────────────────────────────

def test_reference_names_resolve_to_the_plural_table(review):
    tables = ["customers", "orders", "products", "stores", "order_lines"]
    assert review.natural_targets("customer_id", tables) == ["customers"]
    assert review.natural_targets("order_id", tables) == ["orders"]
    assert review.natural_targets("product_id", tables) == ["products"]


def test_plain_id_is_never_a_foreign_key(review):
    """`customers.id` holds values that also exist in `order_lines.id`; it is still not a reference."""
    assert review.looks_like_fk("id") is False
    assert review.natural_targets("id", ["customers", "order_lines"]) == []


def test_a_timestamp_shaped_column_is_not_treated_as_a_reference(review):
    """`sold_at` holds store ids — a naming bug, reported as one, not silently constrained."""
    assert review.looks_like_fk("sold_at") is False
    assert review.MISLEADING_NAME.search("sold_at")


# ── type compatibility ─────────────────────────────────────────────────────

def test_integer_widths_are_compatible_but_int_and_text_are_not(review):
    assert review.compatible("bigint", "integer")
    assert not review.compatible("bigint", "text")
    assert not review.compatible("timestamp with time zone", "bigint")


def test_integer_and_decimal_are_not_treated_as_the_same_key_type(review):
    """A foreign key from `numeric` to `bigint` is worth a human look, not an auto-create.

    The two families are kept apart on purpose: numeric can hold 1.5, so a column that
    is only *currently* whole should not silently become a reference to an integer key.
    """
    assert review.compatible("numeric", "numeric")
    assert not review.compatible("numeric", "bigint")
