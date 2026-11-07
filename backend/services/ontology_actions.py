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

import logging

from services import ontology_runtime

logger = logging.getLogger(__name__)


class ActionError(Exception):
    """No ontology, or the engine refused. A refusal is a RESULT, not a crash."""


def _wrap(fn, key: str, *args, **kwargs):
    try:
        return fn(key, *args, **kwargs)
    except ontology_runtime.OntologyError as exc:
        raise ActionError(str(exc)) from exc


def list_actions(key: str) -> dict:
    """Every declared verb with its parameters, preconditions and compiled effect."""
    return _wrap(ontology_runtime.declared_actions, key)


def invoke(key: str, action: str, params: dict, *, dry_run: bool = False,
           actor: str | None = None) -> dict:
    """`check` (read-only) or `run` (audited write). A refusal comes back as ok=false."""
    return _wrap(ontology_runtime.invoke, key, action, params, dry_run=dry_run, actor=actor)


def audit(key: str, limit: int = 50) -> dict:
    """The append-only audit trail of every write this ontology's verbs have made."""
    return _wrap(ontology_runtime.audit, key, limit=limit)
