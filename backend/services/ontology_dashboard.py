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

from services import ontology_publish, ontology_runtime

logger = logging.getLogger(__name__)

PYTHON = ontology_publish.PYTHON

# The runner and the gate that asserts its payload live INSIDE the ontology feature
# (backend/features/ontology/): the feature owns the compiler, the declarations and the checks that
# hold them honest. The ontology repository is kept as a learning mirror, not a runtime dependency.
ONTOLOGY_FEATURE = pathlib.Path(__file__).resolve().parents[1] / "features" / "ontology"
RUNNER = ONTOLOGY_FEATURE / "compiler" / "run_dashboard.py"

CACHE: dict[str, tuple[float, dict]] = {}
CACHE_SECONDS = 30.0


class DashboardError(Exception):
    """No dashboard declaration, or the runner could not be executed at all."""


def ontology_profile(key: str) -> pathlib.Path | None:
    """Where one ontology's DECLARATIONS live.

    The declarations live IN the app (`backend/features/ontology/profiles/<key>/`). The learning mirror
    in `ONTOLOGY_REPO` is consulted only when that variable is set explicitly — a checkout that still has
    the mirror can point at it, and a deployment that has never heard of it needs nothing.
    """
    candidates = [
        ONTOLOGY_FEATURE / "profiles" / key / f"{key}_settings.json",
        ONTOLOGY_FEATURE / "profiles" / key / "settings.json",
    ]
    mirror_env = os.environ.get("ONTOLOGY_REPO")
    if mirror_env:
        mirror = pathlib.Path(mirror_env)
        candidates += [
            mirror / "ontologies" / key / f"{key}_settings.json",
            mirror / "ontologies" / key / "settings.json",
            mirror / "retail_graph" / f"{key}_settings.json",
        ]
        if key == "retail":
            candidates.append(mirror / "retail_graph" / "settings.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _profile_for(key: str) -> pathlib.Path | None:
    return ontology_profile(key)


def dashboard_path(key: str) -> pathlib.Path | None:
    profile = _profile_for(key)
    if profile is None:
        return None
    path = profile.parent / "dashboard.json"
    return path if path.is_file() else None


def installed() -> list[dict]:
    """Which ontologies have a dashboard declaration — for a nav that does not invent entries.

    Read from the FEATURE (`profiles/*/dashboard.json`), which is where the declarations live. It used to
    read the learning mirror's `ontologies/*`, so a deployment without that repository had no dashboards
    at all while the app was perfectly able to compile them.
    """
    out = []
    for folder in sorted((ONTOLOGY_FEATURE / "profiles").glob("*")):
        if folder.is_dir() and not folder.name.startswith(".") and (folder / "dashboard.json").is_file():
            out.append({"key": folder.name, "path": str(folder / "dashboard.json")})
    return out




def _connection_message(key: str, exc: Exception) -> str:
    """A DB failure, said in terms of the ontology's own DSN."""
    reason = str(exc).strip().splitlines()[0][:300] if str(exc).strip() else exc.__class__.__name__
    target = "?"
    try:
        profile = _profile_for(key)
        if profile is not None:
            import json as _json

            dsn = (_json.loads(profile.read_text(encoding="utf-8")).get("dsn") or {})
            host = dsn.get("host") or "?"
            port = dsn.get("port") or "?"
            dbname = dsn.get("dbname") or "?"
            target = f"{host}:{port}/{dbname}"
    except Exception:                                           # noqa: BLE001
        pass
    return (f"{key} 的数据库连不上（{target}）：{reason}。"
            f"这台机器上没有这个库、或口令变量没配时就是这样——看板本身没有坏，是数据不在。")


def _declared_pages(key: str) -> list[dict]:
    """`dashboard.json` → `pages`: [{label, file, note?}] or [] when the declaration has none.

    A page entry is a promise that `/api/files/<file>` renders; the frontend lists what is here and
    says nothing about pages this ontology does not declare.
    """
    path = dashboard_path(key)
    if path is None:
        return []
    try:
        declared = json.loads(path.read_text(encoding="utf-8")).get("pages") or []
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("dashboard.json for %s unreadable (%s) — no pages listed", key, exc)
        return []
    out = []
    for entry in declared:
        if not isinstance(entry, dict):
            continue
        file = str(entry.get("file") or "").strip()
        if not file:
            continue
        out.append({"label": str(entry.get("label") or file), "file": file,
                    "note": entry.get("note")})
    return out


def panels(key: str, *, refresh: bool = False, filter: str | None = None) -> dict:
    """Every panel of this ontology's dashboard, with its data or its refusal.

    Compiled IN THIS PROCESS by the ontology feature (see `ontology_runtime`): the same code path a
    gate runs, so a panel cannot say something the gate would disagree with.
    """
    cache_key = f"{key}|{filter or ''}"
    cached = CACHE.get(cache_key)
    if cached and not refresh and time.time() - cached[0] < CACHE_SECONDS:
        return {**cached[1], "cached": True}

    started = time.time()
    dim_filters = {}
    if filter:
        if ":" not in filter:
            raise DashboardError(f"filter {filter!r} must be dimension:value")
        prop, value = filter.split(":", 1)
        dim_filters[prop.strip()] = (None if value.strip().lower() in ("null", "none")
                                     else value.strip())
    try:
        payload = ontology_runtime.panels(key, filters=dim_filters or None)
    except ontology_runtime.OntologyError as exc:
        raise DashboardError(str(exc)) from exc
    except Exception as exc:                                    # noqa: BLE001
        # A database that is not on this host surfaces as psycopg2.OperationalError, which used to
        # fall through to the catch-all 500 ("see the server log") — useless to whoever clicked.
        # Name the target and the reason instead: the reader can then tell "the DB is elsewhere"
        # from "the declaration is wrong", which are two different jobs.
        raise DashboardError(_connection_message(key, exc)) from exc

    payload["key"] = key
    payload["elapsed_ms"] = round((time.time() - started) * 1000)
    # The SAME declaration may also have a rendered, fixed-layout cockpit (a home page plus one page
    # per dimension) that lives outside this generic renderer. It is declared, not discovered: a page
    # list invented by the UI would point at files nobody promised exist.
    payload["pages"] = _declared_pages(key)
    # a payload whose every hole still refuses is complete; one with a LIVE refusal is stale
    payload["declaration_stale"] = not payload.get("ok", True)
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
    started = time.time()
    try:
        out = ontology_runtime.ask(key, question, polish=polish)
    except ontology_runtime.OntologyError as exc:
        raise DashboardError(str(exc)) from exc
    return {**out, "ms": round((time.time() - started) * 1000)}


