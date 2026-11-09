"""Tests for `scripts/ontology_restore.py` — the ledger→profile rebuild, on a temp tree.

Why this exists: `new_coldchain_v5` was published, never committed (the publish's own git commit had
failed), and a `git reset --hard` deleted it. It was rebuilt from `ontology_publishes.files`. That
recovery path needs to be a tool, and a tool that writes files needs tests for the paths it must
refuse — a publish entry is not trusted input.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ontology_restore.py"


@pytest.fixture(scope="module")
def restore():
    spec = importlib.util.spec_from_file_location("ontology_restore", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["ontology_restore"] = module
    spec.loader.exec_module(module)
    return module


LEDGER = {
    "new_coldchain_v5_settings.json": '{"title": "cold chain"}',
    "ontology/01-structure.ttl": "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
    "ontology/02-meaning.ttl": "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
    "dashboard.json": "{}",
    "samples.json": "[]",
    "truth.json": "{}",
    "tutorial.json": "{}",
    "ontology.html": "<html></html>",
    "ontology/metrics_ext.ttl": "# metrics",
}


def test_plan_accepts_the_profile_files(restore, tmp_path):
    write, refused = restore.plan(LEDGER, tmp_path / "v5")
    assert refused == []
    assert "new_coldchain_v5_settings.json" in write
    assert "ontology/01-structure.ttl" in write


def test_plan_refuses_paths_that_escape_the_profile(restore, tmp_path):
    write, refused = restore.plan({"../outside.ttl": "x", "/etc/passwd": "x"}, tmp_path / "v5")
    assert write == []
    assert len(refused) == 2, refused


def test_plan_refuses_staging_material(restore, tmp_path):
    write, refused = restore.plan({".staging/123/dashboard.json": "{}"}, tmp_path / "v5")
    assert write == [] and len(refused) == 1


def test_plan_refuses_non_text(restore, tmp_path):
    write, refused = restore.plan({"dashboard.json": {"not": "text"}}, tmp_path / "v5")
    assert write == [] and "not text" in refused[0]


def test_write_creates_nested_files(restore, tmp_path):
    dest = tmp_path / "profiles" / "new_coldchain_v5"
    written, refused = restore.write_profile(LEDGER, dest)
    assert refused == [] and len(written) == len(LEDGER)
    assert (dest / "ontology" / "01-structure.ttl").read_text().startswith("@prefix owl:")
    assert (dest / "new_coldchain_v5_settings.json").is_file()


def test_write_refuses_a_directory_that_already_has_a_profile(restore, tmp_path):
    dest = tmp_path / "profiles" / "new_coldchain_v5"
    dest.mkdir(parents=True)
    (dest / "new_coldchain_v5_settings.json").write_text("{}", encoding="utf-8")

    written, refused = restore.write_profile(LEDGER, dest)

    assert written == []
    assert any("already has files" in why for why in refused)
    assert (dest / "new_coldchain_v5_settings.json").read_text() == "{}", "nothing overwritten"


def test_force_overwrites(restore, tmp_path):
    dest = tmp_path / "profiles" / "new_coldchain_v5"
    dest.mkdir(parents=True)
    (dest / "new_coldchain_v5_settings.json").write_text("stale", encoding="utf-8")

    written, _ = restore.write_profile(LEDGER, dest, force=True)

    assert written
    assert (dest / "new_coldchain_v5_settings.json").read_text() == LEDGER["new_coldchain_v5_settings.json"]
