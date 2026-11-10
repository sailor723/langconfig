"""Prompts: Chinese is what an agent is sent, English is the archive — and the backlog has to be honest.

The same model as skills, applied to `deep_agent_templates.config->>'system_prompt'`: the DB holds Chinese, the
English it came from is frozen at `backend/prompts/en-originals/<id>.md` (outside the database, so it is never
served and can always be diffed against), and every prompt is in exactly one of three states:

    translated      an archive exists
    authored in zh  listed in zh-native.txt (no English original to be a translation of)
    pending         listed in pending-zh.txt — English is what agents are being sent today

A prompt has no headings contract, so the checks are about what a reader would type: fenced code byte-identical,
every identifier/number/URL/path preserved, and enough Chinese prose to be Chinese (measured against the English
*prose*, because prompts are often half code).
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "backend"))
os.chdir(REPO / "backend")  # config.py resolves ../../.env from the process cwd

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("prompt_zh", REPO / "scripts" / "prompt_zh.py")
prompt_zh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prompt_zh)

ARCHIVE, STAGING = prompt_zh.ARCHIVE, prompt_zh.STAGING
PENDING, ZH_NATIVE = prompt_zh.PENDING, prompt_zh.ZH_NATIVE


_CACHE: dict[str, dict] | None = None


def _rows() -> dict[str, dict]:
    """Fetch once per process.

    `asyncio.run()` per test re-opens the event loop, and asyncpg's pooled connections belong to the loop that
    created them — every parametrised case after the first died with "attached to a different loop". The prompts
    do not change while the suite runs, so one read is both correct and enough.
    """
    global _CACHE
    if _CACHE is None:
        _CACHE = {r["id"]: r for r in asyncio.run(prompt_zh._fetch())}
    return _CACHE


def _archived() -> set[str]:
    return {p.stem for p in ARCHIVE.glob("*.md")} if ARCHIVE.is_dir() else set()


def test_the_archive_is_outside_the_database():
    """If the English lived in the DB it would be served to agents; it lives on disk instead."""
    assert ARCHIVE.is_dir(), "the English originals must exist — they are what the Chinese was translated from"
    assert ARCHIVE.parent.name == "prompts"
    assert not list(ARCHIVE.glob("*.json")), "the archive should hold prompts, not derived data"


def test_every_prompt_is_in_exactly_one_state():
    rows, archived = _rows(), _archived()
    zh_native, pending = set(prompt_zh.list_file(ZH_NATIVE)), set(prompt_zh.list_file(PENDING))
    both = sorted((archived & zh_native) | (archived & pending) | (zh_native & pending))
    assert not both, f"these prompts are claimed by more than one language state: {both}"
    unknown = sorted((archived | zh_native | pending) - set(rows))
    assert not unknown, f"a language list names prompts that are not in the DB: {unknown}"
    missing = sorted(set(rows) - archived - zh_native - pending)
    assert not missing, (
        f"these prompts have no declared language (not translated, not authored in Chinese, not pending): "
        f"{missing}")


@pytest.mark.parametrize("prompt_id", sorted(_archived(), key=int))
def test_a_translated_prompt_is_actually_chinese(prompt_id: str):
    rows, en = _rows(), (ARCHIVE / f"{prompt_id}.md").read_text(encoding="utf-8")
    if prompt_id not in rows:
        pytest.skip("archived prompt is no longer in the DB")
    zh = rows[prompt_id]["prompt"]
    assert prompt_zh.reads_as_chinese(zh), (
        f"{prompt_id}: the DB row is still English — the archive exists, so `promote` was not the thing that "
        "wrote it")
    floor = max(3, round(prompt_zh.latin_words(prompt_zh.prose(en)) * prompt_zh.CJK_PER_EN_WORD_MIN))
    assert prompt_zh.cjk_count(zh) >= floor, (
        f"{prompt_id}: {prompt_zh.cjk_count(zh)} CJK characters against a floor of {floor} from the English prose")


@pytest.mark.parametrize("prompt_id", sorted(_archived(), key=int))
def test_a_translated_prompt_keeps_its_code_and_its_identifiers(prompt_id: str):
    rows = _rows()
    if prompt_id not in rows:
        pytest.skip("archived prompt is no longer in the DB")
    en = (ARCHIVE / f"{prompt_id}.md").read_text(encoding="utf-8")
    try:
        prompt_zh.validate(prompt_id, en, rows[prompt_id]["prompt"])
    except prompt_zh.Rejected as exc:                     # pragma: no cover - the message is the assertion
        raise AssertionError(f"{prompt_id}: {exc}") from exc


@pytest.mark.parametrize("prompt_id", sorted(set(prompt_zh.list_file(ZH_NATIVE)), key=int))
def test_a_prompt_authored_in_chinese_really_is_chinese(prompt_id: str):
    rows = _rows()
    if prompt_id not in rows:
        pytest.skip("listed prompt is no longer in the DB")
    assert prompt_zh.reads_as_chinese(rows[prompt_id]["prompt"]), (
        f"{prompt_id} is listed in zh-native.txt but reads as English")


@pytest.mark.parametrize("prompt_id", sorted(set(prompt_zh.list_file(PENDING)), key=int))
def test_a_pending_prompt_really_is_english(prompt_id: str):
    rows = _rows()
    if prompt_id not in rows:
        pytest.skip("pending prompt is no longer in the DB")
    assert not prompt_zh.reads_as_chinese(rows[prompt_id]["prompt"]), (
        f"{prompt_id} reads as Chinese but is listed as pending — move it out of pending-zh.txt")


def test_no_staged_translation_is_left_behind():
    """A staged file is a translation nobody promoted — the DB does not serve it, so it is invisible work."""
    left = sorted(p.stem for p in STAGING.glob("*.md") if not p.name.startswith(".")) if STAGING.is_dir() else []
    assert not left, f"staged but never promoted: {left}"
