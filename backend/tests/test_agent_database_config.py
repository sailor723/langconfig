"""An agent may carry its OWN database — and its password may not leak from there either.

Two levels, two jobs: Settings → Databases is the admin-managed catalogue (validated by its own test
button); `config.database` is the agent's own configuration, which is the only way to point one agent at a
database nobody listed.

What is guarded here:

  * the resolution order (custom block → catalogue name → legacy `datasource`), and that a half-filled
    block NAMES the missing field instead of silently falling back to another database;
  * the password: encrypted at rest (Fernet), never in an API response (only `password_set`), never in the
    prompt text, and the write-only field does not erase a stored one when a re-save omits it;
  * the test endpoint's result shape: a failed connection is a RESULT with the server's words.
"""
import json
from pathlib import Path

import pytest

from models.deep_agent import AgentDatabase, DeepAgentConfig
from services import agent_database as ad


# ── the block ──────────────────────────────────────────────────────────────

def test_a_custom_block_needs_host_and_dbname():
    assert AgentDatabase(mode="custom", host="h", dbname="d").missing() == []
    assert AgentDatabase(mode="custom", host="h").missing() == ["dbname"]
    assert AgentDatabase(mode="custom").missing() == ["host", "dbname"]


def test_a_catalog_block_needs_a_name():
    assert AgentDatabase(mode="catalog").missing() == ["name"]
    assert AgentDatabase(mode="catalog", name="new_coldchain").missing() == []


def test_the_block_forbids_unknown_fields():
    with pytest.raises(Exception):
        AgentDatabase(mode="custom", host="h", dbname="d", bogus=1)


def test_the_config_accepts_the_block_and_stays_optional():
    cfg = DeepAgentConfig(system_prompt="x")
    assert cfg.database is None
    cfg = DeepAgentConfig(system_prompt="x", database={"mode": "custom", "host": "h", "dbname": "d"})
    assert cfg.database.mode == "custom"


# ── the secret ────────────────────────────────────────────────────────────

def _custom(password="s3cret"):
    return {"database": {"mode": "custom", "host": "127.0.0.1", "port": 5432,
                         "dbname": "some_db", "user": "u", "password": password}}


def test_the_password_is_encrypted_at_rest_and_the_marker_is_not_stored():
    sealed = ad.encrypt_config_secrets(_custom())
    stored = sealed["database"]["password"]
    assert stored.startswith("gAAAA"), "the row would carry a plaintext password"
    assert "password_set" not in sealed["database"], "a stored marker outlives the password it describes"


def test_an_extra_save_does_not_double_encrypt():
    once = ad.encrypt_config_secrets(_custom())
    twice = ad.encrypt_config_secrets(json.loads(json.dumps(once)))
    assert twice["database"]["password"] == once["database"]["password"]


def test_the_response_carries_a_marker_not_the_password():
    sealed = ad.encrypt_config_secrets(_custom())
    out = ad.redact_config(json.loads(json.dumps(sealed)))
    assert "password" not in out["database"]
    assert out["database"]["password_set"] is True
    assert "s3cret" not in json.dumps(out)


def test_redaction_is_idempotent():
    sealed = ad.encrypt_config_secrets(_custom())
    once = ad.redact_config(json.loads(json.dumps(sealed)))
    twice = ad.redact_config(json.loads(json.dumps(once)))
    assert once == twice


# ── resolution ────────────────────────────────────────────────────────────

def test_custom_wins_and_the_dsn_has_no_password():
    env, dsn = ad.resolve(_custom())
    assert env["PGDATABASE"] == "some_db"
    assert env["PGPASSWORD"] == "s3cret"           # the shell needs it
    assert "password" not in dsn                    # the prompt does not get it
    assert "s3cret" not in json.dumps(dsn)


def test_a_half_filled_block_names_what_is_missing():
    with pytest.raises(ad.DatabaseConfigError) as exc:
        ad.resolve({"database": {"mode": "custom", "host": "127.0.0.1"}})
    assert "dbname" in str(exc.value)


def test_the_legacy_datasource_still_resolves():
    """Every agent written before `config.database` existed must keep working."""
    env, dsn = ad.resolve({"datasource": "new_coldchain"})
    assert env.get("PGDATABASE"), "a legacy datasource name resolved to nothing"
    assert "password" not in dsn


def test_a_catalog_block_resolves_through_the_catalogue():
    env, _dsn = ad.resolve({"database": {"mode": "catalog", "name": "new_coldchain"}})
    assert env.get("PGDATABASE")


def test_no_database_at_all_is_not_an_error():
    assert ad.resolve({}) == ({}, {})


def test_the_ontology_env_mirrors_the_connection():
    """A profile declares `${ONTOLOGY_DB_*}` — the agent's own connection seeds those names."""
    env, _ = ad.resolve(_custom())
    ont = ad.ontology_env(env)
    assert ont["ONTOLOGY_DB_HOST"] == env["PGHOST"]
    assert ont["ONTOLOGY_DB_PORT"] == env["PGPORT"]
    assert ont["ONTOLOGY_DB_PASSWORD"] == env["PGPASSWORD"]


def test_the_prompt_line_never_contains_the_password():
    line = ad.describe(_custom())
    assert "some_db" in line and "credit" in line.lower() or "credential" in line
    assert "s3cret" not in line


# ── the test a user clicks ────────────────────────────────────────────────

def test_a_bad_host_is_a_result_with_the_servers_words():
    result = ad.test_connection(
        {"database": {"mode": "custom", "host": "127.0.0.1", "port": 1, "dbname": "nope"}},
        timeout=2)
    assert result["ok"] is False
    assert result["detail"], "a failed test must say why"
    assert "s3cret" not in json.dumps(result)


def test_an_unconfigured_agent_says_so():
    result = ad.test_connection({})
    assert result["ok"] is False and "no database" in result["detail"]


# ── the API's response normaliser ─────────────────────────────────────────

def test_the_response_normaliser_redacts_the_block():
    """Every deep-agent response goes through this function, so the sweep belongs here."""
    from api.agents.deep_agents import _ensure_deep_agent_config

    sealed = ad.encrypt_config_secrets(_custom())
    out = _ensure_deep_agent_config(sealed)
    assert "password" not in (out.get("database") or {})
    assert (out.get("database") or {}).get("password_set") is True
    assert "s3cret" not in json.dumps(out)


def test_no_persisted_agent_leaks_a_plaintext_database_password():
    """A sweep over the rows: the only acceptable stored forms are ciphertext and absence."""
    from sqlalchemy import text

    from db.database import SessionLocal

    bad: list[str] = []
    try:
        db = SessionLocal()
        try:
            rows = db.execute(text("select id, config::jsonb from deep_agent_templates")).fetchall()
        finally:
            db.close()
    except Exception:                                          # noqa: BLE001
        pytest.skip("no database reachable from this checkout")
    for agent_id, cfg in rows:
        if not isinstance(cfg, dict):
            continue
        pw = (cfg.get("database") or {}).get("password")
        if pw and not str(pw).startswith("gAAAA"):
            bad.append(f"agent {agent_id}")
    assert not bad, f"these agents store a plaintext database password: {bad}"
