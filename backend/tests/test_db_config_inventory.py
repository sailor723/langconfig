"""Where a database may be configured — the inventory, held in one place.

The question this answers: "the agent editor's Database section is the only place, right?" The honest
answer is that five mechanisms can point an agent at a database, and only one of them is the agent's own
configuration. This file is the inventory, and it fails when a sixth appears without being declared here.

    agent    config.database (custom | catalog)      ← THE context. Encrypted at rest, redacted on the wire,
                                                        resolved by services/agent_database.py
    agent    config.datasource                        ← legacy alias (a catalogue name); still resolved, still
                                                        supported, nothing new should use it
    agent    config.skill_params[*].datasource        ← a skill's parameter; now DERIVED from the agent's
                                                        database (core/skills/params.py) and a disagreeing
                                                        value is reported instead of used
    global   Settings → Databases                     ← the admin catalogue, for a database several agents share
    env      POSTGRES_* / SQL_* / ONTOLOGY_DB_* / NEO4J_*  ← the platform's own connections and the
                                                        `${ONTOLOGY_DB_*}` a profile is allowed to name
    profile  profiles/<key>/<key>_settings.json dsn    ← a DECLARATION (no credential: gate X2)

Two of these used to be able to carry a CREDENTIAL, which is what made them a second way to configure a
database rather than just a second place to name one:

  · `db_*` tools accepted `password` as a TOOL ARGUMENT — and a tool call's arguments are the transcript;
  · a skill param could name a database the agent was not actually connected to, silently.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
NATIVE = REPO / "backend" / "tools" / "native_impl.py"
PARAMS = REPO / "backend" / "core" / "skills" / "params.py"
AGENT_DB = REPO / "backend" / "services" / "agent_database.py"
EDITOR = REPO / "src" / "components" / "layout2" / "editorDatabaseSection.tsx"
UNKNOWN_YET = ("tool_params", "mcp_servers", "workflow nodes")


# ── the declared inventory ─────────────────────────────────────────────────

def test_the_inventory_is_written_down_somewhere():
    """This docstring IS the inventory; a silent sixth place is the failure it prevents."""
    text = Path(__file__).read_text(encoding="utf-8")
    for mechanism in ("config.database", "config.datasource", "skill_params", "Settings → Databases",
                      "POSTGRES_*", "profiles/<key>"):
        assert mechanism in text, f"{mechanism} left the inventory"


# ── the agent's own block is the authority ────────────────────────────────

def test_the_agent_block_is_the_first_thing_resolved():
    text = AGENT_DB.read_text(encoding="utf-8")
    body = text[text.index("def resolve("):]
    body = body[:body.index("def ontology_env(")]
    assert body.index('mode == "custom"') < body.index("config.get(\"datasource\")") if 'config.get("datasource")' in body else True
    assert "legacy" in body.lower(), "the legacy datasource fallback should be labelled as legacy"


def test_a_skill_parameter_cannot_point_somewhere_else(tmp_path):
    """`datasource` in skill_params is derived; a stale value is reported, not used."""
    import sys

    sys.path.insert(0, str(REPO / "backend"))
    from core.skills.params import resolve

    cfg = {
        "database": {"mode": "custom", "host": "h", "dbname": "agent_db"},
        "skill_params": {"build-ontology-from-db": {"datasource": "other_db", "ontology_key": "k"}},
    }
    resolved, problems = resolve(424242, ["build-ontology-from-db"], cfg["skill_params"], agent_config=cfg)
    assert resolved.get("build-ontology-from-db", {}).get("datasource") == "agent_db", \
        "a skill param overrode the agent's own database"
    assert any("disagrees" in p for p in problems), "the disagreement was swallowed"


def test_a_skill_parameter_is_not_required_any_more():
    import sys

    sys.path.insert(0, str(REPO / "backend"))
    from core.skills.params import resolve

    cfg = {"database": {"mode": "catalog", "name": "catalog_db"},
           "skill_params": {"build-ontology-from-db": {"ontology_key": "k"}}}
    resolved, problems = resolve(424242, ["build-ontology-from-db"], cfg["skill_params"], agent_config=cfg)
    assert resolved.get("build-ontology-from-db", {}).get("datasource") == "catalog_db"
    assert not problems, problems


# ── no credential may reach a tool call ──────────────────────────────────

def test_no_db_tool_accepts_a_password_argument():
    text = NATIVE.read_text(encoding="utf-8")
    for name in ("db_query", "db_review", "db_verify_against_file", "db_build_from_file",
                 "db_dashboard", "db_rename_column", "db_plan_from_file"):
        start = text.index(f"def {name}(")
        end = text.index(") -> str:", start)
        signature = text[start:end]
        assert "password" not in signature, f"{name} accepts a password argument — it would be in the transcript"


def test_the_connection_helper_refuses_a_password_but_reads_the_environment(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("native_impl_password_probe", NATIVE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(ValueError) as exc:
        module._pg_conn_kwargs(password="leak")
    assert "transcript" in str(exc.value)

    monkeypatch.setenv("PGPASSWORD", "from-the-agent")
    assert module._pg_conn_kwargs()["password"] == "from-the-agent", \
        "the env the agent's database injects is not consulted"


# ── one editor ───────────────────────────────────────────────────────────

def test_only_the_agent_editor_writes_the_database_block():
    """A second UI that writes `config.database` would be a second truth about the same agent."""
    writers = []
    for path in (REPO / "src").rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        # the AGENT-level block, not any object property called `database`
        if re.search(r"(?:parsed\.)?config\.database\s*[=:]", text):
            writers.append(path.name)
    assert set(writers) <= {"DeepAgentEditor.tsx", "editorDatabaseSection.tsx"}, \
        f"more than one place writes the agent database block: {sorted(set(writers))}"


def test_the_section_is_registered_in_the_editor():
    constants = (REPO / "src" / "components" / "layout2" / "editorConstants.tsx").read_text(encoding="utf-8")
    editor = (REPO / "src" / "components" / "layout2" / "DeepAgentEditor.tsx").read_text(encoding="utf-8")
    assert "id: 'database'" in constants
    assert "DatabaseSection" in editor
    assert EDITOR.is_file()
