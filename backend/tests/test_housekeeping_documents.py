"""Tests for `scripts/housekeeping_documents.py` — classification, on a throw-away tree.

The script's whole job is to tell three things apart:

    healthy triple   file present, catalog entry present      → leave alone
    ORPHAN           file present, nothing references it       → nothing can open it
    DANGLING ref     catalog entry present, file gone          → the UI offers what it cannot open

Getting that classification wrong is what makes a cleanup dangerous, so the logic is tested against a
temp tree instead of the real store: no database, no 600 MB of PDFs, milliseconds.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "housekeeping_documents.py"


@pytest.fixture(scope="module")
def hk():
    spec = importlib.util.spec_from_file_location("housekeeping_documents", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # dataclasses resolve through sys.modules[cls.__module__], so the module must be registered
    # before it is executed — otherwise @dataclass raises AttributeError inside exec_module.
    sys.modules["housekeeping_documents"] = module
    spec.loader.exec_module(module)
    return module


def _catalog(root: pathlib.Path, project: str, entries: dict[str, str]) -> None:
    """Write a per-project catalog the way the app does: absolute `storage_path` per document id."""
    catalog = root / "data" / "documents" / ".kvmeta"
    catalog.mkdir(parents=True, exist_ok=True)
    payload = {
        doc_id: {"id": doc_id, "project_id": 1, "filename": pathlib.Path(rel).name,
                 "storage_path": str((root / rel).resolve())}
        for doc_id, rel in entries.items()
    }
    (catalog / f"{project}.json").write_text(json.dumps(payload), encoding="utf-8")


def _file(root: pathlib.Path, rel: str, size: int = 10) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)


def test_classifies_healthy_orphan_and_dangling(hk, tmp_path):
    _file(tmp_path, "data/documents/project_1/keep_aaa.pdf")
    _file(tmp_path, "data/documents/project_1/orphan_bbb.pdf")
    _catalog(tmp_path, "project_1", {
        "keep": "data/documents/project_1/keep_aaa.pdf",
        "gone": "data/documents/project_1/gone_ccc.pdf",       # referenced, file absent
    })

    verdict = hk.scan(tmp_path)

    assert [pathlib.Path(p).name for p in verdict.orphans] == ["orphan_bbb.pdf"]
    assert [pathlib.Path(p).name for p in verdict.dangling] == ["gone_ccc.pdf"]
    assert verdict.healthy == 1


def test_catalog_is_not_counted_as_a_document(hk, tmp_path):
    _file(tmp_path, "data/documents/project_1/keep.pdf")
    _catalog(tmp_path, "project_1", {"keep": "data/documents/project_1/keep.pdf"})
    verdict = hk.scan(tmp_path)
    assert not any(".kvmeta" in p for p in verdict.files), "the catalog itself must not be a document"
    assert verdict.orphans == []


def test_a_reference_to_a_missing_file_does_not_hide_a_real_one(hk, tmp_path):
    """Same basename, different folder: the twin keeps the file from being called an orphan."""
    _file(tmp_path, "data/documents/project_9/renamed_abc.pdf")
    _catalog(tmp_path, "project_9", {"x": "data/documents/project_8/renamed_abc.pdf"})
    verdict = hk.scan(tmp_path)
    assert verdict.orphans == [], "a reference by basename is still a reference"


def test_quarantine_moves_instead_of_deleting(hk, tmp_path):
    _file(tmp_path, "data/documents/project_1/orphan.pdf", size=123)
    verdict = hk.scan(tmp_path)
    assert len(verdict.orphans) == 1

    res = hk.quarantine_orphans(tmp_path, verdict.orphans, "20260101-000000")

    assert res["moved"], res
    assert not (tmp_path / "data/documents/project_1/orphan.pdf").exists(), "file should have moved"
    parked = pathlib.Path(res["dest"]) / "project_1" / "orphan.pdf"
    assert parked.is_file() and parked.stat().st_size == 123, "content survives the move"
    assert (pathlib.Path(res["dest"]) / "MANIFEST.txt").is_file(), "a manifest says what moved"
    # and after the move there is nothing left to quarantine
    assert hk.scan(tmp_path).orphans == []


def test_prune_refs_removes_only_the_missing_ones(hk, tmp_path):
    _file(tmp_path, "data/documents/project_1/keep.pdf")
    _catalog(tmp_path, "project_1", {
        "keep": "data/documents/project_1/keep.pdf",
        "gone": "data/documents/project_1/gone.pdf",
    })
    verdict = hk.scan(tmp_path)

    res = hk.prune_dangling_refs(tmp_path, verdict.dangling, "20260101-000000")

    assert res["changed"] == 1, res
    catalog = json.loads((tmp_path / "data/documents/.kvmeta/project_1.json").read_text())
    assert list(catalog) == ["keep"], "the live entry stays, the dangling one goes"
    backup = pathlib.Path(res["backup"]) / "project_1.json"
    assert backup.is_file(), "the catalog is backed up before it is rewritten"
    assert len(json.loads(backup.read_text())) == 2, "the backup still has both entries"
    assert hk.scan(tmp_path).dangling == []


def test_report_mode_changes_nothing(hk, tmp_path, capsys):
    _file(tmp_path, "data/documents/project_1/orphan.pdf")
    assert hk.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "UNREFERENCED files" in out and "nothing changed" in out
    assert (tmp_path / "data/documents/project_1/orphan.pdf").is_file()
