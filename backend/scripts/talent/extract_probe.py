#!/usr/bin/env python3
"""探针：用**扩展词表**（`skill_patterns_ext.py`）在已 OCR 的 CV 上再抽一遍，看不可评估的要求能不能解开。

为什么不直接改生产管线：`parse.py` 的 29 条词表一旦扩，`talent_v1` 的 ABox 全部要重建、
`candidate_skill` 换一套、`check_abox_sync` 立刻变红。先用探针量出收益，再决定是否采纳——
与 `ontology_publish` 的 stage → apply 是同一个纪律。

它读 OCR 缓存（`extract.py` 用内容哈希做键，所以缓存可复用、可重跑）。

用法：
    python -m scripts.talent.extract_probe \
        --cv-root client/team-4/unzipped/简历307份 \
        --cache /tmp/talent_probe/ocr-cache \
        --jsonl /tmp/talent_probe/all.jsonl
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import re
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from scripts.talent.skill_patterns_ext import EXTENDED_SKILL_PATTERNS  # noqa: E402


def sha_of(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cv-root", required=True)
    ap.add_argument("--cache", default="/tmp/talent_probe/ocr-cache")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--lang", default="chi_sim+eng")
    ap.add_argument("--out", default="", help="把 (candidate, skill, category, span) 写成 jsonl")
    args = ap.parse_args()

    cache = pathlib.Path(args.cache)
    root = pathlib.Path(args.cv_root)
    key_suffix = f"-{args.dpi}-{args.lang.replace('+','_')}"

    pdfs = sorted(root.rglob("*.pdf"))
    found_text = 0
    per_skill: dict[str, set[str]] = collections.defaultdict(set)
    spans: list[tuple[str, str, str, str]] = []

    for pdf in pdfs:
        cand = pdf.stem
        cached = cache / f"{sha_of(pdf)[:32]}{key_suffix}.txt"
        if not cached.is_file():
            continue
        found_text += 1
        text = cached.read_text(encoding="utf-8", errors="replace")
        for canon, category, pattern, _ev in EXTENDED_SKILL_PATTERNS:
            m = re.search(pattern, text, re.I)
            if not m:
                continue
            per_skill[canon].add(cand)
            lo, hi = max(0, m.start() - 18), min(len(text), m.end() + 18)
            spans.append((cand, f"skill_{canon}", category, text[lo:hi].replace("\n", " ")))

    total = len(pdfs)
    print(f"CV 总数 {total} · 有 OCR 缓存 {found_text}"
          f"（{100*found_text/total:.0f}%）\n")
    print(f"{'技能':18s} {'类别':18s} {'命中':>6s} {'占比':>6s}")
    print("-" * 58)
    for canon, category, _p, _e in EXTENDED_SKILL_PATTERNS:
        n = len(per_skill[canon])
        if n:
            print(f"{canon:18s} {category:18s} {n:>6d} {100*n/max(found_text,1):>5.0f}%")
    zero = [c for c, _c, _p, _e in EXTENDED_SKILL_PATTERNS if not per_skill[c]]
    print("-" * 58)
    print(f"零命中 {len(zero)}/{len(EXTENDED_SKILL_PATTERNS)}：{zero}")

    if args.out:
        out = pathlib.Path(args.out)
        with out.open("w", encoding="utf-8") as fh:
            for row in spans:
                fh.write(json.dumps(
                    {"candidate": row[0], "skill": row[1], "category": row[2], "span": row[3]},
                    ensure_ascii=False) + "\n")
        print(f"\n证据片段已写 {len(spans)} 行 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
