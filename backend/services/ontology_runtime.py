"""The ontology runtime: ONE process, one lock, every ontology.

Why this module exists. The compiler was written as a command-line tool: it read `$APP_SETTINGS`
once at import and bound that profile into module state (`sqlgen.NS` / `CUBE` / `OVERLAY`,
`guard.SETTINGS`, `actions.SETTINGS` / `SCHEMA` / `DSN`, `i18n.SETTINGS`). The app therefore served
every ontology through a CHILD PROCESS — a virtualenv, an interpreter start and a re-import per
request — because two profiles in one interpreter would have fought over those names, and the loser
would answer with the other ontology's tables.

M1 moved the compiler into the app (and its dependencies into the app's venv). This module finishes
the job: `ontology_profile.use()` points the compiler at the profile being served, and `_LOCK`
serialises `use() + compile()` so two concurrent requests cannot interleave. Compiling is
milliseconds; the database round-trip happens under the same lock because the guard's limits and
the connection's DSN are profile state too — measured at 43–280 ms per question, i.e. cheaper than
starting a process was (≈390 ms).

What does NOT happen here: the gates. They still run as their own process, on purpose — a gate must
see the files on disk exactly as a user would, and a crashing gate must not take the app with it.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import threading

logger = logging.getLogger(__name__)

#: The compiler's state is process-wide, so every entry point takes this lock.
_LOCK = threading.RLock()

FEATURE = pathlib.Path(__file__).resolve().parents[1] / "features" / "ontology"
COMPILER = FEATURE / "compiler"
GATES = FEATURE / "gates"
PROFILES = FEATURE / "profiles"
#: The learning mirror, consulted ONLY when a checkout sets `ONTOLOGY_REPO` explicitly. A deployment
#: never sets it: the declarations live in `profiles/`, inside this app.
MIRROR = pathlib.Path(os.environ["ONTOLOGY_REPO"]) if os.environ.get("ONTOLOGY_REPO") else None


class OntologyError(Exception):
    """The ontology cannot be resolved or the compiler refused the request."""


def profile_for(key: str) -> pathlib.Path | None:
    """Where one ontology's DECLARATIONS live: in this app's feature.

    The learning mirror is a fallback only when `ONTOLOGY_REPO` is set — so a checkout that still keeps
    the mirror can read it, and a deployment that has never heard of it resolves everything locally.
    """
    candidates = [
        PROFILES / key / f"{key}_settings.json",
        PROFILES / key / "settings.json",
    ]
    if MIRROR is not None:
        candidates += [
            MIRROR / "ontologies" / key / f"{key}_settings.json",
            MIRROR / "ontologies" / key / "settings.json",
            MIRROR / "retail_graph" / f"{key}_settings.json",
        ]
        if key == "retail":
            candidates.append(MIRROR / "retail_graph" / "settings.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _require(key: str) -> pathlib.Path:
    profile = profile_for(key)
    if profile is None:
        raise OntologyError(f"no ontology {key!r} — nothing to compile")
    return profile


def _compiler():
    """Import the compiler modules, in one place, with the feature on sys.path."""
    import sys

    for path in (str(COMPILER), str(FEATURE)):
        if path not in sys.path:
            sys.path.insert(0, path)
    import ontology_profile  # noqa: PLC0415

    return ontology_profile


def dashboards() -> list[dict]:
    """Which ontologies DECLARE a dashboard (a board is a declaration, not a default)."""
    out = []
    for folder in sorted(PROFILES.glob("*")):
        if folder.is_dir() and (folder / "dashboard.json").is_file():
            out.append({"key": folder.name, "path": str(folder / "dashboard.json")})
    return out


# ── the dashboard ───────────────────────────────────────────────────────────
def panels(key: str, *, filters: dict | None = None) -> dict:
    """Run `<profile dir>/dashboard.json` in this process and return the payload."""
    profile = _require(key)
    path = profile.parent / "dashboard.json"
    if not path.is_file():
        raise OntologyError(
            f"{key} has no dashboard declaration ({path}); the dashboard is a declaration, not a "
            f"default — write one, or this ontology simply has no dashboard yet")
    with _LOCK:
        _compiler().use(profile)
        import run_dashboard  # noqa: PLC0415

        payload = run_dashboard.build(profile, dim_filters=filters or None)
    if payload.get("error") and not payload.get("panels"):
        raise OntologyError(str(payload["error"]))
    return payload


# ── a business question ─────────────────────────────────────────────────────
def ask(key: str, question: str, *, polish: bool = False) -> dict:
    """One question through the ontology's own pipeline (rules first, model only when unsure)."""
    text = (question or "").strip()
    if not text:
        raise OntologyError("ask a question; an empty one has no answer")
    profile = _require(key)
    # the deterministic template answers unless a caller asks for polished prose: an answer here is
    # the number and the SQL behind it, not a paragraph about them
    os.environ.setdefault("NL_ANSWER_LLM", "1" if polish else "0")
    with _LOCK:
        prof = _compiler()
        prof.use(profile)
        import nl  # noqa: PLC0415

        graph = prof.graph()
        try:
            out = nl.ask(text, graph=graph, record=False, slots=False)
        except getattr(nl, "NlRefusal", Exception) as exc:      # a refusal is an answer
            return {"ok": False, "key": key, "question": text,
                    "refused": str(exc), "answer": getattr(exc, "polished", None) or str(exc)}
    result = out.get("result") or {}
    return {
        "ok": True, "key": key, "question": text,
        "answer": out.get("answer"),
        "kind": result.get("kind"),
        "metric": result.get("name"),
        "value": result.get("value"),
        "rows": result.get("rows"),
        "sql": result.get("sql"),
        "guard": result.get("guard"),
        "notes": result.get("notes"),
        "source": out.get("answer_source"),
        "needs_confirmation": out.get("needs_confirmation"),
        "intent": out.get("intent"),
        "steps": [{"step": s.get("step"), "ms": s.get("ms"), "detail": s.get("detail")}
                  for s in (out.get("steps") or [])],
    }


