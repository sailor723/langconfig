"""Per-stage acceptance checks for the ontology pipeline (agent 393).

The manager dispatches one expert per rung and gets back a JSON receipt. A receipt is a CLAIM; this
module is how the claim gets checked. Every function here answers one question mechanically — files
exist, ids line up, gates hold — so "the expert says it is done" and "it is done" cannot drift apart.

Design rules:

* **Deterministic only.** No model, no judgement: file presence, parsed JSON, set inclusion, exact
  row counts, and the existing gate scripts' own verdicts.
* **A gate that did not run is named, never counted as green.** The house rule from
  `scripts/ontology_gates.py` applies here too: `notrun` is reported as `notrun`.
* **No writes.** These functions never create, fix or delete anything; verification that repairs is not
  verification.

Used by the `ontology_verify_stage` tool; the manager calls it after each expert and must not advance
on a FAIL.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

FEATURE = Path(__file__).resolve().parent
PROFILES = FEATURE / "profiles"
GATES = FEATURE / "gates"
BACKEND = FEATURE.parent

#: Render kinds the frontend can actually draw. A board that declares anything else renders empty
#: panels with no error — measured 2026-11-13 on `meeting_v1` (9 panels, all blank, gates green).
RENDER_KINDS = {"panel", "bar", "table", "series", "ranked", "matrix", "composition",
                "hole", "slope", "sankey", "bubble", "treemap", "parallel"}

STAGES = ("plan", "build", "structure", "metrics", "board", "publish")


class StageCheckError(ValueError):
    """Raised for a malformed request (unknown stage, missing key) — not for a failed check."""


# ── helpers ────────────────────────────────────────────────────────────────────

def _profile_dir(key: str) -> Path:
    return PROFILES / (key or "").strip()


def _settings_path(key: str) -> Path:
    return _profile_dir(key) / f"{key}_settings.json"


def _ontology_dir(key: str) -> Path:
    """Where this profile keeps its TTL declarations (`ontology_dir` in its settings).

    The register skeleton declares `"ontology_dir": "ontology"`, and `check_structure` honours it, so
    a profile built that way had a green structure gate and a stage verdict of "0 bytes" at the same
    time: the stage check looked at the profile root, the gate looked at `ontology/`. Measured on
    tpch_sales_v1. Falls back to the profile root when the settings cannot be read.
    """
    d = _profile_dir(key)
    try:
        import json as _json
        prof = _json.loads(_settings_path(key).read_text(encoding="utf-8"))
        rel = Path(prof.get("ontology_dir") or ".")
        return d if rel in (Path("."), Path("")) else d / rel
    except Exception:                                            # noqa: BLE001
        return d


def _load_json(path: Path) -> tuple[Any, str]:
    """(value, error). A malformed file is a FAIL with the parse error, not an exception."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except Exception as exc:                                     # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def _check(name: str, ok: bool, detail: str = "") -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def _not_applicable(name: str, detail: str = "") -> dict:
    """A check this stage genuinely does not apply to — named, and NOT counted as passed.

    The house rule is "an unrun gate is not a passed gate", so a not-applicable item must not be
    `ok: True`. Measured on tpch_sales_v2: the build stage reported FAIL "database exists — tpch"
    because the platform's own database listing (`db_admin`, :5433) cannot see a database that
    lives on the ontology's declared server (:5432); the build had happened, just not here.
    """
    return {"name": name, "ok": False, "detail": detail, "not_applicable": True}


def _run_gate(gate: str, settings: Path, extra: Iterable[str] = ()) -> dict:
    """Run one gate script against one profile and return its verdict.

    `notrun` is passed through as `notrun`: an unrun gate is never green.
    """
    script = GATES / f"{gate}.py"
    if not script.is_file():
        return _check(f"gate {gate}", False, f"no gate script at {script}")
    if not settings.is_file():
        return _check(f"gate {gate}", False, f"no profile settings at {settings}")
    def _run(args: list[str]):
        return subprocess.run([sys.executable, str(script), *args], capture_output=True,
                              text=True, timeout=240, cwd=str(BACKEND))

    base = ["--profile", str(settings), *extra]
    try:
        proc = _run([*base, "--json"])
        if "unrecognized arguments" in (proc.stderr or ""):
            # Not every gate speaks --json (check_samples does not); the verdict is the exit code.
            proc = _run(base)
    except subprocess.TimeoutExpired:
        return _check(f"gate {gate}", False, "timed out after 240s")
    tail = (proc.stdout or "").strip().splitlines()
    verdict = "pass" if proc.returncode == 0 else "fail"
    if not tail and not proc.stdout:
        verdict = "notrun"
    # NOT `(...)[0][:200]`: when `tail` is non-empty that expression takes the FIRST CHARACTER of
    # the gate's last line, so every stage printed "gate check_dashboard :: pass: 1" and the number
    # a reader actually wants (150 checks, 0 failed) was lost. Measured on tpch_sales_v1.
    last_out = tail[-1] if tail else ((proc.stderr or "").strip().splitlines() or [""])[-1]
    detail = str(last_out)[:200]
    return _check(f"gate {gate}", verdict == "pass",
                  f"{verdict}: {detail}" if detail else verdict)


