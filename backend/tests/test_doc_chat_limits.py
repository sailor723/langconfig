# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Doc Chat's two reading limits come from Settings → Knowledge, not from the source.

`MAX_FILES` and `MAX_CONTEXT_CHARS` in `api/knowledge/doc_chat.py` used to be the policy. They are
now only the fallback, and the settings document is primary — the same arrangement
`doc_chat_model` already had. What these tests establish, in order:

1. **The setting is primary, the constant is the fallback.** Unset (and an unusable value) falls
   back; a set value is what the request uses.
2. **The limits actually bound one answer.** Not merely "the helper returned 2" — the number of
   documents loaded and the characters of context, as the endpoint reports them in its `start`
   event.
3. **A request may lower the cap but never raise it.** The budget is the operator's to set, so a
   client asking for more gets the configured cap, not what it asked for.

The settings lookup is stubbed rather than read from Postgres: these are doc-chat tests, and
`runtime_get` opening its own session is exactly what they should not depend on. The DB side —
that a value saved through the mutate API reaches this helper — is covered by
`tests/test_core_settings.py`.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.knowledge import doc_chat


# ── fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def kb_root(tmp_path, monkeypatch):
    """A temporary knowledge root: both resolvers must agree on it, as in production."""
    root = tmp_path / "knowledge"
    monkeypatch.setenv("KB_ROOT", str(root))
    monkeypatch.setenv("DOCUMENTS_KB_ROOT", str(root))
    return root


def _knowledge_base(root, name: str, sizes: dict[str, int]):
    """Write one markdown document per entry — `{filename: content_length}`."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "kb.json").write_text(json.dumps({"name": name, "key": "1"}), encoding="utf-8")
    for filename, length in sizes.items():
        # Distinct, countable content so a document can be identified in the prompt.
        body = f"{filename} " + ("x" * max(0, length - len(filename) - 1))
        (folder / filename).write_text(body, encoding="utf-8")
    return folder


@pytest.fixture
def settings(monkeypatch):
    """Stub the settings lookup. Returns a setter for `{field: value}`."""
    values: dict = {}

    def fake_runtime_get(ns, field, fallback=None):
        assert ns == "knowledge", f"unexpected namespace {ns!r}"
        return values.get(field, fallback)

    monkeypatch.setattr(doc_chat, "runtime_get", fake_runtime_get)
    return values


@pytest.fixture
def client(monkeypatch):
    """A TestClient for the doc-chat router, with the LLM stubbed out.

    Nothing is sent to a model: the fake records the messages so a test can assert on the prompt the
    real endpoint built.
    """
    captured: dict = {}

    class _Chunk:
        def __init__(self, content):
            self.content = content

    class _FakeLLM:
        async def astream(self, messages):
            captured["messages"] = messages
            yield _Chunk("ok")

    async def fake_resolve_llm(request):
        return _FakeLLM()

    monkeypatch.setattr(doc_chat, "_resolve_llm", fake_resolve_llm)
    app = FastAPI()
    app.include_router(doc_chat.router)
    return TestClient(app), captured


def _ask(client, knowledge="kb", **overrides):
    """POST one question and return `(start_event, system_prompt)`."""
    test_client, captured = client
    body = {"knowledge": knowledge, "folder_path": "",
            "messages": [{"role": "user", "content": "how many files"}]}
    body.update(overrides)
    response = test_client.post("/api/doc-chat", json=body)
    assert response.status_code == 200, response.text

    start = None
    for line in response.text.splitlines():
        if line.startswith("data: "):
            event = json.loads(line[6:])
            if event.get("type") == "start":
                start = event
                break
    assert start is not None, response.text
    return start, captured["messages"][0][1]


# ── 1. the setting is primary, the constant is the fallback ──────────

def test_unset_falls_back_to_the_built_in_defaults(settings):
    assert doc_chat.configured_max_files() == doc_chat.MAX_FILES == 300
    assert doc_chat.configured_max_context_chars() == doc_chat.MAX_CONTEXT_CHARS == 1_000_000


def test_a_configured_value_wins(settings):
    settings["doc_chat_max_files"] = 12
    settings["doc_chat_max_context_chars"] = 250_000
    assert doc_chat.configured_max_files() == 12
    assert doc_chat.configured_max_context_chars() == 250_000


@pytest.mark.parametrize("unusable", [0, -1, None, "300", 300.0, True])
def test_an_unusable_value_falls_back_instead_of_breaking(settings, unusable):
    """A hand-edited settings document must not be able to empty the context.

    The schema refuses these at write time (`Field(ge=1)`), so this only matters for a document
    written outside the API — which is exactly the case worth being defensive about. `True` is in
    the list because it is an `int` subclass and would otherwise mean "1 file".
    """
    settings["doc_chat_max_files"] = unusable
    settings["doc_chat_max_context_chars"] = unusable
    assert doc_chat.configured_max_files() == doc_chat.MAX_FILES
    assert doc_chat.configured_max_context_chars() == doc_chat.MAX_CONTEXT_CHARS


# ── 2. the limits actually bound one answer ──────────────────────────

def test_max_files_bounds_the_documents_loaded(kb_root, settings, client):
    """`doc_chat_max_files` decides how many documents reach the prompt, largest first."""
    _knowledge_base(kb_root, "kb", {
        "small.md": 1_000, "medium.md": 2_000, "large.md": 5_000, "huge.md": 20_000,
    })
    settings["doc_chat_max_files"] = 2

    start, prompt = _ask(client)

    assert start["file_count"] == 2
    # The two LARGEST, because the scan sorts by size descending.
    assert "huge.md" in prompt and "large.md" in prompt
    assert "medium.md" not in prompt and "small.md" not in prompt


def test_raising_max_files_loads_the_rest(kb_root, settings, client):
    """The same folder, with the limit raised: the cap is what excluded the small documents."""
    _knowledge_base(kb_root, "kb", {
        "small.md": 1_000, "medium.md": 2_000, "large.md": 5_000, "huge.md": 20_000,
    })
    settings["doc_chat_max_files"] = 10

    start, prompt = _ask(client)

    assert start["file_count"] == 4
    for name in ("small.md", "medium.md", "large.md", "huge.md"):
        assert name in prompt


def test_max_context_chars_bounds_the_context(kb_root, settings, client):
    """`doc_chat_max_context_chars` is the budget: the answer cannot inline more than it allows."""
    _knowledge_base(kb_root, "kb", {f"doc{i}.md": 20_000 for i in range(5)})
    settings["doc_chat_max_context_chars"] = 30_000

    start, prompt = _ask(client)

    # The cap plus the one document header and truncation marker that straddle it.
    assert start["total_chars"] <= 30_000 + 500, start
    assert "...[truncated]" in prompt
    assert start["file_count"] < 5, "the budget must have excluded documents, or it bound nothing"


def test_the_budget_is_the_thing_that_changed(kb_root, settings, client):
    """Same folder, a larger budget: more context, which is what makes the cap meaningful."""
    _knowledge_base(kb_root, "kb", {f"doc{i}.md": 20_000 for i in range(5)})
    settings["doc_chat_max_context_chars"] = 30_000
    small, _ = _ask(client)
    settings["doc_chat_max_context_chars"] = 90_000
    large, _ = _ask(client)

    assert large["total_chars"] > small["total_chars"]


# ── 3. a request may lower the cap, never raise it ───────────────────

def test_a_request_cannot_raise_the_configured_cap(kb_root, settings, client):
    """Asking for more context than the operator allows gets the operator's limit."""
    _knowledge_base(kb_root, "kb", {f"doc{i}.md": 20_000 for i in range(5)})
    settings["doc_chat_max_context_chars"] = 30_000

    start, _ = _ask(client, max_context_chars=20_000_000)

    assert start["total_chars"] <= 30_000 + 500, start


