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
    # No verbs declared means NO file: leaving retail's here is how PromoteCustomer was once compiled
    # against another ontology's graph. `actions_path()` resolves from ACTIVE_PROFILE, so this is only
    # the value a caller reads back for display.
    conventional = base / "schema" / "actions.yml"
    actions.SCHEMA = ((base / prof["actions_file"]).resolve() if prof.get("actions_file")
                      else conventional.resolve() if conventional.is_file() else None)

    # The NL layer's ALIASES are per profile too (区域→zone, 车辆→vehicle …). It used to install them
    # only from `$APP_SETTINGS`, which the app never sets — so switching profiles in-process left the
    # app answering dimension questions with no aliases while the subprocess path had them. `use()` is
    # the one place that knows which profile is active, so it installs them here.
    try:
        import nl  # noqa: PLC0415
        nl.use_profile(path)
    except Exception as exc:                                     # noqa: BLE001
        import logging
        logging.getLogger(__name__).debug("nl aliases not installed for %s: %s", path, exc)

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
