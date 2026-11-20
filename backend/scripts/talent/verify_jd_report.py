#!/usr/bin/env python3
"""交付前回检:把一份 JD 的**事实**重新算一遍,再和"报告里说的"对账。

为什么需要这一步(不是走形式):
    agent 386 交过一份报告,里面同时有**真的**和**假的**:
      · 真的:门禁 161 checks 全绿、HermiT 实测 114/108/99、引用 15 条
      · 假的:_source「7 行」(实际 48)、"有一行含『建立/维护质量体系』与『主导内审』"
        (这份 JD 没有这句)、"excluded 的是一条抬头标题"(实际是 IATF16949)
    三类假话的共同点:**它们都是"从记忆里写的",而记忆来自另一份 JD 或上一轮**。
    所以回检只做一件事:**每个数字现场重算,每句"原文有 X"现场 grep**。

它不解释、不评价文风,只输出一张「主张 → 实测 → 结论」的表。
人(或 agent)拿自己的报告逐行对,对不上的就是假的。

    cd backend && .venv/bin/python -m scripts.talent.verify_jd_report --jd 品质经理

退出码:0 全部对得上 / 1 有对不上的 / 2 文件缺失
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

LINKS = ROOT / "work" / "talent" / "jd_links"
DOCS = ROOT / "work" / "talent" / "jd_docs"


def _gate_summary() -> tuple[str, str]:
    """现场跑门禁,取汇总行。**没有汇总行 = 未完成,不算绿。**"""
    env_cmd = [sys.executable, "-m", "scripts.talent.check_component_catalog"]
    run = subprocess.run(env_cmd, cwd=str(BACKEND), capture_output=True, text=True,
                         timeout=600, env={**__import__("os").environ, "PGPORT": ""})
    out = (run.stdout or "") + (run.stderr or "")
    line = next((ln.strip() for ln in reversed(out.splitlines())
                 if re.search(r"\d+ checks · \d+ failed", ln)), "")
    return line, out


def collect(jd: str) -> dict:
    """把一份 JD 的事实全算一遍,返回 {rows, bad, gate, ok}。

    这个函数是**唯一实现**:CLI(`main`)和 native tool(`talent_verify_jd_report`)
    都调它。回检这件事最怕两种实现给两个答案。
    """

    yml = LINKS / f"{jd}.yaml"
    src = LINKS / "_source" / f"{jd}.txt"
    if not yml.is_file():
        return {"rows": [], "bad": [], "gate": "", "ok": False,
                "error": f"缺 {yml.relative_to(ROOT)}（这份 JD 还没起草）"}
    doc = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
    text = src.read_text(encoding="utf-8") if src.is_file() else ""
    # 用 splitlines():`split("\n")` 在末尾换行处会多出一个空元素,
    # 报出来比 `wc -l` 多 1 —— 回检的数字必须和人对得上,不然它自己就成了噪音源。
    lines = text.splitlines()

    cites = doc.get("citations") or []
    client = [c for c in cites if c.get("origin", "client") == "client"]
    hr = [c for c in cites if c.get("origin") == "hr"]

    rows: list[tuple[str, str, str]] = []   # (主张, 实测, 结论)

    def add(claim: str, measured: str, ok: bool) -> None:
        rows.append((claim, measured, "✅ 一致" if ok and not measured.startswith("!") else
                     ("⚠ 仅注意" if ok else "❌ 不一致")))

    # ── 文件规模:_source 有多少行。报告里最常见的假数字就是它。
    add("原文行数", f"{len(lines)} 行", True)

    # ── 引用计数(客户 / HR / 合计 / 声明值)
    declared = (doc.get("count") or {}).get("atomic_requirements")
    add("客户端引用条数", f"{len(client)} 条", len(client) > 0)
    add("HR 侧引用条数", f"{len(hr)} 条", True)
    add("合计 = 声明值", f"{len(cites)} vs count.atomic_requirements={declared}",
        declared == len(cites))

    # ── 每条客户引用:verbatim 必须是原文逐字子串,且 txt_line 是真实行号
    bad_sub, bad_line = [], []
    for c in client:
        v = c.get("verbatim") or ""
        if v not in text:
            bad_sub.append(c["id"])
            continue
        n = c.get("txt_line")
        if n and (n < 1 or n > len(lines) or v not in lines[n - 1]):
            bad_line.append((c["id"], n))
    add("每条 verbatim 都在原文里", f"不符 {len(bad_sub)} 条 {bad_sub[:3]}", not bad_sub)
    add("每条 txt_line 行号真实", f"不符 {len(bad_line)} 条 {bad_line[:3]}", not bad_line)

    # ── HR 侧引用:不许冒充客户原话,必须有 author + rationale
    fake = [c["id"] for c in hr if any(k in c for k in ("verbatim", "txt_line", "source_text"))]
    thin = [c["id"] for c in hr if not c.get("author") or not c.get("rationale")]
    add("HR 引用不冒充客户原话", f"违规 {len(fake)} 条", not fake)
    add("HR 引用都有 author+rationale", f"缺 {len(thin)} 条 {thin[:3]}", not thin)

    # ── excluded:编号与理由
    exc = doc.get("excluded") or []
    names = ", ".join(f"{e.get('id')}={e.get('candidate_text')}" for e in exc) or "(无)"
    add("excluded 条目", names, True)

    # ── 门禁汇总行:没有这一行 = 未完成
    summary, raw = _gate_summary()
    add("门禁汇总行", summary or "!没有汇总行(门禁中途崩了或没跑)", bool(summary))
    if summary:
        m = re.match(r"(\d+) checks · (\d+) failed", summary)
        if m:
            add("门禁失败数", f"{m.group(2)}", m.group(2) == "0")

    # ── 定稿是否与本引用文件同批(条数对齐)
    fields = DOCS / f"{jd}.fields.json"
    if fields.is_file():
        try:
            import json
            fj = json.loads(fields.read_text(encoding="utf-8"))
            s3 = str(fj).count("S3.") or 0
            add("定稿 fields.json 存在", f"{fields.name}(S3 提及 {s3} 次)", True)
        except Exception as e:
            add("定稿 fields.json 可读", f"!{type(e).__name__}", False)

    bad = [r for r in rows if r[2].startswith("❌")]
    return {"rows": rows, "bad": bad, "gate": summary, "ok": not bad, "jd": jd}


def render(result: dict) -> str:
    """人看的表。CLI 和工具输出都用它,格式统一。"""
    if result.get("error"):
        return result["error"]
    rows, bad = result["rows"], result["bad"]
    w = max((len(a) for a, _, _ in rows), default=10)
    out = [f"# 回检 · {result.get('jd','')}", ""]
    for claim, measured, verdict in rows:
        out.append(f"  {claim:<{w}}  {measured:<46} {verdict}")
    out.append(f"\n{len(rows)} 项 · 不一致 {len(bad)} 项")
    if bad:
        out.append("\n**对不上的项:把你报告里对应的数字/句子改掉,或删掉。**")
        for claim, measured, _ in bad:
            out.append(f"  · {claim} → 实测 {measured}")
    else:
        out.append("全部对得上。可以交付。")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    args = ap.parse_args()
    result = collect(args.jd)
    print(render(result))
    if result.get("error"):
        return 2
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
