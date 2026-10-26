"""Built-in tools and skills are read-only through the API.

Why this is a security test, not a style test
---------------------------------------------
`custom_tools.is_builtin` is a **code-execution trust boundary**
(`core/tools/factory/builders.py`): built-in rows run with the full
`__builtins__` and `os` / `io` / `pathlib` available, while user-created tools go
through AST validation in a restricted namespace. Before this guard, any caller
could `PUT /api/custom-tools/{tool_id}` and rewrite a built-in's
`implementation_config.code`, then `POST /{tool_id}/test` to execute it — i.e. an
unauthenticated remote-code-execution primitive on a single-user install, and
privilege escalation the moment a second person shares the instance.

The same shape applies to skills: a built-in skill's `source_path` points into
`backend/skills/builtin/`, which is git-tracked, so an update wrote through to a
file every install shares.

These tests call the route handlers directly with a real DB session — no HTTP
layer — so they fail loudly if the guard is removed.
"""

import inspect
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from api.tools.routes import CustomToolUpdate, delete_custom_tool, update_custom_tool
from api.skills.routes import update_skill


def _builtin_tool_id(db) -> str:
    tid = db.execute(
        text("select tool_id from custom_tools where is_builtin order by tool_id limit 1")
    ).scalar()
    if not tid:
        pytest.skip("no built-in tools seeded in this database")
    return tid


def _builtin_skill_id(db) -> str:
    sid = db.execute(
        text("select skill_id from skills where source_type = 'builtin' limit 1")
    ).scalar()
    if not sid:
        pytest.skip("no built-in skills in this database")
    return sid


# ── tools ──────────────────────────────────────────────────────────────────

def test_updating_a_builtin_tool_is_forbidden(db_session):
    tid = _builtin_tool_id(db_session)
    with pytest.raises(HTTPException) as exc:
        # Bypass pydantic construction order: the guard runs before any field is
        # written, so an empty payload is enough to prove it rejects.
        update_payload = CustomToolUpdate(description="hijacked")
        import asyncio

        asyncio.run(
            update_custom_tool(tid, update_payload, db_session)
        )
    assert exc.value.status_code == 403
    assert "built-in" in str(exc.value.detail).lower()


def test_builtin_tool_row_is_unchanged_after_the_rejected_update(db_session):
    from models.custom_tool import CustomTool

    tid = _builtin_tool_id(db_session)
    before = db_session.query(CustomTool).filter(CustomTool.tool_id == tid).first()
    before_impl = dict(before.implementation_config or {})
    before_desc = before.description

    import asyncio

    with pytest.raises(HTTPException):
        asyncio.run(
            update_custom_tool(tid, CustomToolUpdate(description="hijacked"), db_session)
        )

    db_session.rollback()
    after = db_session.query(CustomTool).filter(CustomTool.tool_id == tid).first()
    assert after.description == before_desc
    assert dict(after.implementation_config or {}) == before_impl


def test_deleting_a_builtin_tool_is_forbidden(db_session):
    tid = _builtin_tool_id(db_session)
    import asyncio

    with pytest.raises(HTTPException) as exc:
        asyncio.run(delete_custom_tool(tid, db_session))
    assert exc.value.status_code == 403


def test_a_custom_tool_is_still_editable(db_session):
    """The guard must not block ordinary user tools (the whole point of PUT)."""
    from models.custom_tool import CustomTool
    from models.custom_tool import ToolType

    tid = f"test-immut-{uuid.uuid4().hex[:8]}"
    tool = CustomTool(
        tool_id=tid,
        name="Test tool",
        description="before",
        tool_type=ToolType.PYTHON_FUNCTION if hasattr(ToolType, "PYTHON_FUNCTION") else "python_function",
        implementation_config={"function_name": "f", "code": "def f():\n    return 1\n"},
        input_schema={"type": "object", "properties": {}},
        output_format="string",
        is_builtin=False,
    )
    db_session.add(tool)
    db_session.commit()
    try:
        import asyncio

        result = asyncio.run(
            update_custom_tool(tid, CustomToolUpdate(description="after"), db_session)
        )
        # the handler answers {"tool_id", "message", "warnings"} — assert on the
        # row, which is what actually matters
        assert result["tool_id"] == tid
        db_session.expire_all()
        assert (
            db_session.query(CustomTool).filter(CustomTool.tool_id == tid).first().description
            == "after"
        )
    finally:
        db_session.execute(text("delete from custom_tools where tool_id = :t"), {"t": tid})
        db_session.commit()


# ── skills ─────────────────────────────────────────────────────────────────

def test_updating_a_builtin_skill_is_forbidden(db_session):
    sid = _builtin_skill_id(db_session)

    class _Req:
        # The guard fires before any field is read, so a bare object is enough.
        pass

    import asyncio

    with pytest.raises(HTTPException) as exc:
        asyncio.run(update_skill(sid, _Req()))
    assert exc.value.status_code == 403
    assert "built-in" in str(exc.value.detail).lower()


# ── the guard must exist in the source, not only in behaviour ──────────────

def test_guards_are_present_in_the_handlers():
    """Cheap structural check: removing the guard should not look like a refactor."""
    import api.tools.routes as tools_routes
    import api.skills.routes as skills_routes

    tools_src = inspect.getsource(tools_routes.update_custom_tool)
    assert "is_builtin" in tools_src
    assert "403" in tools_src

    skills_src = inspect.getsource(skills_routes.update_skill)
    assert "builtin" in skills_src.lower()
    assert "403" in skills_src


def test_chat_config_is_built_before_the_agent_cache_check():
    """`_resolve_recursion_limit(_safe_config)` runs whether or not the agent was cached.

    The config used to be built inside `if not agent_instance:` only, so the second
    message of a session — by then the agent is cached — raised UnboundLocalError and the
    chat returned 500. Found by a live three-turn conversation, not by the suite: nothing
    here exercised a warm cache.
    """
    import inspect
    import re

    from api.chat import messages as chat_messages

    source = inspect.getsource(chat_messages.send_message)
    # Comments are stripped first: the explanation above the fix quotes the very
    # expressions being located, and a plain string search happily matches the prose
    # instead of the code (this test failed twice that way before the strip).
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )

    assign = code.index("_safe_config = dict(agent.config or {})")
    cache_check = re.search(r"^\s+if not agent_instance:", code, re.M).start()
    use = code.index("_resolve_recursion_limit(_safe_config)")

    assert assign < cache_check, "the config must exist before the cache branch"
    assert assign < use
    # Exactly one assignment, so a later edit cannot reintroduce the inner copy.
    assert len(re.findall(r"^\s*_safe_config = dict\(agent\.config or \{\}\)", source, re.M)) == 1
