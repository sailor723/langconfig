"""State schemas the platform can build from JSON.

LangChain's handoff pattern needs a custom state field — a tool writes
`current_step` (or whatever the reviewer calls it) through a `Command`, and
middleware reads it to change the agent's prompt and tools. `create_agent` takes
that as `state_schema=AgentState` subclass, but an agent stored in the database
cannot carry a Python class, so the platform stores a small field map:

    "state_schema": {"handoff_to": "str", "attempts": "int"}

and builds the subclass here. Keeping it to plain scalars is deliberate: a field
carried across turns must survive JSON storage and a checkpoint round trip.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Type

logger = logging.getLogger(__name__)

#: JSON-friendly type names → Python types. Extending this list is the only way
#: to add a field type, which keeps the state serialisable by construction.
_FIELD_TYPES = {
    "str": str,
    "string": str,
    "int": int,
    "integer": int,
    "float": float,
    "number": float,
    "bool": bool,
    "boolean": bool,
}

#: Field the built-in `handoff` tool writes and the handoff middleware reads.
HANDOFF_FIELD = "handoff_to"
#: Where the conversation came *from* on the last hop. Kept because a transfer
#: is only meaningful as an edge: "转交给 finance" says less than "售后 → 财务".
HANDOFF_FROM_FIELD = "handoff_from"


def build_state_schema(fields: Optional[Dict[str, Any]], *, extra: Optional[Dict[str, Any]] = None) -> Optional[Type]:
    """Return an ``AgentState`` subclass carrying ``fields``.

    ``None`` when there is nothing to add — the caller then leaves
    ``create_agent`` on its default state.
    """
    spec: Dict[str, Any] = dict(fields or {})
    for name, kind in (extra or {}).items():
        spec.setdefault(name, kind)
    if not spec:
        return None

    try:
        from langchain.agents import AgentState
        from typing import Optional as _Optional
    except ImportError:  # pragma: no cover
        logger.warning("AgentState unavailable — custom state fields ignored")
        return None

    annotations: Dict[str, Any] = {}
    namespace: Dict[str, Any] = {"__annotations__": annotations}
    for name, kind in spec.items():
        py_type = _FIELD_TYPES.get(str(kind).lower())
        if py_type is None:
            logger.warning("state field '%s' has unsupported type '%s' — skipped", name, kind)
            continue
        annotations[name] = _Optional[py_type]
        namespace[name] = None

    if not annotations:
        return None

    return type("PlatformAgentState", (AgentState,), namespace)


__all__ = ["HANDOFF_FIELD", "build_state_schema"]
