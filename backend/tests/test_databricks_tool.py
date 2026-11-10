"""`databricks_query` — the read-only guard and the unconfigured refusal.

A warehouse tool is the first place in this app where an agent can reach a *cloud* database, so the two things worth
pinning are the two that keep it safe: it refuses to run without configuration, and it refuses anything that is not a
single read-only statement. The guard mirrors `pg_query`, which had to grow a comment-stripping prefix check because
`/* */ DROP TABLE x` sails past a naive `startswith("select")`.
"""
from __future__ import annotations

import os

import pytest

from tools.native_impl import databricks_query


def _run(sql: str, **kw) -> str:
    return databricks_query.invoke({"sql": sql, **kw})


@pytest.fixture(autouse=True)
def _no_credentials(monkeypatch):
    for var in ("DATABRICKS_HOST", "DATABRICKS_HTTP_PATH", "DATABRICKS_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def test_unconfigured_is_a_loud_refusal_not_an_empty_result():
    out = _run("SELECT 1")
    assert out.startswith("❌")
    assert "DATABRICKS_HOST" in out and "DATABRICKS_HTTP_PATH" in out and "DATABRICKS_TOKEN" in out, (
        "the message should name every missing variable, or the reader has to guess")
    assert ".env" in out, "it should say where the token goes"
    assert "never paste the token" in out, "and that it does not go into a chat message"


@pytest.mark.parametrize("sql", [
    "DELETE FROM samples.tpch.orders",
    "UPDATE t SET a = 1",
    "INSERT INTO t VALUES (1)",
    "DROP TABLE samples.tpch.orders",
    "CREATE TABLE t (a int)",
    "MERGE INTO t USING s ON t.id = s.id",
])
def test_writes_are_refused_before_connecting(sql: str, monkeypatch):
    # Configure just enough to get past the missing-env check: the refusal must happen on the text, not on the network.
    monkeypatch.setenv("DATABRICKS_HOST", "example.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/abc")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    out = _run(sql)
    assert "Only SELECT / WITH / SHOW / DESCRIBE / EXPLAIN" in out, out[:120]


@pytest.mark.parametrize("sql", [
    "SELECT 1; DROP TABLE samples.tpch.orders",
    "SELECT 1;SELECT 2",
])
def test_stacked_statements_are_refused(sql: str, monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "example.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/abc")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    assert "Multiple statements" in _run(sql)


def test_a_comment_cannot_hide_a_write(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "example.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/abc")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    assert "Only SELECT / WITH / SHOW / DESCRIBE / EXPLAIN" in _run("/* health */ DROP TABLE t")


@pytest.mark.parametrize("sql", ["SELECT 1", "WITH x AS (SELECT 1) SELECT * FROM x", "SHOW CATALOGS",
                                 "DESCRIBE samples.tpch.orders", "EXPLAIN SELECT 1"])
def test_read_only_forms_get_through_the_guard(sql: str, monkeypatch):
    """These five reach the driver, so they need the network stack to fail fast.

    Measured: with a bogus host the connector retries and the run hangs past pytest's default patience, so the test
    is skipped unless `DATABRICKS_TEST_NETWORK=1`. The guard itself is covered by the four tests above, which never
    leave the process.
    """
    if os.getenv("DATABRICKS_TEST_NETWORK") != "1":
        pytest.skip("network test — set DATABRICKS_TEST_NETWORK=1 to run")
    monkeypatch.setenv("DATABRICKS_HOST", "127.0.0.1.invalid")
    monkeypatch.setenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/abc")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    out = _run(sql)
    assert "Only SELECT" not in out and "Multiple statements" not in out, out[:120]
    assert "Databricks query error" in out, "with a bogus host it should fail at the connection, not at the guard"
