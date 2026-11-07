"""Point the compiler at ONE profile, in THIS process, right now.

Why this module exists. The compiler was built as a command-line tool: it read `$APP_SETTINGS` once
at import and bound the profile into module state (`sqlgen.NS` / `CUBE` / `OVERLAY`,
`guard.SETTINGS`, `actions.SETTINGS` / `SCHEMA` / `DSN`, `i18n.SETTINGS`). That is why the app
served every ontology through a CHILD PROCESS: two profiles in one interpreter would have fought
over those names, and the loser would answer with the other ontology's tables — the exact class of
bug this feature exists to prevent.

`use()` resets exactly those names, deterministically, from a profile file. It does not re-import,
it does not touch `os.environ` (a process-wide side effect that outlives the request), and it
returns what it pointed at so a caller can log it.

The one thing it CANNOT give you is isolation: the compiler's state is process-wide, so a caller
that serves two ontologies must serialise `use() + compile()` (see `services/ontology_runtime`).
Compiling is milliseconds; the database round-trip is what takes time, and that happens after the
lock is released.
"""
from __future__ import annotations

import json
import pathlib
import sys

# this file sits at backend/features/ontology/profile.py; the compiler is next door in compiler/
FEATURE = pathlib.Path(__file__).resolve().parent
COMPILER = FEATURE / "compiler"
if str(COMPILER) not in sys.path:
    sys.path.insert(0, str(COMPILER))
PROFILES = FEATURE / "profiles"


def use(profile_path: str | pathlib.Path) -> dict:
    """Point the compiler at `profile_path` and return what it now points at."""
    import actions
    import guard
    import i18n
    import sqlgen

    path = pathlib.Path(profile_path).expanduser().resolve()
    prof = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent

    # sqlgen: the namespace, the TTL directory and the computation overlay
    ontology_dir = str((base / prof["ontology_dir"]).resolve()) if prof.get("ontology_dir") else None
    overlay = str((base / prof["overlay"]).resolve()) if prof.get("overlay") else ""
    sqlgen.reconfigure(ns=prof.get("ns") or None, ontology_dir=ontology_dir,
                       overlay=overlay, drop_overlay=not prof.get("overlay"))

    # guard / actions / i18n: the settings file they read their limits, verbs and tables from
    guard.SETTINGS = path
    i18n.SETTINGS = path
    actions.SETTINGS = path
    # the explicit marker the compiler resolves actions/features against (it beats $APP_SETTINGS,
    # which is process-wide and outlives a single request)
    actions.ACTIVE_PROFILE = path
    actions.SCHEMA = pathlib.Path((base / prof["actions_file"]).resolve()) \
        if prof.get("actions_file") else (PROFILES / "retail" / "schema" / "actions.yml")

    return {"profile": str(path), "ns": sqlgen.NS, "ontology_dir": ontology_dir,
            "overlay": overlay or None, "actions_file": str(actions.SCHEMA),
            "dsn": actions.dsn()}


def graph():
    """The graph of whatever profile `use()` last pointed at."""
    import sqlgen

    return sqlgen.load()


def features() -> dict:
    """The active profile's feature flags (actions / tutorial / lane_b …)."""
    import os

    raw = os.environ.get("APP_SETTINGS")
    import actions

    return (actions._settings().get("features") or {}) if hasattr(actions, "_settings") else {}
