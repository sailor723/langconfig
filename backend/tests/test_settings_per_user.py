# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Per-account settings and credentials (migration 037).

Why this exists: ``settings_documents`` used to hold one row per namespace, so
every account on an instance spent the same provider keys — including the web
search keys, which are billed per query. 037 keys the row by ``(user_id, ns)``,
and the owner's row doubles as the shared layer, so:

  own value  →  shared (owner) value  →  schema default

The tests below pin the three properties that make that safe:

1. isolation — an account that sets a key never sees another account's;
2. inheritance — a field the account did not set still resolves;
3. no leakage on write — saving settings for one account must not copy the
   inherited values into its row (which would freeze the inherited key).

Requires PostgreSQL (TEST_DATABASE_URL), like the rest of the DB-backed suite.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core import settings as cs
from core.settings import store

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://langconfig:langconfig_dev@localhost:5432/langconfig_test",
)
SYNC_URL = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

OWNER = store.OWNER_USER_ID
ALICE = 284
BOB = 1070


@pytest.fixture(scope="module")
def db_session_factory():
    # Refuse to run against the application database.
    #
    # Not paranoia: an earlier version of one test in this file opened
    # `db.database.SessionLocal` instead of the test factory and wrote
    # `tavily_api_key = "tvly-shared"` into the real install's owner row. The test
    # passed, the suite stayed green, and the only visible symptom was a green
    # "configured" dot on a search provider nobody had configured. A guard at the
    # one place that builds the engine is cheaper than remembering not to.
    from db.database import DATABASE_URL as APP_DATABASE_URL

    assert SYNC_URL != APP_DATABASE_URL.replace(
        "postgresql+asyncpg://", "postgresql://"
    ), (
        "TEST_DATABASE_URL points at the application database; refusing to run "
        "these tests against live settings"
    )

    engine = create_engine(SYNC_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield Session
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_documents(db_session_factory):
    cs._reset_table_ensure()  # noqa: SLF001 — test hook
    db = db_session_factory()
    try:
        cs.ensure_table(db)
        cs.reset_documents(db)
    finally:
        db.close()
    yield
    db = db_session_factory()
    try:
        cs.reset_documents(db)
    finally:
        db.close()


def _set_key(db, user_id, key_name, value):
    return store.mutate(
        db,
        "models",
        [{"op": "set", "path": ["api_keys", key_name], "value": value}],
        user_id=user_id,
    )


def _key(db, user_id, key_name):
    _own, effective = store.get_effective_document(db, "models", user_id)
    return (effective.get("api_keys") or {}).get(key_name)


# ── isolation ────────────────────────────────────────────────────────────────

def test_an_account_key_is_not_visible_to_another(db_session_factory):
    db = db_session_factory()
    try:
        _set_key(db, ALICE, "deepseek_api_key", "sk-alice")
        _set_key(db, BOB, "deepseek_api_key", "sk-bob")

        assert _key(db, ALICE, "deepseek_api_key") == "sk-alice"
        assert _key(db, BOB, "deepseek_api_key") == "sk-bob"
        assert _key(db, OWNER, "deepseek_api_key") is None
    finally:
        db.close()


def test_the_rows_really_are_separate(db_session_factory):
    """Two accounts writing the same namespace produce two rows, not one."""
    db = db_session_factory()
    try:
        _set_key(db, ALICE, "deepseek_api_key", "sk-alice")
        _set_key(db, BOB, "deepseek_api_key", "sk-bob")
        rows = db.execute(
            text("SELECT user_id FROM settings_documents WHERE ns = 'models' ORDER BY user_id")
        ).fetchall()
        assert [r[0] for r in rows] == sorted([ALICE, BOB])
    finally:
        db.close()


# ── inheritance from the shared (owner) layer ────────────────────────────────

def test_an_unset_field_inherits_the_shared_value(db_session_factory):
    db = db_session_factory()
    try:
        _set_key(db, OWNER, "openai_api_key", "sk-shared-openai")
        _set_key(db, ALICE, "deepseek_api_key", "sk-alice")

        # Alice set one key; the other still resolves from the shared layer.
        assert _key(db, ALICE, "deepseek_api_key") == "sk-alice"
        assert _key(db, ALICE, "openai_api_key") == "sk-shared-openai"
    finally:
        db.close()


def test_an_account_with_no_row_resolves_entirely_from_the_shared_layer(db_session_factory):
    db = db_session_factory()
    try:
        _set_key(db, OWNER, "deepseek_api_key", "sk-shared")
        assert _key(db, BOB, "deepseek_api_key") == "sk-shared"
        assert store.get_document(db, "models", BOB) == {}
    finally:
        db.close()


def test_own_section_stays_own(db_session_factory):
    """``user`` is what the account set — the UI edits this, so inherited values
    must not appear there, or saving would copy them in."""
    db = db_session_factory()
    try:
        _set_key(db, OWNER, "openai_api_key", "sk-shared-openai")
        _set_key(db, ALICE, "deepseek_api_key", "sk-alice")

        resolved = cs.resolve(db, "models", user_id=ALICE)
        own_keys = (resolved.user.get("api_keys") or {})
        assert own_keys.get("deepseek_api_key") == "sk-alice"
        assert "openai_api_key" not in own_keys
        # …while the effective value is complete.
        assert resolved.value["api_keys"]["openai_api_key"] == "sk-shared-openai"
        assert resolved.inherits is True
    finally:
        db.close()


def test_the_owner_does_not_inherit_from_itself(db_session_factory):
    db = db_session_factory()
    try:
        _set_key(db, OWNER, "deepseek_api_key", "sk-shared")
        resolved = cs.resolve(db, "models", user_id=OWNER)
        assert resolved.inherits is False
        assert (resolved.user.get("api_keys") or {}).get("deepseek_api_key") == "sk-shared"
    finally:
        db.close()


# ── non-secret settings are per account too ──────────────────────────────────

def test_model_defaults_are_per_account(db_session_factory):
    db = db_session_factory()
    try:
        cs.mutate(db, "models", [{"op": "set", "path": ["default_model"], "value": "deepseek-chat"}],
                  user_id=ALICE)
        cs.mutate(db, "models", [{"op": "set", "path": ["default_model"], "value": "gpt-4o"}],
                  user_id=BOB)
        assert cs.resolve(db, "models", user_id=ALICE).value["default_model"] == "deepseek-chat"
        assert cs.resolve(db, "models", user_id=BOB).value["default_model"] == "gpt-4o"
    finally:
        db.close()


# ── revisions are per account ────────────────────────────────────────────────

def test_revisions_do_not_collide_between_accounts(db_session_factory):
    db = db_session_factory()
    try:
        _set_key(db, ALICE, "deepseek_api_key", "a")     # alice rev 1
        _set_key(db, BOB, "deepseek_api_key", "b")       # bob rev 1
        assert store.get_revision(db, "models", ALICE) == 1
        assert store.get_revision(db, "models", BOB) == 1
        # A stale-revision write is evaluated per account, not globally.
        _set_key(db, ALICE, "deepseek_api_key", "a2")
        assert store.get_revision(db, "models", ALICE) == 2
        assert store.get_revision(db, "models", BOB) == 1
    finally:
        db.close()


# ── the credential resolver follows the caller ──────────────────────────────

def test_get_api_key_from_db_follows_the_current_identity(db_session_factory, monkeypatch):
    """The runtime path every model client uses must resolve per account.

    ``config`` opens its own session, so the test factory has to stand in for
    ``SessionLocal`` — otherwise this would read the real install's credentials.
    """
    from core.context.current_user import UserContext, reset_current_user, set_current_user

    monkeypatch.setattr("db.database.SessionLocal", db_session_factory)

    db = db_session_factory()
    try:
        _set_key(db, OWNER, "deepseek_api_key", "sk-shared")
        _set_key(db, ALICE, "deepseek_api_key", "sk-alice")
    finally:
        db.close()

    import config

    token = set_current_user(UserContext(id=ALICE, username="alice", role="member"))
    try:
        assert config.get_api_key_from_db("deepseek_api_key") == "sk-alice"
    finally:
        reset_current_user(token)

    token = set_current_user(UserContext(id=BOB, username="bob", role="member"))
    try:
        assert config.get_api_key_from_db("deepseek_api_key") == "sk-shared"
    finally:
        reset_current_user(token)


def test_no_identity_resolves_the_shared_layer(db_session_factory, monkeypatch):
    """Background jobs and scripts have no caller — they must not fall into an
    arbitrary account's credentials."""
    monkeypatch.setattr("db.database.SessionLocal", db_session_factory)

    db = db_session_factory()
    try:
        _set_key(db, OWNER, "deepseek_api_key", "sk-shared")
        _set_key(db, ALICE, "deepseek_api_key", "sk-alice")
    finally:
        db.close()

    import config

    assert config.get_api_key_from_db("deepseek_api_key") == "sk-shared"


# ── delete / cleanup stay per account ───────────────────────────────────────

def test_deleting_one_accounts_document_leaves_the_other(db_session_factory):
    db = db_session_factory()
    try:
        _set_key(db, ALICE, "deepseek_api_key", "sk-alice")
        _set_key(db, BOB, "deepseek_api_key", "sk-bob")
        assert store.delete_document(db, "models", user_id=ALICE) is True
        assert store.get_document(db, "models", ALICE) == {}
        assert (store.get_document(db, "models", BOB).get("api_keys") or {}).get(
            "deepseek_api_key") == "sk-bob"
    finally:
        db.close()


# ── who set the credential (what the Settings UI labels) ─────────────────────

def test_secret_positions_report_who_set_them(db_session_factory):
    """``set`` alone cannot distinguish "mine" from "the team's".

    The value never crosses the wire, so both look identical — which is exactly
    why an account could believe it had configured a key the whole install was
    paying for. ``source`` answers it, and this is the only place that can: it
    needs the own section AND the effective one, before redaction.
    """
    db = db_session_factory()
    try:
        _set_key(db, OWNER, "openai_api_key", "sk-shared-openai")
        _set_key(db, ALICE, "deepseek_api_key", "sk-alice")

        sources = {
            tuple(s["path"]): s["source"]
            for s in cs.resolve(db, "models", user_id=ALICE).wire()["secrets"]
        }
        assert sources[("api_keys", "deepseek_api_key")] == "own"      # alice's
        assert sources[("api_keys", "openai_api_key")] == "shared"     # inherited
        assert sources[("api_keys", "qwen_api_key")] == "unset"

        # The owner set its own values, so nothing is "shared" for it.
        owner_sources = {
            tuple(s["path"]): s["source"]
            for s in cs.resolve(db, "models", user_id=OWNER).wire()["secrets"]
        }
        assert owner_sources[("api_keys", "openai_api_key")] == "own"
    finally:
        db.close()


def test_an_account_value_wins_over_the_shared_one_in_the_label(db_session_factory):
    """Same key set in both layers → it is the account's (that is the one used)."""
    db = db_session_factory()
    try:
        _set_key(db, OWNER, "deepseek_api_key", "sk-shared")
        _set_key(db, ALICE, "deepseek_api_key", "sk-alice")
        sources = {
            tuple(s["path"]): s["source"]
            for s in cs.resolve(db, "models", user_id=ALICE).wire()["secrets"]
        }
        assert sources[("api_keys", "deepseek_api_key")] == "own"
    finally:
        db.close()


def test_the_search_provider_key_status_follows_the_caller(db_session_factory):
    """The search-providers endpoint used to read the own section only, so an
    inherited key reported as missing while it worked at runtime.
    """
    from api.system.search_providers import _get_decrypted_key, _key_source
    from core.context.current_user import UserContext, reset_current_user, set_current_user

    db = db_session_factory()
    try:
        _set_key(db, OWNER, "tavily_api_key", "tvly-shared")

        token = set_current_user(UserContext(id=ALICE, username="alice", role="member"))
        try:
            assert _get_decrypted_key("tavily_api_key", db) == "tvly-shared"
            assert _key_source("tavily_api_key", db) == "shared"
        finally:
            reset_current_user(token)

        token = set_current_user(UserContext(id=OWNER, username="owner", role="admin"))
        try:
            assert _key_source("tavily_api_key", db) == "own"
        finally:
            reset_current_user(token)
    finally:
        db.close()


def test_the_key_test_endpoint_answers_what_the_runtime_does(db_session_factory):
    """`POST /api-keys/test` must see inherited keys.

    It resolved keys from the own section only, so on an account that inherits,
    "Test" answered "No API key stored for 'minimax'" while every agent turn was
    using that very key. A test that contradicts the runtime is worse than none —
    the endpoint's whole purpose is to answer "will this work?".
    """
    from api.system import settings as settings_api
    from core.context.current_user import UserContext, reset_current_user, set_current_user

    db = db_session_factory()
    try:
        _set_key(db, OWNER, "minimax_api_key", "sk-minimax-shared")

        token = set_current_user(UserContext(id=ALICE, username="alice", role="member"))
        try:
            assert settings_api._resolve_api_key(db, "minimax") == "sk-minimax-shared"
            # base_url shares the same map, so it is inherited too
            assert "minimax_api_key" in settings_api._document_api_keys(db)
        finally:
            reset_current_user(token)
    finally:
        db.close()


def test_storage_mode_is_inherited_rather_than_reported_unset(db_session_factory):
    """Storage mode is an install-level choice: an account that never set one
    must see the mode the install runs, not "unset"."""
    from api.system import settings as settings_api
    from core.context.current_user import UserContext, reset_current_user, set_current_user

    db = db_session_factory()
    try:
        cs.mutate(db, "storage", [{"op": "set", "path": ["mode"], "value": "db"}],
                  user_id=OWNER)

        token = set_current_user(UserContext(id=ALICE, username="alice", role="member"))
        try:
            assert settings_api._persisted_storage_mode(db) == "db"
        finally:
            reset_current_user(token)
    finally:
        db.close()


# ── the owner's sharing switches ────────────────────────────────────────────

def _keys_visible_to(db, user_id):
    _own, eff = store.get_effective_document(db, "models", user_id)
    k = eff.get("api_keys") or {}
    return {
        "llm": bool(k.get("deepseek_api_key")),
        "web": bool(k.get("tavily_api_key")),
    }


def test_the_owner_can_stop_sharing_model_keys(db_session_factory):
    """The owner's row is the team's default — until the owner says otherwise.

    Turning it off must leave the other group alone: model keys are the whole cost
    of a turn, search keys are billed per query and are often someone's personal
    free tier. One switch for both would force all-or-nothing.
    """
    db = db_session_factory()
    try:
        _set_key(db, OWNER, "deepseek_api_key", "sk-model")
        _set_key(db, OWNER, "tavily_api_key", "tvly-web")
        assert _keys_visible_to(db, ALICE) == {"llm": True, "web": True}

        store.mutate(db, "models",
                     [{"op": "set", "path": ["share_model_keys_with_team"], "value": False}],
                     user_id=OWNER)

        assert _keys_visible_to(db, ALICE) == {"llm": False, "web": True}
        # The owner keeps its own keys either way.
        assert _keys_visible_to(db, OWNER) == {"llm": True, "web": True}
    finally:
        db.close()


def test_the_owner_can_stop_sharing_web_keys(db_session_factory):
    db = db_session_factory()
    try:
        _set_key(db, OWNER, "deepseek_api_key", "sk-model")
        _set_key(db, OWNER, "tavily_api_key", "tvly-web")

        store.mutate(db, "models",
                     [{"op": "set", "path": ["share_web_keys_with_team"], "value": False}],
                     user_id=OWNER)

        assert _keys_visible_to(db, ALICE) == {"llm": True, "web": False}
        assert _keys_visible_to(db, OWNER) == {"llm": True, "web": True}
    finally:
        db.close()


def test_sharing_off_does_not_take_an_accounts_own_key(db_session_factory):
    """The policy masks the SHARED copy. A key the account set itself survives —
    otherwise turning sharing off would break the very accounts that complied."""
    db = db_session_factory()
    try:
        _set_key(db, OWNER, "deepseek_api_key", "sk-shared")
        _set_key(db, ALICE, "deepseek_api_key", "sk-alice")
        store.mutate(db, "models",
                     [{"op": "set", "path": ["share_model_keys_with_team"], "value": False}],
                     user_id=OWNER)

        own, eff = store.get_effective_document(db, "models", ALICE)
        assert (eff.get("api_keys") or {}).get("deepseek_api_key") == "sk-alice"
        assert (own.get("api_keys") or {}).get("deepseek_api_key") == "sk-alice"
    finally:
        db.close()


def test_sharing_off_still_shares_operational_settings(db_session_factory):
    """Defaults and limits are not a bill: they keep inheriting, so an account
    without a personal default_model is not left with nothing."""
    db = db_session_factory()
    try:
        cs.mutate(db, "models",
                  [{"op": "set", "path": ["default_model"], "value": "deepseek-chat"}],
                  user_id=OWNER)
        store.mutate(db, "models",
                     [{"op": "set", "path": ["share_model_keys_with_team"], "value": False}],
                     user_id=OWNER)

        assert cs.resolve(db, "models", user_id=ALICE).value["default_model"] == "deepseek-chat"
    finally:
        db.close()


def test_sharing_defaults_to_on_for_an_install_that_never_touched_it(db_session_factory):
    """An absent switch means "on" — the pre-toggle behaviour — so an existing
    database keeps working without anyone opening Settings."""
    db = db_session_factory()
    try:
        _set_key(db, OWNER, "deepseek_api_key", "sk-model")
        assert "share_model_keys_with_team" not in store.get_document(db, "models", OWNER)
        assert _keys_visible_to(db, ALICE) == {"llm": True, "web": False}
    finally:
        db.close()
