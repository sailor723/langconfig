#!/usr/bin/env python3
"""Check `work/talent/component_catalog.yaml` —— 组件目录的结构校验 + 门禁实跑。

为什么需要一个脚本,而不是把门禁写在 YAML 的注释里:一份只写在文档里的门禁等于一句愿望。
本仓库的规矩是"能跑起来的才算"。所以 C-G1…C-G7 在这里被执行,不命中就红。

这个脚本守住的是**目录与事实的一致性**,不是目录好不好看。具体三类:

  ① 自洽   —— 三层结构、ID 唯一、类别计数、维度条数合计 95、ordinal 单调
  ② 对库   —— 每个组件的 cv_count 必须等于 candidate_skill 的实测人数;
              每个属性的 cv_coverage 必须等于 candidate 表的实测覆盖;
              组件的 category 必须等于 skill 表的 category
  ③ 待条件 —— C-G3 / C-G7 需要 JD 链接文件(需求侧投影),现在还没建,
              所以它们报 NOT RUN 而不是 PASS —— **没跑过的检查不许说通过**

② 之所以重要,是实测教训:本文件第一版的 cv_count 是凭记忆写的,**53 个里 35 个是错的**
(skill_QC七大手法 写 14、实际 1;skill_线束行业知识 写 15、实际 72)。数字整齐不代表数字对。
现在 C-G6 把它们全部钉在库里。

用法:
    python -m scripts.talent.check_component_catalog             # 全跑
    python -m scripts.talent.check_component_catalog --no-db     # 只跑结构与自洽(不连库)
    python -m scripts.talent.check_component_catalog --links DIR # 同时校验 JD 链接文件(存在时)

Exit: 0 全部通过(允许有 NOT RUN),1 有检查失败,2 目录缺失或无法解析。
"""
from __future__ import annotations

import argparse
import collections
import os
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
CATALOG = ROOT / "work" / "talent" / "component_catalog.yaml"

OK = True
CHECKS = 0
FAILS = 0


def check_true(label: str, cond: bool, detail: str = "") -> None:
    global OK, CHECKS, FAILS
    CHECKS += 1
    good = bool(cond)
    OK = OK and good
    FAILS += 0 if good else 1
    print(f"  [{'PASS' if good else 'FAIL'}] {label}" + ("" if good else f" — {detail}"))


def not_run(label: str, why: str) -> None:
    print(f"  [NOT RUN] {label} — {why}")


# ─────────────────────────────────────────────────────── ① 结构自洽
def check_structure(cat: dict) -> None:
    print("\n=== C-0 结构:三层齐全,ID 唯一 ===")
    for key in ("version", "scope", "rules", "dimensions", "attributes",
                "categories", "components", "gaps", "validation"):
        check_true(f"顶层字段 {key}", key in cat)
    if not OK:
        return

    dim_ids = [d["id"] for d in cat["dimensions"]]
    att_ids = [a["id"] for a in cat["attributes"]]
    cat_ids = [c["id"] for c in cat["categories"]]
    comp_ids = [c["id"] for c in cat["components"]]

    check_true("维度 9 个且 ID 为 A–I",
               dim_ids == list("ABCDEFGHI"), f"实际 {dim_ids}")
    for name, ids in (("属性", att_ids), ("类别", cat_ids), ("组件", comp_ids)):
        dup = [k for k, n in collections.Counter(ids).items() if n > 1]
        check_true(f"{name} ID 唯一({len(ids)} 个)", not dup, f"重复 {dup}")

    total = sum(d["count"] for d in cat["dimensions"])
    check_true(f"9 个维度的 count 合计 = 95(10 份 JD 的原子要求总数)", total == 95, f"实际 {total}")

    stray = [a["id"] for a in cat["attributes"] if a["dimension"] not in dim_ids]
    check_true("每个属性的 dimension 都存在于 dimensions", not stray, f"悬空 {stray}")

    bad_cat = [c["id"] for c in cat["components"] if c["category"] not in cat_ids]
    check_true("C-G4 每个组件的 category 都存在于 categories", not bad_cat, f"悬空 {bad_cat}")

    gaps = {g["id"] for g in cat["gaps"]}
    referenced = set()
    for comp in cat["components"]:
        for key in ("gap", "pending_gap"):
            if comp.get(key):
                referenced.add(comp[key])
    for att in cat["attributes"]:
        if att.get("gap"):
            referenced.add(att["gap"])
    missing = sorted(referenced - gaps)
    check_true("组件/属性引用的 gap 都存在于 gaps", not missing, f"悬空 {missing}")

    # 属性 values 里若指名了组件,该组件必须存在
    dangling = []
    for att in cat["attributes"]:
        for value in att.get("values") or []:
            if isinstance(value, dict) and value.get("component") and value["component"] not in comp_ids:
                dangling.append((att["id"], value["component"]))
    check_true("属性取值里指名的组件都存在", not dangling, f"悬空 {dangling}")


