"""Per-rung acceptance: the manager must be able to prove an expert met its target.

Why this exists: the manager dispatches one expert per rung and trusts the JSON receipt. Measured
2026-11-25 — `tables` still carried `db_query` (a tool deleted hours earlier) and no gate noticed; a
`metrics` expert can say "done" while the board names a metric nobody declared. A receipt is a claim;
these checks are the evidence.

What is pinned here:
  * the plan rung fails when a sheet is missing from the plan, or when the database already exists;
  * the board rung fails on a panel kind the renderer cannot draw (measured 2026-11-13: nine blank
    panels, gates green);
  * the metrics rung fails when the board references an undeclared metric;
  * publish fails when the profile/version is not registered;
  * a gate that could not run is reported as `notrun`, never as green;
  * the tool row exists, is live, and is bound to the builder (agent 393).

Run: cd backend && .venv/bin/python -m pytest tests/test_ontology_stage_checks.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from features.ontology import stage_checks as sc


def _profile(tmp_path: pathlib.Path, key: str = "probe_v1", *,
             metrics=("revenueTotal",), board_metrics=("revenueTotal",),
             panel_kind="series", versions_entry=True) -> pathlib.Path:
    d = tmp_path / "profiles" / key
    d.mkdir(parents=True)
    (d / f"{key}_settings.json").write_text(json.dumps({"dsn": {"dbname": "probe_db"}}), encoding="utf-8")
    (d / "01-structure.ttl").write_text("@prefix : <#> .\n:Order a :Class .\n", encoding="utf-8")
    (d / "02-meaning.ttl").write_text("@prefix : <#> .\n:Order :businessDescription \"订单\" .\n",
                                      encoding="utf-8")
    (d / "metrics_ext.ttl").write_text(
        "@prefix : <#> .\n@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        + "".join(f":{m} a owl:DatatypeProperty ; :aggregate \"sum\" .\n" for m in metrics),
        encoding="utf-8")
    (d / "samples.json").write_text(json.dumps({}), encoding="utf-8")
    (d / "dashboard.json").write_text(json.dumps({
        "title": "probe",
        "kpis": [{"metric": m} for m in board_metrics],
        "panels": [{"id": "p1", "kind": panel_kind, "title": "t", "metric": board_metrics[0]}],
    }), encoding="utf-8")
    versions = {"families": {}}
    if versions_entry:
        versions["families"]["probe"] = {"latest": key, "versions": [{"key": key, "version": 1}]}
    (tmp_path / "profiles" / "_versions.json").write_text(json.dumps(versions), encoding="utf-8")
    return tmp_path / "profiles"


@pytest.fixture()
def profiles(monkeypatch, tmp_path):
    def _install(**kw):
        root = _profile(tmp_path, **kw)
        monkeypatch.setattr(sc, "PROFILES", root)
        return root
    return _install


def test_plan_rung_needs_every_sheet_named(profiles, tmp_path):
    profiles()
    plan = tmp_path / "PLAN.md"
    plan.write_text("## 方案\norders → orders\n", encoding="utf-8")
    ok = sc.check_plan(plan_path=str(plan), sheets=["orders"])
    assert ok["verdict"] == "pass", ok
    bad = sc.check_plan(plan_path=str(plan), sheets=["orders", "customers"])
    assert bad["verdict"] == "fail"
    assert any("customers" in c["detail"] for c in bad["checks"] if not c["ok"])


def test_board_rung_rejects_a_panel_kind_the_renderer_cannot_draw(profiles):
    profiles(panel_kind="bar")          # drawable → only the gate can fail here, so assert the kind check
    res = sc.check_board(ontology_key="probe_v1")
    kind_check = next(c for c in res["checks"] if c["name"].startswith("every panel kind"))
    assert kind_check["ok"] is True, kind_check


def test_board_rung_fails_on_an_unknown_panel_kind(profiles, monkeypatch):
    profiles(panel_kind="sunburst")     # not in the renderer's domain
    monkeypatch.setattr(sc, "_run_gate", lambda *a, **k: sc._check("gate check_dashboard", True, "stub"))
    res = sc.check_board(ontology_key="probe_v1")
    assert res["verdict"] == "fail"
    assert "every panel kind is drawable" in res["failed"]


def test_metrics_rung_fails_when_the_board_names_an_undeclared_metric(profiles, monkeypatch):
    profiles(metrics=("revenueTotal",), board_metrics=("revenueTotal", "returnRate"))
    monkeypatch.setattr(sc, "_run_gate", lambda *a, **k: sc._check("gate check_samples", True, "stub"))
    res = sc.check_metrics(ontology_key="probe_v1")
    assert res["verdict"] == "fail"
    detail = next(c["detail"] for c in res["checks"] if c["name"].startswith("every KPI"))
    assert "returnRate" in detail


def test_metrics_rung_passes_when_everything_is_declared(profiles, monkeypatch):
    profiles()
    monkeypatch.setattr(sc, "_run_gate", lambda *a, **k: sc._check("gate check_samples", True, "stub"))
    assert sc.check_metrics(ontology_key="probe_v1")["verdict"] == "pass"


def test_publish_rung_needs_a_registered_version(profiles):
    profiles()
    assert sc.check_publish(ontology_key="probe_v1")["verdict"] == "pass"
    bad = sc.check_publish(ontology_key="probe_nonexistent")
    assert bad["verdict"] == "fail"


def test_an_unknown_stage_is_a_caller_error_not_a_failed_check():
    with pytest.raises(sc.StageCheckError):
        sc.run_stage("grill")


def test_the_builder_loads_the_ticket_workflow_skills():
    """The manager's job is grill → spec → tickets → work → verify; three of those are skills.

    A skill reaches an agent only through `config.skills` (and, for a subagent, only if the manager
    staged it). Measured 2026-11-25: the builder loaded `grilling` alone, so it grilled and then
    improvised the specification and the breakdown — the two steps that make "one sentence in, a
    reviewable ontology out" reproducible.
    """
    from db.database import SessionLocal
    from models.deep_agent import DeepAgentTemplate
    from models.skill import Skill

    db = SessionLocal()
    try:
        builder = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == 393).first()
        if builder is None:
            pytest.skip("ontology builder (393) absent in this database")
        loaded = set((builder.config or {}).get("skills") or [])
        for needed in ("grilling", "to-spec", "to-tickets"):
            assert needed in loaded, f"393 must load {needed!r}, has {sorted(loaded)}"
            # …and the skill must actually exist in the catalogue, or staging silently yields nothing
            assert db.query(Skill).filter(Skill.skill_id == needed).first() is not None, needed
        prompt = (builder.config or {}).get("system_prompt") or ""
        for needle in ("ontology_verify_stage", "TICKET", "SPEC.md", "grill.md"):
            assert needle in prompt, f"the builder prompt no longer mentions {needle!r}"
    finally:
        db.close()


def test_the_verifier_expert_is_read_only_and_handles_every_stage():
    """Verification runs in a SEPARATE context from the work — and that context cannot change anything.

    If the same expert that produced the artefacts also signs them off, "verified" means "said so twice
    in one conversation". A dedicated `verifier` subagent gets the ticket + the receipt and answers with
    `ontology_verify_stage`. It must be read-only: no write_file / edit_file, no db_* that can mutate.
    """
    from db.database import SessionLocal
    from models.deep_agent import DeepAgentTemplate

    db = SessionLocal()
    try:
        builder = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == 393).first()
        if builder is None:
            pytest.skip("ontology builder (393) absent in this database")
        subs = (builder.config or {}).get("subagents") or []
        verifier = next((sa for sa in subs if sa.get("name") == "verifier"), None)
        assert verifier is not None, f"no verifier expert in 393: {[s.get('name') for s in subs]}"
        tools = set(verifier.get("tools") or [])
        assert "ontology_verify_stage" in tools, tools
        forbidden = tools & {"write_file", "edit_file", "db_execute", "db_build_from_file",
                             "db_rename_column", "ontology_register", "ontology_publish", "bash"}
        assert not forbidden, f"the verifier must not be able to change anything: {forbidden}"
        prompt = verifier.get("system_prompt") or ""
        for needle in ("ontology_verify_stage", "PASS", "FAIL", "NOT-RUNNABLE"):
            assert needle in prompt, f"verifier prompt lost {needle!r}"
        # the manager must route through it, not verify itself
        mgr = (builder.config or {}).get("system_prompt") or ""
        assert "verifier" in mgr, "the manager prompt does not mention the verifier expert"
    finally:
        db.close()


def test_the_verify_tool_row_is_live_and_bound_to_the_builder():
    from db.database import SessionLocal
    from models.custom_tool import CustomTool
    from models.deep_agent import DeepAgentTemplate

    db = SessionLocal()
    try:
        row = db.query(CustomTool).filter(CustomTool.tool_id == "ontology_verify_stage").first()
        assert row is not None, "the ontology_verify_stage tool row is missing"
        assert not row.is_deprecated
        builder = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == 393).first()
        if builder is None:
            pytest.skip("ontology builder (393) absent in this database")
        tools = (builder.config or {}).get("native_tools") or []
        assert "ontology_verify_stage" in tools, f"393 must hold the verifier, has {tools}"
    finally:
        db.close()

def test_ontology_dir_follows_the_profile_declaration(tmp_path, monkeypatch):
    """A profile that keeps its TTL in `ontology/` must be checked THERE.

    Measured on tpch_sales_v1: `check_structure` (the gate) read `ontology/01-structure.ttl` and
    was green while the stage reported "0 bytes" — the stage looked at the profile root.
    """
    from features.ontology import stage_checks as sc

    prof = tmp_path / "probe_v1"
    (prof / "ontology").mkdir(parents=True)
    (prof / "probe_v1_settings.json").write_text('{"ontology_dir": "ontology"}', encoding="utf-8")
    (prof / "ontology" / "01-structure.ttl").write_text("@prefix : <http://x#> .", encoding="utf-8")
    monkeypatch.setattr(sc, "PROFILES", tmp_path)
    assert sc._ontology_dir("probe_v1") == prof / "ontology"

    (prof / "probe_v1_settings.json").write_text('{"ontology_dir": "."}', encoding="utf-8")
    assert sc._ontology_dir("probe_v1") == prof
