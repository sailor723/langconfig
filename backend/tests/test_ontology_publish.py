"""Gates for the ontology publish channel: stage → diff → apply → revert, and its refusals.

The channel is the only way an agent's ontology edit reaches the workbench, and every property
below is one that was wrong at least once while building it:

* the diff shows only what the publish CHANGES (a report listing 12 unchanged files is not a
  review);
* a publish that introduces a new refusal is refused, and its diff is still there to read —
  a refused candidate is exactly what someone wants to look at;
* apply refuses without `confirmed` (an agent may stage, never install);
* a failure AFTER install restores the installed ontology byte for byte;
* `reload_workbench` works from inside a running event loop — it used to call `asyncio.run`
  from the publish API handler, which raised and left the old numbers being served;
* discard removes the staging tree and records the decision;
* a publish that differs in no file is reported as such instead of being "applied".

The publish LEDGER is faked (an in-memory dict) so the gates are hermetic: no Postgres, no
network, no workbench. The file operations, the compile, and the gate run are the real ones —
they are what these assertions are about.

Run: cd backend && .venv/bin/python -m pytest tests/test_ontology_publish.py -v
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import shutil

import pytest

from services import ontology_publish as op

# A minimal ontology that really compiles and really gates: one object, one metric with a
# grain, and a profile the compiler can load. Copied from the logistics declarations' shape so
# the compile path is the production one, not a stub.
STRUCTURE = """@prefix : <https://example.test/pub#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

:Order a owl:Class ; rdfs:label "订单" ;
    :physicalTable "orders" ; :primaryKey "id" .
:quantity a owl:DatatypeProperty ; rdfs:label "数量" ;
    :domain :Order ; :physicalColumn "qty" .
"""

MEANING = """@prefix : <https://example.test/pub#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

# no definitions in this fixture: the one metric below is a plain aggregate on :Order
"""

OVERLAY_GOOD = """@prefix : <https://example.test/pub#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

:orderCount a owl:DatatypeProperty ; rdfs:label "订单数" ;
    :aggregate "count" ; :grain :Order ; :universe :Order .
"""

# The one declaration this file adds on purpose: a metric whose aggregate has no grain. The
# compiler must refuse it BY NAME, which is what makes the publish refused.
OVERLAY_BAD = OVERLAY_GOOD + """
:brokenCount a owl:DatatypeProperty ; rdfs:label "坏的" ;
    :aggregate "sum" ; :universe :Order ; :formula "qty" .
"""

PROFILE = {
    "title": "publish gate test",
    "ns": "https://example.test/pub#",
    "ontology_dir": "ontology",
    "overlay": "metrics_ext.ttl",
    "dsn": {"host": "127.0.0.1", "port": 5432, "dbname": "does_not_matter", "user": "nobody"},
    "guard": {"enabled": False},
    "features": {"actions": False, "lane_b": False, "tutorial": False},
    "samples": [],
}


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A throwaway ontology repo with one INSTALLED ontology, and an in-memory ledger."""
    root = tmp_path / "repo"
    live = root / "ontologies" / "pubtest"
    (live / "ontology").mkdir(parents=True)
    (live / "ontology" / "01-structure.ttl").write_text(STRUCTURE, encoding="utf-8")
    (live / "ontology" / "02-meaning.ttl").write_text(MEANING, encoding="utf-8")
    (live / "metrics_ext.ttl").write_text(OVERLAY_GOOD, encoding="utf-8")
    (live / "pubtest_settings.json").write_text(json.dumps(PROFILE, indent=1), encoding="utf-8")

    ledger: dict[str, dict] = {}

    def fake_audit_row(pid, key, actor, status, note="", files=None, report=None,
                       git_commit=None):
        row = ledger.get(pid) or {"id": pid, "key": key, "created_at": "2026-01-01T00:00:00"}
        row.update({"actor": actor, "status": status, "note": note,
                    "files": files or row.get("files") or {}, "report": report or {},
                    "git_commit": git_commit})
        ledger[pid] = row

    def fake_audit_list(staged_id=None, limit=50):
        rows = list(ledger.values())
        if staged_id:
            return [r for r in rows if r["id"] == staged_id]
        return rows[:limit]

    monkeypatch.setattr(op, "ONTOLOGIES", root / "ontologies")
    # REPO stays real: it is where the compiler lives (retail_graph/sqlgen.py), and pointing it
    # at the throwaway tree made the compile child import nothing and print nothing — which
    # surfaced as "IndexError: list index out of range" instead of "the compiler is missing".
    monkeypatch.setattr(op, "_audit_row", fake_audit_row)
    monkeypatch.setattr(op, "_audit_list", fake_audit_list)
    monkeypatch.setattr(op, "_git", lambda key, message: None)
    monkeypatch.setattr(op, "reload_workbench", lambda key: "")

    # The gate suite (retail_graph/check_ontology_generic.py) opens the profile's DATABASE, so
    # it is stubbed here: these gates are about the publish channel, not about a Postgres being
    # up. The compile stays REAL (it needs only rdflib), and the gate plumbing itself is gated
    # against the installed logistics ontology in the integration test at the bottom of file.
    stub = {"ok": True, "fails": [], "not_run": [], "text": "gates stubbed for the unit test"}
    monkeypatch.setattr(op, "_run_gates", lambda profile_path, truth=None: dict(stub))
    yield live
    shutil.rmtree(root, ignore_errors=True)