def check_gates(cat: dict) -> None:
    print("\n=== C-G1 基数:中间层元件必须能表达「有/没有」或「大于/小于」 ===")
    bad = [a["id"] for a in cat["attributes"]
           if a.get("cardinality") not in ("single", "set")]
    check_true("每个属性都有 cardinality ∈ {single, set}", not bad, f"{bad}")

    no_scale = [a["id"] for a in cat["attributes"]
                if a.get("cardinality") == "single" and not a.get("scale")]
    check_true("每个 single 属性都有 scale(否则 ≥ 无法表达)", not no_scale, f"{no_scale}")

    no_prop = [a["id"] for a in cat["attributes"]
               if a.get("cardinality") == "set" and "prop" not in a]
    check_true("每个 set 属性都显式写了 prop(可以是 null)", not no_prop, f"{no_prop}")

    print("\n=== C-G2 顺序:ordinal / interval 的取值必须单调 ===")
    for att in cat["attributes"]:
        if att.get("cardinality") != "single" or att.get("scale") not in ("ordinal", "interval"):
            continue
        values = att.get("values")
        if not values:
            continue
        codes = [v["code"] if isinstance(v, dict) else v for v in values]
        # 只接受**升序**。第一版同时接受降序,于是把学历顺序整个颠倒也能通过 ——
        # 而颠倒之后 `>=` 会判反,这正是这条门禁要拦的事。一个刻度只允许一种约定。
        check_true(f"{att['id']} {att['label']} 的取值升序({len(codes)} 档)",
                   codes == sorted(codes), f"{codes} —— 降序会让 ≥ 判反")

    print("\n=== C-G5 计数:category.component_count 必须等于实际组件数 ===")
    actual = collections.Counter(c["category"] for c in cat["components"])
    wrong = [(c["id"], c["component_count"], actual.get(c["id"], 0))
             for c in cat["categories"] if c["component_count"] != actual.get(c["id"], 0)]
    check_true("22 个类别的 component_count 全部对得上", not wrong, f"{wrong}")

    empty = [c["id"] for c in cat["categories"] if actual.get(c["id"], 0) == 0]
    check_true("没有空类别(声明了类别却没有任何组件)", not empty, f"{empty}")


