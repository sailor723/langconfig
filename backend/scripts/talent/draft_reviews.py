#!/usr/bin/env python3
"""代拟第 4b 步的 HR 评语 —— 写进 `cv_interview/<名>.yaml` 的 `review` 段。

## 为什么是「代拟」而不是「HR 写的」

4b 的评语来自**一面访谈**(`answers` 段里那 20 多问 20 多答)。这批候选人**还没面**,
所以这里写的每一段都来自**简历复核**,不是访谈。两者不能混:

    drafted_by: ours          ← 我方代拟
    needs_hr_confirm: true    ← HR 面完必须回来改
    not_in_computation: true  ← 不参与 join(与 4b 的规矩一致)
    joins: false

冒充 HR 说过话,是这条链上最贵的一类错 —— 业务领导会把"我方推断"当成"面过的印象"。

## 三段结构与 4b 同构(技能里写死的格式)

    heard        我看到的什么(可复述的事实:哪段、什么岗位名、原文怎么说)
    basis        我据此怎么判断(带数据:品质证据档位、四态计数、阈值比对)
    reservation  我保留什么(未知项、单一证据、OCR 风险、被哪条门槛卡住)

用法:
    python -m scripts.talent.draft_reviews --jd 品质经理
    python -m scripts.talent.draft_reviews --jd 品质经理 --only cand_廖   # 已有的不覆盖
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

from scripts.talent import evaluate as EV  # noqa: E402

CVINTERVIEW = ROOT / "work" / "talent" / "cv_interview"
FACTS = ROOT / "work" / "talent" / "cv_facts.json"
QUALITY = ROOT / "work" / "talent" / "cv_quality.json"
SHORTLIST = ROOT / "work" / "talent" / "shortlist"
EDU = {2: "中专/高中", 3: "大专", 4: "本科", 5: "硕士", 6: "博士"}


def _val(entry, key):
    v = (entry or {}).get(key) or {}
    return v.get("value") if isinstance(v, dict) else v




def _verdict_counts(jd: str, cid: str) -> tuple[dict, dict]:
    """这个人对这份 JD 的逐条判定(四态)。与 evaluate / render_dossiers 同一条引擎。"""
    import collections as _c

    EV.UNDETECTABLE = EV.load_undetectable()
    link = yaml.safe_load((EV.LINKS / f"{jd}.yaml").read_text(encoding="utf-8"))
    library = yaml.safe_load(EV.LIBRARY.read_text(encoding="utf-8"))
    catalog = yaml.safe_load(EV.CATALOG.read_text(encoding="utf-8"))
    reqs = {r["id"]: r for r in library["requirements"]}
    atts = {a["id"]: a for a in catalog["attributes"]}
    by_cat = _c.defaultdict(list)
    for c in catalog["components"]:
        by_cat[c["category"]].append(c["id"])
    for r in reqs.values():
        cats = r.get("categories") or []
        r["_resolved"] = (sorted({x for cat in cats for x in by_cat.get(cat, [])})
                          if cats else list(r.get("components") or []))

    cand = next((c for c in EV.load_candidates() if c["id"] == cid), None)
    if cand is None:
        return {}, {}
    EV.overlay_llm([cand]); EV.overlay_hr([cand])
    result = {}
    for c in link["citations"]:
        req = reqs[c["requirement"]]
        if not req.get("assessable"):
            state, why = "不可判", ("E 维无组件" if req.get("no_component") else "属性未建")
        elif req.get("_resolved"):
            live, blind = EV.split_detectable(req["_resolved"])
            state, why = EV.judge_component(cand["components"], live, req.get("match"))
        elif req.get("attribute"):
            state, why = EV.judge_attribute(atts[req["attribute"]], req, c, cand, "")
        else:
            state, why = "不可判", "既无组件也无属性"
        result[c["requirement"]] = (state, why)
    counts = _c.Counter(s for s, _ in result.values())
    return result, dict(counts)

def draft(cid: str, q: dict, f: dict, sl: dict, tg: dict) -> dict:
    """一个人 → 三段评语。全部由可核数据拼出来,不写没有依据的话。"""
    blocked = {x["candidate"]: x for x in
               ((sl.get("quality_gate") or {}).get("blocked_by_other_requirements") or [])}
    age = _val(f, "age"); edu = EDU.get(_val(f, "education_rank"), "—")
    yrs = _val(f, "years")
    kind = q.get("kind"); months = q.get("months") or 0
    hard = q.get("hard") or []; weak = q.get("weak") or []
    title = q.get("title") or ""; company = q.get("company") or ""
    quote = str(q.get("quote") or "")

    heard = (
        f"简历写到他在「{company}」担任「{title}」"
        + (f",该段 {months} 个月" if q.get("months_known") else ",该段起止没读出来")
        + f"；职责原文:`{quote[:110]}`。"
        + (f"另有弱动作 {', '.join(weak)}(业务/工程职责里也常见)。" if weak else "")
    )

    basis = (
        f"品质岗经历按确定性判据判为 **{q.get('verdict')}**({kind} 档):"
        + (f"岗位名本身在品质序列,不受时长限制。" if kind == "A"
           else f"职责含硬动作 {', '.join(hard) or '—'},且该段达到 24 个月门槛。")
        + f" 基本条件:年龄 {age if age is not None else '读不到'}、学历 {edu}、总年限 {yrs if yrs is not None else '读不到'}。"
    )

    res = []
    if cid in blocked:
        why = ";".join(f"{b['requirement']}({b['why']})" for b in blocked[cid]["blocked_by"])
        res.append(f"他被客户写的硬门槛挡住:{why} —— 要用他必须由客户先放宽那条,否则选上来也用不了。")
    if len(hard) <= 1 and kind == "B":
        res.append(f"只有 {len(hard)} 项硬动作({', '.join(hard) or '无'}),证据面窄;"
                   "是「做过这件事」还是「偶尔碰过」,简历层面分不清。")
    if months == 0:
        res.append("该段起止没读出,只能按岗位名/职责判,**月数无法验算**。")
    if q.get("verdict") != "有":
        res.append("品质岗经历无证据 —— 这不是「不会」,而是「简历没写」,一面必须问。")
    res.append("简历是 OCR 出来的,命中段可能有错字或串行;面试时要复核原文那句。")
    reservation = " ".join(f"({i}) {x}" for i, x in enumerate(res, 1))

    return {
        "joins": False,
        "not_in_computation": True,
        "drafted_by": "ours",
        "needs_hr_confirm": True,
        "basis_of": "简历复核(cv_facts + 工作段 + cv_quality),**不是访谈** —— 本候选人尚未一面",
        "heard": heard,
        "basis": basis,
        "reservation": reservation,
        "known_gaps": [
            f"JD 逐条判定({'/'.join(sorted(tg.get('result') or {})) or '—'}):"
            + " · ".join(f"{k} {v}" for k, v in (tg.get("counts") or {}).items())
            + f" —— 共 {len(tg.get('result') or {})} 条引用",
            "本文件没有 answers 段 —— 一面完成后 4a 落盘答案、这里的三段要按访谈重写",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--overwrite", action="store_true", help="覆盖**代拟**的 review(真访谈永远不覆盖)")
    ap.add_argument("--force-interview", action="store_true",
                    help="连真访谈的 review 也覆盖 —— 只在明确要重写时用")
    args = ap.parse_args()

    tg_f = SHORTLIST / f"{args.jd}.目标名单.yaml"
    sl_f = SHORTLIST / f"{args.jd}.yaml"
    sl = yaml.safe_load(sl_f.read_text(encoding="utf-8")) if sl_f.is_file() else {}
    tg = yaml.safe_load(tg_f.read_text(encoding="utf-8")) if tg_f.is_file() else {}
    q_all = json.loads(QUALITY.read_text(encoding="utf-8"))
    f_all = json.loads(FACTS.read_text(encoding="utf-8"))

    ids = list(tg.get("selected") or sl.get("kept") or [])
    if args.only:
        ids = [i for i in ids if args.only in i]

    CVINTERVIEW.mkdir(parents=True, exist_ok=True)
    made = skipped = 0
    for cid in ids:
        name = cid.replace("cand_", "")
        path = CVINTERVIEW / f"{name}.yaml"
        doc = {}
        if path.is_file():
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        # 有 answers 段 = **真的面过**。代拟稿永远不许覆盖它 —— 实测踩过:
        # `--overwrite` 把廖那份 21 问 21 答的真访谈评语盖掉了,只能从 git 捞回来。
        has_interview = bool(doc.get("answers"))
        if has_interview and not args.force_interview:
            skipped += 1
            print(f"  保留 {name[:40]:42s} 真访谈(answers {len(doc['answers'])} 条)—— 不覆盖")
            continue
        if doc.get("review") and not args.overwrite:
            skipped += 1
            continue
        doc.setdefault("candidate", cid)
        doc.setdefault("channel", "简历复核(无访谈)")
        doc.setdefault("date", datetime.date.today().isoformat())
        doc.setdefault("interviewer", "—")
        # 逐条判定结果(供评语引用)
        result, counts = _verdict_counts(args.jd, cid)
        doc["review"] = draft(cid, q_all.get(cid) or {}, f_all.get(cid) or {}, sl,
                              {"result": result, "counts": counts})
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100),
                        encoding="utf-8")
        made += 1
        print(f"  代拟 {name[:40]:42s} needs_hr_confirm={doc['review'].get('needs_hr_confirm')}")
    print(f"\n写入 {made} 份 · 跳过已有 {skipped} 份(廖那类真访谈的不覆盖)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
