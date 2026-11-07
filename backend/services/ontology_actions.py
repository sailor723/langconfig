"""Declared writes for one ontology: `schema/actions.yml` → compiled preconditions → audited run.

The rule this service exists to keep: **a write is never free SQL.** It is an action declared in the
ontology's `actions.yml`, compiled against the ontology graph by `retail_graph/actions.py` (property →
`:physicalColumn`, object type → `:physicalTable`/`:primaryKey`), admitted only if its declared
preconditions hold, executed in ONE transaction, and recorded in `audit_events` — or refused by name
with nothing written.

Two verbs, and the difference matters:

* `check` — a READ-ONLY dry-run. It reports each precondition with the parameters bound, so a caller can
  see what would have to be true. No transaction is opened that writes anything.
* `run` — the write. It needs a human-confirmed caller; nothing here decides that for you.

Shelling out rather than importing: `actions.py` binds its profile and its `APP_ACTIONS` file at import
time (the samples-reset lesson), so a per-request child process is the honest way to run two ontologies'
action sets from one backend.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess

from services import ontology_publish

logger = logging.getLogger(__name__)

PYTHON = ontology_publish.PYTHON
REPO = pathlib.Path(ontology_publish.REPO)
# The ontology feature: the compiler, the workbench and the declarations live here now. The ontology
# repository is kept as a learning mirror, not a runtime dependency.
FEATURE = pathlib.Path(__file__).resolve().parents[1] / "features" / "ontology"


class ActionError(Exception):
    """No action declaration, or the engine could not be executed at all."""


def ontology_profile(key: str) -> pathlib.Path | None:
    """Where one ontology's DECLARATIONS live.

    The feature owns them now (backend/features/ontology/profiles/<key>/); the ontology repository is
    kept as a learning mirror and still works as a fallback, so a checkout that has not moved yet
    keeps answering.
    """
    feature = pathlib.Path(__file__).resolve().parents[1] / "features" / "ontology"
    mirror = pathlib.Path(os.environ.get("ONTOLOGY_REPO") or "/Users/weiping/dev/Learn/ontology")
    candidates = [
        feature / "profiles" / key / f"{key}_settings.json",
        feature / "profiles" / key / "settings.json",
        mirror / "ontologies" / key / f"{key}_settings.json",
        mirror / "ontologies" / key / "settings.json",
        mirror / "retail_graph" / f"{key}_settings.json",
    ]
    if key == "retail":
        candidates.append(feature / "profiles" / "retail" / "settings.json")
        candidates.append(mirror / "retail_graph" / "settings.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _profile_for(key: str) -> pathlib.Path | None:
    return ontology_profile(key)


def _declaration(key: str) -> tuple[pathlib.Path, pathlib.Path | None]:
    """(profile, actions.yml or None). The profile names its own actions file."""
    profile = _profile_for(key)
    if profile is None:
        raise ActionError(f"no ontology {key!r}")
    try:
        settings = json.loads(profile.read_text())
    except Exception as exc:                                    # noqa: BLE001
        raise ActionError(f"cannot read {profile}: {exc}") from exc
    raw = (settings.get("actions_file") or "").strip()
    if not raw:
        return profile, None
    path = pathlib.Path(raw).expanduser()
    if not path.is_absolute():
        path = (profile.parent / path).resolve()
    return profile, (path if path.is_file() else None)


def _run(key: str, argv: list[str]) -> tuple[int, dict | list | None]:
    profile, actions_file = _declaration(key)
    if actions_file is None:
        raise ActionError(
            f"{key} declares no actions (profile `actions_file` is empty or missing) — a write path "
            f"that is not declared does not exist")
    env = dict(os.environ)
    env.update(ONTOLOGY_REPO=str(REPO), APP_SETTINGS=str(profile), APP_ACTIONS=str(actions_file))
    # the ENGINE (actions.py) stays with the compiler it compiles against; the VERB declaration
    # (actions.yml) is the profile's own file
    proc = subprocess.run([PYTHON, str(FEATURE / "compiler" / "actions.py"), *argv],
                          capture_output=True, text=True,
                          timeout=120, cwd=str(FEATURE / "compiler"), env=env)
    raw = (proc.stdout or "").strip()
    if not raw:
        tail = (proc.stderr or "").strip().splitlines()
        raise ActionError("the action engine printed nothing"
                          + (f" ({tail[-1]})" if tail else f" (exit {proc.returncode})"))
    try:
        payload = json.loads(raw)
    except Exception as exc:                                    # noqa: BLE001
        raise ActionError(f"the action engine's answer was not JSON: {raw[:300]}") from exc
    return proc.returncode, payload


def list_actions(key: str) -> dict:
    """Every declared verb with its parameters, preconditions and compiled effect."""
    try:
        code, payload = _run(key, ["list"])
    except ActionError as exc:
        # "no declaration" is an ANSWER here (an ontology may legitimately have no writes), not a
        # 500: the panel then says so instead of implying the write exists.
        return {"ok": True, "key": key, "actions": [], "note": str(exc)}
    if code != 0:
        return {"ok": False, "key": key, "actions": [], "error": payload}
    return {"ok": True, "key": key, "actions": payload if isinstance(payload, list) else []}


def invoke(key: str, action: str, params: dict, *, dry_run: bool = False,
           actor: str | None = None) -> dict:
    """`check` (read-only) or `run` (audited write). A refusal is a result, exit code 2."""
    verb = "check" if dry_run else "run"
    argv = [verb, "--action", action, "--params", json.dumps(params, ensure_ascii=False)]
    if not dry_run:
        argv += ["--actor", actor or "app"]
    try:
        code, payload = _run(key, argv)
    except ActionError as exc:
        raise ActionError(str(exc)) from exc
    if isinstance(payload, dict):
        payload.setdefault("key", key)
        payload.setdefault("dry_run", dry_run)
    return {"ok": code == 0 and bool(isinstance(payload, dict) and payload.get("ok") is not False),
            "exit_code": code, "key": key, "action": action, "verb": verb, "result": payload}


def audit(key: str, limit: int = 50) -> dict:
    """The append-only audit trail of every write this ontology's verbs have made."""
    try:
        code, payload = _run(key, ["audit"])
    except ActionError as exc:
        return {"ok": False, "key": key, "events": [], "error": str(exc)}
    rows = payload if isinstance(payload, list) else []
    return {"ok": code == 0, "key": key, "events": rows[:limit]}
