# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for the SSRF guard on docx-export image fetching.

The docx exporter downloads images embedded in workflow/task content; those
URLs are attacker-controlled and were fetched with no allowlist, enabling
SSRF against internal services (metadata endpoints, localhost, private
ranges).
"""
import io

import pytest

from api.workflows.executions import _add_image_to_doc


class _FakeDoc:
    def __init__(self):
        self.pictures = []
        self.paragraphs = []

    def add_picture(self, stream, width=None):
        self.pictures.append(stream.read())

    def add_paragraph(self, *args, **kwargs):
        self.paragraphs.append(args)
        return _FakePara()

    def add_heading(self, *args, **kwargs):
        return _FakePara()


class _FakePara:
    alignment = None


@pytest.mark.parametrize("bad_url", [
    "http://127.0.0.1:5432/secret",
    "http://localhost:8765/api/health",
    "http://169.254.169.254/latest/meta-data",
    "http://10.0.0.5/internal",
    "http://192.168.1.10/admin",
    "http://172.16.0.5/private",
    "http://[::1]/local",
])
async def test_private_url_is_blocked_before_fetch(bad_url, monkeypatch):
    """Private/local/metadata URLs must be rejected without any HTTP call."""
    called = []

    async def fake_get(*args, **kwargs):
        called.append(args)
        return None

    monkeypatch.setattr("api.workflows.executions.requests.get", fake_get)
    doc = _FakeDoc()

    # _validate_url_ssrf raises ValueError → propagates out of the helper;
    # the endpoint catches it and adds a placeholder. Assert no fetch.
    with pytest.raises(Exception):
        await _add_image_to_doc(doc, bad_url)
    assert called == [], f"HTTP fetch attempted for blocked URL: {bad_url}"


async def test_public_url_is_fetched_and_embedded(monkeypatch):
    """A safe public URL is downloaded (off the event loop) and embedded."""
    class _Resp:
        status_code = 200
        content = b"\x89PNG-fake-image-bytes"

    # requests.get is invoked via asyncio.to_thread → must be a sync callable.
    def fake_get(*args, **kwargs):
        return _Resp()

    monkeypatch.setattr("api.workflows.executions.requests.get", fake_get)
    doc = _FakeDoc()
    await _add_image_to_doc(doc, "https://example.com/chart.png")
    assert len(doc.pictures) == 1
    assert doc.pictures[0] == b"\x89PNG-fake-image-bytes"
