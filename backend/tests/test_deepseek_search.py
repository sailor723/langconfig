# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""`web_search` on DeepSeek's own Search API.

Why this backend: it needs no new credential (it bills the DeepSeek key the
install already holds, per account since migration 037), bills **per successful
request** at $0.75/1,000 so the result count is free, and returns extracted page
content with each hit — which is the difference between an agent that reads a
source and one that stops at a headline.

What is pinned here, all of it about failure modes rather than the happy path:

  * the request shape the API documents (endpoint, bearer auth, count,
    ``need_content``) and that a custom ``deepseek_api_base`` is honoured;
  * an empty result set and a 429 both fall through to the next provider instead
    of surfacing as "no results" — the account-level QPS is shared by everyone on
    the instance, so being throttled says nothing about the query;
  * a provider error never raises out of a tool call: the turn degrades to
    DuckDuckGo rather than failing;
  * DeepSeek is tried first when its key exists, and Tavily is still honoured when
    it does not.
"""

import asyncio
import json

import pytest

from tools import native_impl


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    """Records the request and returns a canned response."""

    def __init__(self, response, calls):
        self._response = response
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        self._calls.append({"url": url, "headers": headers, "json": json})
        return self._response


def _patch_httpx(monkeypatch, response):
    calls = []
    monkeypatch.setattr(
        "httpx.AsyncClient", lambda *a, **k: _FakeClient(response, calls)
    )
    return calls


def _patch_keys(monkeypatch, **keys):
    def fake_get(name):
        return keys.get(name)

    monkeypatch.setattr("config.get_api_key_from_db", fake_get, raising=False)
    return fake_get


def _run(coro):
    return asyncio.run(coro)


# ── the request the docs specify ────────────────────────────────────────────

def test_request_matches_the_documented_shape(monkeypatch):
    calls = _patch_httpx(
        monkeypatch,
        _FakeResponse(
            200,
            {
                "results": [
                    {"title": "T1", "url": "https://a.example", "content": "body one"},
                ]
            },
        ),
    )
    out = _run(native_impl._deepseek_search("q", 3, "sk-test"))

    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == "https://api.deepseek.com/v1/tools/search"
    assert call["headers"]["Authorization"] == "Bearer sk-test"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["json"] == {"query": "q", "count": 3, "need_content": True}

    # The formatted block keeps the title / url / content trio the other backends emit
    assert "1. T1" in out and "https://a.example" in out and "body one" in out


def test_a_custom_api_base_is_honoured(monkeypatch):
    calls = _patch_httpx(monkeypatch, _FakeResponse(200, {"results": [{"title": "x"}]}))
    _patch_keys(monkeypatch, deepseek_api_base="https://proxy.internal/v1/")

    _run(native_impl._deepseek_search("q", 1, "sk-test"))

    assert calls[0]["url"] == "https://proxy.internal/v1/v1/tools/search"


def test_count_is_clamped_to_the_documented_range(monkeypatch):
    calls = _patch_httpx(monkeypatch, _FakeResponse(200, {"results": [{"title": "x"}]}))

    _run(native_impl._deepseek_search("q", 99, "sk-test"))
    assert calls[-1]["json"]["count"] == 10

    _run(native_impl._deepseek_search("q", 0, "sk-test"))
    assert calls[-1]["json"]["count"] == 5  # nonsense means "unspecified"
    _run(native_impl._deepseek_search("q", -3, "sk-test"))
    assert calls[-1]["json"]["count"] == 5


# ── failure modes: fall through, never raise ────────────────────────────────

def test_empty_results_fall_through(monkeypatch):
    """An empty result set is not billed and is not an answer — the caller must be
    able to try the next provider."""
    _patch_httpx(monkeypatch, _FakeResponse(200, {"results": []}))
    assert _run(native_impl._deepseek_search("q", 5, "sk-test")) is None


def test_rate_limit_falls_through_without_raising(monkeypatch):
    """429 is account-wide, so it says nothing about this query; degrading to DDG
    beats telling the agent there are no results."""
    _patch_httpx(monkeypatch, _FakeResponse(429, {}, text="slow down"))
    assert _run(native_impl._deepseek_search("q", 5, "sk-test")) is None


def test_http_error_falls_through(monkeypatch):
    _patch_httpx(monkeypatch, _FakeResponse(500, {}, text="boom"))
    assert _run(native_impl._deepseek_search("q", 5, "sk-test")) is None


def test_transport_error_falls_through(monkeypatch):
    class _Boom:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *a, **k):
            raise OSError("connection reset")

    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _Boom())
    assert _run(native_impl._deepseek_search("q", 5, "sk-test")) is None


def test_long_page_content_is_clipped(monkeypatch):
    """Each hit carries page text; without a cap, five results can swallow the
    tool budget the agent needs for its own reasoning."""
    _patch_httpx(
        monkeypatch,
        _FakeResponse(200, {"results": [{"title": "t", "url": "u", "content": "x" * 5000}]}),
    )
    out = _run(native_impl._deepseek_search("q", 1, "sk-test"))
    assert "…" in out
    assert len(out) < 1200


# ── ordering in the provider chain ──────────────────────────────────────────

def test_deepseek_is_preferred_when_its_key_exists(monkeypatch):
    _patch_keys(monkeypatch, deepseek_api_key="sk-deepseek", tavily_api_key="tvly-x")
    seen = {}

    async def fake_deepseek(query, max_results, api_key):
        seen["key"] = api_key
        return "DEEPSEEK RESULT"

    monkeypatch.setattr(native_impl, "_deepseek_search", fake_deepseek)

    out = _run(native_impl._try_configured_search_provider("q", 3))
    assert out == "DEEPSEEK RESULT"
    assert seen["key"] == "sk-deepseek"


def test_tavily_still_used_when_the_deepseek_key_is_absent(monkeypatch):
    _patch_keys(monkeypatch, deepseek_api_key=None, tavily_api_key="tvly-x")
    calls = _patch_httpx(
        monkeypatch,
        _FakeResponse(200, {"results": [{"title": "t", "url": "u", "content": "c"}]}),
    )

    out = _run(native_impl._try_configured_search_provider("q", 2))
    assert "api.tavily.com" in calls[0]["url"]
    assert out and "t" in out


def test_no_keys_means_no_provider_and_ddg_takes_over(monkeypatch):
    _patch_keys(monkeypatch, deepseek_api_key=None, tavily_api_key=None, serper_api_key=None)
    assert _run(native_impl._try_configured_search_provider("q", 3)) is None
