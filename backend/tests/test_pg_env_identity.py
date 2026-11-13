"""libpq and the ontology path must agree about who is connecting.

Measured on ECS (2026-11-13, agent 379): the sandbox carried PGHOST/PGPORT/PGDATABASE plus all four
`ONTOLOGY_DB_*` values but no PGUSER/PGPASSWORD, so `psql` fell back to the OS account:

    psql: error: connection to server at "127.0.0.1", port 5432 failed: fe_sendauth: no password
    supplied … Password for user root:

while the agent's psycopg2 route (which reads ONTOLOGY_DB_*) worked. Two connection paths that
disagree about the identity is a platform defect: the agent reads it as "the database is down".
"""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ASSEMBLY = REPO / "backend" / "services" / "deepagent_factory" / "assembly.py"


def _fn():
    text = ASSEMBLY.read_text(encoding="utf-8")
    start = text.index("def _ensure_pg_identity")
    end = text.index("def _datasource_env")
    scope = {"dict": dict}
    exec(compile(text[start:end], str(ASSEMBLY), "exec"), scope)   # noqa: S102 — a pure helper
    return scope["_ensure_pg_identity"]


def test_libpq_identity_is_filled_from_the_ontology_copy():
    fn = _fn()
    env = fn({"PGHOST": "127.0.0.1", "PGPORT": "5432", "PGDATABASE": "meeting_hub",
              "ONTOLOGY_DB_USER": "langconfig", "ONTOLOGY_DB_PASSWORD": "s3cret"})
    assert env["PGUSER"] == "langconfig"
    assert env["PGPASSWORD"] == "s3cret"


def test_an_explicit_libpq_identity_is_never_overwritten():
    fn = _fn()
    env = fn({"PGUSER": "reader", "PGPASSWORD": "own",
              "ONTOLOGY_DB_USER": "langconfig", "ONTOLOGY_DB_PASSWORD": "s3cret"})
    assert (env["PGUSER"], env["PGPASSWORD"]) == ("reader", "own")


def test_nothing_is_invented_when_the_ontology_values_are_absent():
    fn = _fn()
    env = fn({"PGHOST": "127.0.0.1", "PGDATABASE": "meeting_hub"})
    assert "PGUSER" not in env and "PGPASSWORD" not in env


def test_the_assembly_actually_calls_it():
    text = ASSEMBLY.read_text(encoding="utf-8")
    assert "_ensure_pg_identity(" in text.split("def _ensure_pg_identity")[1]