def _files(live: pathlib.Path) -> dict[str, str]:
    out = {}
    for p in sorted(live.rglob("*")):
        if p.is_file() and ".staging" not in p.parts and ".backup" not in p.parts:
            out[str(p.relative_to(live))] = p.read_text(encoding="utf-8")
    return out


def _snapshot(live: pathlib.Path) -> dict[str, bytes]:
    return {str(p.relative_to(live)): p.read_bytes()
            for p in sorted(live.rglob("*")) if p.is_file()
            and ".staging" not in p.parts and ".backup" not in p.parts}


def test_stage_reports_gates_and_leaves_the_installed_ontology_alone(repo):
    """Staging is validation: the installed bytes must not move."""
    before = _snapshot(repo)
    res = op.stage("pubtest", {"metrics_ext.ttl": OVERLAY_GOOD + "\n# a comment\n"},
                   actor="gate", note="no-op edit")
    assert res["ok"] is True, res
    assert _snapshot(repo) == before, "staging wrote into the installed ontology"
    report = res["report"]
    assert report["compile"]["compiled"] == 1
    assert report["new_refusals"] == []
    assert report["gates_ok"] is True
    op.discard(res["staged_id"], actor="gate")


def test_diff_shows_only_the_changed_file(repo):
    """A review needs the one file that changes, and the unchanged ones must not pretend to be
    changes."""
    staged = OVERLAY_GOOD.replace('rdfs:label "订单数"', 'rdfs:label "订单条数"')
    res = op.stage("pubtest", {"metrics_ext.ttl": staged}, actor="gate")
    assert res["ok"] is True, res
    d = op.diff(res["staged_id"])
    assert d["ok"] is True
    assert d["changed"] == ["metrics_ext.ttl"]
    changed = [f for f in d["files"] if f["path"] == "metrics_ext.ttl"][0]
    assert changed["status"] == "changed"
    assert '-:orderCount a owl:DatatypeProperty ; rdfs:label "订单数" ;' in changed["diff"]
    assert '+:orderCount a owl:DatatypeProperty ; rdfs:label "订单条数" ;' in changed["diff"]
    untouched = [f for f in d["files"] if f["path"] == "ontology/01-structure.ttl"][0]
    assert untouched["status"] == "unchanged" and untouched["diff"] == ""
    op.discard(res["staged_id"], actor="gate")


def test_a_new_refusal_refuses_the_publish_but_its_diff_still_exists(repo):
    """The refusal is the contract — and a refused candidate is exactly what a reviewer reads."""
    res = op.stage("pubtest", {"metrics_ext.ttl": OVERLAY_BAD}, actor="gate")
    assert res["ok"] is False
    assert res["report"]["new_refusals"] == ["brokenCount"]
    assert ":grain" in res["report"]["gates_text"] or any(
        ":grain" in str(r.get("why")) for r in res["report"]["compile"]["refused"])
    d = op.diff(res["staged_id"])
    assert d["ok"] is True and d["changed"] == ["metrics_ext.ttl"]
    assert d["status"] == "refused"
    applied = op.apply(res["staged_id"], actor="gate", confirmed=True)
    assert applied["ok"] is False and "refused" in applied["error"]
    op.discard(res["staged_id"], actor="gate")


def test_apply_requires_confirmation(repo):
    """An agent stages; a human installs. Without `confirmed` nothing lands."""
    before = _snapshot(repo)
    res = op.stage("pubtest", {"metrics_ext.ttl": OVERLAY_GOOD + "# x\n"}, actor="agent")
    assert res["ok"] is True, res
    out = op.apply(res["staged_id"], actor="agent", confirmed=False)
    assert out["ok"] is False and "confirmed" in out["error"]
    assert _snapshot(repo) == before
    op.discard(res["staged_id"], actor="gate")


def test_apply_installs_and_a_publish_with_no_change_says_so(repo):
    """Installing the same bytes is a no-op, and it must be reported as one."""
    res = op.stage("pubtest", {"metrics_ext.ttl": OVERLAY_GOOD}, actor="gate")
    assert res["ok"] is True, res
    d = op.diff(res["staged_id"])
    assert d["changed"] == [], d["changed"]
    out = op.apply(res["staged_id"], actor="gate", confirmed=True)
    assert out["ok"] is True
    assert out["report"]["compile"]["compiled"] == 1


