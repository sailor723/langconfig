"""The two type traps a spreadsheet build must not walk into.

`_infer_pg_type` is the only place that decides what a column becomes, and both of its documented
exceptions were false in practice:

* **money** — a column named 金额/amount whose values happen to be whole numbers must stay NUMERIC,
  not BIGINT. That one held.
* **booleans** — the docstring said "Excel hands them over as Python bools", so a column of the TEXT
  `TRUE` / `FALSE` (which is exactly what a CSV export or a hand-typed spreadsheet contains) was
  classified TEXT. The `db-excel-to-postgres` skill tells agents "布尔别建成文本", and there was no way
  to be right. Measured 2026-11-25 on a real xlsx: 已付款 came out `text`.
"""
from __future__ import annotations

from tools.native_impl import _infer_pg_type


def test_a_text_column_of_true_false_is_boolean():
    assert _infer_pg_type(["TRUE", "FALSE", "true", "False"], name="已付款") == "BOOLEAN"
    assert _infer_pg_type(["TRUE", None, ""], name="paid") == "BOOLEAN"


def test_real_bools_still_are_boolean():
    assert _infer_pg_type([True, False, None], name="paid") == "BOOLEAN"


def test_a_word_that_only_starts_like_a_bool_stays_text():
    for value in ("TRUEISH", "False alarm", "yes", "是"):
        assert _infer_pg_type([value, value], name="note") == "TEXT", value


def test_money_stays_numeric_even_when_whole():
    assert _infer_pg_type([100, 250, 75], name="金额") == "NUMERIC"
    assert _infer_pg_type([100, 250], name="order_count") == "BIGINT"


def test_dates_stay_dates():
    assert _infer_pg_type(["2026-01-05", "2026-02-11"], name="下单日期") == "DATE"


def test_the_verifier_treats_text_numbers_and_booleans_as_the_same_value():
    """The file side is always text; the database side is typed.

    Measured 2026-11-25 on agent 375's first real build: a 4-row orders CSV reported
    "0/4 rows match" while both sides' totals were already identical (金额 sum 426.74 vs 426.74),
    because `'100.50'` never equalled `Decimal('100.50')` and `'TRUE'` never equalled `True`.
    A verifier that cries wolf on a correct load is worse than no verifier: the next real
    difference gets dismissed as "that normalisation thing again".
    """
    from tools.native_impl import _canon

    assert _canon("100.50") == _canon(__import__("decimal").Decimal("100.50"))
    assert _canon("250") == _canon(250)
    assert _canon("TRUE") == _canon(True)
    assert _canon("false") == _canon(False)
    assert _canon("2026-01-05") == _canon(__import__("datetime").date(2026, 1, 5))
    # ...and text that is not a number stays text, so a real difference still shows
    assert _canon("alice") == "alice"
    assert _canon("100.50 元") == "100.50 元"


def test_natural_key_fk_needs_same_name_and_value_containment():
    """`db_review` used to find foreign keys only through the `*_id` naming convention.

    That misses the reference a spreadsheet actually carries: `orders.客户 → 客户档案.客户` has no `id`
    anywhere. Measured 2026-11-25 on a 3-sheet workbook: the report said "外键候选（无）" while the
    natural-key reference was right there — so the agent built tables that could not be joined.

    Two guards keep the inference honest: the child column must be the SAME NAME as the parent key
    (values that merely fit are the "值能对上 ≠ 是外键" trap — 客流量 3,1 ⊂ 订单号 1..4), and the child's
    distinct count cannot exceed the parent's.
    """
    from tools.native_impl import _natural_fk_ok

    # same type family, child values a subset of the parent's → a candidate
    assert _natural_fk_ok("txt", "txt", 4, 4, 0) is True
    assert _natural_fk_ok("txt", "txt", 4, 40, 0) is True
    # an orphan means it is not a reference
    assert _natural_fk_ok("txt", "txt", 4, 4, 2) is False
    # more distinct children than the parent can hold → impossible
    assert _natural_fk_ok("txt", "txt", 9, 4, 0) is False
    # different type families never compare (bigint vs text is a Postgres error, not a match)
    assert _natural_fk_ok("int", "txt", 2, 4, 0) is False


def test_fk_tiers_keep_the_weakest_evidence_labelled():
    """Three tiers of evidence, weakest last — and the weakest one is only reached by SET equality.

    `fact_order.customer -> dim_customer.customer_name` has different names AND identical value sets.
    That is a real cue (the user's point), but the same shape appears by accident: 客流量 {3,1} is a
    subset of 订单号 {1,2,3,4}. Set equality plus a measure-name block is what separates them.
    """
    from tools.native_impl import _fk_tier, _MEASURE_NAME

    # tier 2: same name, values contained, no orphans
    assert _fk_tier(True, True, 4, 4, 0, 4, False) == 2
    # tier 3: different name, identical sets both ways, enough distinct values
    assert _fk_tier(False, True, 4, 4, 0, 0, False) == 3
    # a subset that is not the whole set stays unreported
    assert _fk_tier(False, True, 2, 4, 0, 3, False) == 0
    # two distinct values are never enough for the name-agnostic tier
    assert _fk_tier(False, True, 2, 2, 0, 0, False) == 0
    # a measure-looking column is never a key (客流量 / 金额 / 率)
    assert _MEASURE_NAME.search("客流量") and _fk_tier(False, True, 4, 4, 0, 0, True) == 0
    # orphans in either direction disqualify
    assert _fk_tier(False, True, 4, 4, 1, 0, False) == 0
    assert _fk_tier(False, True, 4, 4, 0, 1, False) == 0
    # different type families never compare
    assert _fk_tier(False, False, 4, 4, 0, 0, False) == 0
