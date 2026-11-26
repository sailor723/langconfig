"""Gates for the two dashboard paths: an exploratory render must not impersonate the published board.

There are two ways to draw a board over a database:

* **the ontology pipeline** — `dashboard.json` + `check_dashboard` gates, metrics defined once (the
  published board, rendered by the app);
* **`db_dashboard`** — profile the schema now, render one HTML file, numbers derived on the spot
  (exploratory).

Keeping both is deliberate: exploring a strange database should not require building an ontology first.
What must not happen is the second one looking like the first — the same KPI would then carry two
numbers, both looking official. So: (1) the page says what it is, (2) it never takes the governed
board's filename, and (3) a measure that names a governed metric is refused rather than recomputed.
"""
from __future__ import annotations

import json

import pytest

from services import db_dashboard as D


def _profile_dir(tmp_path, key="store_monthly_v1", dbname="store_monthly_xlsx", metrics=("revenueTotal", "returnRate")):
    p = tmp_path / key
    p.mkdir()
    (p / f"{key}_settings.json").write_text(
        json.dumps({"dsn": {"dbname": dbname}}), encoding="utf-8")
    (p / "dashboard.json").write_text(json.dumps({
        "title": "门店月度经营看板",
        "kpis": [{"metric": m} for m in metrics],
        "panels": [{"metric": metrics[0] + "ByStore"}],
    }), encoding="utf-8")
    return tmp_path


def test_a_published_board_is_found_by_the_database_its_dsn_names(tmp_path):
    root = _profile_dir(tmp_path)
    boards = D.governed_boards("store_monthly_xlsx", profiles_dir=root)
    assert [b["profile"] for b in boards] == ["store_monthly_v1"]
    assert "revenueTotal" in boards[0]["metrics"]
    # a database nothing governs is the normal exploratory case, not an error
    assert D.governed_boards("chinook", profiles_dir=root) == []
    # and the match is on the DATABASE, not on a substring of it
    assert D.governed_boards("store_monthly", profiles_dir=root) == []


def test_a_measure_that_names_a_governed_metric_is_a_collision(tmp_path):
    root = _profile_dir(tmp_path)
    assert D.collides_with_governed("store_monthly_xlsx", "revenueTotal", profiles_dir=root) == [
        "store_monthly_v1:revenueTotal"]
    # case / punctuation do not launder the same name
    assert D.collides_with_governed("store_monthly_xlsx", "revenue_total", profiles_dir=root)
    # a different measure is fine
    assert D.collides_with_governed("store_monthly_xlsx", "客单价", profiles_dir=root) == []


def test_render_refuses_to_recompute_a_governed_metric(tmp_path, monkeypatch):
    root = _profile_dir(tmp_path)
    monkeypatch.setattr(D, "PROFILES_DIR", root)          # the one path both guards read
    monkeypatch.setattr(D, "profile", lambda db, **k: {"db": "store_monthly_xlsx", "chain": [], "time": None, "fact": "t", "tables": [], "bridge": None, "dims": {}})
    monkeypatch.setattr(D, "cube", lambda prof: {"measure": "revenueTotal", "rows": [], "columns": [],
                                                 "level_names": [], "sql": "select 1"})
    monkeypatch.setattr(D, "insights", lambda p, c: [])
    monkeypatch.setattr(D, "summary_text", lambda p, c, i: [])
    out = D.render("store_monthly_xlsx", tmp_path / "x_dashboard.html")
    assert out.startswith("REFUSED:"), out
    assert "store_monthly_v1:revenueTotal" in out
    assert not (tmp_path / "x_dashboard.html").exists(), "a refused render must not write a file"


def test_an_exploratory_render_of_a_governed_database_keeps_its_own_name(tmp_path, monkeypatch):
    root = _profile_dir(tmp_path)
    monkeypatch.setattr(D, "PROFILES_DIR", root)
    monkeypatch.setattr(D, "profile", lambda db, **k: {"db": "store_monthly_xlsx", "chain": [], "time": None, "fact": "t", "tables": [], "bridge": None, "dims": {}})
    monkeypatch.setattr(D, "cube", lambda prof: {"measure": "客单价", "rows": [], "columns": [],
                                                 "level_names": [], "sql": "select 1"})
    monkeypatch.setattr(D, "insights", lambda p, c: [])
    monkeypatch.setattr(D, "summary_text", lambda p, c, i: [])
    monkeypatch.setattr(D, "verify", lambda db, data: [])
    # the plan text describes a real profile; this test only cares about IDENTITY, not its wording
    monkeypatch.setattr(D, "_plan_text", lambda prof, cub: "(plan)")
    out = D.render("store_monthly_xlsx", tmp_path / "store_monthly_xlsx_dashboard.html")
    assert "store_monthly_xlsx_explore.html" in out, out
    assert out.startswith("[探索性看板 · 未治理]"), out
    assert "已有发布看板" in out and "store_monthly_v1" in out
    html = (tmp_path / "store_monthly_xlsx_explore.html").read_text(encoding="utf-8")
    assert "本页是" in html and "探索性" in html, "the page itself must say what it is"
