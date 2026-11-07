"""Gates for ontology builds as background jobs: enqueue → run → land, and its refusals.

The user's flow in two halves: *run the agent to generate the ontology (it takes time), then open it
and refine by chat*. The first half is this job. It must be:

* **refused before it starts** when it cannot work: no key, no brief, a bare folder name with a slash.
  A build costs minutes of agent time, so a typo must not cost that;
* **a row in the queue** (background_tasks), not a chat turn: the whole point is that closing the tab
  does not kill it;
* **landed only on evidence**: auto-land happens when the staged publish has no new refusal and no
  failing gate — read from the publish LEDGER, not from what the agent says it did;
* **never silently green**: a build that staged nothing, or whose gates failed, says so with the
  reason, and leaves the proposal for a person.

The agent turn and the publish channel are faked here (no tokens, no files, no database); the
handler's decision logic and the enqueue/status/report shapes are what these assertions measure.

Run: cd backend && .venv/bin/python -m pytest tests/test_ontology_build.py -v
"""
from __future__ import annotations

import asyncio

import pytest

from services import ontology_build
from services.ontology_build import BuildError


class _FakeReply:
    def __init__(self, message: str = "built it", tools=None):
        self._message = message
        self._tools = tools or [{"tool_name": "ontology_publish"}]

    def model_dump(self):
        return {"message": self._message, "tool_calls": self._tools}


@pytest.fixture()
def env(monkeypatch):
    """A registered build that fakes the agent turn and the publish ledger."""
    state = {"history": [], "applied": [], "sessions": 0, "notes": []}

    async def fake_start(request, db):
        state["sessions"] += 1
        return {"session_id": f"build-session-{state['sessions']}"}

    async def fake_send(request, db):
        state["sent"] = request.message
        return _FakeReply()

    import api.chat.messages as chat_messages
    import api.chat.session as chat_session
    from services import ontology_publish

    monkeypatch.setattr(chat_session, "start_chat_session", fake_start)
    monkeypatch.setattr(chat_messages, "send_message", fake_send)
    monkeypatch.setattr(ontology_publish, "history",
                        lambda key=None, limit=50: list(state["history"]))
    monkeypatch.setattr(ontology_publish, "apply", lambda *a, **kw: state["applied"].append(kw) or {
        "ok": True, "git_commit": "abc1234", "workbench_reloaded": True, "reload_note": ""})
    monkeypatch.setattr(ontology_build, "_note", lambda task_id, note: state["notes"].append(note))

    class _Agent:
        id = 349
        name = "Ontology Builder (logistics)"

    monkeypatch.setattr(ontology_build, "_db", lambda: _FakeDb(_Agent()))
    return state


class _FakeDb:
    """Just enough Session for the handler's agent lookup."""

    def __init__(self, agent):
        self._agent = agent

    def query(self, *a, **kw):
        return self

    def filter(self, *a, **kw):
        return self

    def first(self):
        return self._agent

    def close(self):
        pass


def _stage(id_="1794-x", **report):
    base = {"files": ["tutorial.json"], "new_refusals": [], "carried_refusals": ["atRiskDrivers"],
            "gates_ok": True, "gates_fails": [], "gates_not_run": ["[NOT RUN] R2"],
            "compile": {"metrics": 23, "compiled": 20, "refused": []}}
    base.update(report)
    return {"id": id_, "key": "logistics", "status": "staged", "actor": "agent:user1",
            "note": "build", "created_at": "2026-11-07T00:00:00", "report": base}


def _run(payload, task_id=1):
    return asyncio.run(ontology_build._run_build(payload, task_id))


# ── the request gate ───────────────────────────────────────────────────────────

def test_a_key_with_a_slash_is_refused():
    with pytest.raises(BuildError) as exc:
        asyncio.run(ontology_build.enqueue_build(349, "../etc", "brief"))
    assert "folder name" in str(exc.value)


def test_an_empty_brief_is_refused():
    with pytest.raises(BuildError) as exc:
        asyncio.run(ontology_build.enqueue_build(349, "logistics", "   "))
    assert "brief" in str(exc.value)


# ── landing: on evidence, never on the agent's word ───────────────────────────

def test_a_green_build_lands_itself(env):
    env["history"] = [_stage()]
    out = _run({"agent_id": 349, "ontology_key": "logistics", "brief": "build", "auto_land": True})
    assert out["landed"] is True, out
    assert out["staged_id"] == "1794-x"
    assert env["applied"] and env["applied"][0].get("confirmed") is True
    assert out["report"]["compile"]["compiled"] == 20
    assert "abc1234" in out["reason"]


