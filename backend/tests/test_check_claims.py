"""Numbers in prose need a source — the three failures this gate exists for were all prose numbers.

Measured 2026-11-26 (three builds):
* 「`c_name` 不唯一，15,000 客户被压成 10,000 组」 — false; only 10,000 customers HAVE orders;
* 「末 90 天 = 5,762 单」 — the same build later measured 5,688 and could not reproduce 5,762;
* a STRUCTURE file carried two `:businessDescription` literals on one subject (both "written").

A number a reader acts on must name where it came from. A count of the ARTEFACT (lines, classes,
triples) is its own proof and must NOT be flagged — noise is how a gate gets switched off.
"""
from __future__ import annotations

import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from scripts.check_claims import check_text  # noqa: E402


def test_a_data_number_without_a_source_is_flagged():
    findings = check_text("退货 148,301 行，占 24.69%。", where="x.md")
    assert findings, "a bare row count and percentage must be flagged"
    assert {f["number"] for f in findings} >= {"148,301", "24.69"}


def test_a_number_with_a_source_marker_is_accepted():
    for line in ("退货 148,301 行（metric: returnedLines）。",
                 "退货 148,301 行（sql: select count(*) from lineitem where l_returnflag='R'）。",
                 "退货 148,301 行（table: lineitem.l_returnflag）。",
                 "退货 148,301 行（Q2 裁定：只算 R）。",
                 "行数 600,572（anchor: 文件自带行数）。"):
        assert not check_text(line, where="x.md"), f"should pass: {line}"


def test_a_source_on_the_line_above_counts():
    text = "依据 sql: select count(*) from lineitem\n共 600,572 行。"
    assert not check_text(text, where="x.md")


def test_artefact_counts_are_not_claims():
    for line in ("01-structure.ttl 共 281 行，8 类 / 61 条属性，152 triple。",
                 "S1 那份门禁 93 checks 全绿。"):
        assert not check_text(line, where="x.md"), f"artefact count flagged: {line}"


def test_dates_ports_and_versions_are_not_claims():
    # a date, an IP:port and a version are identifiers, not measurements
    assert not check_text("2026-11-26 定案；库在 127.0.0.1:5432，版本 tpch_sales_v3。", where="x.md")


def test_a_window_is_a_claim_and_needs_its_source():
    # "36,500 天" is a guardrail parameter — a reader acts on it, so it names where it came from
    assert check_text("窗口 default_window_days 36,500 天。", where="x.md")
    assert not check_text("窗口 default_window_days 36,500 天（sql: profile guard 配置）。", where="x.md")
