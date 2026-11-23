#!/usr/bin/env python3
"""第 3 步:HR 看 CV 出短名单 —— **只排除,不挑选**。

这一环是整条流水线里最容易做错的一步,错法只有一种:**用"分数"去挑人**。

为什么不能挑:实测 CV 只够 join 要的 16% 数据项(10 个 JD / 154 个数据项 / 25 项)。
剩下 84% 在一面里才拿得到。一份简历写得细的人,不等于能干;写得少的人,也不等于不行。
按分数排序挑出来的前 N 名,跟"谁的简历写得多"高度相关 —— 那不是筛选,那是筛简历。

所以这一步只做一件事:**把明确不合格的剔掉**。
    剔掉的判据  只有 CV 里真的读到、且真的与要求冲突的项
    读不到      → 保留(不是"保留待定",是直接进短名单)
    读到了且符合 → 保留
    判不了的    → 保留(判不了是我的模型问题,不是他的问题)

一句话:**这一步只保证"不会把明显不行的人送去一面",不负责"选出最像的人"。**
后者是第 5 步(本体 + join)的事,而且必须在一面数据齐了之后做。

用法:
    python -m scripts.talent.screen_cv --jd 品质经理
    python -m scripts.talent.screen_cv --jd 品质经理 --list     # 打印名单
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

from scripts.talent.evaluate import (  # noqa: E402
    CATALOG, FACTS, LIBRARY, LINKS, TRUSTED, load_candidates, overlay_hr,
    overlay_interview, overlay_llm)

COLLECTION = ROOT / "work" / "talent" / "collection"
#: 「品质岗经历」事实(derive_quality_facts 产出)。领域这条以前判不了,169 人全进短名单的原因就是它。
QUALITY = ROOT / "work" / "talent" / "cv_quality.json"
OUT = ROOT / "work" / "talent" / "shortlist"

#: 只认这些 basis —— 与 evaluate 一致,不在这里另立口径
TRUST = TRUSTED

#: 第 3 步只许用**简历里直接写着的**属性排除人。
#: 为什么把 A.3/A.4/A.5/C.4/C.7 挡在外面:那几个是从工作段推出来的
#: (OCR 缺公司名、起止切不全都会让值偏),拿一个已知会偏的推导量去排除人,
#: 比"读到了学历不够"危险得多。这类要求留到第 5 步参与排序,不参与排除。
STATED_ONLY = {"A.1", "A.2", "B.1"}

#: 允许用来排除的算子。只认**数值/序数阈值** —— "落在区间""不低于"。
#: 枚举(in)一律不用于排除:JD 原话常写「机电一体化/电子技术/…**等**工程类专业」,
#: 白名单是举例不是穷举,拿它剔人会把"材料成型及控制工程"这种真工程专业也剔掉。
EXCLUDING_OPS = {"between", ">=", "<=", "="}

#: 原话里出现这些词,说明这条阈值不是穷举的,不能拿来排除
FUZZY = ("等", "优先", "相关", "不限", "类")

#: 属性 id → evaluate 的候选人字段名。目录里写的 prop 是 PG 列名(education_rank),
#: evaluate 里是驼峰(educationRank)—— 这两套名字必须显式对上,不能靠猜。
CAND_KEY = {"A.1": "gender", "A.2": "age", "B.1": "educationRank",
            "B.2": "major", "B.3": "fullTime", "C.1": "yearsStated"}


def judge(item: dict, atts: dict, cand: dict, citation: dict) -> tuple[str, str]:
    """判**一个数据项**。返回 (满足/不满足/未知, 为什么)。

    只有"不满足"能用来排除;未知和不可判都必须保留。
    """
    # 采集清单带 attach(A.x/B.x);引用文件现场推导的项没有,只有 data_item。
    att_id = item.get("attach") or item.get("data_item") or ""
    key = CAND_KEY.get(att_id)
    if not key:
        return "不可判", f"{att_id} 没有供给侧字段"
    value = cand.get(key)
    if value is None:
        return "未知", f"{key} 没读到"
    val = citation.get("value") or {}
    op = item.get("op") or ""
    if op == "between" and "min" in val and "max" in val:
        return (("满足" if val["min"] <= value <= val["max"] else "不满足"),
                f"{val['min']}~{val['max']} vs {value}")
    if op == ">=" and "num" in val:
        return (("满足" if value >= val["num"] else "不满足"), f">={val['num']} vs {value}")
    if op == "in":
        want = val.get("in") or []
        if not want:
            return "不可判", "白名单是空的"
        # 子串匹配:简历写「机电一体化技术」,JD 写「机电一体化」—— 同一件事的两种写法。
        # 但只在**命中白名单**时放行,不命中仍判不满足(这一步是排除法,宽松的只能是"保留")。
        hit = [w for w in want if w in str(value) or str(value) in w]
        return (("满足" if hit else "不满足"), f"{want} vs {value}")
    return "不可判", f"算子 {op} 这一步不判"


def cites_by_req(link: dict) -> dict:
    return {c["requirement"]: c for c in link["citations"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    ap.add_argument("--facts", choices=["abox", "llm"], default="llm")
    ap.add_argument("--list", action="store_true", help="打印短名单里的人")
    # 品质岗经历是**硬要求**(客户原话「3年以上品质管理工作经验」)。默认开启。
    # 判据全部来自工作段的岗位名/职责,可重算 —— 不用 LLM 判人。
    ap.add_argument("--no-quality-gate", action="store_true",
                    help="跳过品质岗经历门槛(只做年龄/学历筛)")
    args = ap.parse_args()

    cat = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    atts = {a["id"]: a for a in cat["attributes"]}
    lib = {r["id"]: r for r in yaml.safe_load(LIBRARY.read_text(encoding="utf-8"))["requirements"]}
    link = yaml.safe_load((LINKS / f"{args.jd}.yaml").read_text(encoding="utf-8"))
    spec_path = COLLECTION / f"{args.jd}.yaml"
    if spec_path.is_file():
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    else:
        # 采集清单还没建(清空后重跑很常见)。不要把 FileNotFoundError 甩给调用方 ——
        # 用引用文件现场推一份等价的:能用"cv 属性"判的项才允许排除。
        print(f"  ! 缺 {spec_path.relative_to(ROOT)} —— 按引用文件现场推导可筛项")
        items, seen = [], set()
        for c in link.get("citations") or []:
            rid = c["requirement"]
            if rid in seen:
                continue
            req = lib[rid]
            if req.get("data_class") != "fact" or not req.get("attribute"):
                continue
            seen.add(rid)
            items.append({"requirement": rid, "req_source": "cv", "attribute": req["attribute"],
                          "data_item": req["attribute"], "value": c.get("value"), "op": req.get("op")})
        spec = {"items": items, "derived": True}

    # 只有 CV 类别(cv)的项允许参与排除。稀薄的、必问的一律不参与 ——
    # 拿"CV 里没有"当理由排除人,就是把采集计划的缺口算到候选人头上。
    screenable, not_screenable = {}, {}
    for s in spec["items"]:
        if s.get("req_source") != "cv":
            continue
        rid = s["requirement"]
        if rid in screenable or rid in not_screenable:
            continue
        req = lib[rid]
        # 采集清单可能是**上一次**的(按旧引用生成)。清单里有、当前引用里没有的要求,
        # 不能拿来排除人 —— 它已经不在这份 JD 里了。以前这里是 `[rid]` 直接取,键一缺就
        # KeyError 崩掉,而崩在"排除人"这一步最危险:看起来像"没人被排除"。
        cite = cites_by_req(link).get(rid)
        if cite is None:
            not_screenable[rid] = "当前引用文件里没有这条要求(采集清单过期,应重跑 build_collection_spec)"
            continue
        verbatim = cite.get("verbatim") or ""
        op = req.get("op")
        why = None
        if op not in EXCLUDING_OPS:
            why = f"算子是 {op},不是阈值 —— 不用于排除"
        elif s.get("attach") and s["attach"] not in STATED_ONLY:
            # 现场推导出来的项没有 attach 字段(那是采集清单才有的)——
            # 之前直接 s["attach"] 会在这里 KeyError 崩掉,而崩在"排除人"这步最危险。
            why = (f"{s['attach']} 是从简历推出来的量(不是直接写着),"
                   f"推导会偏 —— 不用于排除")
        elif any(f in verbatim for f in FUZZY):
            why = f"原话含「{[f for f in FUZZY if f in verbatim][0]}」,白名单不是穷举 —— 不用于排除"
        if why:
            not_screenable[rid] = why
        else:
            # op 写在要求上,但判的时候要按数据项走 —— 所以并进 item,别让 judge 去猜
            screenable[rid] = {"item": {**s, "op": op}, "req": req}

    cands = load_candidates()
    if args.facts == "llm":
        overlay_llm(cands)
        # 短名单要**基于一面结果**:一面答过的值必须并进来。
        # 之前这里只 overlay 了 CV 抽取 —— 于是廖有 22 条真访谈,第 3 步照样按简历判,
        # "基于一面出短名单"这句话在代码里是空的。
        overlay_hr(cands)
        # ⚠ 初筛**不并模拟填充**:cv_mock 里的值是我方编的,拿它淘汰人等于凭空拒绝。
        # 实测就这样误伤了 17 人(mock 年龄 42 判「25~40 vs 42」)。
        from scripts.talent import interview_policy
        _mode, _src = interview_policy.mode_for(args.jd)
        n_iv = overlay_interview(cands, allow_simulated=_mode == interview_policy.MOCK_ALLOWED)
        print(f"  一面记录:并入 {n_iv} 处 · 采信规则 {_mode}({_src})")
    pool = [c for c in cands if not c["duplicate"]]
    cites = {c["requirement"]: c for c in link["citations"]}

    # 值的可信来源:cv_facts 的 basis ∈ TRUSTED / hr_facts / 一面记录。
    # abox 里那个值如果没有可信依据,就当"没读到"→ 保留,不许拿来淘汰。
    import json as _json
    _facts_path = ROOT / "work" / "talent" / "cv_facts.json"
    _facts = _json.loads(_facts_path.read_text(encoding="utf-8")) if _facts_path.is_file() else {}
    from scripts.talent.evaluate import TRUSTED as _TRUSTED

    def _trusted_props(cid: str) -> set:
        d = _facts.get(cid) or {}
        fm = {"age": "age", "education_rank": "educationRank"}
        return {v for k, v in fm.items()
                if (d.get(k) or {}).get("basis") in _TRUSTED
                and (d.get(k) or {}).get("value") is not None}

    def _interview_quality() -> dict:
        """一面记录里坐实了「做过品质岗」的人 → {cid: True}。模拟答案也算,但会标来源。"""
        out = {}
        d = ROOT / "work" / "talent" / "cv_interview"
        if not d.is_dir():
            return out
        for f in d.glob("*.yaml"):
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            for a in doc.get("answers") or []:
                if any(str(x) == "skill_品质岗经历" for x in (a.get("establishes") or [])):
                    out[f"cand_{f.stem}"] = True
        return out

    rows, excluded, untrusted = [], [], []
    for cand in pool:
        verdicts, kill = {}, []
        _trusted = _trusted_props(cand["id"])
        for rid, s in screenable.items():
            item = s["item"]
            state, why = judge(item, atts, cand, cites[rid])
            # 值若不是来自可信来源(cv_facts@TRUSTED / hr / 一面),就不能用来淘汰人:
            # 实测有 12 人的年龄/学历只来自 abox 关键词匹配,拿它拒人比"未知"更糟。
            prop = item.get("prop")
            if state == "不满足" and prop and prop not in _trusted:
                state, why = "未知", f"{prop} 只有不可信来源(未过 TRUSTED),按未知处理"
                untrusted.append({"candidate": cand["id"], "requirement": rid, "prop": prop})
            verdicts[rid] = (state, why)
            if state == "不满足":
                kill.append({"requirement": rid, "requirement_name": s["req"].get("name"),
                             "verbatim": cites[rid].get("verbatim"),
                             "data_item": item["data_item"], "why": why})
        # verdicts 与 reasons 两个都要留:reasons 说明"为什么"(给人看),
        # verdicts 说明"每条要求判成什么"(给门禁复算)。只留 reasons 的话,
        # 门禁无法核实这条排除到底是"有硬证据"还是"没读到"——实测 101 条因此核不了。
        row = {"candidate": cand["id"], "excluded": bool(kill), "reasons": kill,
               "verdicts": {k: v[0] for k, v in verdicts.items()}}
        rows.append(row)
        if kill:
            excluded.append(row)

    kept = [r for r in rows if not r["excluded"]]

    # ── 品质岗经历门槛(硬要求)
    # 语料里 270 人只有 11 人有品质岗经历,其中若干被年龄/学历筛掉 —— 这两件事必须
    # **分开报**:前者是"没做过品质",后者是"做过但因为别的条件被剔",后者要交人复议。
    quality_gate = None
    # 品质岗经历门槛**只对需要它的 JD 生效**。之前无条件套,业务跟单(9 条要求里没有品质)
    # 被按"品质硬动作 ≥24 个月"剔掉 6 个人 —— 客户从没写过这道门槛。
    _needs_quality = any(
        (lib.get(c["requirement"]) or {}).get("attribute") in ("C.2", "C.3", "C.4", "C.5", "C.6")
        or any(str(x).startswith("skill_品质岗经历")
               for x in ((lib.get(c["requirement"]) or {}).get("components") or []))
        for c in link.get("citations") or []
    )
    if not _needs_quality:
        print("  品质岗经历门槛:本 JD 的引用里没有品质/领域经历要求 —— 不套该门槛")
    if not args.no_quality_gate and QUALITY.is_file() and _needs_quality:
        q = json.loads(QUALITY.read_text(encoding="utf-8"))
        # 一面里明确答过「做过品质岗」的人,应当算「有」 —— 这是**访谈证据**,
        # 比简历文本更硬。之前这道门只读 CV,访谈答了也不算,等于第 4 步白做。
        iv_quality = _interview_quality()
        passed, failed, pending = [], [], []
        for r in kept:
            v = q.get(r["candidate"]) or {}
            verdict = v.get("verdict")
            if iv_quality.get(r["candidate"]):
                passed.append(r["candidate"])
                continue
            if verdict == "有":
                passed.append(r["candidate"])
            elif verdict == "无":
                failed.append({"candidate": r["candidate"],
                               "why": v.get("why_short") or "无品质岗经历证据"})
            else:
                # 「待核 / 读不出」= 我们不知道,不是不合格。
                # 之前这里把它们一律塞进 failed,165 个人被一道读不出来的信号挡掉了 ——
                # 那是把「没写」当「没做过」,是这套系统最贵的一类错。
                pending.append({"candidate": r["candidate"], "verdict": verdict,
                                "why": v.get("why_short") or "读不出品质岗经历",
                                "months": v.get("months"),
                                "months_known": v.get("months_known"),
                                "quote": (v.get("quote") or "")[:120]})
                passed.append(r["candidate"])   # 未核 → 保留,并进待核清单
        # 做过品质、但被年龄/学历挡在门外的人 —— 不是漏掉的,是被另一条要求剔掉的
        rescreen = [{"candidate": r["candidate"],
                     "quality": q[r["candidate"]],
                     "blocked_by": r["reasons"]}
                    for r in excluded if (q.get(r["candidate"]) or {}).get("verdict") == "有"]
        quality_gate = {
            "rule": "A 岗位名在品质序列(不限时长) 或 B 职责含硬动作且该段≥min_months;弱动作(客诉/8D、SPC)不算",
            "min_months": (next(iter(q.values())) or {}).get("min_months") if q else None,
            "in_pool_yes": sum(1 for v in q.values() if v.get("verdict") == "有"),
            "needs_verification": pending,
            "passed": passed, "failed": failed, "blocked_by_other_requirements": rescreen,
        }
        kept = [r for r in kept if r["candidate"] in set(passed)]
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{args.jd}.yaml"
    out.write_text(yaml.safe_dump({
        "jd": link.get("jd"), "step": "3 短名单(只排除)",
        "rule": "只用 CV 类别(cv)的数据项排除;读不到/判不了一律保留",
        "facts": args.facts,
        "count": {"pool": len(pool), "kept": len(kept),
                  "excluded": len(excluded) + len((quality_gate or {}).get("failed") or []),
                  "dropped_by_quality_gate": len((quality_gate or {}).get("failed") or [])},
        "screenable_requirements": sorted(screenable),
        "not_screenable": not_screenable,
        "untrusted_source_kept": untrusted,
        # 落盘时**不许**把 verdicts 丢掉:门禁要复算"这条排除是有硬证据,还是没读到"
        # 品质门槛剔掉的人也必须进 excluded —— 否则 kept + excluded ≠ pool,
        # 第三方复算会对不上账(实测差 5 人,是 agent 385 自己在对话里发现的)。
        "excluded": ([{"candidate": r["candidate"], "reasons": r["reasons"],
                       "verdicts": r.get("verdicts") or {}} for r in excluded]
                     + [{"candidate": f["candidate"],
                         "reasons": [{"requirement": "QUALITY-GATE",
                                      "requirement_name": "品质岗经历门槛",
                                      "why": f.get("why") or "无品质岗经历证据"}],
                         "verdicts": {}, "stage": "品质门槛"}
                        for f in ((quality_gate or {}).get("failed") or [])]),
        "kept": [r["candidate"] for r in kept],
        "quality_gate": quality_gate,
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")

    print(f"第 3 步 · {link.get('jd')} · 事实源 {args.facts} · 去重后 {len(pool)} 人")
    print(f"  参与排除的要求:{', '.join(sorted(screenable))}")
    for rid, why in sorted(not_screenable.items()):
        print(f"  不参与:{rid:24s} {why}")
    if untrusted:
        print(f"  因「值来源不可信」未排除:{len(set(x['candidate'] for x in untrusted))} 人")
    print(f"  保留 {len(kept)} 人 · 排除 {len(excluded)} 人 "
          f"({100*len(excluded)/max(1,len(pool)):.0f}%)")
    why = collections.Counter(r["reasons"][0]["requirement"] for r in excluded)
    for rid, n in why.most_common():
        print(f"    {rid:24s} {lib[rid].get('name','')[:16]:18s} 排除 {n:3d} 人")
    states = collections.Counter()
    for r in rows:
        for rid, s in r["verdicts"].items():
            states[(rid, s)] += 1
    if quality_gate:
        print(f"\n  品质岗经历门槛:全语料 {quality_gate['in_pool_yes']} 人具备"
              f"(B 档需该段 ≥{quality_gate['min_months']} 个月;弱动作不算)")
        print(f"    通过 {len(quality_gate['passed'])} 人 · "
              f"无证据 {len(quality_gate['failed'])} 人 · "
              f"**做过品质但被其他要求剔掉 {len(quality_gate['blocked_by_other_requirements'])} 人**")
        for x in quality_gate["blocked_by_other_requirements"]:
            qv = x["quality"]
            why = ",".join(f"{b['requirement']}({b['why']})" for b in x["blocked_by"])
            print(f"    [需复议] {x['candidate'][:46]}  品质证据 {qv['kind']}档/{qv['months']}月"
                  f"「{qv['title'][:14]}」 —— 被 {why} 排除")

    print("\n  各要求的判决分布(只算可筛项):")
    for rid in sorted(screenable):
        c = collections.Counter({k[1]: v for k, v in states.items() if k[0] == rid})
        print(f"    {rid:24s} 满足{c['满足']:3d} 不满足{c['不满足']:3d} "
              f"未知{c['未知']:3d} 不可判{c['不可判']:3d}")
    print(f"\n写出 {out.relative_to(ROOT)}")
    if args.list:
        print("\n短名单:")
        for r in kept:
            print("  ", r["candidate"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
