"""Dashboard panels for one ontology: DECLARED in `dashboard.json`, compiled by the ontology.

The backend's whole job here is to hand the declaration to the compiler and carry the answer back.
It does not know a single metric name, does not build SQL, and does not compute a rate: every number
in a panel arrives already compiled by `retail_graph/sqlgen.py`, already bounded by `guard.py`, and
already labelled by the declaration (`rdfs:label`). That is what keeps "the dashboard shows X" and
"the ontology says X" the same claim.

A panel that cannot answer comes back as a panel that cannot answer — with the refusal naming the
declaration that is missing. That is a result, not an error: a dashboard which silently drops a
block is how a business mistake survives a year of review.

Run target: `retail_graph/run_dashboard.py` in the ontology repo (it also has the gate,
`check_dashboard.py`, which asserts the same payload). Shelling out, not importing, because the
compiler resolves its profile once per process — the lesson from the samples reset gate.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import time

from services import ontology_publish

logger = logging.getLogger(__name__)

PYTHON = ontology_publish.PYTHON
REPO = pathlib.Path(ontology_publish.REPO)

CACHE: dict[str, tuple[float, dict]] = {}
CACHE_SECONDS = 30.0


class DashboardError(Exception):
    """No dashboard declaration, or the runner could not be executed at all."""


def _profile_for(key: str) -> pathlib.Path | None:
    """A key is either an ontology folder under `ontologies/` or a built-in dataset."""
    candidates = [
        REPO / "ontologies" / key / f"{key}_settings.json",
        REPO / "ontologies" / key / "settings.json",
        REPO / "retail_graph" / f"{key}_settings.json",
    ]
    if key == "retail":
        candidates.append(REPO / "retail_graph" / "settings.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def dashboard_path(key: str) -> pathlib.Path | None:
    profile = _profile_for(key)
    if profile is None:
        return None
    path = profile.parent / "dashboard.json"
    return path if path.is_file() else None


def installed() -> list[dict]:
    """Which ontologies have a dashboard declaration — for a nav that does not invent entries."""
    out = []
    for folder in sorted((REPO / "ontologies").glob("*")):
        if folder.is_dir() and not folder.name.startswith(".") and (folder / "dashboard.json").is_file():
            out.append({"key": folder.name, "path": str(folder / "dashboard.json")})
    return out


def panels(key: str, *, refresh: bool = False, filter: str | None = None) -> dict:
    """Every panel of this ontology's dashboard, with its data or its refusal."""
    cache_key = f"{key}|{filter or ''}"          # a filtered view is a different answer
    cached = CACHE.get(cache_key)
    if cached and not refresh and time.time() - cached[0] < CACHE_SECONDS:
        return {**cached[1], "cached": True}

    profile = _profile_for(key)
    if profile is None:
        raise DashboardError(f"no ontology {key!r} — nothing to read a dashboard from")
    path = profile.parent / "dashboard.json"
    if not path.is_file():
        raise DashboardError(
            f"{key} has no dashboard declaration ({path}); the dashboard is a declaration, not a "
            f"default — write one, or this ontology simply has no dashboard yet")

    env = dict(os.environ)
    env["ONTOLOGY_REPO"] = str(REPO)
    env["APP_SETTINGS"] = str(profile)
    started = time.time()
    try:
        argv = [PYTHON, "run_dashboard.py", "--profile", str(profile)]
        if filter:
            argv += ["--filter", filter]
        proc = subprocess.run(
            argv,
            capture_output=True, text=True, timeout=180, cwd=str(REPO / "retail_graph"), env=env)
    except subprocess.TimeoutExpired as exc:
        raise DashboardError(f"the dashboard runner did not finish in {exc.seconds}s") from exc
    except Exception as exc:                                    # noqa: BLE001
        raise DashboardError(f"could not run the dashboard runner: {exc}") from exc

    lines = (proc.stdout or "").strip().splitlines()
    if not lines:
        tail = (proc.stderr or "").strip().splitlines()
        raise DashboardError("the dashboard runner printed nothing"
                            + (f" ({tail[-1]})" if tail else f" (exit {proc.returncode})"))
    try:
        payload = json.loads(lines[-1])
    except Exception as exc:                                    # noqa: BLE001
        raise DashboardError(f"the runner's answer was not JSON: {lines[-1][:300]}") from exc

    payload["key"] = key
    payload["elapsed_ms"] = round((time.time() - started) * 1000)
    # exit 1 = the DECLARATION is stale (a hole started answering, or a live panel refuses).
    # It is still a payload worth showing — with the staleness visible in it.
    payload["declaration_stale"] = proc.returncode == 1
    CACHE[cache_key] = (time.time(), payload)
    return {**payload, "cached": False}


# ── business questions, next to the numbers ──────────────────────────────────────
# The dashboard answers "what happened"; this answers "why / what about X" in the user's own words.
# It runs the ontology's OWN pipeline (`answer-ontology-question/scripts/ask.py`: rules first, a
# model only when unsure, refusal by name) with the deterministic template answering — no LLM prose,
# so an answer that arrives here is the number and the SQL behind it, not a paragraph about them.
ASK_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "skills" / "builtin" / \
    "answer-ontology-question" / "scripts" / "ask.py"


def ask(key: str, question: str, *, polish: bool = False) -> dict:
    """One business question through the ontology. A refusal comes back as `ok=false` + the words."""
    text = (question or "").strip()
    if not text:
        raise DashboardError("ask a question; an empty one has no answer")
    profile = _profile_for(key)
    if profile is None:
        raise DashboardError(f"no ontology {key!r}")
    if not ASK_SCRIPT.is_file():
        raise DashboardError(f"the question pipeline is missing ({ASK_SCRIPT})")

    env = dict(os.environ, ONTOLOGY_REPO=str(REPO), APP_SETTINGS=str(profile))
    argv = [PYTHON, str(ASK_SCRIPT), text, "--profile", str(profile), "--json"]
    if not polish:
        argv.append("--no-polish")
    started = time.time()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=180,
                              cwd=str(REPO / "retail_graph"), env=env)
    except subprocess.TimeoutExpired as exc:
        raise DashboardError(f"the question did not finish in {exc.seconds}s") from exc

    raw = (proc.stdout or "").strip()
    if not raw:
        tail = (proc.stderr or "").strip().splitlines()
        raise DashboardError("the pipeline printed nothing"
                            + (f" ({tail[-1]})" if tail else f" (exit {proc.returncode})"))
    try:
        payload = json.loads(raw[raw.index("{"):])
    except Exception as exc:                                     # noqa: BLE001
        raise DashboardError(f"the pipeline's answer was not JSON: {raw[:300]}") from exc

    ms = round((time.time() - started) * 1000)
    if not payload.get("ok"):
        return {"ok": False, "key": key, "question": text, "ms": ms,
                "refused": payload.get("refused") or payload.get("text") or "refused",
                "answer": payload.get("text") or payload.get("refused") or "refused"}
    result = payload.get("result") or {}
    return {
        "ok": True, "key": key, "question": text, "ms": ms,
        "answer": payload.get("answer"),
        "kind": result.get("kind"),
        "metric": result.get("name"),
        "value": result.get("value"),
        "rows": result.get("rows"),
        "sql": result.get("sql"),
        "guard": result.get("guard"),
        "notes": result.get("notes"),
        "source": payload.get("answer_source"),
        "needs_confirmation": payload.get("needs_confirmation"),
        "intent": payload.get("intent"),
        "steps": [{"step": s.get("step"), "ms": s.get("ms"), "detail": s.get("detail")}
                  for s in (payload.get("steps") or [])],
    }
