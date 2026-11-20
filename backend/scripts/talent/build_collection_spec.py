#!/usr/bin/env python3
"""从 JD 反推**候选人必须交哪些数据**,再把每一项分派给 CV 或一面访谈。

为什么要反推,不顺着 CV 抽:大部分简历只有几行字,顺着抽只能抽出"这个人写了什么",
抽不出"这个岗需要什么"。顺着抽的后果是每份 CV 的字段集都不一样,join 的时候
一半人因为"没读到"被判成未知 —— 那不是候选人的问题,是采集计划没做。

所以顺序是:
    ① JD 原话            (jd_links,已逐字校验)
    ② 要求               (requirement_library,JD 无关)
    ③ 数据项             (属性 prop / 组件 component) ← 这一层才是 join 真正读的东西
    ④ 来源分派           (CV 有就 CV 拿,CV 稀薄就得一面问)
    ⑤ 问句 + 答案类型     (问完必须能写进同一个字段,否则问了也用不上)

分派是按**实测覆盖率**定的,不是拍的:每个数据项在 270 份 CV 里有多少人有值,
算出来才知道该不该指望 CV。覆盖率低的项一律走访谈 —— 不是"CV 优先,访谈兜底",
而是"CV 拿不到就别指望它,直接列进一面清单"。

用法:
    python -m scripts.talent.build_collection_spec --jd 品质经理
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]

import yaml  # noqa: E402

CATALOG = ROOT / "work" / "talent" / "component_catalog.yaml"
LIBRARY = ROOT / "work" / "talent" / "requirement_library.yaml"
LINKS = ROOT / "work" / "talent" / "jd_links"
FACTS = ROOT / "work" / "talent" / "cv_facts.json"
HR_FACTS = ROOT / "work" / "talent" / "hr_facts.json"
INTERVIEW = ROOT / "work" / "talent" / "cv_interview"
OUT = ROOT / "work" / "talent" / "collection"

TRUSTED = {"stated", "inferred", "computed"}
#: 属性 prop → cv_facts.json 里那一条的键
FACT_KEY = {"age": "age", "education_rank": "education_rank", "major": "major",
            "gender": "gender", "full_time": "full_time", "years_stated": "years"}
#: HR 视角的属性 prop → hr_facts.json 里那一条的键(derive_hr_facts 算出来的)
HR_KEY = {"notice_weeks": "notice_weeks", "recent5y_segments": "recent5y_segments",
          "avg_tenure_years": "avg_tenure_years"}

#: 覆盖率分档。阈值是分派规则的一部分,写在这里而不是散在代码里。
CV_SOLID, CV_THIN = 0.50, 0.10

EDU_NAME = {2: "中专/高中", 3: "大专", 4: "本科", 5: "硕士", 6: "博士"}

#: 属性 → 问句模板 + 答案要写成什么。{label} 是属性名,{verbatim} 是 JD 原话。
ASK = {
    "A.2": ("多大年纪?(或出生年月)", "整数年龄,写入 age"),
    "A.1": ("性别?(仅在该岗原话明确要求时记录)", "男/女,写入 gender"),
    "B.1": ("最高学历是什么?(中专/大专/本科/硕士/博士)", "学历档位,写入 education_rank(2..6)"),
    "B.2": ("所学专业是什么?大专、本科分别填", "专业名原文,写入 major"),
    "B.3": ("这几段学历里,哪几段是全日制?", "是与否,写入 full_time"),
    "A.3": ("最快什么时候能到岗?几周内?", "整数周(随时=0),写入 notice_weeks"),
    "A.4": ("能不能接受在这个地点上班?", "能/不能,写入 commute_ok"),
    "A.5": ("期望薪资多少?(月薪区间)", "区间上限,写入 salary_max_k(K/月)"),
    "C.7": ("把每一段工作经历的起止报一遍(近 5 年的尤其要说清)",
            "起止年月,累加段数写入 recent5y_segments"),
    "C.4": ("每段工作分别做了多久?", "起止年月,取均值得 avg_tenure_years"),
    "C.1": ("从事 {domain} 多少年?(只算 {domain})", "整数年,写入 years_stated"),
    "C.6": ("把每一段工作经历的起止报一遍", "起止年月,累加后写入 years_computed"),
}


def load() -> tuple[dict, dict, dict, dict]:
    cat = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    lib = {r["id"]: r for r in yaml.safe_load(LIBRARY.read_text(encoding="utf-8"))["requirements"]}
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    return cat, lib, facts, {a["id"]: a for a in cat["attributes"]}


def prop_coverage(facts: dict, prop: str) -> int:
    key = FACT_KEY.get(prop)
    if not key:
        return 0
    n = 0
    for d in facts.values():
        item = d.get(key) or {}
        if item.get("basis") in TRUSTED and item.get("value") is not None:
            n += 1
    return n


def hr_coverage(prop: str) -> int:
    """HR 那几个量在 270 份里能算出多少 —— 用实测,不用估。"""
    key = HR_KEY.get(prop)
    if not key or not HR_FACTS.is_file():
        return 0
    data = json.loads(HR_FACTS.read_text(encoding="utf-8"))
    return sum(1 for d in data.values()
               if (d.get(key) or {}).get("basis") == "computed"
               and (d.get(key) or {}).get("value") is not None)


def component_holders(facts: dict, labels: set[str]) -> int:
    n = 0
    for d in facts.values():
        held = {s["name"] for s in ((d.get("skills") or {}).get("value") or [])}
        if held & labels:
            n += 1
    return n


def items_for(req: dict, atts: dict) -> list[dict]:
    """一条要求 → 它需要的数据项。属性一条、组件 n 条、都没有就是"只能问"。"""
    att_id = req.get("attribute")
    if att_id:
        att = atts[att_id]
        return [{"kind": "property", "key": att.get("prop") or att_id,
                 "attach": att_id, "label": att["label"],
                 "prop_exists": att.get("prop_exists"),
                 "type": att.get("scale"), "cardinality": att.get("cardinality")}]
    comps = req.get("components") or []
    return [{"kind": "component", "key": c, "attach": c, "label": None,
             "prop_exists": True, "type": "boolean", "cardinality": "single"}
            for c in comps]


def candidate_state(cid: str, facts: dict, comp_by_id: dict) -> dict:
    """这个候选人现在手上有什么 —— CV 有算有,访谈补的也算有,但标出来源。

    「有没有」只认可信 basis(stated/inferred/computed);rejected 与
    computed_unverified 不算 —— 那是不该用来判的值,当成"没有"比当成"有"安全。
    """
    d = facts.get(cid) or {}
    state: dict[str, dict] = {}
    for prop, key in FACT_KEY.items():
        item = d.get(key) or {}
        ok = item.get("basis") in TRUSTED and item.get("value") is not None
        state[prop] = {"have": ok, "value": item.get("value"),
                       "basis": item.get("basis"), "from": "cv" if ok else None}
    # HR 那几个量是算出来的(derive_hr_facts),同样算"已经有"
    hr_all = json.loads(HR_FACTS.read_text(encoding="utf-8")) if HR_FACTS.is_file() else {}
    hd = hr_all.get(cid) or {}
    for prop, key in HR_KEY.items():
        item = hd.get(key) or {}
        ok = item.get("basis") == "computed" and item.get("value") is not None
        state[prop] = {"have": ok, "value": item.get("value"),
                       "basis": item.get("basis"), "from": "cv" if ok else None}
    # 薪资在平台归档里,不在简历里 —— 单独标出来源,免得跟"简历自述"混为一谈
    state.setdefault("salary_max_k", {"have": False, "value": None,
                                      "basis": None, "from": None})

    # HR 那几个量是算出来的(derive_hr_facts),同样算"已经有" ——
    # 不算的话,一面脚本会把"已经满足的项"再问一遍,而判定那边说它满足,两边打架
    hr_all = json.loads(HR_FACTS.read_text(encoding="utf-8")) if HR_FACTS.is_file() else {}
    hd = hr_all.get(cid) or {}
    for prop, key in HR_KEY.items():
        item = hd.get(key) or {}
        ok = item.get("basis") == "computed" and item.get("value") is not None
        state[prop] = {"have": ok, "value": item.get("value"),
                       "basis": item.get("basis"), "from": "cv" if ok else None}
    state.setdefault("salary_max_k", {"have": False, "value": None,
                                      "basis": None, "from": None})

    held = {s["name"] for s in ((d.get("skills") or {}).get("value") or [])}
    for cid2, comp in comp_by_id.items():
        state[cid2] = {"have": comp["label"] in held, "value": comp["label"] in held,
                       "basis": "stated", "from": "cv" if comp["label"] in held else None}

    iv_path = INTERVIEW / f"{cid.replace('cand_', '')}.yaml"
    if iv_path.is_file():
        iv = yaml.safe_load(iv_path.read_text(encoding="utf-8")) or {}
        raw_answers = iv.get("answers") or []
        # dict 按 field 建会**覆盖同名条目** —— 同一个字段问了两件事时(F.SKILL 既是
        # 品质问题分析又是 6S),前一条会被后一条吃掉。所以 establishes 走原列表。
        answers = {a["field"]: a for a in raw_answers}
        # 访谈答过的属性字段:按 field_schema 的映射落到 prop 上,只对还空着的生效
        PROP_OF_FIELD = {"F.AGE": "age", "F.EDU_LEVEL": "education_rank",
                         "F.EDU_MAJOR": "major", "F.GENDER": "gender",
                         "F.EDU_FULLTIME": "full_time", "F.EXP_YEARS": "years_stated"}
        for fid, prop in PROP_OF_FIELD.items():
            if fid in answers and not state[prop]["have"]:
                state[prop] = {"have": True, "value": answers[fid].get("answer"),
                               "basis": "interview", "from": "interview"}
        # 属性:answers 里的 props 显式声明"这条回答把哪个属性填成什么"
        for a in raw_answers:
            for prop, val in (a.get("props") or {}).items():
                if prop in state and not state[prop]["have"]:
                    state[prop] = {"have": True, "value": val,
                                   "basis": "interview", "from": "interview"}
        # 组件:@establishes 是采访人写进记录的,不是程序猜的
        for a in raw_answers:
            for comp_id in a.get("establishes") or []:
                if comp_id in state and not state[comp_id]["have"]:
                    state[comp_id] = {"have": True, "value": True, "basis": "interview",
                                      "from": "interview"}
    return state


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    ap.add_argument("--candidate", default="", help="给了就只列这个人还缺的数据项")
    args = ap.parse_args()

    cat, lib, facts, atts = load()
    link = yaml.safe_load((LINKS / f"{args.jd}.yaml").read_text(encoding="utf-8"))
    comp_by_id = {c["id"]: c for c in cat["components"]}
    total = len(facts)

    spec: list[dict] = []
    for c in link["citations"]:
        req = lib[c["requirement"]]
        items = items_for(req, atts)
        if not items:
            spec.append({
                "jd": args.jd, "citation": c["id"], "requirement": c["requirement"],
                "requirement_name": req.get("name"), "verbatim": c.get("verbatim"),
                "kind": "none", "value": c.get("value"),
                "data_item": None, "attach": None, "label": req.get("name"),
                "type": "text", "cardinality": "single", "prop_exists": False,
                "cv_holders": 0, "cv_coverage": 0.0, "source": "interview",
                "judge_ready": False,
                "library_says_assessable": bool(req.get("assessable")),
                "library_blocked_by": req.get("blocked_by") or "没有可判的数据项(E 维无组件)",
            })
            continue
        for it in items:
            if it["kind"] == "property":
                have = hr_coverage(it["key"]) or prop_coverage(facts, it["key"])
            else:
                have = component_holders(facts, {comp_by_id[it["key"]]["label"]})
            cov = have / total if total else 0.0
            if it["kind"] == "component" and cov < CV_THIN:
                src = "interview"
            elif cov >= CV_SOLID:
                src = "cv"
            elif cov >= CV_THIN:
                src = "cv_then_interview"
            else:
                src = "interview"
            spec.append({
                "jd": args.jd, "citation": c["id"], "requirement": c["requirement"],
                "requirement_name": req.get("name"), "verbatim": c.get("verbatim"),
                "kind": it["kind"], "value": c.get("value"),
                "data_item": it["key"], "attach": it["attach"],
                "label": it["label"] or comp_by_id.get(it["key"], {}).get("label"),
                "type": it["type"], "cardinality": it["cardinality"],
                "prop_exists": it["prop_exists"],
                "cv_holders": have, "cv_coverage": round(cov, 3),
                "source": src,
                # 数据在不在 ≠ 能不能判。库标了不可判(比如专业匹配规则没定)的,数据齐也判不了,
                # 这一栏就是为了让这两件事不再混在一起
                "judge_ready": bool(it["prop_exists"]) and (it["kind"] != "none"),
                "library_says_assessable": bool(req.get("assessable")),
                "library_blocked_by": req.get("blocked_by"),
            })

    # 一条要求归到一档:取它最难拿到的那一项。同一条要求不该在两档里各出现一次。
    RANK = {"cv": 0, "cv_then_interview": 1, "interview": 2}
    req_source: dict[str, str] = {}
    for s in spec:
        cur = req_source.get(s["requirement"])
        if cur is None or RANK[s["source"]] > RANK[cur]:
            req_source[s["requirement"]] = s["source"]
    for s in spec:
        s["req_source"] = req_source[s["requirement"]]

    OUT.mkdir(parents=True, exist_ok=True)
    yaml_out = OUT / f"{args.jd}.yaml"
    yaml_out.write_text(yaml.safe_dump(
        {"jd": link.get("jd"), "candidate_count": total, "thresholds": {
            "cv_solid": CV_SOLID, "cv_thin": CV_THIN},
         "count": {"citations": len(link["citations"]), "data_items": len(spec),
                   "cv": sum(1 for s in spec if s["source"] == "cv"),
                   "cv_then_interview": sum(1 for s in spec if s["source"] == "cv_then_interview"),
                   "interview": sum(1 for s in spec if s["source"] == "interview")},
         "items": spec},
        allow_unicode=True, sort_keys=False), encoding="utf-8")

    dist = collections.Counter(s["source"] for s in spec)
    by_req = collections.defaultdict(list)
    for s in spec:
        by_req[s["requirement"]].append(s)
    print(f"JD: {link.get('jd')} · {len(link['citations'])} 条要求 → {len(spec)} 个数据项"
          f"(语料 {total} 份)")
    print(f"  CV 直接拿   {dist['cv']:2d} 项")
    print(f"  CV 稀薄→问  {dist['cv_then_interview']:2d} 项")
    print(f"  只能访谈     {dist['interview']:2d} 项")
    print()
    for rid, its in by_req.items():
        worst = min(its, key=lambda x: x["cv_coverage"])
        print(f"{rid:24s} {lib[rid].get('name','')[:16]:18s} "
              f"覆盖最好 {max(x['cv_coverage'] for x in its)*100:3.0f}% "
              f"最差 {worst['cv_coverage']*100:3.0f}% · "
              f"{'/'.join(sorted({x['source'] for x in its}))}")
    # ── 给人看的清单:分三段,因为问法和责任方都不一样
    def question(req_rows: list[dict]) -> tuple[str, str]:
        """一个要求只问一次 —— 六个组件问六遍同一句话,一面问不下来,HR 也不会那么问。"""
        s = req_rows[0]
        comps = [r["label"] for r in req_rows if r["kind"] == "component"]
        att = s["attach"] if s["kind"] == "property" else None
        if att and att in ASK:
            dom = ((s.get("value") or {}).get("domain") or "该领域")
            q, ans = ASK[att]
            return q.replace("{domain}", dom), ans
        if comps:
            cats = {comp_by_id[r["data_item"]]["category"] for r in req_rows if r["kind"] == "component"}
            if "LanguageSkill" in cats:
                return ("英语到什么程度?两件事分开说:① 能不能独立写英文报告/邮件;"
                        "② 能不能开口开会、和客户直接沟通(还是要靠翻译)。",
                        "两项分别 能/不能,写入 hasSkill:skill_英语、skill_8D报告")
            if cats & {"QualityMethod", "QualitySystem", "HarnessCraft", "SkillSet"}:
                return (f"「{s['verbatim']}」—— 逐项说:用过没有、上一次用是什么时候、"
                        f"你在其中负责什么。要听具体的事,不是会不会:" + "、".join(comps),
                        "逐项 有/无 + 逐字引述,写入 hasSkill:" + "、".join(
                            r["data_item"] for r in req_rows if r["kind"] == "component"))
            return (f"「{s['verbatim']}」—— 这几项里哪些是你亲手做过?逐项说:时间、公司、"
                    f"你负责哪一段、结果:" + "、".join(comps),
                    "逐项 有/无 + 逐字引述,写入 hasSkill:" + "、".join(
                        r["data_item"] for r in req_rows))
        return (f"「{s['verbatim']}」这条,你怎么理解?举一个你自己身上的例子。",
                "文字记录 —— **没有对应数据项,入不了 join,只能进人看的部分**")

    md = [f"# 采集清单 · {link.get('jd')}", "",
          f"> JD 共 {len(link['citations'])} 条要求 → **{len(spec)} 个数据项**。"
          f"语料 {total} 份。覆盖率是实测的,不是估的。", "",
          "> 顺序是**从 JD 反推数据**,不是顺着简历抽:先定这个岗要哪些数据,再定谁去拿。",
          "> 覆盖率低于 %d%% 的项直接进一面清单 —— 指望 CV 就是指望不上。" % int(CV_THIN * 100),
          ""]

    groups = [
        ("cv", "一、CV 就能拿到(不用问)",
         "这些字段 CV 里覆盖率过半,直接读,不占面试时间。"),
        ("cv_then_interview", "二、CV 稀薄 —— 问了才稳",
         "CV 里偶尔有。有就采信,没有就在一面里补;不补这一条就只能是「未知」。"),
        ("interview", "三、必须一面问出来(CV 里基本没有)",
         "这些是 join 的主要障碍。不问,结果里永远是「未知」,不是「不满足」。"),
    ]
    for key, title, desc in groups:
        rows = [s for s in spec if s["req_source"] == key]
        if not rows:
            continue
        md += [f"## {title}", "", f"{desc}", ""]
        md += ["| 要求 | 数据项 | CV 覆盖 | 问句 | 答案写成 |",
               "|---|---|---|---|---|"]
        grouped = collections.defaultdict(list)
        for s in rows:
            grouped[s["requirement"]].append(s)
        for rid, rs in grouped.items():
            q, ans = question(rs)
            cov = f"{max(r['cv_coverage'] for r in rs)*100:.0f}%"
            items = "、".join(r["label"] or r["data_item"] for r in rs)
            md.append(f"| {rid} | {items} | {cov} | {q} | {ans} |")
        md.append("")

    no_item = [s for s in spec if s["kind"] == "none"]
    if no_item:
        md += ["## 四、问了也判不了 —— 没有可判的数据项", "",
               "这些项一面问得再细,join 也给不出「满足/不满足」—— 它们没有对应的属性或组件。", "",
               "| 要求 | 原因 |", "|---|---|"]
        for s in no_item:
            md.append(f"| {s['requirement']} {s['requirement_name']} | {s['library_blocked_by']} |")
        md.append("")

    stale = [s for s in spec
             if s["library_says_assessable"] is False and s["judge_ready"]]
    if stale:
        md += ["## 五、库里的旧说法与现实不符(要修库,不是要问候选人)", "",
               "要求库写着「判不了」,但目录里这个属性早就建好了、CV 里也有值。",
               "**这类矛盾会让一份好数据被白判成「不可判」**,所以单列出来。", "",
               "| 要求 | 库的理由 | 现实 |", "|---|---|---|"]
        for s in stale:
            md.append(f"| {s['requirement']} {s['requirement_name']} | "
                      f"{s['library_blocked_by']} | 数据项 {s['data_item']} 已有 "
                      f"{s['cv_coverage']*100:.0f}% 覆盖 |")
        md.append("")

    # 「半判」:数据收齐了也只能判一半 —— 判据是引用自带的 note 和 level_check,
    # 不是拿关键词去猜要求库的正文(那样会把"读不到所以判不了"误伤成"要求残缺")。
    half = {}
    for c in link["citations"]:
        note = (c.get("note") or "")
        req = lib[c["requirement"]]
        lvl = req.get("level_check") or {}
        if re.search(r"未建|只判", note):
            half[c["requirement"]] = note.strip().replace("\n", " ")[:110]
        elif lvl.get("assessable") is False:
            half[c["requirement"]] = ("其中一面判不了:" + (lvl.get("why") or "")
                                      + f"(level_check {lvl.get('attribute')})")
    # 已经在第五节认定「库的旧说法有误」的,这里不再按那条旧说法复述一遍 —— 否则自相矛盾
    stale_ids = {s["requirement"] for s in spec
                 if s["library_says_assessable"] is False and s["judge_ready"]}
    half = {k: v for k, v in half.items() if k not in stale_ids}
    if half:
        md += ["## 六、数据齐了也只能半判 —— 要求本身只表达了一半", "",
               "这是要求侧的缺陷,不是候选人的。数据照收,但别指望这一条能给出干净的结论。", "",
               "| 要求 | 缺的是哪一半 |", "|---|---|"]
        for rid, why in sorted(half.items()):
            md.append(f"| {rid} {lib[rid].get('name','')} | {why} |")
        md.append("")

    (OUT / f"{args.jd}.采集清单.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    if args.candidate:
        state = candidate_state(args.candidate, facts, comp_by_id)
        grouped = collections.defaultdict(list)
        for s in spec:
            grouped[s["requirement"]].append(s)
        need, got = [], []
        for rid, rs in grouped.items():
            miss = [s for s in rs if not (state.get(s["data_item"]) or {}).get("have")]
            (need if miss else got).append((rid, rs, miss))

        cm = [f"# 一面脚本 · {args.candidate.replace('cand_', '')}", "",
              f"> 岗位 **{link.get('jd')}**。{len(grouped)} 条要求里,"
              f"**{len(got)} 条数据已经够了,{len(need)} 条还缺**。", "",
              "> 只列缺的 —— 已经不缺的不再占面试时间。每一条都标了答案要落成什么,"
              "因为问完必须能写进同一个字段,否则问了也用不上。", "",
              "---", ""]
        if not need:
            cm += ["**这条要求对应的数据都齐了,这一岗不用再问。**", ""]
        for rid, rs, miss in need:
            q, ans = question(rs)
            names = "、".join(r["label"] or r["data_item"] for r in rs)
            miss_names = "、".join(r["label"] or r["data_item"] for r in miss)
            cm += [f"## {rid} · {lib[rid].get('name','')}", "",
                   f"**JD 原话**:「{rs[0]['verbatim']}」", "",
                   f"**要落成**:{names}", "",
                   f"**缺**:{miss_names}", "",
                   f"**问**:{q}", "",
                   f"**答案格式**:{ans}", "",
                   "**现状**:"
                   + ";".join(f"{r['label'] or r['data_item']}="
                              f"{'有' if (state.get(r['data_item']) or {}).get('have') else '无'}"
                              for r in rs), ""]
        if got:
            cm += ["---", "", "## 已经够了(不用问)", "",
                   "| 要求 | 数据项 | 现在的值 | 来源 |", "|---|---|---|---|"]
            for rid, rs, _ in got:
                for r in rs:
                    st = state.get(r["data_item"]) or {}
                    cm.append(f"| {rid} | {r['label'] or r['data_item']} | "
                              f"{st.get('value')} | {st.get('from') or '—'} |")
            cm.append("")
        cand_md = OUT / f"{args.jd}.{args.candidate.replace('cand_', '')[:24]}.一面脚本.md"
        cand_md.write_text("\n".join(cm) + "\n", encoding="utf-8")
        print(f"写出 {cand_md.relative_to(ROOT)}")
        print(f"  要求 {len(grouped)} · 已够 {len(got)} · 还缺 {len(need)}")

    print(f"写出 {(OUT / f'{args.jd}.采集清单.md').relative_to(ROOT)}")
    print(f"写出 {yaml_out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
