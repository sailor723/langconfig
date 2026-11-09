#!/usr/bin/env python3
"""Find and fix broken relative links between our own markdown files.

Why this exists: `docs/` was reorganised into `docs/system-architecture/` and `docs/installation/`,
and the links inside the documents were never updated. Measured 2026-11-09: 33 links still used the
pre-reorg flat layout (`docs/system-architecture.md` instead of
`docs/system-architecture/system-architecture.md`), 17 pointed into a `docs/reference/` tree that has
never existed, and 4 pointed at `plans/` documents that are not in the repo. Nothing failed — a broken
link in markdown is just text.

    ./scripts/docs_link_check.py            # report
    ./scripts/docs_link_check.py --fix      # rewrite the ones whose target is unambiguous
    ./scripts/docs_link_check.py --check    # exit 1 if anything is still broken (used by the tests)

Only links between OUR files are considered: `http(s)://`, `mailto:`, `#anchors` and absolute
site paths are ignored. The fix is deliberately conservative — it rewrites a link only when exactly
one file in the repository has the target's basename, so a rename is followed and a deletion is not
guessed at.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
from urllib.parse import unquote

#: Markdown links and images: [text](target) / ![alt](target). Bare `<path>` autolinks are ignored.
LINK = re.compile(r"(!?\[[^\]]*\]\()([^)\s]+)(\))")
IGNORE_PREFIX = ("http://", "https://", "mailto:", "tel:", "#", "/", "data:")


def _doc_files(root: pathlib.Path) -> list[pathlib.Path]:
    files = sorted(p for p in (root / "docs").rglob("*.md") if p.is_file())
    files += sorted(p for p in root.glob("*.md") if p.is_file())
    files += sorted(p for p in (root / "backend").glob("README.md"))
    return files


def _basename_index(root: pathlib.Path) -> dict[str, list[pathlib.Path]]:
    """filename -> every file in the repo with that name (docs and code alike)."""
    index: dict[str, list[pathlib.Path]] = {}
    skip = {".git", "node_modules", ".venv", "dist", ".uv-cache", "outputs", "data", "__pycache__"}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in skip for part in p.relative_to(root).parts):
            continue
        index.setdefault(p.name, []).append(p)
    return index


def _resolve(doc: pathlib.Path, target: str) -> pathlib.Path:
    """Where a link target points, ignoring any #anchor."""
    return (doc.parent / unquote(target.split("#", 1)[0])).resolve()


def _mask_fenced_blocks(text: str) -> str:
    """Blank out ``` fences (keeping byte offsets) so illustrative trees are not treated as links."""
    out, inside = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            inside = not inside
            out.append(" " * len(line))
            continue
        out.append(" " * len(line) if inside else line)
    return "\n".join(out)


def scan(root: pathlib.Path) -> list[dict]:
    findings: list[dict] = []
    index = _basename_index(root)
    for doc in _doc_files(root):
        text = doc.read_text(encoding="utf-8")
        masked = _mask_fenced_blocks(text)
        for m in LINK.finditer(masked):
            target = m.group(2)
            if target.startswith(IGNORE_PREFIX):
                continue
            rel_target = target.split("#", 1)[0]
            if not rel_target:
                continue
            dest = _resolve(doc, target)
            if dest.exists():
                continue
            name = pathlib.Path(unquote(rel_target)).name
            candidates = [c for c in index.get(name, []) if c.is_file()]
            findings.append({
                "doc": doc, "target": target, "anchor": target[len(rel_target):],
                "name": name, "candidates": candidates,
                "line": text[:m.start()].count("\n") + 1,
            })
    return findings


def new_target(doc: pathlib.Path, finding: dict) -> str | None:
    """The replacement link, when exactly one file in the repo answers to that basename."""
    candidates = [c for c in finding["candidates"] if c.is_file()]
    if len(candidates) != 1:
        return None
    import os

    relative = os.path.relpath(candidates[0], doc.parent).replace(os.sep, "/")
    return unquote(relative) + finding["anchor"]


def fix(root: pathlib.Path, findings: list[dict]) -> tuple[list[dict], list[dict]]:
    """Rewrite the unambiguous links in place; return (fixed, still-broken)."""
    fixed: list[dict] = []
    unfixable: list[dict] = []
    by_doc: dict[pathlib.Path, list[dict]] = {}
    for f in findings:
        replacement = new_target(f["doc"], f)
        if replacement is None:
            unfixable.append(f)
            continue
        f["replacement"] = replacement
        by_doc.setdefault(f["doc"], []).append(f)

    for doc, items in by_doc.items():
        text = doc.read_text(encoding="utf-8")
        for f in items:
            text = text.replace(f"]({f['target']})", f"]({f['replacement']})")
        doc.write_text(text, encoding="utf-8")
        fixed.extend(items)
    return fixed, unfixable


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Broken relative links between our markdown files.")
    ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    ap.add_argument("--fix", action="store_true", help="rewrite links whose target is unambiguous")
    ap.add_argument("--check", action="store_true", help="exit 1 when anything is broken")
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root).resolve()

    findings = scan(root)
    if args.fix:
        fixed, unfixable = fix(root, findings)
        print(f"fixed {len(fixed)} link(s):")
        for f in fixed:
            print(f"  {f['doc'].relative_to(root)}:{f['line']}  {f['target']} -> {f['replacement']}")
        findings = scan(root)                    # re-scan: what is left?
        print(f"\nstill broken: {len(findings)}")

    if not findings:
        print("no broken relative links")
        return 0
    for f in findings:
        print(f"  {f['doc'].relative_to(root)}:{f['line']}  {f['target']}"
              + (f"   (candidates: {len(f['candidates'])})" if f["candidates"] else "   (no such file)"))
    if args.check:
        print(f"\n{len(findings)} broken link(s)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
