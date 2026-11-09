"""The workspace search endpoint — `GET /api/workspace/search` (spec: search-panel-honesty).

Why these tests exist, in the order they matter:

1. **Bounded by construction.** The scan walks THIS account's workspace and takes no path from the
   caller, so path traversal is not a filter that can be forgotten — there is no path input at all.
   The test pins that: a query containing `../../.env` returns no match rather than reading outside.
2. **Refused before it costs anything.** An empty query is 400 and an absurd one is 413, both raised
   before the filesystem is touched. A scan that cannot succeed should not start.
3. **Caps are real.** A term that appears everywhere must not return everything: MAX_MATCHES and the
   per-file byte cap are consequences of "the sidebar must not freeze".
4. **Binary and build noise is skipped.** A match inside a `.png` or under `node_modules/` is not a
   search result.

The scan is tested directly (no app, no database): it is pure filesystem work, and the route only adds
validation around it.
"""
from __future__ import annotations

import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.workspace import files_routes as fr


def _tree(root: pathlib.Path) -> pathlib.Path:
    (root / "src").mkdir(parents=True)
    (root / "src" / "Panel.tsx").write_text(
        "export default function Panel() {\n  // the SearchPanel term lives here\n  return null;\n}\n",
        encoding="utf-8")
    (root / "notes.md").write_text("nothing to see\nSEARCHPANEL appears on line two\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "dep.js").write_text("searchpanel in a dependency\n", encoding="utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG searchpanel binary")
    return root


# ── the scan ────────────────────────────────────────────────────────────────

def test_finds_a_term_with_line_and_column(tmp_path):
    base = _tree(tmp_path)
    res = fr.search_text_files(base, "SearchPanel")

    files = sorted(m["file"] for m in res["matches"])
    assert files == ["notes.md", "src/Panel.tsx"]
    panel = next(m for m in res["matches"] if m["file"] == "src/Panel.tsx")
    # "  // the SearchPanel …": two spaces + "// the " is 9 characters, so the term starts at column 10
    assert panel["line"] == 2 and panel["column"] == 10
    assert panel["kind"] == "file"


def test_case_insensitive(tmp_path):
    base = _tree(tmp_path)
    assert fr.search_text_files(base, "searchpanel")["matches"], "lowercase must match too"
    assert fr.search_text_files(base, "SEARCHPANEL")["matches"]


def test_skips_dependencies_and_binaries(tmp_path):
    base = _tree(tmp_path)
    files = {m["file"] for m in fr.search_text_files(base, "searchpanel")["matches"]}
    assert files == {"notes.md", "src/Panel.tsx"}, "node_modules and .png must not appear"


def test_a_query_cannot_reach_outside_the_workspace(tmp_path):
    """The route takes no path, so traversal cannot be attempted — prove the scan agrees."""
    base = _tree(tmp_path / "ws")
    (tmp_path / ".env").write_text("SECRET=searchpanel\n", encoding="utf-8")

    res = fr.search_text_files(base, "../../.env")
    assert res["matches"] == []
    assert all(not m["snippet"].startswith("SECRET") for m in res["matches"])


def test_caps_matches_and_says_so(tmp_path):
    base = tmp_path
    (base / "many.md").write_text("hit\n" * 50, encoding="utf-8")
    res = fr.search_text_files(base, "hit", max_matches=10)
    assert len(res["matches"]) == 10
    assert res["truncated"] is True


def test_skips_files_over_the_byte_cap(tmp_path):
    base = tmp_path
    (base / "small.md").write_text("hit\n", encoding="utf-8")
    (base / "big.md").write_text("hit\n" + "x" * 2_000, encoding="utf-8")
    res = fr.search_text_files(base, "hit", max_file_bytes=1_000)
    assert [m["file"] for m in res["matches"]] == ["small.md"]


def test_empty_query_scans_nothing(tmp_path):
    res = fr.search_text_files(_tree(tmp_path), "   ")
    assert res == {"matches": [], "scanned": 0, "truncated": False}


# ── the HTTP edge: validation before any scan ──────────────────────────────

@pytest.fixture
def client(monkeypatch, tmp_path):
    """A tiny app with just this router; the workspace root points at a temp tree."""
    base = _tree(tmp_path / "ws")

    class _Mgr:
        def user_base(self):
            return base

    monkeypatch.setattr("services.workspace_manager.get_workspace_manager", lambda: _Mgr())

    app = FastAPI()
    app.include_router(fr.router, prefix="/api/workspace")

    from db.database import get_db

    def _db():
        class _Q:
            def order_by(self, *_a, **_k):
                return self

            def limit(self, *_a, **_k):
                return self

            def all(self):
                return []

        class _DB:
            def query(self, *_a, **_k):
                return _Q()

        yield _DB()

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def test_empty_query_is_400(client):
    res = client.get("/api/workspace/search", params={"q": "   "})
    assert res.status_code == 400
    assert "q is required" in res.json()["detail"]


def test_absurd_query_is_413(client):
    res = client.get("/api/workspace/search", params={"q": "x" * (fr.MAX_QUERY_CHARS + 1)})
    assert res.status_code == 413
    assert str(fr.MAX_QUERY_CHARS) in res.json()["detail"]


def test_a_real_query_returns_matches_and_scan_counts(client):
    res = client.get("/api/workspace/search", params={"q": "SearchPanel"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True and body["q"] == "SearchPanel"
    assert {m["file"] for m in body["matches"]} == {"notes.md", "src/Panel.tsx"}
    assert body["scanned"]["files"] == 2
    assert body["truncated"] is False
