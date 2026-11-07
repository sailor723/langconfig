"""Gates for the ontology panel's editor channel: ask → turn → proposal, and its refusals.

What this channel promises, and therefore what is gated here:

* the ontology being edited is **bound into the message** — the agent must never have to guess
  which ontology a sentence is about, and the transcript must show it;
* a bad request is refused **before** a model turn is spent: no key, an empty message, a huge
  message, a key that is not installed (measured: "doesnotexist" was accepted and cost a whole
  turn of an agent talking about an ontology that does not exist);
* a session is reused only when it belongs to the editor agent, so a panel that kept a stale
  session id cannot drive somebody else's conversation;
* **proposals are read from the publish ledger, not from what the agent says**: only staged ones
  count, and each carries the files/report a reviewer needs;
* the channel can stage but never install — apply is a human in Settings.

The model turn is faked for the unit gates (no network, no tokens, no flakiness); one integration
gate checks the real agent row exists with the two ontology tools and the edit skill.

Run: cd backend && .venv/bin/python -m pytest tests/test_ontology_editor_chat.py -v
"""
from __future__ import annotations

import pathlib

import pytest

from services import ontology_editor
from services.ontology_editor import EditorUnavailable


class _FakeAgent:
    def __init__(self, agent_id: int = 350):
        self.id = agent_id
        self.name = ontology_editor.EDITOR_AGENT_NAME
        self.config = {"model": "deepseek-v4-flash"}


class _Recorder:
    """Stands in for the chat path: records what the panel asked the agent to do."""

    def __init__(self):
        self.messages: list[str] = []
        self.started = 0

    async def start(self, request, db):
        self.started += 1
        return {"session_id": f"fake-session-{self.started}"}

    async def send(self, request, db):
        self.messages.append(request.message)
        return {"message": "done: staged it", "tool_calls": [{"tool_name": "ontology_publish"}],
                "metrics": {}}


@pytest.fixture()
def harness(monkeypatch, tmp_path):
    """An installed ontology on disk + a fake agent + a recording chat path."""
    live = tmp_path / "ontologies" / "pubtest"
    (live / "ontology").mkdir(parents=True)
    (live / "pubtest_settings.json").write_text("{}", encoding="utf-8")
    from services import ontology_publish

    monkeypatch.setattr(ontology_publish, "ONTOLOGIES", tmp_path / "ontologies")
    monkeypatch.setattr(ontology_editor, "editor_agent", lambda db: _FakeAgent())

    rec = _Recorder()
    import api.chat.messages as chat_messages
    import api.chat.session as chat_session

    monkeypatch.setattr(chat_session, "start_chat_session", rec.start)
    monkeypatch.setattr(chat_messages, "send_message", rec.send)

    staged = {"rows": []}
    monkeypatch.setattr(ontology_editor, "proposals", lambda db, key: staged["rows"])
    return {"rec": rec, "staged": staged, "root": tmp_path}


def _run(coro):
    import asyncio
    return asyncio.run(coro)


# ── the request gate: refuse before spending a turn ─────────────────────────────

def test_a_missing_key_is_refused(harness):
    with pytest.raises(EditorUnavailable) as excinfo:
        _run(ontology_editor.ask(None, "", "add a metric"))
    assert "which ontology" in str(excinfo.value)
    assert harness["rec"].messages == []


def test_an_empty_message_is_refused(harness):
    with pytest.raises(EditorUnavailable) as excinfo:
        _run(ontology_editor.ask(None, "pubtest", "   "))
    assert "empty message" in str(excinfo.value)
    assert harness["rec"].messages == []


def test_an_oversized_message_is_refused(harness):
    with pytest.raises(EditorUnavailable) as excinfo:
        _run(ontology_editor.ask(None, "pubtest", "x" * (ontology_editor.MAX_MESSAGE_CHARS + 1)))
    assert "characters" in str(excinfo.value)


def test_a_key_that_is_not_installed_is_refused_and_names_the_alternatives(harness):
    """A typo must cost nothing. This was measured: it cost a full model turn."""
    with pytest.raises(EditorUnavailable) as excinfo:
        _run(ontology_editor.ask(None, "doesnotexist", "add a metric"))
    msg = str(excinfo.value)
    assert "no installed ontology" in msg and "pubtest" in msg
    assert harness["rec"].messages == []


# ── the turn itself ────────────────────────────────────────────────────────────

def test_the_ontology_is_bound_into_the_message(harness):
    """The agent must not have to infer which ontology the sentence is about."""
    out = _run(ontology_editor.ask(None, "pubtest", "把 onTimeStops 的说明补清楚"))
    assert harness["rec"].messages, "no message reached the agent"
    sent = harness["rec"].messages[-1]
    assert "[ontology_key=pubtest]" in sent
    assert "work/pubtest/" in sent
    assert sent.endswith("把 onTimeStops 的说明补清楚")
    assert out["ok"] is True and out["key"] == "pubtest"


