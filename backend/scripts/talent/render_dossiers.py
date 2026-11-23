#!/usr/bin/env python3
"""把短名单上的候选人做成「HR 面完的档案」—— **每条结论都能指回原文或明确标成未知**。

## 这份档案要回答的问题

HR 拿到一份档案,想知道三件事:这个人是谁、他满足哪些要求、**还有哪些不知道**。
第三件最容易被写档案的人糊弄过去 —— 把"没读到"写成"不符合",或者把推断写成事实。
所以这份档案只有四种状态,和判定引擎完全一致:

    满足 / 不满足 / **未知**(简历里读不到) / 不可判(这条要求本身没有可用的数据项)

**未知绝不折成不满足**,也绝不编一个值填上。档案里"缺"的那几项,就是一面要问的问题。

## 数据从哪来

| 内容 | 来源 | 性质 |
|---|---|---|
| 年龄/学历/年限/专业 | `cv_facts.json`(LLM 抽取,带逐字引文) | 简历里写着的 |
| 工作段(公司/岗位名/起止/职责) | `parse_experience` 从正文切 | 简历里写着的 |
| 品质岗经历 | `cv_quality.json`(岗位名/职责的确定性判据) | 简历里写着的 |
| 每条 JD 要求的判定 | `evaluate` 的四态引擎 | **判定**,不是事实 |
| 短名单/目标名单里的位置 | `shortlist/*.yaml` | 流程产物 |

用法:
    python -m scripts.talent.render_dossiers --jd 品质经理
    python -m scripts.talent.render_dossiers --jd 品质经理 --only cand_廖___
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

from scripts.talent import evaluate as EV  # noqa: E402
from scripts.talent.cv_parse import parse_experience  # noqa: E402

EDU = {2: "中专/高中", 3: "大专", 4: "本科", 5: "硕士", 6: "博士"}
SHORTLIST = ROOT / "work" / "talent" / "shortlist"
CVTEXT = ROOT / "work" / "talent" / "cv_text"
OUTDIR = ROOT / "work" / "talent" / "cv_docs"


def _fact(entry: dict, key: str):
    v = (entry or {}).get(key) or {}
    return v.get("value"), v.get("basis"), v.get("quote")


def _segments(cid: str, facts: dict) -> list[dict]:
    src = str((facts.get(cid) or {}).get("source_file") or "")
    p = CVTEXT / f"{pathlib.Path(src).stem}.txt"
    if not p.is_file():
        return []
    try:
        return parse_experience(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []


def build(jd: str, rows: list[dict], tier_of: dict[str, str]) -> list[str]:
    """返回一份 md 的全文(10 人)。"""
    link = yaml.safe_load((EV.LINKS / f"{jd}.yaml").read_text(encoding="utf-8"))
    library = yaml.safe_load(EV.LIBRARY.read_text(encoding="utf-8"))
    catalog = yaml.safe_load(EV.CATALOG.read_text(encoding="utf-8"))
    reqs = {r["id"]: r for r in library["requirements"]}
    atts = {a["id"]: a for a in catalog["attributes"]}
    by_cat = collections.defaultdict(list)
    for c in catalog["components"]:
        by_cat[c["category"]].append(c["id"])
    for r in reqs.values():
        cats = r.get("categories") or []
        r["_resolved"] = (sorted({x for cat in cats for x in by_cat.get(cat, [])})
                          if cats else list(r.get("components") or []))

    facts = json.loads((ROOT / "work/talent/cv_facts.json").read_text(encoding="utf-8"))
    quality = json.loads((ROOT / "work/talent/cv_quality.json").read_text(encoding="utf-8"))
    cands = {c["id"]: c for c in EV.load_candidates()}
    EV.overlay_llm(list(cands.values()))
    EV.overlay_hr(list(cands.values()))

    L: list[str] = []
    A = L.append
    A(f"# {jd} · 短名单候选人档案({len(rows)} 人)")
    A("")
    A("> 每个人三种信息分开写:**简历里写着的** / **判定结果** / **还不知道的**。")
    A("> 四种状态:满足 · 不满足 · **未知**(简历读不到)· 不可判(这条要求没有可用的数据项)。")
    A("> **未知不折成不满足**,也不编值 —— 它就是一面要问的问题。")
    A("")
    A("| # | 候选人 | 定位 | 年龄 | 学历 | 年限 | 品质证据 | 已判可判 | 未知 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        cid = r["id"]; f = facts.get(cid, {}); q = quality.get(cid, {})
        age = _fact(f, "age")[0]; edu = _fact(f, "education_rank")[0]; yrs = _fact(f, "years")[0]
        A(f"| {i} | {cid.replace('cand_','')} | {tier_of.get(cid,'')} | {age or '—'} | "
          f"{EDU.get(edu,'—') if edu else '—'} | {yrs if yrs is not None else '—'} | "
          f"{q.get('kind') or '—'}档 {q.get('months') or 0}月 | {r['可判']}/10 | {r['未知']} |")
    A("")

    for i, r in enumerate(rows, 1):
        cid = r["id"]; f = facts.get(cid, {}); q = quality.get(cid, {}); cand = cands.get(cid, {})
        A(f"---\n\n## {i}. {cid.replace('cand_','')}")
        A("")
        A(f"**定位**:{tier_of.get(cid, '—')}")
        A("")
        A("### 简历里写着的")
        A("")
        for label, key in (("年龄", "age"), ("学历", "education_rank"), ("专业", "major"),
                           ("年限", "years"), ("性别", "gender")):
            val, basis, quote = _fact(f, key)
            if val is None:
                A(f"- **{label}**:读不到")
            else:
                shown = EDU.get(val, val) if key == "education_rank" else val
                A(f"- **{label}**:{shown}(依据 {basis}{';原文「' + str(quote)[:40] + '」' if quote else ''})")
        A("")
        segs = _segments(cid, facts)
        if segs:
            A("**工作段**(从正文切出):")
            A("")
            A("| 起止 | 公司 | 岗位名 | 该段月数 |")
            A("|---|---|---|---|")
            for s in segs[:6]:
                A(f"| {s.get('span') or '—'} | {str(s.get('company') or '')[:22]} | "
                  f"{str(s.get('title') or '')[:18] or '—'} | {q.get('months') if s.get('title') == q.get('title') else ''} |")
            A("")
        A("### 品质岗经历(确定性判据)")
        A("")
        if q.get("verdict") == "有":
            A(f"- 判定:**有**({q.get('kind')} 档)")
            A(f"- 岗位名「{q.get('title')}」· {q.get('company')} · {q.get('span')}")
            A(f"- 该段 {'%d 个月' % q['months'] if q.get('months_known') else '起止未读到(不按月判)'}")
            A(f"- 硬动作:{', '.join(q.get('hard') or []) or '—'};弱动作:{', '.join(q.get('weak') or []) or '—'}")
            A(f"- 原文:`{str(q.get('quote') or '')[:140]}`")
        else:
            A(f"- 判定:{q.get('verdict') or '无'} —— {q.get('why_short') or '岗位名与职责都没有品质动作'}")
        A("")
        A("### 对照 JD 的 10 条要求(判定结果)")
        A("")
        A("| 要求 | 客户原话 | 判定 | 依据 |")
        A("|---|---|---|---|")
        for c in link["citations"]:
            rid = c["requirement"]; req = reqs.get(rid, {})
            state, why = r["result"].get(rid, ("不可判", ""))
            mark = {"满足": "**满足**", "不满足": "**不满足**", "未知": "未知", "不可判": "不可判"}.get(state, state)
            A(f"| {rid} | 「{str(c.get('verbatim'))[:26]}」 | {mark} | {str(why)[:60]} |")
        A("")
        A("### 还不知道的(= 一面要问)")
        A("")
        unknown = [(rid, why) for rid, (st, why) in r["result"].items() if st == "未知"]
        if unknown:
            for rid, why in unknown:
                A(f"- **{rid}** {reqs.get(rid,{}).get('name','')}:{why}")
        else:
            A("- 无(这份要求的 10 条都能判)")
        A("")
        A(f"**小结**:可判 {r['可判']}/10 · 满足 {r['满足']} · 不满足 {r['不满足']} · "
          f"未知 {r['未知']} · 不可判 {r['不可判']}")
        A("")
    return L


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    ap.add_argument("--only", default="", help="只出某人(候选人 id)")
    args = ap.parse_args()

    tg_f = SHORTLIST / f"{args.jd}.目标名单.yaml"
    sl_f = SHORTLIST / f"{args.jd}.yaml"
    if not sl_f.is_file():
        print(f"先跑 screen_cv --jd {args.jd}")
        return 2
    sl = yaml.safe_load(sl_f.read_text(encoding="utf-8")) or {}
    tg = yaml.safe_load(tg_f.read_text(encoding="utf-8")) if tg_f.is_file() else {}
    blocked = {x["candidate"] for x in ((sl.get("quality_gate") or {}).get("blocked_by_other_requirements") or [])}

    ids = list(sl.get("kept") or [])
    ids = list(tg.get("selected") or ids)
    tier_of = {cid: ("需复议" if cid in blocked else "正式") for cid in ids}
    if args.only:
        ids = [i for i in ids if args.only in i]

    # 逐人判一遍(与 evaluate 同一条引擎)
    EV.UNDETECTABLE = EV.load_undetectable()
    link = yaml.safe_load((EV.LINKS / f"{args.jd}.yaml").read_text(encoding="utf-8"))
    library = yaml.safe_load(EV.LIBRARY.read_text(encoding="utf-8"))
    catalog = yaml.safe_load(EV.CATALOG.read_text(encoding="utf-8"))
    reqs = {r["id"]: r for r in library["requirements"]}
    atts = {a["id"]: a for a in catalog["attributes"]}
    by_cat = collections.defaultdict(list)
    for c in catalog["components"]:
        by_cat[c["category"]].append(c["id"])
    for r in reqs.values():
        cats = r.get("categories") or []
        r["_resolved"] = (sorted({x for cat in cats for x in by_cat.get(cat, [])})
                          if cats else list(r.get("components") or []))

    cands = {c["id"]: c for c in EV.load_candidates()}
    EV.overlay_llm(list(cands.values())); EV.overlay_hr(list(cands.values()))

    rows = []
    for cid in ids:
        cand = cands.get(cid)
        if cand is None:
            continue
        result = {}
        for c in link["citations"]:
            req = reqs[c["requirement"]]
            if not req.get("assessable"):
                state, why = "不可判", ("E 维无组件" if req.get("no_component") else "属性未建")
            elif req.get("_resolved"):
                live, blind = EV.split_detectable(req["_resolved"])
                state, why = EV.judge_component(cand["components"], live, req.get("match"))
                if blind:
                    why += f"(另有 {len(blind)} 项检不出)"
            elif req.get("attribute"):
                state, why = EV.judge_attribute(atts[req["attribute"]], req, c, cand, "")
            else:
                state, why = "不可判", "既无组件也无属性"
            result[c["requirement"]] = (state, why)
        rows.append({"id": cid, "result": result,
                     "满足": sum(1 for s, _ in result.values() if s == "满足"),
                     "不满足": sum(1 for s, _ in result.values() if s == "不满足"),
                     "未知": sum(1 for s, _ in result.values() if s == "未知"),
                     "不可判": sum(1 for s, _ in result.values() if s == "不可判"),
                     "可判": sum(1 for s, _ in result.values() if s in ("满足", "不满足"))})

    OUTDIR.mkdir(parents=True, exist_ok=True)
    out = OUTDIR / f"{args.jd}.候选人档案.md"
    out.write_text("\n".join(build(args.jd, rows, tier_of)) + "\n", encoding="utf-8")
    print(f"档案:{len(rows)} 人 → {out.relative_to(ROOT)}  {out.stat().st_size} B")
    for r in rows:
        print(f"  [{tier_of.get(r['id'],'')}] {r['id'].replace('cand_','')[:40]:42s} "
              f"可判 {r['可判']}/10 满足 {r['满足']} 不满足 {r['不满足']} 未知 {r['未知']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
