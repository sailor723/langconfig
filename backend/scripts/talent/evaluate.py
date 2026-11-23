#!/usr/bin/env python3
"""用 yaml 的尺子量一遍所有候选人 —— 只做 join,不用推理机,不碰 Neo4j。

四种状态,不是两种:满足 / 不满足 / **未知**(简历没读到)/ 不可判(这一支判不了)。
"未知"永远不能折成"不满足" —— 270 人里年限未知的有一半,折进去就等于凭空判了一批人不合格。

三个年限口径,必须分开:
    platform   平台文件名「10年以上」  派生值、截断在 10   277 人都有,但 10 是上限不是真值
    stated     简历头部「15年」        候选人自述           118 人
    computed   工作经历逐段累加         唯一**可重算**        54 人,且尚不可验证

要求用哪个口径由 year_basis 决定:写在要求上是默认值,写在引用上可覆盖 ——
"比哪个年限"是每份 JD 的判断,不是要求的属性(同 tier 的逻辑)。

要求引用类别还是组件:用 categories 的要求接受该类下任何组件,所以目录里新增同类
组件时要求自动覆盖,不用改 yaml。这是本体层唯一能赚到的钱。

用法:
    python -m scripts.talent.evaluate --jd 品质经理
    python -m scripts.talent.evaluate --jd 品质经理 --facts llm
    ... --facts llm --year-basis platform
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

CATALOG = ROOT / "work" / "talent" / "component_catalog.yaml"
LIBRARY = ROOT / "work" / "talent" / "requirement_library.yaml"
LINKS = ROOT / "work" / "talent" / "jd_links"
FACTS = ROOT / "work" / "talent" / "cv_facts.json"
HR_FACTS = ROOT / "work" / "talent" / "hr_facts.json"
INTERVIEW = ROOT / "work" / "talent" / "cv_interview"
#: 本体推理落盘的事实(专业→专业类→门类)。由 build_major_taxonomy 生成,join 只读不算。
ONT_FACTS = ROOT / "work" / "talent" / "ontology_facts.json"
PROFILE = BACKEND / "features" / "ontology" / "profiles" / "talent_v1" / "talent_v1_settings.json"

COVERAGE = 0.5

PROP_FIELD = {"A.1": "gender", "A.2": "age", "B.1": "educationRank",
              "B.2": "major", "B.3": "fullTime", "C.1": "yearsStated", "C.6": "yearsComputed",
              # HR 视角的属性(A.3-A.5 / C.4 / C.7):数据来自 derive_hr_facts
              "A.3": "notice_weeks", "A.4": "commute_ok", "A.5": "salary_max_k",
              "C.4": "avg_tenure_years", "C.7": "recent5y_segments"}
BASIS_FIELD = {"platform": "yearsPlatform", "stated": "yearsStated", "computed": "yearsComputed"}
TRUSTED = {"stated", "inferred", "computed"}

#: 目录里标了 `detectable: false` 的组件:原文要求了,但我们目前检不出来。
#: 它们**不进判定的分母**,只在理由里如实标出。目前只有 skill_5WHY。
UNDETECTABLE: set[str] = set()


def load_undetectable() -> set[str]:
    cat = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    return {c["id"] for c in cat.get("components") or [] if c.get("detectable") is False}


def split_detectable(resolved: list[str]) -> tuple[list[str], list[str]]:
    """(能判的组件, 要求了但检不出的组件)。两处消费者共用这一个切分。"""
    live = [x for x in resolved if x not in UNDETECTABLE]
    blind = [x for x in resolved if x in UNDETECTABLE]
    return live, blind


def load_candidates() -> list[dict]:
    """供给侧从 abox.ttl 读 —— 那才是唯一真源,不是 PG。"""
    import rdflib
    from rdflib import Literal, URIRef
    from rdflib.namespace import RDF

    settings = json.loads(PROFILE.read_text(encoding="utf-8"))
    ns = (settings.get("ns") or "").rstrip("#") + "#"
    g = rdflib.Graph()
    g.parse(PROFILE.parent / settings.get("abox", "abox.ttl"), format="turtle")
    SAME_AS = "http://www.w3.org/2002/07/owl#sameAs"

    def one(node, prop, *, absolute=False):
        for v in g.objects(node, URIRef(prop if absolute else ns + prop)):
            if isinstance(v, Literal):
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return str(v)
            return str(v).rsplit("#", 1)[-1]
        return None

    out = []
    for node in g.subjects(RDF.type, URIRef(ns + "Candidate")):
        out.append({
            "id": str(node).rsplit("#", 1)[-1],
            "age": one(node, "age"),
            "educationRank": one(node, "educationRank"),
            "yearsPlatform": one(node, "yearsExperience"),
            "yearsStated": None, "yearsComputed": None,
            "gender": None, "major": None, "fullTime": None,
            "duplicate": bool(one(node, SAME_AS, absolute=True)),
            "components": {str(o).rsplit("#", 1)[-1]
                           for o in g.objects(node, URIRef(ns + "hasSkill"))},
        })
    return out


def overlay_llm(cands: list[dict]) -> int:
    if not FACTS.is_file():
        print(f"  ! 缺 {FACTS.relative_to(ROOT)} —— 先跑 promote_cv_facts")
        return 0
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    # 技能也要覆盖。之前 --facts llm 只覆盖属性、不动组件,于是判定用的是 abox 的
    # 关键词匹配结果,而定稿展示的是 LLM 逐字抽取的结果 —— 同一批语料 249/270 人两者不一致。
    # 后果很具体:简历写着「熟练应对二方与三方审核」的人,被判"没有客户验厂经验"。
    cat = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    label2id = {c["label"]: c["id"] for c in cat["components"]}
    field_map = {"age": "age", "education_rank": "educationRank", "major": "major",
                 "gender": "gender", "full_time": "fullTime"}
    used = 0
    for c in cands:
        d = facts.get(c["id"]) or {}
        for field, key in field_map.items():
            item = d.get(field) or {}
            if item.get("basis") in TRUSTED and item.get("value") is not None:
                c[key] = item["value"]; used += 1
        y = d.get("years") or {}
        if y.get("basis") in TRUSTED and y.get("value") is not None:
            c["yearsStated"] = int(y["value"]); used += 1
        sk = d.get("skills") or {}
        if sk.get("basis") in TRUSTED:
            c["components"] = {label2id[s["name"]] for s in (sk.get("value") or [])
                               if s.get("name") in label2id}
            used += 1
    return used


def overlay_hr(cands: list[dict]) -> int:
    """把 derive_hr_facts 算出来的量挂到候选人身上。

    只有 basis=computed 的才认 —— 那几个量是**推出来的**,推不出来的留 None,
    不许填 0。填 0 会让"切不出工作段"的人被判成"零在职",那是凭空判人不合格。
    """
    if not HR_FACTS.is_file():
        print(f"  ! 缺 {HR_FACTS.relative_to(ROOT)} —— 先跑 derive_hr_facts")
        return 0
    data = json.loads(HR_FACTS.read_text(encoding="utf-8"))
    used = 0
    for c in cands:
        d = data.get(c["id"]) or {}
        for prop in ("notice_weeks", "recent5y_segments", "avg_tenure_years"):
            item = d.get(prop) or {}
            if item.get("basis") == "computed" and item.get("value") is not None:
                c[prop] = item["value"]
                used += 1
    return used


#: 访谈记录里的字段 id → join 读的属性名。和 field_schema 不是一回事:
#: 那边是"档案里有哪些字段",这里是"判定时读哪个量"。
IV_FIELD_PROP = {"F.AGE": "age", "F.EDU_LEVEL": "educationRank", "F.EDU_MAJOR": "major",
                 "F.GENDER": "gender", "F.EDU_FULLTIME": "fullTime",
                 "F.EXP_YEARS": "yearsStated"}


MOCK = ROOT / "work" / "talent" / "cv_mock"


def overlay_mock(cands: list[dict]) -> int:
    """把 mock_fill 生成的模拟值并进候选人 —— 只在授权范围内、只补空位。

    模拟值和真事实**分开存**是刻意的:cv_facts.json 里只允许有读来的东西。
    这里并进来时会在候选人身上留 `_mock` 标记,判定说明据此标成「模拟」,
    而不是把它当成读到的数据。
    """
    from scripts.talent import interview_policy
    pol = (interview_policy.load().get("mock_fill") or {})
    if pol.get("mode") != "allowed":
        return 0
    n = 0
    for c in cands:
        f = MOCK / f"{c['id'].replace('cand_', '')}.yaml"
        if not f.is_file():
            continue
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if doc.get("jd") not in (pol.get("scope") or []):
            continue
        mock = c.setdefault("_mock", {})
        for prop, rec in (doc.get("props") or {}).items():
            if c.get(prop) is None:
                c[prop] = rec.get("value")
                mock[prop] = rec
                n += 1
        for comp, rec in (doc.get("components") or {}).items():
            if rec.get("held") and comp not in c["components"]:
                c["components"].add(comp)
                mock[comp] = rec
                n += 1
    return n


def overlay_interview(cands: list[dict], *, allow_simulated: bool = False) -> int:
    """把一面记录并进候选人。**一处实现**,判定和采集清单都走这里。

    之前这段逻辑写在 build_collection_spec 里,判定脚本读不到 —— 于是同一个廖,
    一面脚本说"到岗/通勤都有了",evaluate 说"没读到"。两边各自都"看起来正常",
    这才是最难查的那种错。

    三种落法,全部显式写在访谈 yaml 里,程序不猜:
        props:       {属性名: 值}        直接定值
        establishes: [skill_xxx]         坐实了哪个组件
        字段 id                           按 IV_FIELD_PROP 映射到属性
    """
    n = 0
    for c in cands:
        path = INTERVIEW / f"{c['id'].replace('cand_', '')}.yaml"
        if not path.is_file():
            continue
        iv = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for a in iv.get("answers") or []:
            # **模拟答案是开发用的,默认不进判定。** 实测踩过:9 份模拟访谈被当成真访谈,
            # 第 5 步直接给出「入选 4 人」—— 一份看起来完全正常的录用建议,而里面 9 个人
            # 从没被面过。要用模拟数据只能显式 --include-simulated,并且结论必须标演练。
            if str(a.get("basis") or "interview") in ("simulated", "simulated_interview") \
                    and not allow_simulated:
                continue
            for prop, val in (a.get("props") or {}).items():
                if c.get(prop) is None:
                    c[prop] = val; n += 1
            for comp in a.get("establishes") or []:
                if comp not in c["components"]:
                    c["components"].add(comp); n += 1
            # 明确否认也要记 —— 否则"我问过了,他说没有"和"我没问到"在判定里长得一样
            for comp in a.get("denies") or []:
                c.setdefault("_denied", set()).add(comp)
            prop = IV_FIELD_PROP.get(a.get("field") or "")
            if prop and c.get(prop) is None:
                c[prop] = a.get("answer"); n += 1
    return n


def overlay_major_field(cands: list[dict]) -> int:
    """按专业名查本体落盘的表,给候选人挂上 `majorField`(工学/管理学/…)。

    这一步为什么不能自己算:判断"机电一体化技术属不属于工程类"是**分类**问题,
    不是字符串问题。分类已经在 build_major_taxonomy 里让推理机做完并落了盘,
    这里只做查表 —— 查表是可复现的,重新分类不是。
    """
    if not ONT_FACTS.is_file():
        return 0
    table = json.loads(ONT_FACTS.read_text(encoding="utf-8")).get("majors") or {}
    n = 0
    for c in cands:
        raw = c.get("major")
        if raw is None:
            c["majorFields"], c["majorHits"] = set(), []
            continue
        text = str(raw)
        hits = [m for m in table if m and m in text]
        c["majorHits"] = hits
        c["majorFields"] = {table[m]["field"] for m in hits}
        if hits:
            n += 1
        else:
            # 专业写了、但一个字都对不上分类表 —— 这是**分类覆盖不到**,不是候选人没专业。
            # 记下来,让判定报「不可判」,别混进「不满足」。
            c["majorFields"] = set()
    return n


#: 证据强度分级。能力类的"满足"不是一个二元结论 —— "他说他会"和"他拿出过案例"差别很大。
#:   strong 案例/实测:面试记录里带 case/test,或业务现场出题做对了
#:   weak   自述:简历写的、面试里说自己会
#:   none   无证据
EVIDENCE_RANK = {"none": 0, "weak": 1, "strong": 2}
EVIDENCE_CN = {"strong": "案例/实测", "weak": "仅自述", "none": "无证据"}


def component_evidence(cid: str, comp: str, cv: dict, iv: dict) -> str:
    """这个组件是被什么强度的证据坐实的。

    刻意只看**记录里是否明写了** case/test —— 不从答案自由文本里猜"这像不像案例",
    那会变成主观判断。想升级成 strong,就在采集时把 evidence_level 记下来。
    """
    for a in (iv or {}).get("answers") or []:
        if comp in (a.get("establishes") or []):
            lv = str(a.get("evidence_level") or "").lower()
            if lv in ("case", "test", "strong"):
                return "strong"
            return "weak"
    skills = ((cv.get(cid) or {}).get("skills") or {}).get("value") or []
    if any(str(x.get("name")) == comp.replace("skill_", "") for x in skills):
        return "weak"
    return "none"


def judge_component(held: set, needed: list, match: dict | None = None,
                    absence: str = "unknown", evidence: str | None = None,
                    denied: set | None = None) -> tuple:
    """组件类判定。匹配口径由**要求自己**决定,不是全局一个 50%:

    match: {kind: any_of, n: 1}  → 命中其中任意一项即满足
    match: {kind: all_of}        → 全都要(默认按 COVERAGE 覆盖率)
    2026-11-21 admin 定:品质工具(5 项)是 any_of 1 —— 具体会哪个工具由业务面确认。
    全局 50% 口径下全库只有 2 人过;any_of 1 下有 17 人过,差别全在这条口径上。
    """
    if not needed:
        return "不可判", "没有组件"
    hit = [c for c in needed if c in held]
    if not hit:
        # **一直在问、当面否认** 和 **一项都没读到**,是两件事:
        #   前者是候选人自己说的「没有」—— 有来源、可引原话,判不满足;
        #   后者只是材料里读不到 —— 只能记未知,交给第 4 步去问。
        # 之前只有前者也被记成未知,于是面完 30 个人,未知一条都没少。
        _denied = denied or set()
        if _denied and all(c in _denied for c in needed):
            return "不满足", f"{len(needed)} 项一面明确否认(自述:没有相关经历或举不出例子)"
    if not hit and absence == "unknown":
        # **一项都没读到 ≠ 一项都不会。** 简历里没写、词表没覆盖、或者他确实没做过 ——
        # 这三件事在这一层分不开,所以只能记「未知」,交给第 4 步去问。
        # 之前这里直接判「不满足」,实测把 148 个没在简历里写"品质问题分析"的人判成不合格。
        return "未知", f"{len(needed)} 项一项都没读到(可能没写/没做过,需面谈确认)"
    kind = (match or {}).get("kind")
    if kind == "any_of":
        n = int((match or {}).get("n") or 1)
        return ("满足" if len(hit) >= n else "不满足"), f"{len(hit)}/{len(needed)}(需要≥{n}项)"
    if kind == "all_of":
        # 客户用「及/和/、」把几项并列时,通常是**都要**。默认的 50% 覆盖率会把它读成"会一个就行"。
        return ("满足" if len(hit) == len(needed) else "不满足"), f"{len(hit)}/{len(needed)}(需要全部{len(needed)}项)"
    return ("满足" if len(hit) / len(needed) >= COVERAGE else "不满足"), f"{len(hit)}/{len(needed)}"


def judge_attribute(att: dict, req: dict, cit: dict, cand: dict, forced: str) -> tuple:
    attr_id = att["id"]
    prop = PROP_FIELD.get(attr_id)
    if attr_id in ("C.1", "C.6"):
        basis = forced or cit.get("year_basis") or req.get("year_basis") or "platform"
        prop = BASIS_FIELD.get(basis, "yearsPlatform")
    if not prop:
        return "不可判", f"{attr_id} 没有供给侧字段"
    val = cit.get("value") or {}
    op = req.get("op")
    # 先看 JD 这边给没给取值 —— JD 没给阈值是「不可判」,不是「候选人未知」。
    # 这两件事混起来的后果是:看名单的人以为"这人没数据",实际是"这个岗没定标准"。
    if op in (">=", "<=", "between") and not (set(val) & {"num", "min", "max"}):
        return "不可判", f"算子 {op} 但 JD 没给取值"
    value = cand.get(prop)
    if value is None:
        return "未知", f"{prop} 没读到"
    if op == "between" and "min" in val and "max" in val:
        return ("满足" if val["min"] <= value <= val["max"] else "不满足"), \
               f"{val['min']}~{val['max']} vs {value}"
    if op == ">=" and "num" in val:
        return ("满足" if value >= val["num"] else "不满足"), f">={val['num']} vs {value}"
    if op == "<=" and "num" in val:
        return ("满足" if value <= val["num"] else "不满足"), f"<={val['num']} vs {value}"
    if op == "in":
        want = val.get("in") or []
        text = str(value)
        by_name = [w for w in want if w in text]
        fields = cand.get("majorFields") or set()
        need_field = req.get("match_field")
        if by_name:
            return "满足", f"专业名命中 {by_name}（{value}）"
        if need_field and fields:
            if need_field in fields:
                hits = "、".join(cand.get("majorHits") or [])
                return "满足", (f"门类命中 {need_field}（{value} → {hits}，"
                                f"本体:{need_field}）")
            return "不满足", f"门类 {sorted(fields)} 不含 {need_field}（{value}）"
        if need_field:
            # 只有声明了 match_field(要用门类)时,"分类表里没有"才等于不可判。
            # 不声明门类(D 口径)时,名字没中就是**不满足** —— 这里原先写错了:
            # 文件不在时 189 人从"不满足"变成"不可判",等于把"没命中"伪装成"判不了"。
            if not fields:
                return "不可判", f"「{value}」不在专业分类表里 —— 分类覆盖不到,不是不合格"
            return "不满足", f"专业名与门类都不命中（{value}）"
        return "不满足", f"专业名没命中白名单（{value}）"
    if op == "=":
        want = val.get("in") or ([val["value"]] if "value" in val else [])
        if want:
            return ("满足" if value in want else "不满足"), f"{want} vs {value}"
        return "不可判", "eq 但没有取值"
    return "不可判", f"算子 {op} 无判定规则"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", default="品质经理")
    ap.add_argument("--facts", choices=["abox", "llm"], default="abox")
    ap.add_argument("--year-basis", choices=["platform", "stated", "computed"], default="")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--include-duplicates", action="store_true")
    ap.add_argument("--interview", action="store_true", help="把一面记录并进判定")
    ap.add_argument("--real-only", action="store_true",
                    help="强制只认真人答案(默认按 interview_policy.yaml)")
    args = ap.parse_args()

    global UNDETECTABLE
    UNDETECTABLE = load_undetectable()
    catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    library = yaml.safe_load(LIBRARY.read_text(encoding="utf-8"))
    link = yaml.safe_load((LINKS / f"{args.jd}.yaml").read_text(encoding="utf-8"))
    atts = {a["id"]: a for a in catalog["attributes"]}
    reqs = {r["id"]: r for r in library["requirements"]}

    by_cat = collections.defaultdict(list)
    for c in catalog["components"]:
        by_cat[c["category"]].append(c["id"])
    for r in reqs.values():
        cats = r.get("categories") or []
        r["_resolved"] = (sorted({x for cat in cats for x in by_cat.get(cat, [])})
                          if cats else list(r.get("components") or []))

    cands = load_candidates()
    n_llm = overlay_llm(cands) if args.facts == "llm" else 0
    n_hr = overlay_hr(cands)
    n_iv = 0
    if getattr(args, "interview", False):
        from scripts.talent import interview_policy
        _mode, _src = interview_policy.mode_for(
            args.jd, override="real" if getattr(args, "real_only", False) else None)
        # 规则只在 interview_policy 一处,选人和判定不许各判一套
        n_iv = overlay_interview(
            cands, allow_simulated=_mode == interview_policy.MOCK_ALLOWED)
        print(f"  [面试] 采信规则 {_mode} —— {_src}")
    n_mf = overlay_major_field(cands)
    pool = [c for c in cands if args.include_duplicates or not c["duplicate"]]
    cit = link["citations"]

    print(f"JD: {link['jd']} · {len(cit)} 条引用 → {len({c['requirement'] for c in cit})} 条要求")
    print(f"候选人: {len(pool)} 人(另有 {len(cands) - len(pool)} 份重复已排除)")
    print(f"事实源: {args.facts}" + (f"(覆盖 {n_llm} 个字段)" if args.facts == "llm" else "")
          + f" · HR 事实 {n_hr} 个量"
          + (f" · 一面记录 {n_iv} 处" if args.interview else "")
          + (f" · 专业门类(仅参考,当前口径不参与判定) {n_mf} 人" if n_mf else ""))
    print(f"年限口径: {args.year_basis or '按引用/要求声明'}   组件覆盖率阈值: {COVERAGE}")

    per_req = collections.defaultdict(collections.Counter)
    rows = []
    for cand in pool:
        result = {}
        for c in cit:
            req = reqs[c["requirement"]]
            if not req.get("assessable"):
                state, why = "不可判", ("E 维无组件" if req.get("no_component") else "属性未建")
            elif req.get("_resolved"):
                live, blind = split_detectable(req["_resolved"])
                state, why = judge_component(cand["components"], live, req.get("match"))
                if blind:
                    why += f"（另有 {len(blind)} 项原文要求但当前检不出:{'、'.join(blind)}）"
            elif req.get("attribute"):
                state, why = judge_attribute(atts[req["attribute"]], req, c, cand, args.year_basis)
            else:
                state, why = "不可判", "既无组件也无属性"
            result[c["requirement"]] = (state, why)
            per_req[c["requirement"]][state] += 1
        rows.append({"id": cand["id"], "result": result,
                     "满足": sum(1 for s, _ in result.values() if s == "满足"),
                     "不满足": sum(1 for s, _ in result.values() if s == "不满足"),
                     "未知": sum(1 for s, _ in result.values() if s == "未知"),
                     "不可判": sum(1 for s, _ in result.values() if s == "不可判"),
                     "可判": sum(1 for s, _ in result.values() if s in ("满足", "不满足"))})

    print(f"\n{'='*84}\n每条要求的分母(多少人被它真正判过)\n{'='*84}")
    for c in cit:
        rid = c["requirement"]; n = per_req[rid]
        tag = "  [优先]" if c.get("tier") == "desirable" else ""
        print(f"{rid:26s} {reqs[rid].get('name','')[:18]:20s} "
              f"满足{n['满足']:4d} 不满足{n['不满足']:4d} 未知{n['未知']:4d} 不可判{n['不可判']:4d}{tag}")

    print(f"\n{'='*84}\n分布\n{'='*84}")
    dist = collections.Counter(r["满足"] for r in rows)
    for k in sorted(dist, reverse=True):
        zu = sum(1 for r in rows if r["满足"] == k and r["未知"] == 0)
        print(f"   满足 {k:2d} 条 → {dist[k]:4d} 人   (零未知 {zu} 人)")

    if args.top:
        print(f"\n{'='*84}\nTop {args.top}\n{'='*84}")
        rows.sort(key=lambda r: (-r["满足"], r["未知"], r["id"]))
        for r in rows[:args.top]:
            gaps = [rid for rid, (s, _) in r["result"].items() if s == "不满足"]
            print(f"@{r['id']}")
            print(f"   满足{r['满足']} 不满足{r['不满足']} 未知{r['未知']} 不可判{r['不可判']}"
                  + (f"   差:{'·'.join(gaps)}" if gaps else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