def _declared_metrics(key: str) -> set[str]:
    """Metric ids declared in `metrics_ext.ttl` (subject of a `... Metric` type triple)."""
    ttl = _profile_dir(key) / "metrics_ext.ttl"
    if not ttl.is_file():
        return set()
    text = ttl.read_text(encoding="utf-8", errors="ignore")
    ids: set[str] = set()
    # This repo declares metrics as datatype properties: `:revenueTotal a owl:DatatypeProperty ;`.
    # `cube:Metric` / `ex:…Metric` shapes are kept too, because other ontologies (imported ones) use them.
    for pattern in (
        r"(?m)^:([A-Za-z_][\w]*)\s+a\s+owl:DatatypeProperty",
        r"(?m)^\s*(?:ex:|:)?([A-Za-z_][\w]*)\s+a\s+[^\n]*Metric",
        r"cube:metric\s+(?:ex:|:)?([A-Za-z_][\w]*)",
    ):
        for m in re.finditer(pattern, text):
            ids.add(m.group(1))
    return ids


def _board_metric_refs(key: str) -> list[str]:
    dash = _profile_dir(key) / "dashboard.json"
    if not dash.is_file():
        return []
    data, _err = _load_json(dash)
    if not isinstance(data, dict):
        return []
    refs = [k.get("metric") for k in (data.get("kpis") or []) if isinstance(k, dict)]
    refs += [p.get("metric") for p in (data.get("panels") or []) if isinstance(p, dict)]
    for ref in (data.get("panels") or []):
        if isinstance(ref, dict):
            for s in (ref.get("series") or []):
                if isinstance(s, dict) and s.get("metric"):
                    refs.append(s["metric"])
    return [r for r in refs if r]


def _versions() -> dict:
    data, _err = _load_json(PROFILES / "_versions.json")
    return data if isinstance(data, dict) else {}


# ── stage checks ───────────────────────────────────────────────────────────────

def check_plan(*, plan_path: str = "", db_name: str = "", sheets: Iterable[str] = ()) -> dict:
    """S2 acceptance: a plan exists, covers every sheet, and **nothing was built yet**."""
    checks: list[dict] = []
    if plan_path:
        p = Path(plan_path).expanduser()
        text = ""
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="ignore")
        checks.append(_check("plan file exists and is non-empty", bool(text.strip()),
                             f"{p} ({len(text)} chars)"))
        missing = [s for s in (sheets or []) if str(s) and str(s) not in text]
        if sheets:
            checks.append(_check("plan mentions every sheet", not missing,
                                 f"missing: {missing}" if missing else "all sheets named"))
    _db_note = ""
    if db_name:
        from services import db_admin
        try:
            names = {d["database"] for d in db_admin.list_databases(with_objects=False)["databases"]}
            checks.append(_check("the plan stage did NOT create the database",
                                 db_name not in names,
                                 f"{db_name} {'already exists' if db_name in names else 'absent (expected)'}"))
        except Exception as exc:                                 # noqa: BLE001
            _db_note = f"(could not list databases: {type(exc).__name__})"
            checks.append(_check("database listing", False, _db_note))
    return _result("plan", checks)