def test_a_request_may_lower_the_configured_cap(kb_root, settings, client):
    """A narrower question over a large knowledge base can ask for less."""
    _knowledge_base(kb_root, "kb", {f"doc{i}.md": 20_000 for i in range(5)})
    settings["doc_chat_max_context_chars"] = 200_000

    start, _ = _ask(client, max_context_chars=25_000)

    assert start["total_chars"] <= 25_000 + 500, start


# ── the knowledge base's own manifest is not a document ──────────────
# Every fixture above writes a `kb.json`, so these tests depend on this rule; this one states it.

def test_the_knowledge_base_manifest_is_never_read_as_a_document(kb_root, settings, client):
    """`kb.json` sits inside the folder the scan walks, and is not one of its documents.

    It was being read as one: inlined into every answer, counted in `file_count`, and citable as a
    source (`[Source: kb.json]`). 16 of 19 knowledge bases on this install carry one. The other two
    readers of a knowledge base — `kv_ingest.disk_hashes` and `/index-missing` — already excluded
    it; the scan was the third and the one that forgot.
    """
    _knowledge_base(kb_root, "kb", {"only.md": 500})
    start, prompt = _ask(client)

    assert start["file_count"] == 1, "the manifest must not be counted as a document"
    assert "kb.json" not in prompt


def test_a_folder_holding_only_a_manifest_is_not_offered_as_a_scope(kb_root, settings, client):
    """The folder list and the scan must agree, or the selector offers scopes that answer nothing."""
    folder = _knowledge_base(kb_root, "kb", {"real.md": 500})
    nested = folder / "empty_but_for_manifest"
    nested.mkdir()
    (nested / "kb.json").write_text('{"name": "nested"}', encoding="utf-8")

    test_client, _ = client
    response = test_client.get("/api/doc-chat/folders", params={"knowledge": "kb"})
    assert response.status_code == 200
    assert response.json()["folders"] == []
