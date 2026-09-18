"""Per-session MemorySaver cache for the analysis chat agent.

Why this exists
---------------
`_run_analysis_agent` is called fresh on every chat turn. The
default `MemorySaver()` it creates lives only for the duration of
one message → no memory across questions in the same session.

This module keeps a singleton `MemorySaver()` per
`(session_id, skills_tuple)` so the same agent + checkpointer
gets reused across turns in one session. Same `session_id` +
different skills = different checkpointer (so switching
dashboards gives a clean slate).

To survive server restarts, replace `MemorySaver` with
`PostgresSaver` (already in `requirements.txt`):
    from langgraph.checkpoint.postgres import PostgresSaver
    with PostgresSaver.from_conn_string("postgresql://...") as cp:
        cp.setup()
        # ... use cp instead of MemorySaver
"""
from typing import Optional
from langgraph.checkpoint.memory import MemorySaver

# Key: (session_id, frozenset(skills)) → MemorySaver instance
_cache: dict[tuple[str, frozenset], MemorySaver] = {}


def get_checkpointer(session_id: str, skills: tuple[str, ...]) -> MemorySaver:
    """Return the singleton MemorySaver for the given (session_id, skills).

    Different skills (e.g. switching from sql-analyst to erp-analyst)
    yields a different checkpointer, so the new agent starts with a
    clean message history.
    """
    key = (session_id, frozenset(skills))
    cp = _cache.get(key)
    if cp is None:
        cp = MemorySaver()
        _cache[key] = cp
    return cp


def reset_session(session_id: str) -> int:
    """Forget all checkpointer instances for `session_id`. Returns the
    number cleared. Useful for explicit 'clear chat' actions."""
    n = 0
    for k in list(_cache.keys()):
        if k[0] == session_id:
            del _cache[k]
            n += 1
    return n


def all_sessions() -> list[str]:
    """For diagnostics: list all session_ids currently cached."""
    return sorted({k[0] for k in _cache.keys()})
