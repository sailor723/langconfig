#!/usr/bin/env python3
"""Prompts: English is the archive, Chinese is what the model is sent.

The same decision as skills, applied to the other half of the library. A prompt in this app is
`deep_agent_templates.config->>'system_prompt'` — the text an agent is actually handed — and it is what the
Prompts activity shows. Chinese is the working language, so:

    the DB row holds Chinese                    ← what an agent and the Prompts activity read
    backend/prompts/en-originals/<id>.md        ← the English it came from, frozen, never served

The archive lives on disk, outside the database, for the same reason it does for skills: a translation you cannot
diff against its source is a claim, not a record. `promote` writes the Chinese into the DB **after** archiving the
English, so the two can never disagree about what was translated.

States, and a prompt is in exactly one (`tests/test_prompt_translations.py` checks all three directions):

    translated      an archive exists at en-originals/<id>.md
    authored in zh  listed in zh-native.txt (there is no English original to archive)
    pending         listed in pending-zh.txt — still English

Usage::

    python scripts/prompt_zh.py status
    python scripts/prompt_zh.py show   <id>            # the English to translate (--from db), or a staged draft
    python scripts/prompt_zh.py check  <id> [<id>…]    # validate staged Chinese, change nothing
    python scripts/prompt_zh.py promote <id> [<id>…]   # archive the English, write the Chinese to the DB

There is deliberately no `archive` step: an archive that exists beside a still-English prompt is a claim that a
translation happened, which is the one thing this file must never say. `promote` freezes the English and writes the
Chinese in the same breath.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import re
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
PROMPTS = BACKEND / "prompts"
ARCHIVE = PROMPTS / "en-originals"
STAGING = PROMPTS / ".zh-staging"
PENDING = PROMPTS / "pending-zh.txt"
ZH_NATIVE = PROMPTS / "zh-native.txt"

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(BACKEND))          # `db`, `models`: the app package root
import os  # noqa: E402
os.chdir(BACKEND)                          # config.py loads ../../.env relative to the process cwd
from skill_translation_fidelity import normalise, severity, split_fences, squash, tokens_in  # noqa: E402

CJK_PER_EN_WORD_MIN = 0.6
CJK_VS_LATIN_MIN = 0.15


class Rejected(Exception):
    pass


# ── database ─────────────────────────────────────────────────────────────────────────────────────
_FETCH_CACHE: dict[tuple[str, ...] | None, list[dict]] = {}


async def _fetch(ids: list[str] | None = None) -> list[dict]:
    """Read the prompts once per process.

    asyncpg's pool belongs to the event loop that created it, so a second `asyncio.run()` in the same process
    dies with "attached to a different loop" — measured, in both the CLI (`check` fetching twice) and the test
    suite. Caching also makes the verbs cheap: they all read the same 61 rows.
    """
    key = None if ids is None else tuple(sorted(ids, key=int))
    if key not in _FETCH_CACHE:
        _FETCH_CACHE[key] = await _fetch_uncached(ids)
    return _FETCH_CACHE[key]


async def _fetch_uncached(ids: list[str] | None = None) -> list[dict]:
    from db.database import AsyncSessionLocal
    from sqlalchemy import text as sql

    sql_text = ("select id, name, coalesce(config->>'system_prompt','') as prompt "
                "from deep_agent_templates order by id")
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(sql(sql_text))).all()
    out = [{"id": str(r[0]), "name": r[1], "prompt": r[2]} for r in rows if (r[2] or "").strip()]
    return [r for r in out if ids is None or r["id"] in ids]


_LOOP: asyncio.AbstractEventLoop | None = None


def run(coro):
    """Run a coroutine on one process-wide loop (asyncpg's pool is bound to the loop that created it)."""
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
    return _LOOP.run_until_complete(coro)


async def _write_prompt(prompt_id: str, text: str) -> None:
    from db.database import AsyncSessionLocal
    from sqlalchemy import text as sql

    async with AsyncSessionLocal() as session:
        await session.execute(
            sql("update deep_agent_templates "
                "set config = jsonb_set(coalesce(config::jsonb, '{}'::jsonb), '{system_prompt}', "
                "                to_jsonb(cast(:t as text))), "
                "    updated_at = now() where id = :i"),
            {"t": text, "i": int(prompt_id)},
        )
        await session.commit()


# ── text helpers (shared with the skill checker) ─────────────────────────────────────────────────
def body_of(text: str) -> str:
    """Prompts have no frontmatter; kept for symmetry with skill_zh.py callers."""
    return text


def cjk_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def latin_words(text: str) -> int:
    return len(re.findall(r"\b[A-Za-z]{3,}\b", text))


def prose(text: str) -> str:
    out, inside = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if not inside:
            out.append(line)
    return "\n".join(out)


def reads_as_chinese(text: str) -> bool:
    """Is the prose of this prompt Chinese?

    Measured on the prose, not the whole text: a prompt is often half code, and a code block full of English
    identifiers would otherwise outvote the Chinese around it. The absolute floor is small (8 characters) because
    a prompt can legitimately be one line — `case-5-support` is 17 characters — while the density ratio is what
    separates a Chinese prompt from an English one that happens to quote a Chinese label.
    """
    body = prose(text)
    cjk, latin = cjk_count(body), latin_words(body)
    return cjk >= 8 and cjk >= latin * CJK_VS_LATIN_MIN


def list_file(path: pathlib.Path) -> list[str]:
    if not path.is_file():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#") and re.fullmatch(r"\d+", ln.strip())]


def write_ids(path: pathlib.Path, ids: list[str], header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(header.splitlines()) + "\n\n" + "\n".join(sorted(ids, key=int)) + "\n"
    path.write_text(body, encoding="utf-8")


def english_source(prompt_id: str, rows: dict[str, dict]) -> pathlib.Path:
    """The English to compare against: the archive once translated, else the DB row written to a temp file.

    Before promotion the DB *is* the English for that prompt, so checking a staged draft reads it from `rows`
    (fetched once by the caller — a second `asyncio.run()` would hand asyncpg a dead event loop). Writing it to a
    temp file keeps `validate` a pure text-to-text function.
    """
    archived = archive_path(prompt_id)
    if archived.is_file():
        return archived
    if prompt_id not in rows:
        raise Rejected(f"prompt {prompt_id} is not in the DB")
    src = pathlib.Path(tempfile.gettempdir()) / f"prompt_zh_en_{prompt_id}.txt"
    src.write_text(rows[prompt_id]["prompt"], encoding="utf-8")
    return src


def archive_path(prompt_id: str) -> pathlib.Path:
    return ARCHIVE / f"{prompt_id}.md"


def staged_path(prompt_id: str) -> pathlib.Path:
    return STAGING / f"{prompt_id}.md"


# ── commands ────────────────────────────────────────────────────────────────────────────────────
def validate(prompt_id: str, en: str, zh: str) -> None:
    """Raise Rejected unless `zh` is an honest Chinese rendering of `en`.

    Two things a prompt must not lose: the code an agent copies (fenced blocks byte-identical, identifiers,
    numbers, URLs and paths all present), and the amount of prose (a density floor taken from the English *prose*,
    because prompt bodies are often half code and a code-derived floor demands more Chinese than the source has).
    """
    if not zh.strip():
        raise Rejected("staged translation is empty")

    en_prose, en_blocks = split_fences(en)
    zh_prose, zh_blocks = split_fences(zh)

    if len(zh_blocks) != len(en_blocks):
        raise Rejected(f"{len(zh_blocks)} fenced block(s) against {len(en_blocks)} in the original — a prompt's "
                       "code blocks are copied verbatim by whoever reuses it")
    for (info_en, body_en), (info_zh, body_zh) in zip(en_blocks, zh_blocks):
        info = info_en.strip().lower()
        if body_en.strip() != body_zh.strip() and info not in {"markdown", "md", "text", ""}:
            raise Rejected(f"a ```{info_en or '(unlabelled)'} block differs from the original but is not a "
                           "document template — code is data, not prose")

    zh_squashed = squash(normalise(zh_prose))
    lost = [t for t in tokens_in(en_prose)
            if severity(t) == "hard" and squash(normalise(t)) not in zh_squashed]
    if lost:
        raise Rejected(f"these identifiers, numbers, URLs or paths are in the English and not in the Chinese: "
                       f"{lost[:8]}")

    floor = max(3, round(latin_words(prose(en)) * CJK_PER_EN_WORD_MIN))
    if cjk_count(zh) < floor:
        raise Rejected(f"{cjk_count(zh)} CJK characters against {latin_words(prose(en))} English prose words "
                       f"(floor {floor}) — the prompt would still be English at the top level")
    if cjk_count(zh) < latin_words(zh) * CJK_VS_LATIN_MIN:
        raise Rejected(f"{latin_words(zh)} English words against {cjk_count(zh)} CJK characters — mostly "
                       "untranslated")


def cmd_status() -> int:
    rows = run(_fetch())
    archived = {p.stem for p in ARCHIVE.glob("*.md")} if ARCHIVE.is_dir() else set()
    zh_native, pending = set(list_file(ZH_NATIVE)), set(list_file(PENDING))
    staged = {p.stem for p in STAGING.glob("*.md") if not p.name.startswith(".")} if STAGING.is_dir() else set()
    ids = {r["id"] for r in rows}
    print(f"  prompts in the DB        {len(rows)}")
    print(f"  translated (archived)    {len(archived & ids)}")
    print(f"  authored in Chinese      {len(zh_native & ids)}")
    print(f"  still English (pending)  {len(pending & ids)}")
    print(f"  staged, unvalidated      {len(staged & ids)}")
    unknown = sorted((archived | zh_native | pending) - ids)
    if unknown:
        print(f"  WARN: listed but not in the DB: {unknown}")
    unchinese = [r["id"] for r in rows if not reads_as_chinese(r["prompt"]) and r["id"] not in pending]
    if unchinese:
        print(f"  WARN: read as English but not pending: {unchinese}")
    return 0


def cmd_check(ids: list[str]) -> int:
    if not ids:
        ids = sorted({p.stem for p in STAGING.glob("*.md")}, key=int)
    rows = {r["id"]: r for r in run(_fetch())}
    rc = 0
    for prompt_id in ids:
        try:
            staged = staged_path(prompt_id)
            if not staged.is_file():
                raise Rejected(f"nothing staged at {staged.relative_to(REPO)}")
            english = english_source(prompt_id, rows)
            validate(prompt_id, english.read_text(encoding="utf-8"), staged.read_text(encoding="utf-8"))
            print(f"  ok      {prompt_id}  {rows.get(prompt_id, {}).get('name', '')}")
        except Rejected as exc:
            print(f"  REJECT  {prompt_id}: {exc}", file=sys.stderr)
            rc = 1
    return rc


def cmd_promote(ids: list[str]) -> int:
    rows = {r["id"]: r for r in run(_fetch())}
    pending = list_file(PENDING)
    zh_native = set(list_file(ZH_NATIVE))
    rc, done = 0, []
    for prompt_id in ids:
        try:
            staged = staged_path(prompt_id)
            if not staged.is_file():
                raise Rejected(f"nothing staged at {staged.relative_to(REPO)}")
            if prompt_id in zh_native:
                raise Rejected("listed in zh-native.txt — authored in Chinese, not a translation")
            archive = archive_path(prompt_id)
            if not archive.is_file():
                current = rows.get(prompt_id, {}).get("prompt", "")
                if not current or reads_as_chinese(current):
                    raise Rejected("nothing English to archive — refusing to overwrite it")
                ARCHIVE.mkdir(parents=True, exist_ok=True)
                archive.write_text(current, encoding="utf-8")
                print(f"  archived {prompt_id} → {archive.relative_to(REPO)}")
            zh = staged.read_text(encoding="utf-8")
            validate(prompt_id, archive.read_text(encoding="utf-8"), zh)
            run(_write_prompt(prompt_id, zh))
            staged.unlink()
            done.append(prompt_id)
            print(f"  promoted {prompt_id}  {rows.get(prompt_id, {}).get('name', '')}")
        except Rejected as exc:
            print(f"  REJECT  {prompt_id}: {exc}", file=sys.stderr)
            rc = 1
    if done:
        remaining = [i for i in pending if i not in set(done)]
        write_ids(PENDING, remaining, PENDING_HEADER)
        print(f"\n  pending-zh.txt: {len(pending)} → {len(remaining)}")
    return rc


def cmd_show(prompt_id: str, source: str) -> int:
    if source == "db":
        rows = run(_fetch([prompt_id]))
        print(rows[0]["prompt"] if rows else f"(no prompt {prompt_id} in the DB)")
    else:
        path = archive_path(prompt_id) if source == "archive" else staged_path(prompt_id)
        print(path.read_text(encoding="utf-8") if path.is_file() else f"(missing {path})")
    return 0


PENDING_HEADER = """# Prompts that are still English.
#
# A prompt is `deep_agent_templates.config->>'system_prompt'` — the text an agent is handed and the text the
# Prompts activity shows. Every prompt is in exactly one state, and `tests/test_prompt_translations.py` checks
# this file in both directions:
#
#   translated      Chinese in the DB, English frozen at backend/prompts/en-originals/<id>.md
#   zh-native.txt   written in Chinese from the start; there is no English original
#   pending         this file — English is what agents are being sent
#
# Move a prompt with `python scripts/prompt_zh.py promote <id>`, never by hand."""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["status", "check", "promote", "show"])
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--from", dest="source", choices=["db", "archive", "staged"], default="db")
    args = ap.parse_args(argv)

    if args.command == "status":
        return cmd_status()
    ids = [i for i in args.ids if i.isdigit()]
    if args.command == "check" and not args.ids:
        return cmd_check([])                 # every staged prompt
    if not ids:
        ap.error("name at least one prompt id (a deep_agent_templates id)")
    if args.command == "check":
        return cmd_check(ids)
    if args.command == "promote":
        return cmd_promote(ids)
    return cmd_show(ids[0], args.source)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