def check_build(*, db_name: str = "", expect: dict | None = None,
                ontology_key: str = "") -> dict:
    """S4 acceptance: the database exists and every expected table has exactly the promised rows.

    `ontology_key` makes the stage honest about WHICH server it is talking to: an ontology whose
    data was not built by this pipeline (it already lived on its own server) has no "build" to
    accept, and the stage says so by name instead of failing on a database it never created.
    """
    from services import db_admin

    checks: list[dict] = []
    try:
        info = db_admin.list_databases(with_objects=False)
        names = {d["database"] for d in info["databases"]}
    except Exception as exc:                                     # noqa: BLE001
        return _result("build", [_check("database listing", False, f"{type(exc).__name__}: {exc}")])
    if db_name not in names and ontology_key:
        # not on the platform's server — ask the profile where it IS
        where, reachable = _db_declared_elsewhere(ontology_key, db_name)
        if reachable:
            return _result("build", [_not_applicable(
                "database exists (on the profile's declared server, not the platform's)",
                f"{db_name} is reachable at {where}; this database was not created by the "
                f"pipeline, so there is no build to accept here — the per-table row counts in the "
                f"`tables` receipt are the evidence, and they are named, not assumed")])
    checks.append(_check("database exists", db_name in names, db_name))
    if db_name in names and expect:
        for table, want in (expect or {}).items():
            try:
                # 精确行数只在「描述单表」里；表清单给的是估算值（rows_estimate），不能拿来做判据
                out = db_admin.describe(db_name, table)
                got = out.get("rows")
            except Exception as exc:                             # noqa: BLE001
                checks.append(_check(f"{table}: {want} rows", False, f"{type(exc).__name__}: {exc}"))
                continue
            checks.append(_check(f"{table}: {want} rows", got == want, f"got {got!r}"))
    return _result("build", checks)


def check_structure(*, ontology_key: str = "") -> dict:
    """S1/S2 acceptance: both TTL declarations exist and the structure gate holds."""
    d = _ontology_dir(ontology_key)
    checks = []
    for name in ("01-structure.ttl", "02-meaning.ttl"):
        f = d / name
        size = f.stat().st_size if f.is_file() else 0
        checks.append(_check(f"{name} exists", f.is_file() and size > 0, f"{size} bytes"))
    checks.append(_run_gate("check_structure", _settings_path(ontology_key)))
    return _result("structure", checks)


def check_metrics(*, ontology_key: str = "") -> dict:
    """S3–S5 acceptance: every metric the board names is declared, samples parse, samples gate holds."""
    d = _profile_dir(ontology_key)
    checks = []
    ttl = d / "metrics_ext.ttl"
    checks.append(_check("metrics_ext.ttl exists", ttl.is_file() and ttl.stat().st_size > 0,
                         f"{ttl.stat().st_size if ttl.is_file() else 0} bytes"))
    declared = _declared_metrics(ontology_key)
    refs = _board_metric_refs(ontology_key)
    if refs:
        missing = sorted({r for r in refs if r not in declared}) if declared else sorted(set(refs))
        checks.append(_check("every KPI/panel metric is declared", not missing,
                             f"undeclared: {missing}" if missing else f"{len(set(refs))} refs all declared"))
    samples = d / "samples.json"
    if samples.is_file():
        _val, err = _load_json(samples)
        checks.append(_check("samples.json parses", not err, err or "ok"))
    else:
        checks.append(_check("samples.json exists", False, "missing"))
    checks.append(_run_gate("check_samples", _settings_path(ontology_key)))
    # The samples gate proves the numbers; it does not read the DECLARATIONS. Measured on
    # orders_demo_v1: TICKET-04 closed on `metrics_ext.ttl exists / samples parses /
    # check_samples` while eight metrics carried no `:businessDescription` naming their source
    # (C5b) — a metric with no source is not a declaration, so the generic gate is part of what
    # this stage claims to accept, not an extra.
    checks.append(_run_gate("check_ontology_generic", _settings_path(ontology_key)))
    return _result("metrics", checks)


