# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for the duplicate FilesystemMiddleware fix.

The deepagents SDK always injects its own FilesystemMiddleware when a
backend is active; the DeepAgent assembly additionally passed an
instrumented copy, producing two ls/read_file/write_file/... tool sets
with different roots that LangGraph merges last-wins by accident.
"""
import tempfile

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware

from services.deepagent_factory.assembly import _is_filesystem_middleware
from services.deepagents_instrumentation import instrument_deepagents_middleware


def _make_fs_middleware():
    tmp = tempfile.mkdtemp()
    fs = FilesystemMiddleware(backend=FilesystemBackend(root_dir=tmp))
    return fs, instrument_deepagents_middleware(fs)


def test_plain_filesystem_middleware_detected():
    fs, _ = _make_fs_middleware()
    assert _is_filesystem_middleware(fs)


def test_instrumented_filesystem_middleware_detected():
    _, inst = _make_fs_middleware()
    assert _is_filesystem_middleware(inst)


def test_unrelated_middleware_not_detected():
    assert not _is_filesystem_middleware(object())
    assert not _is_filesystem_middleware(None)


def test_filtering_drops_only_filesystem_middleware():
    fs, inst = _make_fs_middleware()
    keep = object()
    stack = [inst, keep, fs, "string-entry"]
    filtered = [mw for mw in stack if not _is_filesystem_middleware(mw)]
    assert len(filtered) == 2
    assert filtered[0] is keep
    assert filtered[1] == "string-entry"
