"""What a translation may not lose: identifiers, numbers, URLs, paths — and code blocks.

`tests/test_skill_translations.py` proves a translation is *shaped* like its original (same `##` headings, same
fence count, dense enough Chinese, frontmatter pointing at the archive, the loader parses it). Every one of
those can hold while the words are wrong, and no test looked at the words.

This one looks at the part of "wrong" that a machine can see. It compares each translated skill to its archived
original and fails on:

1. **a lost hard token** — an identifier, a number, a URL or a real path present in the English prose and absent
   from the Chinese. `scripts/skill_translation_fidelity.py` sorts tokens into `hard` (data — anything with an
   underscore, digit, inner capital, ALLCAPS run, URL or path shape) and `soft` (English phrases that sat in
   backticks, such as `back/forward`, which the translator is *supposed* to render as 前进/后退). Only hard
   losses fail here; the soft ones are the job being done.
2. **changed code** — a fenced block whose info string says it is code (`python`, `bash`, `ts`, `json`, …) and
   whose body differs from the original. A changed `markdown` or unlabelled block is a document template, which
   the library translates on purpose, so it is not a failure.

Measured when it was written: the first run over 101 pairs found three real defects — `implement` had lost its
provenance block entirely, `edit-ontology-metrics` still said `atRiskDriver` after the English had become
`atRiskDrivers`, and four skills called the verification floor 本仓库的地板 where 54 called it 本仓库的底线.

Meaning is still not machine-checkable. A skill can keep every token and lose the argument; that is what a
reviewer reads for, and this file does not claim otherwise.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from skill_translation_fidelity import BUILTIN, ARCHIVE, check, severity  # noqa: E402


def _translated() -> list[str]:
    if not ARCHIVE.is_dir():
        return []
    return sorted(d.name for d in ARCHIVE.iterdir()
                  if (d / "SKILL.md").is_file() and (BUILTIN / d.name / "SKILL.md").is_file())


@pytest.mark.parametrize("skill_id", _translated(), ids=str)
def test_no_identifier_number_url_or_path_was_lost(skill_id: str):
    missing, _, errors = check(skill_id, False)
    assert not errors, errors
    lost = [token for token in missing if severity(token) == "hard"]
    assert not lost, (
        f"{skill_id}: the English prose has these and the Chinese does not: {lost[:8]} — an identifier, number, "
        "URL or path that vanished from a procedure is a procedure that now does something else")


@pytest.mark.parametrize("skill_id", _translated(), ids=str)
def test_no_code_block_was_translated(skill_id: str):
    _, fences, errors = check(skill_id, True)
    assert not errors, errors
    changed = [note for note in fences if note.startswith("CODE CHANGED")]
    assert not changed, (
        f"{skill_id}: a fenced block whose info string says it is code differs from the original:\n  "
        + "\n  ".join(changed[:4]))
