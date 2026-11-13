"""`db_query` must be able to answer many questions in ONE call.

Measured 2026-11-14 on the ontology builder (agent 380): 6 085 s of wall clock for 1 618 separate
shell calls, i.e. ~4 s per model round-trip while each query ran in milliseconds. The round-trip is
the cost, so the tool has to accept a batch — and the batch has to be safe: read-only, bounded,
and honest about which statement failed.

These tests are about the tool's *contract*, so they fake the connection rather than needing a
database: a gate suite that only runs when Postgres is up would go green by never running.
"""
import psycopg2

from tools import native_impl


def test_split_keeps_semicolons_inside_literals_and_comments():
    sql = """
    select 'a;b' as v from t1;
    -- this ; is a comment, not a boundary
    select 2 as w from t2
    """
    parts = native_impl._split_sql_statements(sql)
    assert len(parts) == 2, parts
    assert parts[0].startswith("select 'a;b'")
    assert parts[1].startswith("-- this ; is a comment") and parts[1].endswith("from t2")


def test_split_ignores_doubled_quotes_and_comment_only_chunks():
    parts = native_impl._split_sql_statements(
        "select 'it''s; fine' from t;"  # doubled quote, semicolon inside
        " -- trailing comment only ; \n"
        "select 1 from t2;"
    )
    assert len(parts) == 2, parts
    assert "it''s; fine" in parts[0]


def test_split_drops_a_chunk_that_is_only_a_comment():
    assert native_impl._split_sql_statements("-- nothing here\n") == []


class _FakeCursor:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.executed = []
        self.description = [("col",)]
        self._rows = []

    def execute(self, statement):
        self.executed.append(statement)
        if statement.startswith("SET statement_timeout"):
            return
        for needle, outcome in self.behaviour.items():
            if needle in statement:
                if isinstance(outcome, Exception):
                    raise outcome
                self._rows = outcome
                return
        self._rows = []

    def fetchall(self):
        return list(self._rows)


class _FakeConn:
    def __init__(self, behaviour):
        self.cur = _FakeCursor(behaviour)
        self.closed = False
        self.readonly = None
        self.rollbacks = 0

    def set_session(self, **kwargs):
        self.readonly = kwargs.get("readonly")

    def cursor(self):
        return self.cur

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def _patch_connect(monkeypatch, conn):
    monkeypatch.setattr(psycopg2, "connect", lambda **kwargs: conn)
    return conn


def test_batch_runs_every_statement_on_one_connection_and_labels_results(monkeypatch):
    conn = _patch_connect(monkeypatch, _FakeConn({"from t1": [(7,)]}))
    out = native_impl.db_query.invoke({
        "db_name": "demo",
        "sqls": ["select count(*) from t1", "select count(*) from t2"],
    })
    assert "### [1/2]" in out and "### [2/2]" in out
    assert "| 7 |" in out                       # first statement's rows
    assert out.count("### [") == 2
    assert conn.readonly is True                # read-only session, always
    assert conn.closed is True                  # one connection, closed at the end
    query_calls = [s for s in conn.cur.executed if not s.startswith("SET ")]
    assert len(query_calls) == 2                # two questions, one connect


def test_one_broken_statement_does_not_kill_the_batch(monkeypatch):
    conn = _patch_connect(
        monkeypatch,
        _FakeConn({"from bad": RuntimeError("relation bad does not exist"), "from good": [(3,)]}),
    )
    out = native_impl.db_query.invoke({
        "db_name": "demo",
        "sqls": ["select 1 from bad", "select 2 from good"],
    })
    assert "relation bad does not exist" in out
    assert "| 3 |" in out, "the second statement still must run"
    assert conn.rollbacks == 1


def test_non_readonly_statement_refuses_the_whole_batch(monkeypatch):
    conn = _patch_connect(monkeypatch, _FakeConn({}))
    out = native_impl.db_query.invoke({
        "db_name": "demo",
        "sqls": ["select 1 from t", "drop table t"],
    })
    assert "Nothing ran" in out
    assert "2/2" in out, "the refusal must name which statement was not read-only"
    assert conn.cur.executed == [], "nothing may reach the cursor once one statement is refused"


def test_batch_cap_is_named(monkeypatch):
    conn = _patch_connect(monkeypatch, _FakeConn({}))
    out = native_impl.db_query.invoke({
        "db_name": "demo",
        "sqls": [f"select {i} from t" for i in range(native_impl._MAX_DB_QUERY_BATCH + 1)],
    })
    assert f"batch cap is {native_impl._MAX_DB_QUERY_BATCH}" in out
    assert conn.cur.executed == []


def test_semicolons_in_the_single_sql_argument_become_a_batch(monkeypatch):
    """The old code refused `;` outright; an agent that pasted two SELECTs lost a whole round-trip."""
    conn = _patch_connect(monkeypatch, _FakeConn({"from t2": [(9,)]}))
    out = native_impl.db_query.invoke({
        "db_name": "demo",
        "sql": "select 1 from t1; select 2 from t2;",
    })
    assert "### [1/2]" in out and "### [2/2]" in out
    assert "| 9 |" in out
    assert len([s for s in conn.cur.executed if not s.startswith("SET ")]) == 2


def test_output_is_capped_so_one_batch_cannot_blow_up_the_context(monkeypatch):
    big = [("x" * 200,) for _ in range(200)]
    _patch_connect(monkeypatch, _FakeConn({"from t": big}))
    out = native_impl.db_query.invoke({
        "db_name": "demo",
        "sqls": [f"select payload from t" for _ in range(5)],
    })
    assert len(out) <= native_impl._MAX_DB_QUERY_CHARS + 400
    assert "output truncated" in out


REPO = __import__("pathlib").Path(__file__).resolve().parents[2]
SKILL = REPO / "backend" / "skills" / "builtin" / "build-ontology-from-db" / "SKILL.md"
SKILL_EN = REPO / "backend" / "skills" / "en-originals" / "build-ontology-from-db" / "SKILL.md"


def test_the_skill_teaches_the_batched_form_too():
    """Three artefacts have to agree: the prompt, the tool list, and the skill.

    The skill is what the builder actually re-reads between ladder steps, so a batch tool that only
    the system prompt mentions is a rule the agent meets once and forgets — and the skill's own
    "one aggregate, one statement" line reads as "one SELECT per call" if left alone.
    """
    text = SKILL.read_text(encoding="utf-8")
    assert "db_query(sqls=" in text, "the skill never shows the batched call"
    assert "6 085" in text, "the skill states the rule without the measurement behind it"
    assert "批量只读查询" in text, "the capability table does not list the batched query"


def test_the_english_original_carries_the_same_rule():
    """The Chinese skill is a machine translation of the archive; a rule only in the translation is
    lost the next time the pair is regenerated, so both sides must say it."""
    text = SKILL_EN.read_text(encoding="utf-8")
    assert "db_query(sqls=[" in text
    assert "6 085" in text
    assert "batched read-only queries" in text
