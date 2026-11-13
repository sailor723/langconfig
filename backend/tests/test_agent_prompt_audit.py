"""The prompt audit must catch the defects it was written for — and not invent others.

Three real defects on this instance, all found by reading a prompt rather than by a test:

1. agent 379's dsn example was **two examples glued at an edit** — `…"password": "${MEETING_V1_DB_PASSWORD}"}`,
   "port": "${ONTOLOGY_DB_PORT:-5432}", … "user": "${ONTOLOGY_DB_USER:-weiping}", "password": ""}`.
   Two ports, two users, a trailing literal `""`, and not valid JSON. Whatever the agent copied out of it
   would not connect.
2. agent 378's dsn named `dbname: "sunhing"` while the database (and the installed profile) is
   `sunhing_kpi` — right shape, wrong target.
3. 39 agents had a machine tail baked **into `agent_docs["AGENTS.md"]`**: `## Identity`, the workspace
   boundary block, and a nested copy of the document itself, re-injected on every turn.

The parser is the part that has to be right: every dsn this platform writes contains `${VAR:-default}`,
so a regex that stops at the first `}` truncates the object and reports "not valid JSON" about a
perfectly good line. That bug was in the first version of the audit and flagged four correct agents.
"""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AUDIT = REPO / "backend" / "scripts" / "audit_agent_prompts.py"
SEED = REPO / "backend" / "scripts" / "seeds" / "in" / "seed_ontology_build_agent.py"

GOOD_DSN = ('"dsn": {"host": "${ONTOLOGY_DB_HOST:-127.0.0.1}", "port": '
            '"${ONTOLOGY_DB_PORT:-5432}", "dbname": "meeting_hub", "user": '
            '"${ONTOLOGY_DB_USER:-weiping}", "password": "${MEETING_V1_DB_PASSWORD}"}')
#: verbatim from agent 379 before the repair
GLUED_DSN = ('"dsn": {"host": "${ONTOLOGY_DB_HOST:-127.0.0.1}", "port": '
             '"${ONTOLOGY_DB_PORT:-5433}", "dbname": "meeting_hub", "user": '
             '"${ONTOLOGY_DB_USER:-langconfig}", "password": "${MEETING_V1_DB_PASSWORD}"}", "port": '
             '"${ONTOLOGY_DB_PORT:-5432}", "dbname": "meeting_hub", "user": '
             '"${ONTOLOGY_DB_USER:-weiping}", "password": ""}')


def _audit_module():
    spec = importlib.util.spec_from_file_location("audit_agent_prompts", AUDIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_the_dsn_parser_keeps_variable_defaults_inside_the_object():
    blocks = _audit_module().find_dsn_blocks("写这一行：\n  `" + GOOD_DSN + "`\n")
    assert len(blocks) == 1, blocks
    assert blocks[0].count('"password"') == 1, blocks[0]
    assert blocks[0].endswith("}"), blocks[0]


def test_a_glued_dsn_is_a_failure_named_as_such():
    fails, _notes = _audit_module().audit({"system_prompt": "x\n  `" + GLUED_DSN + "`\n"})
    joined = "\n".join(fails)
    assert "粘在一起" in joined, fails
    assert "5433" in joined and "5432" in joined, joined


def test_a_literal_password_is_a_failure_but_an_empty_one_is_the_deployment():
    module = _audit_module()
    secret = GOOD_DSN.replace('"${MEETING_V1_DB_PASSWORD}"', '"hunter2"')
    fails, _ = module.audit({"system_prompt": "`" + secret + "`"})
    assert any("字面量口令" in f for f in fails), fails
    empty = GOOD_DSN.replace('"${MEETING_V1_DB_PASSWORD}"', '""')
    fails, _ = module.audit({"system_prompt": "`" + empty + "`"})
    assert not any("字面量口令" in f for f in fails), fails


def test_a_prompt_that_disagrees_with_the_installed_profile_fails():
    """The check that would have caught 378 before anyone ran it."""
    fails, _ = _audit_module().audit({
        "system_prompt": "`" + GOOD_DSN.replace('"meeting_hub"', '"sunhing"') + "`",
        "skill_params": {"build-ontology-from-db": {"ontology_key": "sunhing_v1"}},
    })
    assert any("dbname" in f and "sunhing_kpi" in f for f in fails), fails


def test_a_tail_baked_into_the_instruction_document_is_a_failure():
    docs = {"AGENTS.md": "# 三条提醒\n\n1. 停两次\n\n## Identity\n\n- **Agent ID**: 348\n\n"
                        "## AGENTS.md (embedded)\n\n# 三条提醒\n"}
    fails, _ = _audit_module().audit({"system_prompt": "body"}, docs)
    assert any("agent_docs[AGENTS.md]" in f for f in fails), fails


def test_stripping_a_document_tail_keeps_what_the_author_wrote():
    module = _audit_module()
    original = "# Ontology Builder (clinic)\n\n1. 停两次\n2. 拒绝清单是交付物\n"
    polluted = original + "\n## Identity\n\n- **Agent ID**: 348\n"
    assert module.strip_doc_tail(polluted).strip() == original.strip()


def test_the_seed_puts_the_database_name_in_the_dsn_example():
    """`datasource` is the registration key; the dsn needs the DATABASE name (sunhing_kpi)."""
    text = SEED.read_text(encoding="utf-8")
    assert 'DATASOURCE_DB = os.environ.get("DATASOURCE_DB")' in text
    assert '"dbname": "{DATASOURCE_DB}"' in text, "the dsn example is back on the datasource key"
    assert '"dbname": "{DATASOURCE}"' not in text


def test_the_seed_reads_deployment_defaults_from_the_installed_profile(monkeypatch):
    """sunhing_kpi is on 5433/langconfig, meeting_hub on 5432/weiping — one global default is wrong.

    The seed used to take DSN_PORT/DSN_USER from the environment with a single fallback, so a
    builder for the 5433 database taught `port: 5432` and the mismatch only surfaced when someone
    asked a number. The installed profile is the authority; env still wins for a brand-new key.
    """
    import importlib.util

    monkeypatch.setenv("ONTOLOGY_KEY", "sunhing_v1")
    monkeypatch.setenv("DATASOURCE", "sunhing")
    monkeypatch.setenv("DATASOURCE_DB", "sunhing_kpi")
    monkeypatch.delenv("DSN_PORT", raising=False)
    monkeypatch.delenv("DSN_USER", raising=False)
    monkeypatch.delenv("DSN_PASSWORD_VAR", raising=False)

    spec = importlib.util.spec_from_file_location("seed_profile_defaults", SEED)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert (module.DSN_PORT, module.DSN_USER) == ("5433", "langconfig"), \
        "the seed ignored the installed profile's dsn — it will teach a dsn that cannot connect"
    assert '"dbname": "sunhing_kpi"' in module.SYSTEM_PROMPT