def check_board(*, ontology_key: str = "") -> dict:
    """S6 acceptance: the board parses, every panel kind is drawable, and the dashboard gate holds."""
    d = _profile_dir(ontology_key)
    checks = []
    dash = d / "dashboard.json"
    checks.append(_check("dashboard.json exists", dash.is_file(), str(dash)))
    data, err = _load_json(dash) if dash.is_file() else (None, "missing")
    checks.append(_check("dashboard.json parses", not err, err or "ok"))
    if isinstance(data, dict):
        kpis = data.get("kpis") or []
        panels = data.get("panels") or []
        checks.append(_check("declares at least one KPI or panel", bool(kpis or panels),
                             f"kpis={len(kpis)} panels={len(panels)}"))
        kinds = {p.get("kind") for p in panels if isinstance(p, dict) and p.get("kind")}
        unknown = sorted(k for k in kinds if k not in RENDER_KINDS)
        checks.append(_check("every panel kind is drawable", not unknown,
                             f"unsupported: {unknown}" if unknown else f"{sorted(kinds) or 'none'}"))
    checks.append(_run_gate("check_dashboard", _settings_path(ontology_key)))
    # `check_dashboard` reads dashboard.json and nothing else — it never opens tutorial.json.
    # Measured while verifying TICKET-06: the board stage reported PASS on a ticket whose
    # deliverable was the tutorial, so the PASS carried no information about it. The T family
    # (T1 steps / T2 every step's metric is declared / T3 a refusal step exists / T4 the step
    # runs / T5 no empty step) lives in check_ontology_generic, so that gate belongs here too.
    checks.append(_run_gate("check_ontology_generic", _settings_path(ontology_key)))
    return _result("board", checks)


def check_publish(*, ontology_key: str = "") -> dict:
    """S7 acceptance: the profile is on disk and its version is registered (staged, not installed)."""
    d = _profile_dir(ontology_key)
    checks = [_check("profile directory exists", d.is_dir(), str(d))]
    versions = _versions()
    families = versions.get("families") or {}
    entry = families.get(ontology_key) or {}
    known = bool(entry)
    if not known:
        for fam, val in families.items():
            for item in (val or {}).get("versions") or []:
                key = item.get("key") if isinstance(item, dict) else item
                if key == ontology_key:
                    known = True
                    break
            if known:
                break
    detail = (f"latest={entry.get('latest')!r}" if entry
              else ("listed under its family's versions" if known else "not registered"))
    checks.append(_check("registered in _versions.json", known, detail))
    return _result("publish", checks)


def _result(stage: str, checks: list[dict]) -> dict:
    ok = bool(checks) and all(c["ok"] for c in checks)
    if checks and all(c.get("not_applicable") for c in checks):
        return {"stage": stage, "verdict": "not-applicable",
                "checks": checks, "detail": "this stage does not apply to this ontology"}
    return {"stage": stage, "verdict": "pass" if ok else "fail", "checks": checks,
            "failed": [c["name"] for c in checks if not c["ok"]]}


def run_stage(stage: str, *, ontology_key: str = "", db_name: str = "", plan_path: str = "",
              expect: dict | None = None, sheets: Iterable[str] = ()) -> dict:
    """Dispatch one stage check. Unknown stage → StageCheckError (a caller bug, not a failed check)."""
    stage = (stage or "").strip().lower()
    if stage not in STAGES:
        raise StageCheckError(f"unknown stage {stage!r}; expected one of {', '.join(STAGES)}")
    if stage == "plan":
        return check_plan(plan_path=plan_path, db_name=db_name, sheets=sheets)
    if stage == "build":
        return check_build(db_name=db_name, expect=expect)
    if stage == "structure":
        return check_structure(ontology_key=ontology_key)
    if stage == "metrics":
        return check_metrics(ontology_key=ontology_key)
    if stage == "board":
        return check_board(ontology_key=ontology_key)
    return check_publish(ontology_key=ontology_key)


def _db_declared_elsewhere(ontology_key: str, db_name: str) -> tuple[str, bool]:
    """(where, reachable) for a database the platform does not host.

    Resolves the profile's OWN dsn through the compiler's `dsn` module — the same code the
    workbench and the gates use — so "the database is on another server" is answered by the
    declaration, not by a second connection convention.
    """
    settings_file = _settings_path(ontology_key)
    try:
        import json as _json
        prof = _json.loads(settings_file.read_text(encoding="utf-8"))
        sys.path.insert(0, str(Path(__file__).resolve().parent / "compiler"))
        import dsn as _dsn                                          # noqa: PLC0415
        import psycopg2                                            # noqa: PLC0415
        params = _dsn.resolved({"dsn": dict(prof.get("dsn") or {}, dbname=db_name)})
        where = f"{params.get('host')}:{params.get('port')}/{db_name}"
        conn = psycopg2.connect(connect_timeout=5, **params)
        conn.close()
        return where, True
    except Exception:                                              # noqa: BLE001
        return "", False
