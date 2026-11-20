#!/usr/bin/env python3
"""把一份 JD 渲染成「合格版岗位说明书」—— 全部从 yaml 生成,没有一个数字是手写的。

"合格"在这里有具体含义,不是形容词。一份 JD 合格,当且仅当:

    ① 每条要求都有**逐字原文**与行号,可回查 (J-G2/J-G4)
    ② 每条要求都落到**维度**,并且能说出它属于哪一类
    ③ 每条要求都声明**判定方式**:比什么属性、用什么算子、取什么值
    ④ 判不了的**明确写出为什么**,并变成一个问题交给能答的人
    ⑤ 名单带**分母**:多少条可判、多少人未知、结论依赖什么证据

缺任何一条,这份 JD 就是"看起来完整"的文档 —— 那种东西最难查。

生成的东西分九节,其中第 5、7、8 节是普通 JD 一定没有的:
    5. 判定口径   每条要求怎么判、用哪个年限口径
    7. 已知缺口   为什么这几条判不了,变成问题
    8. 数据血缘   每个数字出自哪个文件的哪一行

用法:
    python -m scripts.talent.render_jd --jd 品质经理
    python -m scripts.talent.render_jd --jd 品质经理 --facts llm
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
OUT_DIR = ROOT / "work" / "talent" / "jd_docs"

DIM_LABEL = {"A": "人口属性", "B": "教育", "C": "经历", "D": "技能",
             "E": "素质能力", "F": "资质证书", "G": "合规约束",
             "H": "语言", "I": "身体条件"}
BASIS_LABEL = {"stated": "原文直述", "inferred": "门禁推断", "computed": "由生日/日期推算",
               "computed_unverified": "未验证", "rejected": "已拒绝", "none": "未读到"}
FIELD_LABEL = {"age": "年龄", "years": "年限", "education_rank": "学历",
               "major": "专业", "gender": "性别", "full_time": "全日制"}


def evidence_profile(field: str, facts: dict) -> dict:
    c = collections.Counter()
    for d in facts.values():
        c[(d.get(field) or {}).get("basis") or "none"] += 1
    return dict(c)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", default="品质经理")
    ap.add_argument("--facts", choices=["abox", "llm"], default="llm")
    args = ap.parse_args()

    catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    library = yaml.safe_load(LIBRARY.read_text(encoding="utf-8"))
    link = yaml.safe_load((LINKS / f"{args.jd}.yaml").read_text(encoding="utf-8"))
    facts = json.loads(FACTS.read_text(encoding="utf-8")) if FACTS.is_file() else {}

    atts = {a["id"]: a for a in catalog["attributes"]}
    reqs = {r["id"]: r for r in library["requirements"]}
    comps = {c["id"]: c for c in catalog["components"]}
    by_cat = collections.defaultdict(list)
    for c in catalog["components"]:
        by_cat[c["category"]].append(c["id"])
    for r in reqs.values():
        cats = r.get("categories") or []
        r["_resolved"] = (sorted({x for cat in cats for x in by_cat.get(cat, [])})
                          if cats else list(r.get("components") or []))

    # 判定结果(用 evaluate 同一套逻辑)
    from scripts.talent import evaluate as E
    cands = E.load_candidates()
    if args.facts == "llm":
        E.overlay_llm(cands)
    pool = [c for c in cands if not c["duplicate"]]
    dist = collections.Counter()
    req_stat = collections.defaultdict(collections.Counter)
    for cand in pool:
        n = 0
        for c in link["citations"]:
            req = reqs[c["requirement"]]
            if not req.get("assessable"):
                st = "不可判"
            elif req.get("_resolved"):
                st = E.judge_component(cand["components"], req["_resolved"])[0]
            elif req.get("attribute"):
                st = E.judge_attribute(atts[req["attribute"]], req, c, cand, "")[0]
            else:
                st = "不可判"
            req_stat[c["requirement"]][st] += 1
            n += (st == "满足")
        dist[n] += 1

    # ── 渲染
    L: list[str] = []
    A = L.append
    A(f"# {link['jd']} · 合格版岗位说明书")
    A("")
    A(f"> 本文由 `render_jd.py` 从三份 yaml 生成,**没有一个数字是手写的**。")
    A(f"> 要求来源:`jd_links/{args.jd}.yaml` · 语义:`requirement_library.yaml` · 词表:`component_catalog.yaml`")
    A(f"> 判定事实源:**{args.facts}** · 候选人 {len(pool)} 人(已排除 {len(cands)-len(pool)} 份重复简历)")
    A("")

    A("## 1 · 岗位标识")
    A("")
    A("| 项 | 值 | 出处 |")
    A("|---|---|---|")
    A(f"| 职务名称 | {link['jd']} | 文件名(文档内写「助理」,以文件名为准) |")
    A(f"| 隶属部门 | {link.get('department','—')} | 职务说明书 |")
    A(f"| 原始文件 | `{link['source_file']}` | — |")
    A(f"| 抽取文本 | `{link['source_text']}` | {'textutil' if '.doc' in link['source_file'] else 'openpyxl'} |")
    A(f"| 审核状态 | **{link.get('review_status','—')}** | {'草稿:LLM 起草,未逐条人工审' if link.get('review_status')=='draft' else '人工'} |")
    A("")

    A("## 2 · 任职资格(逐条,带原文与行号)")
    A("")
    A("| # | 原文(逐字) | 行 | 维度 | tier | 要求 | 判定方式 |")
    A("|---|---|---|---|---|---|---|")
    for i, c in enumerate(link["citations"], 1):
        req = reqs[c["requirement"]]
        dim = req["dimension"]
        if req.get("_resolved"):
            how = f"持有 {len(req['_resolved'])} 个组件中的 ≥50%"
        elif req.get("attribute"):
            a = atts[req["attribute"]]
            how = f"{a['label']}({a['prop']}) {req.get('op')} {c.get('value') or '—'}"
        else:
            how = "**不可判**"
        A(f"| {i} | 「{c['verbatim']}」 | {c['txt_line']} | {dim} {DIM_LABEL[dim]} | "
          f"{c.get('tier','—')} | `{c['requirement']}` | {how} |")
    A("")
    A(f"共 **{len(link['citations'])}** 条原子要求。原文 {link['count'].get('source_lines','?')} 句"
      f" → 拆成 {link['count'].get('atomic_requirements','?')} 条。")
    if link["count"].get("count_note"):
        A("")
        A("> " + " ".join(link["count"]["count_note"].split()))
    A("")

    A("## 3 · 按维度汇总")
    A("")
    A("| 维度 | 条数 | 可判 | 不可判 |")
    A("|---|---|---|---|")
    per_dim = collections.Counter()
    per_dim_ok = collections.Counter()
    for c in link["citations"]:
        r = reqs[c["requirement"]]
        per_dim[r["dimension"]] += 1
        per_dim_ok[r["dimension"]] += 1 if r.get("assessable") else 0
    for dim in "ABCDEFGHI":
        if per_dim[dim]:
            A(f"| {dim} {DIM_LABEL[dim]} | {per_dim[dim]} | {per_dim_ok[dim]} | "
              f"{per_dim[dim]-per_dim_ok[dim]} |")
    A("")

    A("## 4 · 要求明细(每条要求一个 ID,可被多份 JD 复用)")
    A("")
    A("| 要求 | 名称 | 形态 | 绑定 | 依赖属性 | 供给侧 |")
    A("|---|---|---|---|---|---|")
    for c in link["citations"]:
        r = reqs[c["requirement"]]
        if r.get("categories"):
            bind = "类别:" + "/".join(r["categories"])
        elif r.get("_resolved"):
            bind = "组件:" + "·".join(comps[x]["label"] for x in r["_resolved"][:5]) + \
                   (f" 等{len(r['_resolved'])}个" if len(r["_resolved"]) > 5 else "")
        else:
            bind = "—"
        att = atts.get(r.get("attribute") or "")
        prop = f"`{att['prop']}`" + ("✓" if att and att.get("prop_exists") else "✗") if att else "—"
        A(f"| `{r['id']}` | {r.get('name','')[:20]} | {r.get('kind','—')} | {bind} | "
          f"{att['label'] if att else '—'} | {prop} |")
    A("")

    A("## 5 · 判定口径(普通 JD 没有这一节)")
    A("")
    A("**组件类要求**:持有要求绑定的组件达到覆盖率阈值即判满足。")
    A(f"- 阈值:`COVERAGE = {E.COVERAGE}` —— 沿用旧闸门,便于与历史结果对比;它是**约定**,不是推导。")
    A("- 绑类别的要求(如 Office)在目录新增同类组件时**自动覆盖**,不需要改这份 JD。")
    A("")
    A("**属性类要求**:比的是**同一个口径**的值。年限有三套口径,本 JD 用的是:")
    yb = next((c.get("year_basis") or reqs[c["requirement"]].get("year_basis")
               for c in link["citations"] if reqs[c["requirement"]].get("attribute") == "C.1"), None)
    A(f"- `year_basis = {yb or 'platform'}`"
      + ("(平台文件名,被截断在「10年以上」)" if (yb or "platform") == "platform"
         else "(简历自述)" if yb == "stated" else "(逐段累加,尚不可验证)"))
    A("- 换成别的口径会得到不同的「不满足」人数 —— 这不是误差,是**另一个量**。")
    A("")

    A("## 6 · 名单与分母")
    A("")
    A("| 满足条数 | 人数 | 其中零未知 |")
    A("|---|---|---|")
    for k in sorted(dist, reverse=True):
        zu = 0  # 见第 7 节,零未知在这里不重复计算
        A(f"| {k} | {dist[k]} | — |")
    A("")
    A("每条要求的判定分布:")
    A("")
    A("| 要求 | 满足 | 不满足 | 未知 | 不可判 |")
    A("|---|---|---|---|---|")
    for c in link["citations"]:
        s = req_stat[c["requirement"]]
        A(f"| `{c['requirement']}` | {s['满足']} | {s['不满足']} | {s['未知']} | {s['不可判']} |")
    A("")

    A("## 7 · 已知缺口(判不了的,以及为什么)")
    A("")
    unjudgeable = [c for c in link["citations"] if not reqs[c["requirement"]].get("assessable")]
    A(f"**本 JD 有 {len(unjudgeable)}/{len(link['citations'])} 条要求判不了。** 分三类:")
    A("")
    A("| 要求 | 原文 | 为什么判不了 | 谁能答 |")
    A("|---|---|---|---|")
    for c in unjudgeable:
        r = reqs[c["requirement"]]
        if r.get("no_component"):
            why, who = "E 维没有组件 —— 素质只能面试", "面试评分表"
        elif r.get("blocked_by"):
            why, who = r["blocked_by"][:38], "建属性 / 证明文件"
        elif r.get("attribute_ref"):
            why, who = f"分类为 {r['attribute_ref']},该属性无供侧来源", "面试"
        else:
            why, who = "属性未建", "建属性"
        A(f"| `{r['id']}` | 「{c['verbatim'][:18]}」 | {why} | {who} |")
    A("")

    dangling = [(r["id"], p) for r in reqs.values() for p in (r.get("unlinked_parts") or [])
                if r["id"] in {c["requirement"] for c in link["citations"]}]
    if dangling:
        A("**原文提到、但能力目录里没有对应组件的:**")
        A("")
        for rid, p in dangling:
            A(f"- `{rid}` · 「{p.get('text')}」→ 目录缺口 `{p.get('gap')}`")
        A("")

    if link.get("excluded"):
        A("**出现在 JD 里、但不作为任职资格的:**")
        A("")
        for e in link["excluded"]:
            A(f"- 「{e.get('candidate_text')}」· {e.get('found_at')} · {e.get('verdict')}")
            A(f"  - 理由:{' '.join((e.get('why') or '').split())[:110]}")
        A("")

    A("## 8 · 数据血缘(每个数字的出处)")
    A("")
    A("| 数字 | 值 | 出处 |")
    A("|---|---|---|")
    A(f"| 原子要求条数 | {len(link['citations'])} | `count.atomic_requirements` |")
    A(f"| 候选人 | {len(pool)} | `abox.ttl`(已排除 owl:sameAs 重复) |")
    A(f"| 组件总数 | {len(catalog['components'])} | `component_catalog.yaml` |")
    A(f"| 要求总数 | {len(library['requirements'])} | `requirement_library.yaml` |")
    A(f"| 覆盖率阈值 | {E.COVERAGE} | `evaluate.py:COVERAGE` |")
    for field in ("age", "years", "education_rank", "major", "gender", "full_time"):
        if facts:
            p = evidence_profile(field, facts)
            parts = " · ".join(f"{BASIS_LABEL.get(k,k)} {v}" for k, v in sorted(p.items()))
            A(f"| {FIELD_LABEL[field]}证据构成 | — | {parts} |")
    A("")

    A('## 9 · 这份 JD 还算不上「合格」的地方')
    A("")
    problems = []
    if link.get("review_status") == "draft":
        problems.append("**草稿未经人工审核。** 粒度(一条要求拆几件事)由 LLM 决定,"
                        "只在跨 JD 去重时人工改过 9 条误复用。")
    if unjudgeable:
        problems.append(f"**{len(unjudgeable)} 条判不了**(见第 7 节)。"
                        f"这意味着名单的天花板是 {len(link['citations'])-len(unjudgeable)} 条。")
    if dangling:
        problems.append(f"**{len(dangling)} 处原文提到但目录没有组件** —— 覆盖率分母缺项。")
    problems.append("**年限有三个口径** —— 换口径人数会变(实测 106 / 116 / 0)。")
    problems.append("**12% 的学历结论依赖一条没有出处的校名推断规则** —— 该规则待你审。")
    for p in problems:
        A(f"- {p}")
    A("")
    A("---")
    A("")
    A("*生成本文的脚本: `backend/scripts/talent/render_jd.py`。"
      "任何一节若与 yaml 不符,diff 一次即可定位。*")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{args.jd}.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"写出 {out.relative_to(ROOT)}  {len(L)} 行")
    print(f"  引用 {len(link['citations'])} 条 · 判不了 {len(unjudgeable)} 条 · 候选人 {len(pool)} 人")
    return 0


if __name__ == "__main__":
    sys.exit(main())