# ─────────────────────────────────────────────────────── ② 对库
def check_against_db(cat: dict) -> None:
    import psycopg2

    try:
        conn = psycopg2.connect(
            host=os.environ.get("ONTOLOGY_DB_HOST", "127.0.0.1"),
            port=int(os.environ.get("ONTOLOGY_DB_PORT", "5433")),
            dbname=os.environ.get("ONTOLOGY_DB_NAME", "talent_db"),
            user=os.environ.get("ONTOLOGY_DB_USER", "langconfig"),
            password=os.environ.get("ONTOLOGY_DB_PASSWORD", "langconfig_dev"),
        )
    except Exception as exc:
        not_run("C-G6 / 覆盖率 / 类别 —— 连不上 talent_db", str(exc).strip().splitlines()[0])
        return

    try:
        with conn.cursor() as cur:
            cur.execute("select skill, count(*) from candidate_skill group by skill")
            skill_rows = dict(cur.fetchall())
            cur.execute("select skill, category from skill")
            skill_cat = dict(cur.fetchall())
            cur.execute("select education_rank, count(*) from candidate "
                        "where education_rank is not null group by 1")
            edu_rows = {int(k): v for k, v in cur.fetchall()}
            cur.execute("select count(*), count(education_rank), count(years_experience), "
                        "count(age) from candidate")
            total, edu, years, age = cur.fetchone()
    finally:
        conn.close()

    print(f"\n=== C-G6 对库:cv_count 必须是实测人数(语料 {total} 份) ===")
    wrong = [(c["id"], c["cv_count"], skill_rows.get(c["id"], 0))
             for c in cat["components"] if c["cv_count"] != skill_rows.get(c["id"], 0)]
    check_true(f"{len(cat['components'])} 个组件的 cv_count 全部等于 candidate_skill 实测",
               not wrong, f"{len(wrong)} 条不符, e.g. {wrong[:3]}")

    declared = sum(c["cv_count"] for c in cat["components"])
    check_true("组件 cv_count 合计 = candidate_skill 总行数",
               declared == sum(skill_rows.values()),
               f"{declared} vs {sum(skill_rows.values())}")

    orphan = sorted(set(skill_rows) - {c["id"] for c in cat["components"]})
    check_true("库里的技能没有一个是目录漏掉的", not orphan, f"漏 {orphan[:5]}")
    phantom = sorted({c["id"] for c in cat["components"]} - set(skill_rows))
    check_true("目录里的组件没有一个是库里不存在的", not phantom, f"多 {phantom[:5]}")

    cat_wrong = [(c["id"], c["category"], skill_cat.get(c["id"]))
                 for c in cat["components"] if skill_cat.get(c["id"]) != c["category"]]
    check_true("每个组件的 category 等于 skill 表的 category", not cat_wrong,
               f"{len(cat_wrong)} 条不符, e.g. {cat_wrong[:3]}")

    print("\n=== 属性覆盖率:cv_coverage 必须是实测值 ===")
    measured = {}
    for att in cat["attributes"]:
        prop = att.get("prop")
        if not prop:
            continue
        if prop == "education_rank":
            measured[att["id"]] = edu
        elif prop == "years_experience":
            measured[att["id"]] = years
        elif prop == "age":
            measured[att["id"]] = age
    for att_id, real in measured.items():
        att = next(a for a in cat["attributes"] if a["id"] == att_id)
        check_true(f"{att_id} {att['label']} 的 cv_coverage = {real}/{total}",
                   att["cv_coverage"] == real, f"目录写 {att['cv_coverage']}")

    for att in cat["attributes"]:
        if att.get("cardinality") == "single" and att.get("prop") == "education_rank":
            bad = [(v["code"], v["cv_count"], edu_rows.get(v["code"]))
                   for v in att.get("values") or []
                   if isinstance(v, dict) and v.get("cv_count") != edu_rows.get(v["code"])]
            check_true("B.1 各学历档的人数 = 库里的实测分布", not bad, f"{bad}")


