"""Registering an ontology whose database is NOT the platform's own.

Measured 2026-11-25: TPC-H's SF0.1 database runs on a SECOND local Postgres (:5432, role
`weiping`) while this deployment's ontology database is :5433 / role `langconfig`. The
registration probe only ever tried the platform credentials, so it refused a database that was
answering fine — and because a refusal here is what stops a build, the only workaround would
have been to point the whole platform at a different server.

What these tests hold:

* a skeleton with no `dsn` keeps the platform template (`${ONTOLOGY_DB_*}`) — the common case;
* a skeleton with a `dsn` carries it verbatim (plus the database name), so the build reads the
  server the registration was told about;
* `register()` probes THAT dsn, so a wrong server is refused by name instead of producing an
  empty ontology that looks like thin data.

No database is required: the refusal case uses a port nothing listens on.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services import ontology_register as reg  # noqa: E402


def test_skeleton_without_dsn_keeps_the_platform_template():
    sk = reg._profile_skeleton("probe_v1", "some_db", "主题", note="unit")
    assert sk["dsn"]["host"] == "${ONTOLOGY_DB_HOST:-127.0.0.1}"
    assert sk["dsn"]["dbname"] == "some_db"


def test_skeleton_with_dsn_carries_the_declared_server():
    dsn = {"host": "${TPCH_DB_HOST:-127.0.0.1}", "port": "${TPCH_DB_PORT:-5432}",
           "user": "${TPCH_DB_USER:-weiping}", "password": "${TPCH_DB_PASSWORD}"}
    sk = reg._profile_skeleton("probe_v1", "tpch", "主题", note="unit", dsn=dsn)
    assert sk["dsn"]["port"] == "${TPCH_DB_PORT:-5432}"
    assert sk["dsn"]["user"] == "${TPCH_DB_USER:-weiping}"
    # the database always comes from the caller, never from the connection block
    assert sk["dsn"]["dbname"] == "tpch"
    assert dsn.get("dbname") is None, "the caller's dict must not be mutated"


def test_register_probes_the_declared_dsn_and_names_the_failure():
    # 5999 is not a Postgres here; the point is that the message quotes a refusal, not a traceback.
    with pytest.raises(reg.RegisterError) as exc:
        reg.register("probe_dsn_case", "tpch",
                     dsn={"host": "127.0.0.1", "port": "5999", "user": "nobody", "password": "x"},
                     probe=True)
    assert "does not answer" in str(exc.value)
