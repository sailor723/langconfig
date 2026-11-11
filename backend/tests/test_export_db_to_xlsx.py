"""`scripts/export_db_to_xlsx.py` — the parts that can be wrong without a database.

The export itself needs a live Postgres, so these tests cover what makes it safe and
reproducible: the `${ENV:-default}` expansion the ontology profiles rely on, the
"unknown profile" message (it should name the profiles that DO exist), and the
read-only guarantee, which is a property of the source rather than of any output.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "export_db_to_xlsx.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("export_db_to_xlsx", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    if not SCRIPT.is_file():
        pytest.skip("export script not present")
    return _load_script()


# ── placeholder expansion ────────────────────────────────────────────────────

def test_expansion_uses_the_default_when_the_variable_is_unset(script, monkeypatch):
    monkeypatch.delenv("ONTOLOGY_DB_PORT", raising=False)
    assert script.expand_placeholders("${ONTOLOGY_DB_PORT:-15432}") == "15432"


def test_expansion_prefers_the_environment(script, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_DB_HOST", "pg.internal")
    assert script.expand_placeholders("${ONTOLOGY_DB_HOST:-127.0.0.1}") == "pg.internal"


def test_expansion_leaves_plain_values_alone(script):
    assert script.expand_placeholders("retail_db") == "retail_db"
    assert script.expand_placeholders(5432) == 5432


def test_an_empty_default_is_allowed(script, monkeypatch):
    monkeypatch.delenv("NEVER_SET_THIS", raising=False)
    assert script.expand_placeholders("${NEVER_SET_THIS:-}") == ""


# ── the profile loader ──────────────────────────────────────────────────────

def test_unknown_profile_names_the_ones_that_exist(script, capsys):
    with pytest.raises(SystemExit) as exc:
        script.load_profile_dsn("no-such-profile")
    message = str(exc.value)
    assert "no-such-profile" in message
    assert "retail" in message, "the error should list the real profiles, not just complain"


def test_the_retail_profile_resolves_to_a_connectable_shape(script, monkeypatch):
    monkeypatch.delenv("ONTOLOGY_DB_PORT", raising=False)
    monkeypatch.delenv("ONTOLOGY_DB_HOST", raising=False)
    dsn = script.load_profile_dsn("retail")
    assert dsn["dbname"] == "retail_db"
    assert dsn["user"] == "postgres"
    assert dsn["port"] == 15432, "port must come from the profile default, as an int"
    assert isinstance(dsn["port"], int)


# ── the read-only contract ──────────────────────────────────────────────────

def test_the_script_opens_the_session_read_only():
    """A dump tool that can write is one typo away from changing its source."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set_session(readonly=True" in text
    # Every statement it builds from a table name quotes that identifier.
    assert text.count('select count(*) as n from "{table}"') == 1
    assert text.count('select * from "{table}"') == 1