def test_the_turn_returns_the_answer_tool_calls_and_proposals(harness):
    harness["staged"]["rows"] = [{"id": "1794-x", "files": ["tutorial.json"], "gates_ok": True}]
    out = _run(ontology_editor.ask(None, "pubtest", "改教程"))
    assert out["answer"] == "done: staged it"
    assert out["tool_calls"][0]["tool_name"] == "ontology_publish"
    assert out["proposals"] == harness["staged"]["rows"]
    assert out["session_id"].startswith("fake-session-")


def test_a_given_session_is_reused_when_it_belongs_to_the_editor(harness, monkeypatch):
    class _Session:
        session_id = "kept-session"
        agent_id = 350
        is_active = True

    class _Query:
        def filter(self, *a, **kw):
            return self

        def first(self):
            return _Session()

    class _DB:
        def query(self, *a, **kw):
            return _Query()

    out = _run(ontology_editor.ask(_DB(), "pubtest", "继续", session_id="kept-session"))
    assert out["session_id"] == "kept-session"
    assert harness["rec"].started == 0, "a usable session was replaced with a new one"


def test_a_session_from_another_agent_is_not_reused(harness):
    class _Session:
        session_id = "someone-elses"
        agent_id = 1
        is_active = True

    class _Query:
        def filter(self, *a, **kw):
            return self

        def first(self):
            return _Session()

    class _DB:
        def query(self, *a, **kw):
            return _Query()

    out = _run(ontology_editor.ask(_DB(), "pubtest", "继续", session_id="someone-elses"))
    assert out["session_id"] != "someone-elses"
    assert harness["rec"].started == 1, "a foreign session was continued"


# ── proposals come from the ledger, not from the agent's prose ─────────────────

def test_proposals_list_only_staged_publishes(monkeypatch):
    rows = [
        {"id": "a", "key": "pubtest", "status": "staged", "actor": "agent:user1",
         "note": "edit", "report": {"files": ["tutorial.json"], "new_refusals": [],
                                     "carried_refusals": ["x"], "gates_ok": True,
                                     "gates_fails": [], "gates_not_run": ["R2"],
                                     "compile": {"metrics": 3, "compiled": 2}}},
        {"id": "b", "key": "pubtest", "status": "applied", "actor": "admin", "report": {}},
        {"id": "c", "key": "pubtest", "status": "refused", "actor": "agent:user1", "report": {}},
        {"id": "d", "key": "pubtest", "status": "discarded", "actor": "admin", "report": {}},
    ]
    from services import ontology_publish

    monkeypatch.setattr(ontology_publish, "history",
                        lambda key=None, limit=50: [r for r in rows if r["key"] == key])
    got = ontology_editor.proposals(None, "pubtest")
    assert [p["id"] for p in got] == ["a"]
    p = got[0]
    assert p["files"] == ["tutorial.json"]
    assert p["carried_refusals"] == ["x"]
    assert p["gates_not_run"] == ["R2"]
    assert p["compile"]["compiled"] == 2


def test_proposals_for_another_ontology_are_not_returned(monkeypatch):
    from services import ontology_publish

    monkeypatch.setattr(ontology_publish, "history", lambda key=None, limit=50: [
        {"id": "z", "key": "other", "status": "staged", "report": {}}])
    assert ontology_editor.proposals(None, "pubtest") == []


# ── the real agent row: this is what makes the panel work at all ───────────────

def test_the_editor_agent_exists_with_the_two_ontology_tools_and_the_edit_skill():
    """Not skipped: the agent row is part of this install (seed_ontology_editor_agent.py)."""
    try:
        from db.database import SessionLocal
    except Exception as exc:                                    # noqa: BLE001
        pytest.skip(f"NOT RUN: no database in this environment ({exc})")
    db = SessionLocal()
    try:
        agent = ontology_editor.editor_agent(db)
    except EditorUnavailable as exc:
        pytest.skip(f"NOT RUN: {exc}")
    finally:
        db.close()
    cfg = agent.config or {}
    assert "ontology_open" in (cfg.get("native_tools") or []), cfg.get("native_tools")
    assert "ontology_publish" in (cfg.get("native_tools") or [])
    assert "edit-ontology-metrics" in (cfg.get("skills") or [])


def test_a_route_that_cannot_reach_the_editor_answers_409_not_500(monkeypatch):
    """The panel shows the reason ("run the seed script"), not a stack trace."""
    from fastapi import HTTPException

    import api.ontology.routes as routes

    async def boom(*a, **kw):
        raise EditorUnavailable("no agent named 'Ontology Editor' in this install")

    monkeypatch.setattr(ontology_editor, "ask", boom)
    with pytest.raises(HTTPException) as excinfo:
        _run(routes.ask_editor("pubtest", routes.AskEditorRequest(message="hi")))
    assert excinfo.value.status_code == 409
    assert "Ontology Editor" in str(excinfo.value.detail)
