"""Docs guard — every relative link between our own markdown files must resolve.

Why: `docs/` was reorganised into `docs/system-architecture/` and `docs/installation/`, and the links
inside the documents were never updated. Measured 2026-11-09: 33 links still used the pre-reorg flat
layout, 17 pointed into a `docs/reference/` tree that never existed, and 4 pointed at `plans/`
documents that are not in the repository. Nothing failed, because a broken link in markdown is just
text — which is exactly why it needs a test rather than a habit.

The scanner is `scripts/docs_link_check.py` (same code the fixer uses). It ignores external URLs,
anchors, and anything inside a fenced code block — an illustrative tree in a design note is not a link
someone can click.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "docs_link_check.py"


@pytest.fixture(scope="module")
def linkcheck():
    spec = importlib.util.spec_from_file_location("docs_link_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["docs_link_check"] = module
    spec.loader.exec_module(module)
    return module


def test_no_broken_relative_links_between_our_docs(linkcheck):
    findings = linkcheck.scan(REPO)
    if not findings:
        return
    lines = [f"{f['doc'].relative_to(REPO)}:{f['line']}  {f['target']}" for f in findings[:20]]
    pytest.fail(
        f"{len(findings)} relative link(s) point at a file that does not exist:\n  "
        + "\n  ".join(lines)
        + "\n\nfix the unambiguous ones with: ./scripts/docs_link_check.py --fix\n"
          "and unlink the rest in prose (a link that can never resolve is worse than a name)")


def test_the_checker_ignores_fenced_examples(linkcheck, tmp_path):
    """A design note that draws a directory tree must not be read as a set of links."""
    doc = tmp_path / "docs" / "example.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "# example\n\n"
        "Real link: [exists](example.md)\n\n"
        "```md\n"
        "bundle/\n  metrics/revenue.md\n  tables/orders.md\n"
        "see [nothing](../tables/orders.md)\n"
        "```\n",
        encoding="utf-8",
    )
    findings = linkcheck.scan(tmp_path)
    assert [f["target"] for f in findings] == [], "links inside a fence must be ignored"


def test_the_checker_finds_a_link_to_a_file_that_is_gone(linkcheck, tmp_path):
    doc = tmp_path / "docs" / "a.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("[gone](system-architecture.md)\n", encoding="utf-8")
    findings = linkcheck.scan(tmp_path)
    assert len(findings) == 1 and findings[0]["target"] == "system-architecture.md"


def test_a_renamed_target_is_found_by_basename(linkcheck, tmp_path):
    """The fixer must be able to follow a file that moved into a subdirectory — but only when the
    basename is unique, which is what keeps it from guessing."""
    (tmp_path / "docs" / "system-architecture").mkdir(parents=True)
    moved = tmp_path / "docs" / "system-architecture" / "system-architecture.md"
    moved.write_text("# moved\n", encoding="utf-8")
    doc = tmp_path / "docs" / "a.md"
    doc.write_text("[it](system-architecture.md)\n", encoding="utf-8")

    findings = linkcheck.scan(tmp_path)
    assert len(findings) == 1
    assert linkcheck.new_target(doc, findings[0]) == "system-architecture/system-architecture.md"