# ── the declared write verbs ────────────────────────────────────────────────
def _actions():
    with _LOCK:
        prof = _compiler()
        import actions  # noqa: PLC0415

        return prof, actions


def declared_actions(key: str) -> dict:
    """Every verb this ontology declares, with its compiled preconditions."""
    profile = _require(key)
    try:
        prof, actions = _actions()
        with _LOCK:
            prof.use(profile)
            if actions.actions_path() is None or not pathlib.Path(actions.actions_path()).is_file():
                return {"ok": True, "key": key, "actions": [],
                        "note": "this ontology declares no write verbs (no actions file)"}
            compiled = actions.compile_actions(actions.load_graph(), actions.load_config())
            return {"ok": True, "key": key, "actions": actions.list_actions(compiled)}
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "key": key, "actions": [], "error": f"{type(exc).__name__}: {exc}"}


def invoke(key: str, action: str, params: dict, *, dry_run: bool = False,
           actor: str | None = None) -> dict:
    """`check` (read-only) or `run` (one transaction + an audit row). A refusal is a result."""
    profile = _require(key)
    prof, actions = _actions()
    with _LOCK:
        prof.use(profile)
        try:
            compiled = actions.compile_actions(actions.load_graph(), actions.load_config())
            if dry_run:
                payload = actions.check_action(action, params, compiled=compiled)
            else:
                payload = actions.run_action(action, params, actor or "app", compiled=compiled)
            # a dry run that would not be admitted IS the refusal a caller is asking about
            ok = payload.get("admitted") if dry_run else payload.get("ok")
            return {"ok": bool(ok), "exit_code": 0 if ok else 2, "key": key, "action": action,
                    "verb": "check" if dry_run else "run", "result": payload}
        except Exception as exc:                                # noqa: BLE001 — a refusal, by name
            return {"ok": False, "exit_code": 2, "key": key, "action": action,
                    "verb": "check" if dry_run else "run",
                    "result": {"ok": False, "refused": str(exc)}}


def audit(key: str, limit: int = 50) -> dict:
    """The append-only trail of the writes this ontology's verbs have made."""
    profile = _require(key)
    prof, actions = _actions()
    try:
        with _LOCK:
            prof.use(profile)
            return {"ok": True, "key": key, "events": actions.recent_audit(limit=limit)}
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "key": key, "events": [], "error": f"{type(exc).__name__}: {exc}"}


def profile_info(key: str) -> dict:
    """What the runtime is pointed at — for a health check that does not guess."""
    profile = _require(key)
    settings = json.loads(profile.read_text(encoding="utf-8"))
    return {"key": key, "profile": str(profile), "ns": settings.get("ns"),
            "dsn": {k: v for k, v in (settings.get("dsn") or {}).items() if k != "password"},
            "features": settings.get("features") or {},
            "dashboard": str(profile.parent / "dashboard.json")
            if (profile.parent / "dashboard.json").is_file() else None}
