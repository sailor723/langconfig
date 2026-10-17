"""Credentials never travel with a seed — in either direction.

Outbound (seed out) and inbound (seed in) are guarded independently, so a
regression on one side cannot leak on the other. Tested separately:

  1. ``export_settings.py`` drops every ``role="secret"`` field by consulting the
     settings schema — not a hand-written list of key names.
  2. ``_secretscan`` detects credential-shaped strings in the agents/tools
     artefacts (which carry user-authored prompt text and tool code), and
     ``export_baseline.py`` sweeps the whole published set.

The regression these encode: ``models.local_api_key`` is a secret one field away
from ``models.api_keys``, and the list-based strip exported it as Fernet
ciphertext — which is readable by every teammate when API_KEY_ENCRYPTION_KEY is
blank, as the team setup recommends.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SEEDS_OUT = Path(__file__).resolve().parents[1] / "scripts" / "seeds" / "out"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SEEDS_OUT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def secretscan():
    return _load("_secretscan")


# Fixtures are assembled at runtime on purpose: a literal that looks like a key
# gets a repository flagged by secret scanners (GitHub push protection included)
# even though it is fake. Nothing here is, or ever was, a real credential.
def _fake(prefix: str, n: int = 28) -> str:
    return prefix + "".join(chr(97 + (i * 7) % 26) for i in range(n))


SK_LIKE = _fake("sk-proj-")
TVLY_LIKE = _fake("tvly-", 16)
FERNET_LIKE = _fake("gAAAAA", 60) + "="
BEARER_LIKE = "Bearer " + _fake("", 30)
SLACK_LIKE = "https://hooks.slack.com/services/" + _fake("T000/B000/", 20)
DISCORD_LIKE = "https://discord.com/api/webhooks/123456789/" + _fake("", 20)
JWT_LIKE = "eyJ" + _fake("", 20) + "." + _fake("", 20) + "." + _fake("", 20)
ASSIGNED_LIKE = _fake("", 24)


def _database_name() -> str:
    from sqlalchemy.engine import make_url
    from db.database import engine
    return make_url(engine.url.render_as_string(hide_password=False)).database or ""


# These tests write settings documents (they exercise the inbound merge), so they
# are gated on a scratch database. Without this guard they silently ran against
# the developer's live DB and overwrote real values — a credential included.
requires_scratch_db = pytest.mark.skipif(
    "test" not in _database_name(),
    reason="writes settings documents; run with POSTGRES_DB=<name containing "
           "'test'> to exercise the inbound guard",
)


# ── detection ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    f'k = "{SK_LIKE}"',
    f'TAVILY="{TVLY_LIKE}"',
    f'local_api_key = "{FERNET_LIKE}"',
    f'{{"api_key": "{SK_LIKE}"}}',
    f'token: "{ASSIGNED_LIKE}"',
    f'Authorization: {BEARER_LIKE}',
    f'{SLACK_LIKE}',
    f'{DISCORD_LIKE}',
    f'auth: {JWT_LIKE}',
])
def test_detects_credentials(secretscan, text):
    assert secretscan.scan(text), f"should have been detected: {text}"


@pytest.mark.parametrize("text", [
    'api_key = os.getenv("DEEPSEEK_API_KEY")',
    'api_key: "${MY_KEY}"',
    '"api_key": "your-api-key-here"',
    '"api_key": ""',
    "reads models.api_keys per call",
    "You are a helpful agent. Use tools when needed.",
    'DEFAULT_MODEL = "deepseek-chat"',
])
def test_ignores_placeholders_and_prose(secretscan, text):
    assert secretscan.scan(text) == [], f"false positive: {text}"


def test_redaction_removes_the_value(secretscan):
    secret = SK_LIKE
    clean, findings = secretscan.redact(f'key = "{secret}"')
    assert secret not in clean
    assert secretscan.REDACTED in clean
    assert findings


def test_guard_refuses_without_redact(secretscan):
    with pytest.raises(SystemExit) as exc:
        secretscan.guard(f'key = "{SK_LIKE}"', source="probe.sql")
    assert exc.value.code == 1


def test_guard_redacts_when_asked(secretscan):
    secret = SK_LIKE
    out = secretscan.guard(f'key = "{secret}"', source="probe.sql", redact_instead=True)
    assert secret not in out


def test_guard_passes_clean_text_through(secretscan):
    text = "INSERT INTO t VALUES ('harmless');"
    assert secretscan.guard(text, source="probe.sql") == text


# ── the settings scrub ───────────────────────────────────────────────────────

def test_scrub_drops_every_secret_the_schema_declares():
    export = _load("export_settings")
    from core.settings.registry import get as get_spec
    from core.settings.secrets import secret_paths

    doc = {
        "default_model": "deepseek-chat",
        "api_keys": {"deepseek_api_key": "sk-real", "tavily_api_key": "tvly-real"},
        "local_api_key": "local-real",           # the field the list-based strip missed
    }
    clean, dropped = export.scrub("models", doc)

    assert "local_api_key" not in clean
    assert "api_keys" not in clean            # emptied, then removed
    assert clean["default_model"] == "deepseek-chat"

    # every secret path the schema knows about is gone from the output
    for path in secret_paths(get_spec("models").schema):
        node = clean
        for part in path:
            node = node.get(part) if isinstance(node, dict) else None
        assert not node, f"secret survived the scrub: {'.'.join(path)}"

    assert any("local_api_key" in d for d in dropped)


def test_scrub_keeps_machine_paths_out_of_the_seed():
    export = _load("export_settings")
    clean, dropped = export.scrub("workspace", {"workspace_path": "/home/me/ws"})
    assert "workspace_path" not in clean
    assert any("workspace_path" in d for d in dropped)


# ── inbound: seed in must refuse credentials too ─────────────────────────────

@requires_scratch_db
def test_inbound_guard_strips_a_tampered_seed(tmp_path):
    """A seed carrying keys must not write them, and must not touch ours."""
    from core.settings.team_seed import apply_team_seed
    from db.database import SessionLocal
    from core.settings import store

    marker = "team-value-from-tampered-seed"
    db = SessionLocal()
    had_row = store.row_exists(db, "models")
    before = store.get_document(db, "models") if had_row else {}
    try:
        # Start from a known "untouched" state: keep only the per-machine
        # secrets, drop every team-owned key. The three-way merge only takes a
        # team value where the existing one still equals the code default, so a
        # leftover locally-changed value from another test would (correctly)
        # be kept and this test would be asserting the wrong thing.
        store.put_document(
            db, "models",
            {k: v for k, v in before.items() if k in ("api_keys", "local_api_key")},
        )

        seed = tmp_path / "tampered.json"
        seed.write_text(
            '{"__meta__": {}, "models": {"api_keys": {"openai_api_key": "REPO-LEAK"},'
            f' "local_api_key": "REPO-LEAK-LOCAL", "default_model": "{marker}"}}}}'
        )
        result = apply_team_seed(path=seed, db=db)

        # every credential field is refused, and named
        assert result["present"] is True
        blocked = " ".join(result["blocked"])
        assert "models.api_keys.openai_api_key" in blocked
        assert "models.local_api_key" in blocked

        # the non-secret team value still lands (assert the OUTCOME — the merge's
        # internal "applied" list depends on what the DB already held)
        assert store.get_document(db, "models")["default_model"] == marker

        # and the seeded credentials were never written
        models = store.get_document(db, "models")
        assert (models.get("api_keys") or {}).get("openai_api_key") != "REPO-LEAK"
        assert models.get("local_api_key") != "REPO-LEAK-LOCAL"
    finally:
        store.put_document(db, "models", before)      # leave the DB as we found it
        db.close()


@requires_scratch_db
def test_inbound_guard_leaves_the_machines_own_keys_alone(tmp_path):
    from core.settings.team_seed import apply_team_seed
    from db.database import SessionLocal
    from core.settings import store

    db = SessionLocal()
    try:
        store.mutate(db, "models", [
            {"op": "set", "path": ["api_keys", "deepseek_api_key"], "value": "MINE"},
        ])
        seed = tmp_path / "s.json"
        seed.write_text('{"__meta__": {}, "models": {"api_keys": {"deepseek_api_key": "THEIRS"}}}')
        apply_team_seed(path=seed, db=db)
        assert store.get_document(db, "models")["api_keys"]["deepseek_api_key"] == "MINE"
    finally:
        db.close()


@requires_scratch_db
def test_clean_seed_reports_no_refusals():
    from core.settings.team_seed import apply_team_seed
    from db.database import SessionLocal

    db = SessionLocal()
    try:
        result = apply_team_seed(db=db)      # the real committed seed
        assert result["blocked"] == [], result["blocked"]
    finally:
        db.close()