# ─────────────────────────────────────────────────────── ③ 待条件
def check_links(cat: dict, links_dir: pathlib.Path | None) -> None:
    print("\n=== C-G3 / C-G7 JD 链接门禁 ===")
    files = sorted(links_dir.glob("*.yaml")) if links_dir and links_dir.is_dir() else []
    if not files:
        not_run("C-G3 每条 JD 引用都带逐字原文",
                "还没有 JD 链接文件(需求侧投影未建),没有东西可查")
        not_run("C-G7 prop_exists=false 的属性不得被已判定的要求引用",
                "同上 —— 需要链接文件里的 assessable 标记")
        return

    comp_ids = {c["id"] for c in cat["components"]}
    att_ids = {a["id"]: a for a in cat["attributes"]}
    gap_ids = {g["id"] for g in cat.get("gaps") or []}
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        reqs = doc.get("requirements") or []
        missing_verbatim = [r.get("id") for r in reqs if not r.get("verbatim")]
        check_true(f"{path.name}:{len(reqs)} 条要求全部带 verbatim",
                   not missing_verbatim, f"{missing_verbatim}")

        # C-G3 的实形:verbatim 必须是原文的逐字子串。这是"要求被改写/被编造"的唯一解药。
        source_rel = doc.get("source_text") or ""
        source_path = (ROOT / source_rel) if source_rel else None
        if source_path and source_path.is_file():
            text = source_path.read_text(encoding="utf-8")
            invented = [r.get("id") for r in reqs
                        if r.get("verbatim") and r["verbatim"] not in text]
            check_true(f"{path.name}: 每条 verbatim 都是原文逐字子串",
                       not invented, f"{invented} —— 在 {source_rel} 里找不到")

            # source_text 必须是原文的**一整行**;verbatim 必须是 source_text 的子串。
            # 这是把"文字当主锚点"落地的地方 —— 行号会随重新抽取而漂,文字不会。
            lines_set = {ln.strip() for ln in text.split("\n")}
            bad_src = [r.get("id") for r in reqs
                       if r.get("source_text") and r["source_text"].strip() not in lines_set]
            check_true(f"{path.name}: source_text 都是原文的一整行", not bad_src, f"{bad_src[:3]}")
            not_in_src = [r.get("id") for r in reqs
                          if r.get("source_text") and r.get("verbatim")
                          and r["verbatim"] not in r["source_text"]]
            check_true(f"{path.name}: verbatim 都落在 source_text 里", not not_in_src,
                       f"{not_in_src[:3]} —— 引文和它声称的出处原句不一致")

            # txt_line 必须是**真实文件行号**,不是段内序号。
            # 第一版就是段内序号(1~7),而真行号是 14~20 —— 差 13 行,名字却叫 sourceLine。
            lines_of = text.split("\n")
            wrong_line = []
            for r in reqs:
                v = r.get("verbatim")
                if not v or r.get("txt_line") is None:
                    continue
                real = [i + 1 for i, ln in enumerate(lines_of) if v in ln]
                if not real:
                    wrong_line.append((r.get("id"), r["txt_line"], None))
                elif r["txt_line"] not in real:
                    wrong_line.append((r.get("id"), r["txt_line"], real))
            check_true(f"{path.name}: txt_line 是原文的真实行号",
                       not wrong_line, f"{wrong_line[:3]} —— 段内序号不是行号")
        else:
            not_run(f"{path.name}: verbatim 逐字回查", f"缺 source_text({source_rel or '未声明'})")

        # J-G2:自己声明的原子条数必须等于实际列出的条数
        declared = (doc.get("count") or {}).get("atomic_requirements")
        check_true(f"{path.name}: 声明的原子条数 {declared} = 实际 {len(reqs)}",
                   declared == len(reqs), "声明与实际不符")

        # 留空必须指向目录里存在的 gap
        bad_gap = [(r.get("id"), p2.get("gap")) for r in reqs
                   for p2 in (r.get("unlinked_parts") or []) if p2.get("gap") not in gap_ids]
        check_true(f"{path.name}: unlinked_parts 指向的 gap 都存在", not bad_gap, f"{bad_gap}")

        # J-G3:被排除的条目也要可回查
        excl = doc.get("excluded") or []
        no_proof = [e.get("id") for e in excl if not e.get("found_at")]
        check_true(f"{path.name}: {len(excl)} 条被排除项都写了 found_at", not no_proof, f"{no_proof}")
        bad_comp = [(r.get("id"), c) for r in reqs for c in (r.get("components") or [])
                    if c not in comp_ids]
        check_true(f"{path.name}: 引用的组件都在目录里", not bad_comp, f"{bad_comp[:3]}")
        bad_att = [(r.get("id"), r["attribute"]) for r in reqs
                   if r.get("attribute") and r["attribute"] not in att_ids]
        check_true(f"{path.name}: 引用的属性都在目录里", not bad_att, f"{bad_att[:3]}")

        # J-G4:要求必须连到**携带信息**的最具体节点。
        #   prop 有名字(哪怕还没建)  → 连 Attribute:它告诉我们要建哪个属性
        #   prop 是 null             → 连 Dimension:那个属性只是分类标签,不是候选人侧属性
        stub = [(r.get("id"), r["attribute"]) for r in reqs
                if r.get("attribute") and att_ids.get(r["attribute"], {}).get("prop") is None]
        check_true(f"{path.name}: 没有把要求连到 prop=null 的空壳属性", not stub,
                   f"{stub} —— 应改用 dimension:")

        dim_ids = {d["id"] for d in cat["dimensions"]}
        bad_dim = [(r.get("id"), r["dimension"]) for r in reqs
                   if r.get("dimension") and r["dimension"] not in dim_ids]
        check_true(f"{path.name}: 直接声明的 dimension 都在目录里", not bad_dim, f"{bad_dim}")

        # 每条要求都必须能落进恰好一个维度:要么经属性,要么自己声明,要么挂组件(→D)
        att_dim = {a["id"]: a["dimension"] for a in cat["attributes"]}
        landing = []
        for r in reqs:
            dim = att_dim.get(r.get("attribute") or "") or r.get("dimension") \
                or ("D" if r.get("components") else None)
            if not dim:
                landing.append(r.get("id"))
        check_true(f"{path.name}: 每条要求都能落进一个维度", not landing,
                   f"{landing} —— 既没属性也没 dimension 也没组件")

        blocked = []
        for req in reqs:
            att = att_ids.get(req.get("attribute") or "")
            if req.get("assessable") and att and att.get("prop_exists") is False:
                blocked.append((req.get("id"), att["id"], "attribute"))
            level = req.get("level_check") or {}
            latt = att_ids.get(level.get("attribute") or "")
            if level.get("assessable") and latt and latt.get("prop_exists") is False:
                blocked.append((req.get("id"), latt["id"], "level_check"))
        check_true(f"{path.name}: 没有把「属性未建」的要求标成可判定",
                   not blocked, f"{blocked[:3]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-db", action="store_true", help="只跑结构与自洽,不连库")
    ap.add_argument("--links", default="", help="JD 链接文件目录(可选,存在时才校验 C-G3/C-G7)")
    # --catalog 让变异测试可以在副本上跑:一个只在真文件上能跑的门禁是没法证明自己有牙齿的
    ap.add_argument("--catalog", default=str(CATALOG), help="默认读 work/talent/component_catalog.yaml")
    args = ap.parse_args()

    catalog = pathlib.Path(args.catalog).resolve()
    if not catalog.is_file():
        print(f"NOT RUN — 找不到目录 {catalog}")
        return 2
    try:
        cat = yaml.safe_load(catalog.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"NOT RUN — {catalog.name} 无法解析:\n{exc}")
        return 2

    print(f"catalog: {catalog}  v{cat.get('version')}")
    print(f"规模: 维度 {len(cat.get('dimensions') or [])} · 属性 {len(cat.get('attributes') or [])} "
          f"· 类别 {len(cat.get('categories') or [])} · 组件 {len(cat.get('components') or [])}")

    check_structure(cat)
    if not OK:
        print(f"\n{CHECKS} checks · {FAILS} failed · 结构不成立,跳过后续门禁")
        return 1

    check_gates(cat)
    if args.no_db:
        not_run("C-G6 对库校验", "--no-db")
    else:
        check_against_db(cat)
    check_links(cat, pathlib.Path(args.links) if args.links else None)

    print(f"\n{CHECKS} checks · {FAILS} failed · {'green' if OK else 'RED'}")
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
