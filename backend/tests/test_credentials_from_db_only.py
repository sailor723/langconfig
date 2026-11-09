"""PostgreSQL is the ONLY source of provider credentials.

The rule, in one line: **no API key is read from ``.env`` or the shell.** Keys
live encrypted in the ``models`` settings document and are resolved through
``config.get_api_key_from_db``. Before this was enforced the codebase read them
from four different places depending on which path you asked, which produced a
genuinely confusing failure: the Settings "Test" button went green from a ``.env``
value while every agent failed on a missing key.

These tests pin the rule where it is cheap to check — the config surface and the
resolution helpers — plus a source scan for the one pattern that regresses
silently (``os.getenv("<PROVIDER>_API_KEY")`` in runtime modules).
"""

from __future__ import annotations

import pathlib
import re

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]


# ── the config surface has no credential fields at all ───────────────────────

def test_settings_model_declares_no_api_key_fields():
    from config import settings

    fields = type(settings).model_fields
    offenders = [f for f in fields if f.endswith("_api_key")]
    assert offenders == [], (
        "Settings must not declare provider credential fields — a field here "
        f"gives .env a second source of truth: {offenders}"
    )


def test_db_key_helper_is_the_accessor():
    import config

    assert callable(config.get_api_key_from_db)
    # it reads the database, so with no argument it cannot invent a value
    assert config.get_api_key_from_db("definitely_not_a_real_key_field") is None


def test_env_credentials_are_reported_not_loaded(monkeypatch):
    """A stray key in the environment is named, and nothing else happens."""
    from config import settings

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-should-be-ignored")
    names = settings.env_only_credentials()
    assert "deepseek_api_key" in names
    # …and it is still not readable as a credential
    assert not hasattr(settings, "deepseek_api_key")


# ── the resolvers agree with each other ──────────────────────────────────────

def test_settings_test_path_matches_the_agent_path():
    """The Settings 'Test' button must resolve what an agent resolves."""
    from config import get_api_key_from_db
    from db.database import SessionLocal
    from api.system.settings import _resolve_api_key

    db = SessionLocal()
    try:
        for provider, field in (("deepseek", "deepseek_api_key"),
                                ("openai", "openai_api_key")):
            assert _resolve_api_key(db, provider) == get_api_key_from_db(field), provider
    finally:
        db.close()


def test_test_path_ignores_the_environment(monkeypatch):
    from db.database import SessionLocal
    from api.system.settings import _resolve_api_key

    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-environment")
    monkeypatch.setenv("openai_api_key", "sk-from-the-environment")
    db = SessionLocal()
    try:
        # no OpenAI key in the DB on a clean checkout, so the answer is None —
        # never the environment value
        assert _resolve_api_key(db, "openai") != "sk-from-the-environment"
    finally:
        db.close()


def test_onboarding_key_detection_ignores_the_environment(monkeypatch):
    from db.database import SessionLocal
    from api.system.settings import _has_any_chat_api_key

    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-environment")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-the-environment")
    db = SessionLocal()
    try:
        doc_keys = (__import__("core.settings.store", fromlist=["x"])
                    .get_document(db, "models").get("api_keys") or {})
        expected = any(v for v in doc_keys.values())
        assert _has_any_chat_api_key(db) is expected
    finally:
        db.close()


# ── no runtime module reads a provider key from the environment ─────────────

# Generated code emitted for *exported* standalone apps legitimately reads env:
# it runs outside LangConfig, where a .env file IS the credential store. The
# codegen package exists to emit exactly that, so it is exempt by nature.
EXEMPT: set[str] = set()   # the retired exporter that used to be exempt here is deleted
EXEMPT_DIRS = {
    "core/codegen",                            # generates exported apps
}

PROVIDER_KEY_RE = re.compile(
    r"""os\.(?:getenv|environ(?:\.get)?)\s*[\(\[]\s*["']"""      # os.getenv(" / os.environ["
    r"""(?:[A-Z0-9_]+_API_KEY)["']""",                          # OPENAI_API_KEY
)

SCAN_DIRS = ("api", "core", "services", "tools")


def test_no_runtime_module_reads_a_provider_key_from_env():
    offenders: list[str] = []
    for d in SCAN_DIRS:
        for path in (BACKEND / d).rglob("*.py"):
            rel = path.relative_to(BACKEND).as_posix()
            if rel in EXEMPT or "__pycache__" in rel:
                continue
            if any(rel.startswith(d + "/") for d in EXEMPT_DIRS):
                continue
            in_doc = False
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            ):
                # Text inside a triple-quoted block is a CODE TEMPLATE for the
                # exported standalone app, not runtime code (api/agents/
                # deep_agents.py holds both kinds in one file).
                if line.count('"""') % 2 == 1:
                    in_doc = not in_doc
                    continue
                if in_doc:
                    continue
                if not PROVIDER_KEY_RE.search(line):
                    continue
                if line.strip()[:1] in ("'", '"'):
                    continue
                offenders.append(f"{rel}:{lineno}: {line.strip()[:90]}")
    assert offenders == [], (
        "provider keys must come from the database, not the environment:\n  "
        + "\n  ".join(offenders)
    )


# ── the env templates carry no provider credentials ─────────────────────────

@pytest.mark.parametrize("template", ["../env_example", ".env.example"])
def test_env_templates_hold_no_provider_keys(template):
    path = (BACKEND / template).resolve()
    if not path.exists():
        pytest.skip(f"{template} not present")
    body = path.read_text(encoding="utf-8", errors="ignore")
    hits = [
        line.strip()
        for line in body.splitlines()
        if re.match(r"^\s*[A-Z0-9_]*_API_KEY\s*=\s*\S", line)
        and not line.strip().startswith("#")
        # the Fernet master key is infrastructure, not a provider credential
        and "API_KEY_ENCRYPTION_KEY" not in line
    ]
    assert hits == [], f"{template} must not carry provider keys: {hits}"
