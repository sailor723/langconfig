"""The dashboard template's own failure modes, as text guards.

Every one of these shipped and broke the page during development, and each is a single
declaration or attribute — cheap to assert, impossible to see in a 90 KB screenshot:

  * a missing `#filterbar` element → `Cannot set properties of null` and no panel drew;
  * `const state` declared after first use → `Cannot access 'state' before initialization`;
  * two declarations of the same rollup → `Identifier 'byL0' has already been declared`;
  * a d3 v6 click handler `(d) => …` on a v7 bundle → `d` was the event, the filter went
    undefined and wiped every panel;
  * the esbuild bundle exposes one namespace per module, so `D3LIB.select(...)` is an object,
    not a function (`sel is not a function` at load time).
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVICE = REPO / "backend" / "services" / "db_dashboard.py"


def _src() -> str:
    if not SERVICE.is_file():
        import pytest

        pytest.skip("dashboard service not present")
    return SERVICE.read_text(encoding="utf-8")


def test_the_filter_bar_element_exists():
    src = _src()
    assert 'id="filterbar"' in src, "renderFilterBar() writes into #filterbar — without it every draw aborts"


def test_the_filter_state_is_declared_once_and_before_use():
    src = _src()
    assert src.count("const state = {level: null, value: null};") == 1
    # view() is called by renderSummary(), so `state` has to exist first
    assert src.index("const state = {level: null, value: null}") < src.index("renderSummary()")


def test_click_handlers_use_the_d3_v7_signature():
    src = _src()
    assert ".on('click', (event, d) =>" in src
    assert ".on('click', (d) =>" not in src, "d3 v7 passes (event, datum); the old form filtered on the event"


def test_the_bundle_namespace_is_destructured():
    src = _src()
    assert "A.select.select" in src, "the IIFE exposes namespaces, so select has to come off A.select"
    assert "LI.select" not in src, "`D3LIB.select` is an object, not a function"


def test_every_panel_is_drawn_from_the_filtered_view():
    src = _src()
    for fn in ("drawSankey", "drawBubble", "drawTree", "drawBars", "drawLine"):
        assert f"function {fn}(" in src, f"{fn} is gone"
    assert src.count("view()") >= 5, "each panel must read view(), not rows, or a filter shows in one panel only"
    assert "function drawAll()" in src and "drawAll();" in src


def test_the_page_still_verifies_before_it_ships():
    src = _src()
    assert "def verify(" in src and "the numbers do not match the database" in src