def test_a_failure_after_install_restores_the_installed_ontology(repo):
    """The backup is the promise: a post-install gate failure reverts BYTE for byte.

    Fault injection, because a real post-install failure needs a file that compiles in the
    staging tree and not in the installed one — the mechanism is what is under test here, and
    the assertion is about the bytes on disk afterwards.
    """
    before = _snapshot(repo)
    res = op.stage("pubtest", {"metrics_ext.ttl": OVERLAY_GOOD + "\n# changed\n"}, actor="gate")
    assert res["ok"] is True, res

    calls = {"n": 0}

    def flaky(profile_path, truth=None):
        calls["n"] += 1
        # stage() ran before this stub was installed: call 1 is apply's re-check, call 2 is
        # the run against the INSTALLED path — the one that must restore from the backup.
        if calls["n"] >= 2:
            return {"ok": False, "fails": ["injected: post-install gate"], "not_run": [], "text": ""}
        return {"ok": True, "fails": [], "not_run": [], "text": "ok"}

    op._run_gates = flaky
    try:
        out = op.apply(res["staged_id"], actor="gate", confirmed=True)
    finally:
        op._run_gates = lambda profile_path, truth=None: {
            "ok": True, "fails": [], "not_run": [], "text": "ok"}

    assert out["ok"] is False and "reverted" in out["error"]
    assert _snapshot(repo) == before, "the installed ontology was NOT restored byte for byte"


def test_discard_removes_the_staging_tree_and_records_it(repo):
    res = op.stage("pubtest", {"metrics_ext.ttl": OVERLAY_GOOD + "# y\n"}, actor="gate")
    staging = op._staging_dir("pubtest") / res["staged_id"]
    assert staging.is_dir()
    out = op.discard(res["staged_id"], actor="gate")
    assert out["ok"] is True and out["status"] == "discarded"
    assert not staging.exists()
    again = op.discard(res["staged_id"], actor="gate")
    assert again["ok"] is True  # idempotent: discarding a discarded publish is not an error


def test_reload_workbench_survives_a_running_event_loop(repo, monkeypatch):
    """The bug: `asyncio.run()` inside the publish API handler raised RuntimeError and the
    workbench kept serving the old code while the publish reported success."""
    from services import ontology_workbench as ow

    async def fake_started(row, wait_s=15):
        return {"up": True}

    monkeypatch.setattr(ow, "ensure_started", fake_started)
    monkeypatch.setattr(ow, "stop", lambda key: {"ok": True})
    monkeypatch.setattr(ow, "_profile_rows", lambda: [{"key": "pubtest", "url": "http://x"}])

    async def inside_loop():
        return op.reload_workbench("pubtest")

    note = asyncio.run(inside_loop())
    assert note == "", f"reload reported a failure from inside a loop: {note!r}"


def test_history_status_filter_and_diff_after_apply(repo):
    res = op.stage("pubtest", {"metrics_ext.ttl": OVERLAY_GOOD}, actor="gate")
    assert op.history("pubtest")[0]["status"] == "staged"
    out = op.apply(res["staged_id"], actor="gate", confirmed=True)
    assert out["ok"] is True
    assert op.history("pubtest")[0]["status"] == "applied"
    # the staging tree is gone after an apply, so the diff says so instead of pretending
    d = op.diff(res["staged_id"])
    assert d["ok"] is False and "staging dir" in d["error"]


# ── the gate plumbing itself, against a REAL ontology and its REAL database ──────
# Everything above stubs the gate suite. This one does not: it stages the installed logistics
# ontology through the channel and asserts the report carries the compiler's real numbers. It is
# skipped — loudly, by name — on a machine without the repo or its database.
@pytest.mark.skipif(
    not pathlib.Path("/Users/weiping/dev/Learn/ontology/ontologies/logistics").is_dir(),
    reason="NOT RUN: the ontology repo with the logistics ontology is not on this machine",
)
def test_real_gates_on_the_installed_logistics_ontology(monkeypatch, tmp_path):
    repo_root = pathlib.Path("/Users/weiping/dev/Learn/ontology/ontologies")
    ledger: dict[str, dict] = {}
    monkeypatch.setattr(op, "_audit_row", lambda pid, key, actor, status, **kw: ledger.update(
        {pid: {"id": pid, "key": key, "status": status, "actor": actor,
               "report": kw.get("report") or {}, "note": kw.get("note") or "",
               "created_at": "2026-01-01T00:00:00"}}))
    monkeypatch.setattr(op, "_audit_list",
                        lambda staged_id=None, limit=50: [ledger[staged_id]] if staged_id else [])
    monkeypatch.setattr(op, "_git", lambda key, message: None)

    live = repo_root / "logistics"
    files = {str(p.relative_to(live)): p.read_text(encoding="utf-8")
             for p in sorted(live.rglob("*"))
             if p.is_file() and ".staging" not in p.parts and ".backup" not in p.parts
             and p.suffix in (".ttl", ".json")}
    res = op.stage("logistics", files, actor="gate", note="real gate run")
    try:
        assert res["report"]["compile"]["metrics"] == 23
        assert res["report"]["compile"]["compiled"] == 20
        assert sorted(r["name"] for r in res["report"]["compile"]["refused"]) == [
            "atRiskDrivers", "driverRecentOnTimeRate", "plannedStopsVisited"]
        assert res["report"]["new_refusals"] == []
        # R2 has no truth map for this profile: it must be NAMED, not silently green
        assert any("R2" in n for n in res["report"]["gates_not_run"]), res["report"]["gates_not_run"]
        assert res["ok"] is True, res
    finally:
        op.discard(res["staged_id"], actor="gate")
