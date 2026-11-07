"""Which databases are OFFERED — the on/off list from Settings → Databases.

One rule for every surface that lists databases (the Studio picker, the dashboard
browser, the Settings table itself): the stored `databases` setting decides.

  * No setting at all  → everything discovered is offered. An install that never
    opened the page keeps working after the upgrade.
  * A setting exists   → it IS the offered list. Anything not in it is off.

`items` holds only the switched-ON rows, so "off" is represented by absence —
one source of truth instead of a flag that can disagree with the list.
"""
import logging
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


def settings_items() -> List[Dict[str, Any]]:
    """The stored `databases` rows (all of them), or [] when nothing is stored.

    `.value` is the document the caller actually runs with (owner section merged
    with the account's own), which is what the pickers should mirror.
    """
    try:
        from core import settings as core_settings
        from db.database import SessionLocal

        db = SessionLocal()
        try:
            doc = core_settings.resolve(db, "databases").value or {}
        finally:
            db.close()
        items = (doc or {}).get("items") or []
        return [dict(i) for i in items if isinstance(i, dict) and i.get("name")]
    except Exception as exc:  # noqa: BLE001 — a settings problem must not empty every picker
        logger.warning(f"[databases] cannot read the databases setting: {exc}")
        return []


def offered_names(items: Optional[Iterable[Dict[str, Any]]] = None) -> set:
    """Names that are switched on (a `enabled: false` row counts as off)."""
    rows = settings_items() if items is None else list(items)
    return {str(i["name"]) for i in rows if i.get("enabled", True) and i.get("name")}


def is_offered(name: str, items: Optional[Iterable[Dict[str, Any]]] = None) -> bool:
    rows = settings_items() if items is None else list(items)
    if not rows:
        return True  # nothing configured → the setting is not narrowing anything
    return str(name) in offered_names(rows)


def disabled_names(items: Optional[Iterable[Dict[str, Any]]] = None) -> set:
    """Names an admin switched OFF on purpose.

    Kept apart from "unknown" because readers treat the two differently: a
    database switched off is a decision (hide it), while a dashboard family
    nobody registered yet is an unfinished draft (its author still sees it).
    """
    rows = settings_items() if items is None else list(items)
    return {str(i["name"]) for i in rows if not i.get("enabled", True) and i.get("name")}


def visibility_of(name: str, items: Optional[Iterable[Dict[str, Any]]] = None) -> str:
    """How `name` should be shown: ``published`` / ``hidden`` / ``private``.

    * ``published`` — switched on: every account sees it. The list is a team
      decision, so the data behind it is the team's data;
    * ``hidden``    — switched off on purpose: nobody sees it;
    * ``private``   — not in the setting at all: a draft, visible to whoever
      generated it (see services/dashboard_owners).
    """
    rows = settings_items() if items is None else list(items)
    if not rows:
        return "published"  # nothing configured → the setting narrows nothing
    if str(name) in offered_names(rows):
        return "published"
    if str(name) in disabled_names(rows):
        return "hidden"
    return "private"


def filter_offered(names: Iterable[str], items: Optional[Iterable[Dict[str, Any]]] = None) -> List[str]:
    """Keep the names the setting offers; everything when nothing is configured."""
    rows = settings_items() if items is None else list(items)
    if not rows:
        return list(names)
    on = offered_names(rows)
    return [n for n in names if n in on]


def connection_for(name: str) -> Dict[str, Any]:
    """Connection facts an admin entered for one database row, or {}.

    Settings → Databases has host / port / dbname / user / password columns. They
    exist because a `target` can be a server this install has never heard of: the
    only other place to put its credentials is `SQL_TARGETS` in `.env`, which
    needs a shell and a restart. The row is the same decision, made in the UI.

    Only non-empty values are returned, so a half-filled row cannot blank out a
    working `.env` target: an omitted field keeps whatever the built-in/env
    resolution had.
    """
    row = next(
        (i for i in settings_items() if str(i.get("name")) == str(name)),
        None,
    )
    if not row:
        return {}
    # A `platform` row means "a database on the platform server": its host/port/role
    # come from POSTGRES_*, and honouring the columns here would let a stray value
    # send queries to an unlisted server. `target` and `dashboard` rows are the ones
    # whose columns describe a real connection (dashboard rows simply stay empty).
    if str(row.get("kind") or "platform") == "platform":
        return {}
    out: Dict[str, Any] = {}
    for key in ("host", "port", "user", "password", "dbname"):
        value = row.get(key)
        if value not in (None, ""):
            out[key] = value
    return out


def kind_of(name: str) -> Optional[str]:
    """`platform` / `target` / `dashboard` for one row, or None when unregistered."""
    row = next(
        (i for i in settings_items() if str(i.get("name")) == str(name)),
        None,
    )
    if not row:
        return None
    return str(row.get("kind") or "platform")