def test_a_new_refusal_blocks_the_landing_and_names_it(env):
    env["history"] = [_stage(new_refusals=["brokenCount"])]
    out = _run({"agent_id": 349, "ontology_key": "logistics", "brief": "build", "auto_land": True})
    assert out["landed"] is False
    assert "brokenCount" in out["reason"]
    assert env["applied"] == [], "a publish with a new refusal was installed"


def test_a_failing_gate_blocks_the_landing(env):
    env["history"] = [_stage(gates_ok=False, gates_fails=["tutorial T4: metric step did not run"])]
    out = _run({"agent_id": 349, "ontology_key": "logistics", "brief": "build", "auto_land": True})
    assert out["landed"] is False
    assert "tutorial T4" in out["reason"]


def test_auto_land_off_never_applies(env):
    env["history"] = [_stage()]
    out = _run({"agent_id": 349, "ontology_key": "logistics", "brief": "build", "auto_land": False})
    assert out["landed"] is False
    assert env["applied"] == []
    assert "auto-land is off" in out["reason"]


def test_a_build_that_staged_nothing_says_so(env):
    env["history"] = []
    out = _run({"agent_id": 349, "ontology_key": "logistics", "brief": "build", "auto_land": True})
    assert out["ok"] is False
    assert "without staging a publish" in out["reason"]
    assert out["staged_id"] is None if "staged_id" in out else True


def test_the_latest_staged_publish_is_the_one_considered(env):
    env["history"] = [
        _stage("old-id", created_at="2026-01-01"),
        _stage("new-id"),
    ]
    env["history"][0]["created_at"] = "2026-01-01T00:00:00"
    env["history"][1]["created_at"] = "2026-02-01T00:00:00"
    out = _run({"agent_id": 349, "ontology_key": "logistics", "brief": "build", "auto_land": True})
    assert out["staged_id"] == "new-id"


def test_the_turn_reuses_a_given_session_and_opens_one_otherwise(env):
    env["history"] = [_stage()]
    _run({"agent_id": 349, "ontology_key": "logistics", "brief": "b", "session_id": "kept"},
         task_id=2)
    assert env["sessions"] == 0, "a provided session was replaced"
    assert env["sent"] == "b"
    env["history"] = [_stage()]
    _run({"agent_id": 349, "ontology_key": "logistics", "brief": "b"}, task_id=3)
    assert env["sessions"] == 1, "no session was opened for a build without one"


def test_progress_notes_are_recorded_for_the_panel(env):
    env["history"] = [_stage()]
    _run({"agent_id": 349, "ontology_key": "logistics", "brief": "build"}, task_id=9)
    assert any("reading the database" in n for n in env["notes"])
    assert any("auto-landing" in n for n in env["notes"])


# ── status / listing shapes the panel depends on ───────────────────────────────

def test_an_unknown_task_is_reported_not_raised(monkeypatch):
    class _Db:
        def query(self, *a, **kw):
            return self

        def filter(self, *a, **kw):
            return self

        def first(self):
            return None

        def close(self):
            pass

    monkeypatch.setattr(ontology_build, "_db", lambda: _Db())
    assert ontology_build.build_status(424242) == {
        "ok": False, "error": "no build task 424242"}


def test_recent_builds_filter_by_ontology_key(monkeypatch):
    class _Task:
        def __init__(self, id_, key, status="COMPLETED", result=None):
            self.id = id_
            self.task_type = ontology_build.TASK_TYPE
            self.payload = {"ontology_key": key, "agent_id": 349, "auto_land": True}
            self.status = status
            self.created_at = None
            self.result = result

    tasks = [_Task(3, "logistics", result={"staged_id": "x", "landed": True}),
             _Task(2, "clinic"), _Task(1, "logistics")]

    class _Db:
        def query(self, *a, **kw):
            return self

        def filter(self, *a, **kw):
            return self

        def order_by(self, *a, **kw):
            return self

        def limit(self, *a, **kw):
            return self

        def all(self):
            return tasks

        def close(self):
            pass

    monkeypatch.setattr(ontology_build, "_db", lambda: _Db())
    rows = ontology_build.recent_builds(ontology_key="logistics", limit=5)
    assert [r["task_id"] for r in rows] == [3, 1]
    assert rows[0]["landed"] is True
