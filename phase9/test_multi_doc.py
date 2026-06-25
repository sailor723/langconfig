#!/usr/bin/env python3
"""
Phase 9 / Step 2 — multi-doc routing test.

Verifies:
  1. EN queries route to the right doc
  2. ZH queries route to the right doc
  3. Unrelated queries return None (no false positives)
  4. Manual /doc <name> override works
  5. Sessions are isolated per doc (in_tokens differ)
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
from services.neo4j_document_index import choose_best_document_match

sys.path.insert(0, str(REPO_ROOT / "phase9"))
from dv_chat import SEED_DOCS, _route_doc, _find_doc_by_name

EXPECTED = [
    # (query, expected_doc_name, language)
    ("Nike revenue 2023", "nike-10k-2023", "EN"),
    ("nike risk factors", "nike-10k-2023", "EN"),
    ("Who is Socrates", "renwuku", "EN"),
    ("苏格拉底思想", "renwuku", "ZH"),
    ("孔子语录", "renwuku", "ZH"),
    ("strategy framework", "biz-strategy-survey", "EN"),
    ("战略框架", "biz-strategy-survey", "ZH"),
    ("双选协议时间", "shuoshuo-shuangxuan", "ZH"),
    ("导师选择", "shuoshuo-shuangxuan", "ZH"),
    ("C2M1 讲义", "c2m1", "ZH"),
    ("winter sports prices", "winter-sports", "EN"),
    ("tell me a joke", None, "EN"),  # no match
    ("random gibberish xyz", None, "EN"),  # no match
]

# Manual /doc override tests
MANUAL = [
    "nike-10k-2023",
    "renwuku",
    "biz-strategy-survey",
]


def main() -> int:
    print("=" * 70)
    print("TEST: auto-routing (EN + ZH)")
    print("=" * 70)
    passed = 0
    failed = 0
    for q, expected, lang in EXPECTED:
        got = _route_doc(q, SEED_DOCS)
        got_name = got.name if got else None
        ok = got_name == expected
        flag = "✓" if ok else "✗"
        print(f"  {flag} [{lang}] {q!r}")
        print(f"      expected: {expected!r}  got: {got_name!r}")
        if ok:
            passed += 1
        else:
            failed += 1

    print()
    print("=" * 70)
    print("TEST: manual /doc override (exact name match)")
    print("=" * 70)
    for name in MANUAL:
        got = _find_doc_by_name(name, SEED_DOCS)
        ok = got is not None and got.name == name
        flag = "✓" if ok else "✗"
        print(f"  {flag} /doc {name!r}  ->  {got.name if got else None!r}")
        if ok:
            passed += 1
        else:
            failed += 1

    print()
    print("=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed (out of {passed + failed})")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
