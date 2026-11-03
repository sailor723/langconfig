"""Who owns a generated dashboard.

The Analysis activity lists every `*.html` in `data/analysis_dbs/`, and that
directory is shared by every account. Measured before this module existed: five
accounts (admin, user1…user4) all got the same 38 pages, because `list_dashboards`
globbed the directory with no owner filter at all.

Why a sidecar registry and not per-user directories: the file path is the API.
Pages are served by name (`/api/files/<name>`, the iframe's `src`, the ERD and
Gantt links inside a generated page), so moving them under `users/<id>/` would
break every in-page link and the generator's output contract in one step. The
files stay where they are; ownership is recorded next to them.

Semantics, deliberately simple:

* An entry in the registry means ONE owner — that account sees the page.
* No entry means **shared**: the pre-account demo pages (Chinook, Sun Hing, ERP…)
  and anything a script produced outside a request. Those stay visible to
  everyone, which is the honest reading of "nobody owns this".
* Ownership is recorded when a page is created through the app (upload / init) or
  by the `gen_dashboard` tool, using the request's user (`subject_user_id()`).

Known gap, stated rather than hidden: `/api/files/<name>` does not check
ownership, so a page is *hidden* from other accounts' lists but still fetchable by
name. Closing that needs the file route to consult this registry — see the note in
`docs/system-architecture/system-architecture.md`.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[2]
DASHBOARD_DIR = REPO / "data" / "analysis_dbs"
REGISTRY = DASHBOARD_DIR / ".dashboard_owners.json"


def _load() -> dict:
    import json as _json

    try:
        raw = _json.loads(REGISTRY.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001 — say why; never fail the listing
        logger.warning("dashboard owner registry unreadable (%s: %s)", type(exc).__name__, exc)
        return {}
    return raw if isinstance(raw, dict) else {}


def _save(data: dict) -> None:
    # Write-then-rename: a half-written registry would silently un-own every page.
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(REGISTRY.parent), prefix=".owners-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=0, sort_keys=True)
        os.replace(tmp, REGISTRY)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def owner_of(filename: str) -> Optional[int]:
    """Owner id, or None when the page is shared (no entry)."""
    entry = _load().get(filename)
    if isinstance(entry, dict):
        uid = entry.get("owner")
        return int(uid) if isinstance(uid, (int, float)) else None
    return None


def record(filename: str, user_id: Optional[int]) -> None:
    """Record a page's owner. A None user leaves the page shared."""
    if not filename or user_id is None:
        return
    data = _load()
    current = owner_of(filename)
    if current == user_id:
        return
    data[filename] = {"owner": int(user_id)}
    try:
        _save(data)
    except Exception as exc:  # noqa: BLE001 — ownership is bookkeeping, not a run blocker
        logger.warning("could not record owner for %s (%s: %s)", filename, type(exc).__name__, exc)


def record_many(filenames: Iterable[str], user_id: Optional[int]) -> None:
    if user_id is None:
        return
    data = _load()
    changed = False
    for f in filenames:
        if not f:
            continue
        entry = data.get(f)
        if isinstance(entry, dict) and entry.get("owner") == int(user_id):
            continue
        data[f] = {"owner": int(user_id)}
        changed = True
    if not changed:
        return
    try:
        _save(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not record owners (%s: %s)", type(exc).__name__, exc)


def is_visible(filename: str, user_id: Optional[int]) -> bool:
    """Shared pages are visible to everyone; owned ones only to their owner.

    `user_id is None` (no accounts at all) sees everything — the single-user
    install must keep working.
    """
    if user_id is None:
        return True
    owner = owner_of(filename)
    return owner is None or owner == user_id


def filter_visible(filenames: Iterable[str], user_id: Optional[int]) -> list[str]:
    if user_id is None:
        return list(filenames)
    data = _load()
    out = []
    for f in filenames:
        entry = data.get(f)
        owner = entry.get("owner") if isinstance(entry, dict) else None
        if owner is None or owner == user_id:
            out.append(f)
    return out
