#!/usr/bin/env python3
"""算出 HR 侧要求要用的那几个量:任职段数、近 5 年段数、平均在职、到岗周数。

为什么单独一个脚本:这几个量**不是简历里写的**,是从简历推出来的。
推出来的东西必须能和原文对账,所以每个值都带 evidence(用了哪几段、哪几行)。

四个量:
    segment_count        任职段数        —— 从「工作经历」里切出的起止段数
    recent5y_segments    近 5 年段数     —— 同一批段,裁到最近 5 年窗口
    avg_tenure_years     平均在职年数    —— 各段时长均值
    notice_weeks         到岗周数        —— 简历头「到岗日期」归一成周

哪些能用、哪些不能,是**量出来的**不是猜的(270 份):
    段数 / 平均在职   243 份(90%)   —— 可以用
    到岗周数           11 份( 4%)   —— 基本只能一面问
    薪资              160 份(58%)   —— 平台归档有,但不是简历自述

口径必须写明,否则这几个数字会互相污染:
    * 段数来自**正则切出的起止**,不是候选人自述的"我在几家公司做过"
    * 「至今」按 REF 月算(语料最新记录到 2026 年,REF 取 2026-11)
    * 时长按**月数**相减,不按天数 —— 简历只给到月
    * 切不出起止的段不计入;一份都切不出的人,四个量全部留空(不填 0)
      —— 填 0 会被下游当成"零在职",那是凭空判人不合格

用法:
    python -m scripts.talent.derive_hr_facts
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

TEXT = ROOT / "work" / "talent" / "cv_text"
OUT = ROOT / "work" / "talent" / "hr_facts.json"

#: 「至今」按这个月算。语料里最新的记录到 2026 年,所以取 2026-11。
#: 这是一个**决定**,不是事实 —— 换 REF 会改变所有在岗人的段时长与近 5 年窗口。
REF_YEAR, REF_MONTH = 2026, 11
REF_M = REF_YEAR * 12 + REF_MONTH - 1

from scripts.talent.cv_parse import parse_experience  # noqa: E402

#: 「至今」按这个月算。语料里最新的记录到 2026 年,所以取 2026-11。
#: 这是一个**决定**,不是事实 —— 换 REF 会改变所有在岗人的段时长与近 5 年窗口。
REF_YEAR, REF_MONTH = 2026, 11
REF_M = REF_YEAR * 12 + REF_MONTH - 1

#: 到岗写法的归一。「随时」=0 周;「一个月」=4 周;没写 = None(不是 0)
NOTICE = [("随时", 0.0), ("立刻", 0.0), ("即时", 0.0), ("马上", 0.0),
          ("一周", 1.0), ("1周", 1.0), ("两周", 2.0), ("2周", 2.0),
          ("半个月", 2.0), ("三周", 3.0), ("3周", 3.0), ("一个月", 4.0),
          ("1个月", 4.0), ("一个月内", 4.0), ("两个月", 8.0), ("2个月", 8.0),
          ("三个月", 12.0), ("3个月", 12.0)]


def _month(s: str) -> int | None:
    """把「2019年4月」「2019.04」「2019-4」「2019」都换成月序号。"""
    y = re.search(r"((?:19|20)\d{2})", s or "")
    if not y:
        return None
    mo = re.search(r"[.\-/年]\s*(\d{1,2})", s or "")
    return int(y.group(1)) * 12 + (int(mo.group(1)) - 1 if mo else 0)


def segments(text: str) -> list[dict]:
    """切出工作段,并把起止换成月序号算时长。

    切段用共享的 parse_experience(和渲染定稿同一个函数)—— 之前这里另写了一份,
    结果同一批语料一个切出 243 段、一个切出 95 段。同一件事不许有两份实现。
    """
    out = []
    for j in parse_experience(text):
        a = _month(j["start"])
        b = REF_M if j["end"] in ("至今", "现在") else _month(j["end"])
        if a is None or b is None or b < a:
            continue
        out.append({"start": j["start"], "end": j["end"], "months": b - a + 1,
                    "line": j["pos"] + 1, "company": j.get("company"),
                    "title": j.get("title")})
    return out


def notice_weeks(text: str) -> tuple[float | None, str]:
    m = re.search(r"到岗(?:日[期时]|时间)\s*[:：;；]?\s*([^\n]{0,12})", text)
    if not m:
        return None, "原文没有「到岗时间」这一项"
    raw = m.group(1).strip()
    for key, weeks in NOTICE:
        if key in raw:
            return weeks, f"原文「到岗…{raw}」"
    return None, f"原文写了「{raw}」,但读不出周数(不猜)"


def load_candidates() -> list[dict]:
    """候选人 id 与原文文件的对应关系,只能从库里取。

    踩过的坑:一开始拿文件名直接拼 id(`cand_` + 文件名主干),结果 abox 里的 id 是
    **清洗过的**(`cand_副总助理_东莞_8_13K_王___1年以内`,方括号空格换成下划线),
    270 个键只有 7 个对得上,HR 事实覆盖率看起来像"只有 7 个人有"。
    对不上不是数据没有,是我把两套名字当成一套了。
    """
    import psycopg2
    conn = psycopg2.connect(host=os.environ["ONTOLOGY_DB_HOST"],
                            port=int(os.environ["ONTOLOGY_DB_PORT"]), dbname="talent_db",
                            user=os.environ["ONTOLOGY_DB_USER"],
                            password=os.environ["ONTOLOGY_DB_PASSWORD"])
    with conn.cursor() as cur:
        cur.execute("select id, source_file from candidate order by id")
        rows = cur.fetchall()
    conn.close()
    return [{"id": r[0], "text": TEXT / (pathlib.Path(r[1]).stem[:80] + ".txt")} for r in rows]


def main() -> int:
    cands = load_candidates()
    facts: dict[str, dict] = {}
    stat = {"seg_ok": 0, "notice_ok": 0, "zero": 0, "no_text": 0}
    for cand in cands:
        cid, path = cand["id"], cand["text"]
        if not path.is_file():
            stat["no_text"] += 1
            facts[cid] = {}
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        segs = segments(text)
        weeks, why_n = notice_weeks(text)
        if segs:
            stat["seg_ok"] += 1
            total = sum(s["months"] for s in segs)
            recent = [s for s in segs
                      if (REF_M if s["end"] in ("至今", "现在") else _month(s["end"])) >= REF_M - 60]
            facts[cid] = {
                "segment_count": {"value": len(segs), "basis": "computed",
                                  "evidence": [f"第{s['line']}行 {s['start']}-{s['end']}"
                                               for s in segs]},
                "recent5y_segments": {"value": len(recent), "basis": "computed",
                                      "window": f"{REF_YEAR - 5}-{REF_MONTH:02d} 起",
                                      "evidence": [f"{s['start']}-{s['end']}" for s in recent]},
                "avg_tenure_years": {"value": round(total / len(segs) / 12, 1),
                                     "basis": "computed", "total_months": total},
            }
        else:
            stat["zero"] += 1
            facts[cid] = {}
        if weeks is not None:
            stat["notice_ok"] += 1
        facts[cid]["notice_weeks"] = {"value": weeks,
                                      "basis": "computed" if weeks is not None else "missing",
                                      "why": why_n}

    OUT.write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    n = len(cands)
    print(f"候选人 {n} 份(取自库,id 与 abox 同源)· REF = {REF_YEAR}-{REF_MONTH:02d}")
    print(f"  段数/平均在职可算  {stat['seg_ok']:3d} ({100*stat['seg_ok']/max(1,n):.0f}%)"
          f"   —— 切不出起止的 {stat['zero']} 份,留空不填 0")
    print(f"  到岗周数可读       {stat['notice_ok']:3d} ({100*stat['notice_ok']/max(1,n):.0f}%)"
          f"   —— 这条基本只能一面问")
    if stat["no_text"]:
        print(f"  ! 找不到原文的 {stat['no_text']} 份")
    print(f"写出 {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
