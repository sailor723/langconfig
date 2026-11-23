#!/usr/bin/env python3
"""第 5b 步:从最终名单里取出这批人,并给每个人一个说得清的理由。

    人数不由本脚本决定:池子是第 5b 步的最终名单(已按 jd_inputs.final_max 切过),
    这里**不再二次限制**。`--top` 只在 pool≠target(交叉比对/复核)时才有意义。

排序规则(2026-11-20 用户定):
    ① 满足条数多的在前
    ② 并列时,**未知少的在前**(信息完整的人先,不是"简历写得多"的人)
    ③ 再并列时,不满足少的在前
    ④ 全并列就按 id(稳定,重跑不换人)

为什么不用分数:实测 299 个合格人里 222 人(74%)同分并列,纯按分数排
"凭什么是他"答不出来。四态计数至少能让每个人说清"他满足哪几条、缺哪几条"。

**这个脚本最重要的一段输出不是名单,是"还不够格挑"这件事。**
短名单 169 人里通常只有个位数做过一面。没一面的人,大部分数据项是「未知」——
这时候按"未知少的优先"排,排出来的是"谁的简历写得细",而不是"谁更合适"。
所以脚本会先报三个数:短名单多少人、有一面数据多少人、其中真正可比的人多少。
数字不够就直接说"现在挑不了",不硬凑 4 个。
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

from scripts.talent import interview_policy  # noqa: E402
from scripts.talent import names as _names  # noqa: E402
from scripts.talent.evaluate import (  # noqa: E402
    CATALOG, LIBRARY, LINKS, component_evidence, judge_attribute, judge_component,
    load_candidates, overlay_hr, overlay_interview, overlay_llm, overlay_mock, overlay_mock)

SHORTLIST = ROOT / "work" / "talent" / "shortlist"
OUT = ROOT / "work" / "talent" / "picks"


def load_inputs(jd: str):
    cat = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    lib = {r["id"]: r for r in yaml.safe_load(LIBRARY.read_text(encoding="utf-8"))["requirements"]}
    link = yaml.safe_load((LINKS / f"{jd}.yaml").read_text(encoding="utf-8"))
    atts = {a["id"]: a for a in cat["attributes"]}

    by_cat = collections.defaultdict(list)
    for c in cat["components"]:
        by_cat[c["category"]].append(c["id"])
    for r in lib.values():
        cats = r.get("categories") or []
        r["_resolved"] = (sorted({x for cat_ in cats for x in by_cat.get(cat_, [])})
                          if cats else list(r.get("components") or []))
    return cat, lib, link, atts


ARCHIVE = ROOT / "work" / "talent" / "llm_verdicts"
CONFLICTS = ROOT / "work" / "talent" / "conflicts"


def apply_combo_c(cid: str, jd: str, onto: dict, link: dict) -> tuple[dict, list]:
    """组合 C:本体判定 → LLM 判定(存档)→ 不可判硬保护 → 冲突进复议。

    为什么不可判必须"硬":LLM 会给没有数据项的条款下结论(实测 C-10 九成人都被判「满足」)。
    为什么冲突不自动跟本体:实测 C 类冲突里本体错 24 格、LLM 错 3 格 —— 自动跟会整批继承。

    返回 (最终判定, 冲突清单)。
    """
    f = ARCHIVE / jd / f"{cid.replace('cand_', '')}.yaml"
    if not f.is_file():
        return onto, []
    doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    cells = doc.get("cells") or {}
    out, conflicts = dict(onto), []
    for c in link["citations"]:
        rid = c["id"]
        cell = cells.get(rid)
        if not cell:
            continue
        # judge_all 的键是 requirement id,存档的键是引用 id(C-01)
        req_id = c["requirement"]
        o = onto[req_id]["state"]
        l = cell.get("state")
        if o == "不可判":
            continue                       # 硬保护:LLM 无权改
        if l == o:
            out[req_id] = dict(onto[req_id], 来源="本体与LLM一致")
        elif l == "未知":
            # LLM 说未知、本体有结论 → **保留本体的结论**,只把"LLM 没看到"记成弱信号。
            # 反过来做(把本体结论抹成未知)就等于让 LLM 的谨慎度否决本体的数据 ——
            # 那批格子实测有 23 个,抹掉之后所有人都会变成"信息不足",名单就没意义了。
            out[req_id] = dict(onto[req_id], 来源="本体(LLM 未读到)",
                               llm_unknown=True)
        elif o == "未知":
            # 本体判未知、LLM 有结论 → 这是 LLM 真正补缺口的地方
            out[req_id] = {"state": l, "why": cell.get("why") or "",
                           "citation": rid, "来源": "LLM 补缺口",
                           "llm_quote": cell.get("quote")}
        else:
            # C 类冲突:不替任何一方拍板,单独记账,并把该格标成复议
            out[req_id] = {"state": "复议", "why": f"本体:{o} / LLM:{l}",
                           "citation": rid, "来源": "冲突待裁",
                        "llm_quote": cell.get("quote"), "llm_why": cell.get("why")}
            conflicts.append({"clause": rid, "name": c.get("requirement"),
                              "ontology": o, "llm": l,
                              "llm_why": cell.get("why"), "llm_quote": cell.get("quote")})
    return out, conflicts


_CVF: dict | None = None
_IVC: dict = {}


def _cv_facts() -> dict:
    global _CVF
    if _CVF is None:
        f = ROOT / "work" / "talent" / "cv_facts.json"
        _CVF = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    return _CVF


def _iv_doc(cid: str) -> dict:
    if cid not in _IVC:
        f = ROOT / "work" / "talent" / "cv_interview" / f"{cid.replace('cand_', '')}.yaml"
        _IVC[cid] = (yaml.safe_load(f.read_text(encoding="utf-8")) if f.is_file() else {}) or {}
    return _IVC[cid]


def evidence_cn(cid: str, comps: list) -> str:
    """这条能力类"满足"背后是案例还是自述。"""
    lv = [component_evidence(cid, x, _cv_facts(), _iv_doc(cid)) for x in comps]
    best = max(lv, key=lambda v: {"strong": 2, "weak": 1, "none": 0}.get(v, 0)) if lv else "weak"
    return "案例/实测" if best == "strong" else "仅自述"


def judge_all(cand: dict, link: dict, lib: dict, atts: dict) -> dict:
    out = {}
    for c in link["citations"]:
        r = lib[c["requirement"]]
        cls = r.get("data_class")
        if cls == "soft":
            # 软素质:没有数据项、没有刻度 → 对所有人都是不可判。不许拿它淘汰任何人。
            state, why = "不可判", "软素质要求,没有可判的数据项(见 jd_reviews 的 deferred 决定)"
        elif not r.get("assessable"):
            state, why = "不可判", r.get("blocked_by") or "属性/组件未建"
        elif r["_resolved"]:
            state, why = judge_component(cand["components"], r["_resolved"], r.get("match"),
                                         denied=cand.get("_denied"))
            if state == "满足":
                why += f" · 证据:{evidence_cn(cand['id'], r['_resolved'])}"
        elif r.get("attribute"):
            state, why = judge_attribute(atts[r["attribute"]], r, c, cand, "")
        else:
            state, why = "不可判", "既无组件也无属性"
        out[c["requirement"]] = {"state": state, "why": why, "citation": c["id"]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    ap.add_argument("--top", type=int, default=4)
    # 采信规则**不存在代码里**,在 work/talent/interview_policy.yaml。
    # 这两个开关只是强制覆盖;默认读策略文件,谁授权的、哪天、为什么,都在文件里。
    ap.add_argument("--include-simulated", action="store_true",
                    help="强制放开模拟访谈(覆盖策略文件;产物仍全程标「模拟(演练)」)")
    ap.add_argument("--real-only", action="store_true",
                    help="强制只认真人答案(覆盖策略文件)")
    ap.add_argument("--facts", choices=["abox", "llm"], default="llm")
    # 组合 C:本体先判 → LLM 判(读存档)→ 不可判硬保护 → 冲突进复议
    ap.add_argument("--no-llm", action="store_true",
                    help="只用本体判定(组合 A);默认有存档就用 C")
    ap.add_argument("--interviewed-only", action="store_true",
                    help="只排做过一面的(默认也排,但会标注数据来源)")
    # 第 5 步有两种合法问法:①只在第 3 步的短名单里挑 ②把已有完整档案的人全拿来对 JD
    # 第二种是"交叉比对"—— 用来复核第 3 步有没有看漏人,不能直接当录用名单。
    ap.add_argument("--pool", choices=["target", "shortlist", "interviewed", "all"],
                    default="target",
                    help="候选人范围:target=第5步目标名单(默认 —— 第 6 步只能从第 5 步的名单里选) · "
                         "shortlist=第3步保留的人(复核用,不是录用名单) · "
                         "interviewed=有访谈档案的人 · all=全库")
    args = ap.parse_args()

    override = "mock" if args.include_simulated else ("real" if args.real_only else None)
    mode, mode_src = interview_policy.mode_for(args.jd, override=override)
    mock_ok = mode == interview_policy.MOCK_ALLOWED

    cat, lib, link, atts = load_inputs(args.jd)
    cands = load_candidates()
    if args.facts == "llm":
        overlay_llm(cands)
    overlay_hr(cands)
    # **不再并 cv_mock**(2026-11-23):那是「简历缺字段的模拟填充」,在没有一面数据时用的。
    # 现在一面把字段填满了,再叠一层 mock 就等于名单读真数据、判定说明读真+假,
    # 同一个人两份文件对不上(实测 24/40 人不一致:名单 10 满足,说明写成 12)。
    n_iv = overlay_interview(cands, allow_simulated=mock_ok)
    by_id = {c["id"]: c for c in cands}

    # 「有访谈」不能只看文件在不在 —— 一份**模拟**档案也是文件。
    # 实测踩过:9 份模拟访谈被算成"有一面数据",于是第 5 步给出「入选 4 人」,
    # 而其中 9 个人从没被面过。判据必须是「里面有没有非模拟的答案」。
    def _answers(cid: str) -> list:
        path = ROOT / "work" / "talent" / "cv_interview" / f"{cid.replace('cand_', '')}.yaml"
        if not path.is_file():
            return []
        return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("answers") or []

    def _counts(cid: str) -> tuple[int, int]:
        ans = _answers(cid)
        real = sum(1 for a in ans if interview_policy.is_real_basis(a))
        return real, len(ans) - real

    def _has_real_interview(cid: str) -> bool:
        """**真人**答过的(不含 simulated)。这一条与任何开关无关 ——
        把开关写进来过一次,结果"演练"标签永远不亮,模拟的人仍被标成 [访谈]。"""
        return _counts(cid)[0] > 0

    def _in_pool(cid: str) -> bool:
        real, sim = _counts(cid)
        return bool(real) or (mock_ok and sim > 0)

    def _source(cid: str) -> str:
        """四档来源,不许含糊成"有访谈"。"""
        real, sim = _counts(cid)
        if real and sim:
            return "真+模拟"
        if real:
            return "真访谈"
        if sim:
            return "模拟(演练)"
        return "简历"

    sl_path = SHORTLIST / f"{args.jd}.yaml"
    sl = yaml.safe_load(sl_path.read_text(encoding="utf-8")) if sl_path.is_file() else {}
    kept_ids = [cid for cid in (sl.get("kept") or []) if cid in by_id]
    if sl:
        excluded = sl["count"]["excluded"]
    else:
        excluded = 0

    # 第 3 步把谁放在哪、被哪条卡住 —— 这是第 5 步复核要用的证据,
    # 不能只报一个"排除 101 人"的总数。
    qg = (sl.get("quality_gate") or {})
    blocked = {b["candidate"]: b for b in (qg.get("blocked_by_other_requirements") or [])}
    failed = {f["candidate"]: f.get("why", "") for f in (qg.get("failed") or [])}

    def _step3(cid: str) -> tuple[str, str]:
        if cid in kept_ids:
            return "短名单", ""
        if cid in blocked:
            b = blocked[cid]
            reqs = b.get("blocked_by") or []
            if reqs:
                r = reqs[0]
                return "需复议", (f"{r.get('requirement')} 「{str(r.get('verbatim') or '')[:24]}」 "
                                 f"{r.get('why')}")
            return "需复议", ""
        if cid in failed:
            return "未过品质门槛", failed[cid]
        return "第3步排除", ""

    tgt_path = SHORTLIST / f"{args.jd}.目标名单.yaml"
    if args.pool == "target":
        # 第 6 步只从第 5 步的目标名单(5~8 人)里选,不从 150 人的初筛池里选。
        # 之前默认走 kept,等于跳过了"短名单"这一关 —— 那是流程错位。
        tgt = yaml.safe_load(tgt_path.read_text(encoding="utf-8")) if tgt_path.is_file() else {}
        if tgt and not str(tgt.get("step") or "").startswith("5"):
            print(f"目标名单是旧产物({tgt.get('step')})—— 先跑第 5 步:"
                  f"shortlist_after_interview --jd {args.jd}")
            return 2
        # 第 5b 步的最终名单才是"送去用人部门面"的那批人;
        # 短名单(selected)更大,是"够格排队"的人。没写 final 的老产物退回用 selected。
        want = ((tgt.get("final") or {}).get("ids") or tgt.get("selected") or [])
        pool_ids = [c for c in want if c in by_id]
        if not pool_ids:
            print("没有目标名单,先跑 shortlist_after_interview --jd " + args.jd)
            return 2
    elif args.pool == "shortlist":
        pool_ids = kept_ids
    elif args.pool == "interviewed":
        # 有档案就有得判;能不能用还要看第 3 步那关(下面的「第3步」列会说)
        pool_ids = [c["id"] for c in cands if sum(_counts(c["id"])) > 0]
    else:
        pool_ids = [c["id"] for c in cands if not c["duplicate"]]

    # 判定分母:不可判的要求对谁都不算 —— 拿它算"满足率"会让每个人都被压低
    judgeable = [c["requirement"] for c in link["citations"]
                 if lib[c["requirement"]].get("assessable")
                 or lib[c["requirement"]].get("_resolved")]

    iv_ids = {c["id"] for c in cands if _in_pool(c["id"])}
    rows, _all_conflicts = [], []
    for cid in pool_ids:
        v = judge_all(by_id[cid], link, lib, atts)
        conflicts = []
        if not args.no_llm:
            v, conflicts = apply_combo_c(cid, args.jd, v, link)
        if conflicts:
            _all_conflicts.append({"candidate": cid, **{"cells": conflicts}})
        st = collections.Counter(x["state"] for x in v.values())
        rows.append({"candidate": cid, "verdicts": v,
                     "满足": st["满足"], "不满足": st["不满足"],
                     "未知": st["未知"], "不可判": st["不可判"],
                     "复议": st["复议"], "冲突": conflicts,
                     "有访谈": cid in iv_ids,
                     "数据来源": _source(cid),
                     "真访谈条数": _counts(cid)[0],
                     "模拟条数": _counts(cid)[1],
                     "第3步": _step3(cid)[0],
                     "阻塞": _step3(cid)[1]})
        rows[-1]["模拟"] = rows[-1]["数据来源"] == "模拟(演练)"
    pool_iv = [r for r in rows if r["有访谈"]]
    rows_by_id = {r["candidate"]: r for r in rows}
    if args.pool == "target":
        # **不重排**:名单的顺序就是第 5 步用九层证据阶梯排出来的顺序。
        # 之前这里按"满足数"再排一次,于是第 5 步的第 2 名到第 6 步掉出前 4 ——
        # 同一批人两个顺序,谁看都会问哪份算数。
        ranked = [rows_by_id[c] for c in pool_ids if c in rows_by_id]
    else:
        ranked = sorted(pool_iv if args.interviewed_only else rows,
                        key=lambda r: (-r["满足"], r["未知"], r["不满足"], r["candidate"]))
    # target = 第 5b 步的最终名单:它自己已经按 final_max 切过人数,这里**不再二次限制**。
    # 之前写死 args.top(默认 4),于是最终名单 5 个人只显示 4 个、标题还写「最多 4 人」。
    if args.pool == "target":
        cap = len(ranked)
    else:
        cap = args.top
    top = ranked[:cap]

    # 排序陷阱检测:按"未知少的优先"排,可能把"不满足更多"的人排到前面
    inversions = []
    for a, b in zip(ranked, ranked[1:]):
        if a["不满足"] < b["不满足"] and a["满足"] <= b["满足"]:
            inversions.append((a["candidate"], b["candidate"],
                               a["不满足"], b["不满足"]))
            if len(inversions) >= 5:
                break

    if not args.no_llm:
        CONFLICTS.mkdir(parents=True, exist_ok=True)
        # C 类冲突台账:双方判定 + 双方引文。**不替任何一方拍板**,只登记等人裁。
        (CONFLICTS / f"{args.jd}.yaml").write_text(yaml.safe_dump({
            "jd": args.jd,
            "rule": "本体与 LLM 判定冲突 → 不自动跟本体(实测 C 类冲突本体错 24 格 / LLM 错 3 格),"
                    "登记待裁;裁前该格按「复议」处理,不进满足率",
            "count": sum(len(c["cells"]) for c in _all_conflicts),
            "items": _all_conflicts,
        }, allow_unicode=True, sort_keys=False), encoding="utf-8")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{args.jd}.yaml").write_text(yaml.safe_dump({
        "jd": link.get("jd"),
        "step": ("5 选人(最终名单 %d 人)" % len(top)) if args.pool == "target"
                else ("选人(最多 %d 人)" % cap),
        "pool": {"kind": args.pool,
                 "size": len(pool_ids),
                 "meaning": {"target": "第 5b 步最终名单(≤ final_max,送去用人部门面)",
                             "shortlist": "第 3 步保留的人",
                             "interviewed": "有访谈档案的人(交叉比对,不是录用名单)",
                             "all": "全库(交叉比对)"}[args.pool]},
        "order": ["满足 desc", "未知 asc", "不满足 asc", "id"],
        # 采信规则写进产物:半年后有人问"这 4 个人凭什么用模拟数据选出来",
        # 答案在这一段里,不在某个人的记忆里。
        "interview_policy": {"mode": mode, "source": mode_src,
                             "decided_by": interview_policy.record(args.jd).get("decided_by"),
                             "decided_at": str(interview_policy.record(args.jd).get("decided_at") or "") or None},
        "count": {"shortlist": len(pool_ids), "excluded": excluded,
                  "with_interview": len(pool_iv),
                  "with_real_interview": sum(1 for r in pool_iv if r["真访谈条数"]),
                  "with_mock_only": sum(1 for r in pool_iv if r["数据来源"] == "模拟(演练)"),
                  "judgeable_requirements": len(judgeable),
                  "total_requirements": len(link["citations"])},
        "top": [{"rank": i + 1, "candidate": r["candidate"],
                 "满足": r["满足"], "不满足": r["不满足"], "未知": r["未知"],
                 "不可判": r["不可判"], "有访谈": r["有访谈"],
                 "数据来源": r["数据来源"],
                 "真访谈条数": r["真访谈条数"], "模拟条数": r["模拟条数"],
                 "第3步": r["第3步"], "阻塞": r["阻塞"]}
                for i, r in enumerate(top)],
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")

    POOL_DESC = {"target": "**第 5b 步最终名单**",
                 "shortlist": "第 3 步保留的人",
                 "interviewed": "**所有填好档案的人**(交叉比对 —— 用来复核第 3 步有没有看漏人,不是录用名单)",
                 "all": "**全库**(交叉比对,不是录用名单)"}
    if args.pool == "target":
        order_note = ("> 顺序 **不重排**:直接用第 5b 步最终名单的顺序(九层证据阶梯排出来的),"
                      "这里只补逐人理由与判定说明。")
    else:
        order_note = (f"> 排序:满足多者先 → 未知少者先 → 不满足少者先 → id 稳定。最多 {args.top} 人。")
    md = [f"# 第 5 步选人 · {link.get('jd')}", "",
          f"> 范围:{POOL_DESC[args.pool]},共 {len(pool_ids)} 人。", order_note, ""]
    md += ["## 先说够不够格挑", "",
           "| | 数 |", "|---|---|",
           f"| 参与比对的人 | **{len(pool_ids)}** 人 |",
           f"| 其中在初筛保留名单里 | **{sum(1 for r in rows if r['第3步'] == '短名单')}** 人 |",
           f"| 其中做过一面的 | **{len(pool_iv)}** 人 |",
           f"| —— 真访谈 | **{sum(1 for r in pool_iv if r['真访谈条数'])}** 人 |",
           f"| —— 只有模拟 | **{sum(1 for r in pool_iv if r['数据来源'] == '模拟(演练)')}** 人 |",
           f"| 采信规则 | `{mode}` · {mode_src} |",
           f"| 可判的要求 | {len(judgeable)} / {len(link['citations'])} 条"
           f"(其余 {len(link['citations']) - len(judgeable)} 条没有可判的数据项) |", ""]
    if len(pool_iv) < cap:
        md += [f"> ⚠ **现在挑不出 {cap} 个可信的人。** 短名单 {len(pool_ids)} 人里只有 "
               f"{len(pool_iv)} 人做过一面,其余的人大量要求是「未知」。",
               "> 这时候按\"未知少的优先\"排,排出来的是**谁的简历写得细**,不是谁更合适。",
               "> 缺的不是算法,是第 4a 步的一面数据 —— 先把短名单里的人在电话里过一遍,这一步才有意义。", ""]

    head = (f"## 入选({len(top)} 人)" if args.pool in ("target", "shortlist")
            else f"## 交叉比对·按「满足条数」排出的 {len(top)} 人")
    md += [head, ""]
    mock_used = [r for r in top if r["模拟条数"]]
    if mock_used:
        md += [f"> ⚠ **演练模式**:本次有 **{len(mock_used)}** 人用了 `basis: simulated` 的模拟访谈答案。",
               "> 那些字段与评语不是真人说的,是我方按简历推的。",
               "> **本名单不得作为录用决策依据** —— 真实选人必须先把访谈答案换成 `basis: interview`。",
               f"> 依据:`interview_policy.yaml` 的 `mode: {mode}`({mode_src})。", ""]
    md += ["| # | 候选人 | 满足 | 不满足 | 未知 | 不可判 | 数据来源 | 初筛 | CV |",
           "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(top, 1):
        md.append(f"| {i} | {_names.name_of(r['candidate'])} | {r['满足']} | "
                  f"{r['不满足']} | {r['未知']} | {r['不可判']} | "
                  f"{r['数据来源']} | {r['第3步']} | "
                  f"[看 CV](#tal:cv/{r['candidate']}) |")
    md.append("")

    for i, r in enumerate(top, 1):
        md += [f"### 第 {i} 位 · {_names.name_of(r['candidate'])} · "
               f"[看 CV](#tal:cv/{r['candidate']})", "",
               f"满足 **{r['满足']}** · 不满足 **{r['不满足']}** · "
               f"未知 **{r['未知']}** · 不可判 **{r['不可判']}**", "",
               "| 要求 | 判定 | 依据 |", "|---|---|---|"]
        for c in link["citations"]:
            v = r["verdicts"][c["requirement"]]
            name = lib[c["requirement"]].get("name", "")
            md.append(f"| {c['id']} {name} | **{v['state']}** | {v['why']} |")
        md.append("")

    outside = [r for r in ranked if r["第3步"] != "短名单"]
    if outside:
        md += ["## 名单外的人:被哪一条卡住", "",
               "交叉比对最有用的产出就是这一段 —— **他够格,但被某条客户原文挡住了**。",
               "这些人不是「不合格」,是「过不了这一条」—— 要不要见,取决于那条门槛批不批。", "",
               "| 候选人 | 第3步 | 满足 | 卡在哪 |", "|---|---|---|---|"]
        for r in outside:
            md.append(f"| {r['candidate'].replace('cand_','')[:30]} | {r['第3步']} | "
                      f"{r['满足']} | {r['阻塞'] or '—'} |")
        md.append("")

    if inversions:
        md += ["## 排序陷阱:这条规则会把人排反", "",
               "\"未知少的优先\"有个已知副作用:一个 7 满足/1 未知/5 不满足的人,"
               "会排在 7 满足/3 未知/0 不满足 的人前面。", "",
               "| 排在前的 | 排在后的 | 前的不满足 | 后的不满足 |", "|---|---|---|---|"]
        for a, b, na, nb in inversions:
            md.append(f"| {a.replace('cand_','')[:22]} | {b.replace('cand_','')[:22]} | "
                      f"{na} | {nb} |")
        md += ["", "> 这不是 bug,是规则的取舍。要改的话有两种:**不满足先于未知**"
               "(信息不全但确定合格的先),或者**先按不满足分档、再按未知分档**。",
               "> 现在按你定的规则执行,但这个副作用摆在这里,不藏。", ""]

    (OUT / f"{args.jd} 选人.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"第 6 步 · {link.get('jd')}")
    real_iv = sum(1 for r in pool_iv if r["真访谈条数"])
    scope = {"target": "目标名单", "shortlist": "初筛保留", "interviewed": "有档案的人",
             "all": "全库"}.get(args.pool, args.pool)
    print(f"  {scope} {len(pool_ids)} 人 · 有一面数据 {len(pool_iv)} 人"
          f"(真 {real_iv} / 只有模拟 {len(pool_iv) - real_iv}) · "
          f"可判要求 {len(judgeable)}/{len(link['citations'])}")
    print(f"  采信规则 {mode} —— {mode_src}")
    if not args.no_llm:
        _nc = sum(len(c["cells"]) for c in _all_conflicts)
        print(f"  判定组合 C(本体→LLM→不可判硬保护)· 冲突 {_nc} 格"
              + (f" → {CONFLICTS.relative_to(ROOT)}/{args.jd}.yaml" if _nc else ""))
    print(f"  {'入选' if args.pool in ('target', 'shortlist') else '排出'} {len(top)} 人:")
    TAG = {"真访谈": "[访谈]", "真+模拟": "[真+模拟]", "模拟(演练)": "[模拟]", "简历": ""}
    for i, r in enumerate(top, 1):
        step3 = "" if r["第3步"] == "短名单" else f"  [{r['第3步']}]"
        print(f"    {i}. 满足{r['满足']} 不满足{r['不满足']} 未知{r['未知']} "
              f"{TAG.get(r['数据来源'], '')} {r['candidate'][:40]}{step3}")
    if len(pool_iv) < cap:
        print(f"  ⚠ 只有 {len(pool_iv)} 人做过一面,少于 {cap} —— 现在挑不出 {cap} 个可信的人")
    if real_iv < len(top):
        print(f"  ⚠ 入选的 {len(top)} 人里只有 {real_iv} 人有真访谈数据 —— "
              f"其余是模拟(演练),不能拿去当录用依据")
    if inversions:
        print(f"  ⚠ 排序陷阱 {len(inversions)} 处:未知少的人被排到了不满足更多的人前面")
    print(f"写出 {(OUT / f'{args.jd} 选人.md').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
