#!/usr/bin/env python3
"""Every number a deliverable states must name where it came from.

    python -m scripts.check_claims work/tpch_sales_v3/NOTES.md work/tpch_sales_v3/grill.md
    python -m scripts.check_claims --json work/tpch_sales_v3/SPEC.md

Why this exists (measured, 2026-11-26): three separate builds produced prose numbers that were
wrong or unbacked, and every one of them was caught by a human reading the file, not by a gate:

* 「`c_name` 不唯一，15,000 客户被压成 10,000 组」 — false: `c_name` is unique; only 10,000
  customers HAVE orders. Same conclusion, opposite cause, and the cause is what a reader acts on.
* 「末 90 天 = 5,762 单」 — the same build later measured 5,688 and could not reproduce 5,762;
  the number had been published in prose before it was ever run.
* A STRUCTURE file carried two `:businessDescription` literals on one subject, so the gate's
  `g.value()` picked one at random — "both written" read as "which one wins is undefined".

So the rule this script enforces is narrow and mechanical: **a number in prose needs a source
marker on the same line (or the line above)** — one of

    metric: <name>        a declared metric
    sql: <…>              the query that produced it
    table: <table.column>  a physical column
    q:N / Q<N>            a grill decision it came from
    anchor                an anchor agreed outside the build (row counts from the file itself)
    measured:<path>       a sample/notes file that holds the number

Numbers that are NOT claims (versions, dates, ports, section numbers, hex digests, byte counts of
files that name themselves) are exempt — a check that flags `2026-11-26` would be noise, and noise
is how a gate gets switched off.

Exit: 0 every claim is sourced · 1 at least one number has no source · 2 usage/paths.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]

#: A number that is a CLAIM about the data — not a version, not a date, not a port.
_CLAIM = re.compile(r"(?<![\w.\-/])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
                    r"(行|单|笔|条|个|家|次|%|％|元|天|月|年|小时|倍)")

#: Markers that make a claim checkable. Deliberately loose on the marker's tail: what matters is
#: that a READER can follow it, not that it parses.
_MARKERS = re.compile(r"(metric\s*:|sql\s*:|table\s*:|:Q\d+|q\d+|Q\d+|anchor|measured\s*:|"
                      r"grill|锚点|依据|来源)", re.I)

#: Lines that are structurally not prose claims.
_SKIP_LINE = re.compile(r"^\s*(#|\||```|\$|>>>|-{2,}|={2,})")

#: Structural vocabulary: a count of lines / classes / properties / triples / checks is about the
#: ARTEFACT, and the artefact is its own proof — demanding a `sql:` marker for "281 行" is the noise
#: that gets a gate switched off. Data numbers (rows, orders, percentages, money, spans) are the
#: ones a reader acts on, and those are what this check is for.
_ARTEFACT_LINE = re.compile(r"(行（|行\)|\.ttl|\.md|\.py|\.json|类|属性|triple|checks|字节|B\)|"
                            r"条声明|列)", re.I)

#: A number inside these constructs is a code/identifier, not a claim.
_SKIP_INLINE = re.compile(r"`[^`]*`|https?://\S+|\b[0-9a-f]{16,}\b|\b\d{4}-\d{2}-\d{2}\b|"
                          r"\b\d{1,3}(?:\.\d{1,3}){3}\b|:\d{2,5}\b")


def _strip_inline(line: str) -> str:
    """Remove the spans where a number means something else (code, URLs, dates, IPs, ports)."""
    return _SKIP_INLINE.sub(" ", line)


def check_text(text: str, *, where: str = "") -> list[dict]:
    """Find claim-looking numbers with no source marker on their line or the line above."""
    out: list[dict] = []
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        if _SKIP_LINE.match(raw):
            continue
        if _ARTEFACT_LINE.search(raw):
            continue
        stripped = _strip_inline(raw)
        claims = _CLAIM.findall(stripped)
        if not claims:
            continue
        window = raw + "\n" + (lines[i - 1] if i else "")
        if _MARKERS.search(window):
            continue
        for number, unit in claims:
            out.append({"file": where, "line": i + 1, "number": number, "unit": unit,
                        "text": raw.strip()[:160]})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="files to check (.md / .txt / .json prose)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    findings: list[dict] = []
    read = 0
    for raw in args.paths:
        p = pathlib.Path(raw).expanduser()
        if not p.is_absolute():
            p = (BACKEND / p) if (BACKEND / p).exists() else (pathlib.Path.cwd() / p)
        if not p.is_file():
            print(f"no such file: {p}", file=sys.stderr)
            return 2
        read += 1
        findings += check_text(p.read_text(encoding="utf-8", errors="ignore"), where=str(p))

    if args.as_json:
        print(json.dumps({"files": read, "unbacked": findings,
                          "ok": not findings}, ensure_ascii=False, indent=2))
    else:
        print(f"{read} file(s) · {len(findings)} number(s) with no source marker")
        for f in findings[:40]:
            print(f"  {pathlib.Path(f['file']).name}:{f['line']}  {f['number']}{f['unit']}"
                  f"   ← {f['text']}")
        if len(findings) > 40:
            print(f"  … and {len(findings) - 40} more")
        print()
        print("a claim needs `metric:` / `sql:` / `table:` / `Q<n>` / `anchor` on its line "
              "(or the line above). If the number is a measurement, say which query produced it.")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
