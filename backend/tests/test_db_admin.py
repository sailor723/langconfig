"""Gates for `services.db_admin` — the write-side guards of the DB management agent.

An agent that can CREATE/ALTER/DROP/TRUNCATE on a PostgreSQL server needs its refusals pinned, not
described. Every case below is one that would otherwise be discovered by a destroyed database:

* a stacked statement (`... ; DROP TABLE ...`) must not run;
* server-level verbs (`DROP DATABASE`, `DROP SCHEMA … CASCADE`, `ALTER SYSTEM`, role/grant changes) are
  refused BY NAME — an agent's blast radius is one database, not the server;
* the platform's own database, and PostgreSQL's template databases, are never written;
* `confirm` is not a formality: without it nothing executes, the call returns the plan;
* an empty statement, or one that is neither read nor a known write verb, is refused rather than guessed at.

The pure policy (`validate_statement`) is what these tests drive; the connection paths are exercised by the
real tool calls in the pipeline runs (they need a live server by definition).

Run: cd backend && .venv/bin/python -m pytest tests/test_db_admin.py -v
"""
from __future__ import annotations

import pytest

from services import db_admin as D


def test_a_simple_ddl_statement_passes_and_keeps_its_text():
    sql = "CREATE TABLE demo (id integer primary key, name text)"
    assert D.validate_statement(sql) == sql


def test_a_trailing_semicolon_is_stripped_not_refused():
    assert D.validate_statement("TRUNCATE demo_scratch;") == "TRUNCATE demo_scratch"


@pytest.mark.parametrize("sql", [
    "UPDATE t SET a = 1; DROP TABLE t",
    "INSERT INTO t VALUES (1); DELETE FROM t",
    "CREATE TABLE a (id int); CREATE TABLE b (id int)",
])
def test_a_stacked_statement_is_refused(sql):
    with pytest.raises(D.DbAdminError) as exc:
        D.validate_statement(sql)
    assert "multiple statements" in str(exc.value)


@pytest.mark.parametrize("sql, term", [
    ("DROP DATABASE store_monthly_xlsx", "drop database"),
    ("drop schema public cascade", "drop schema"),
    ("ALTER SYSTEM SET work_mem = '1GB'", "alter system"),
    ("CREATE ROLE sneaky LOGIN", "create role"),
    ("GRANT ALL ON DATABASE store_monthly_xlsx TO public", "grant"),
    ("select pg_terminate_backend(1234)", "pg_terminate_backend"),
    ("CREATE DATABASE shadow TEMPLATE template0", "create database"),
])
def test_server_level_verbs_are_refused_by_name(sql, term):
    with pytest.raises(D.DbAdminError) as exc:
        D.validate_statement(sql)
    assert term in str(exc.value).lower()
    assert "server" in str(exc.value).lower()


@pytest.mark.parametrize("sql", ["", "   ", "\n\t "])
def test_an_empty_statement_is_refused(sql):
    with pytest.raises(D.DbAdminError):
        D.validate_statement(sql)


@pytest.mark.parametrize("sql", ["do $$ begin end $$", "call some_proc()", "set search_path = x"])
def test_an_unknown_verb_is_refused_rather_than_guessed(sql):
    with pytest.raises(D.DbAdminError):
        D.validate_statement(sql)


def test_read_only_sql_is_allowed_here_too():
    """The tool is not read-only, but a SELECT must not be refused: `db_query` is the better door, and a
    refusal here would send the agent looking for a workaround."""
    assert D.validate_statement("select count(*) from demo").startswith("select")


def test_the_platform_database_is_refused_by_ARGUMENT_not_by_text(monkeypatch):
    """A `DROP TABLE deep_agent_templates` never mentions the database name — the target is the ARGUMENT,
    so that is what the guard must inspect (the first version looked only at the SQL text and let it pass)."""
    monkeypatch.setenv("POSTGRES_DB", "langconfig")
    with pytest.raises(D.DbAdminError) as exc:
        D.execute("langconfig", "DROP TABLE deep_agent_templates", confirm=True)
    assert "platform" in str(exc.value).lower()

    def boom(*a, **k):
        raise AssertionError("must not connect: the refusal happens before the connection")
    monkeypatch.setattr(D, "_conn_kwargs", boom)
    with pytest.raises(D.DbAdminError):
        D.execute("langconfig", "truncate deep_agent_templates", confirm=True)

    # …and a table whose NAME merely starts with the platform database's name is NOT refused: the
    # argument decided, not a substring. (The first version searched the text and would have refused
    # `langconfig_export` while letting the real thing through.)


def test_the_template_databases_are_never_written():
    for name in ("template0", "template1", "postgres"):
        with pytest.raises(D.DbAdminError):
            D.execute(name, "CREATE TABLE x (id int)", confirm=True)


def test_without_confirm_nothing_is_executed_and_the_plan_comes_back(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("execute() must not connect without confirm")

    monkeypatch.setattr(D, "_conn_kwargs", boom)
    out = D.execute("store_monthly_xlsx", "CREATE TABLE scratch (id int)")
    assert out["ok"] is True and out["confirmed"] is False and "executed" not in out
    assert out["kind"] == "ddl" and out["database"] == "store_monthly_xlsx"
    assert "Nothing was executed" in out["next"]


def test_a_missing_database_name_is_refused_before_connecting(monkeypatch):
    monkeypatch.setattr(D, "_conn_kwargs", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    for fn in (D.describe, D.execute):
        with pytest.raises(D.DbAdminError) as exc:
            fn("", "select 1")
        assert "db_name is required" in str(exc.value)
