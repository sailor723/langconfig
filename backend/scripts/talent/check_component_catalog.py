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
import json
import os
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
CATALOG = ROOT / "work" / "talent" / "component_catalog.yaml"
LIBRARY = ROOT / "work" / "talent" / "requirement_library.yaml"
TEMPLATE = ROOT / "work" / "talent" / "jd_template.yaml"

OK = True
CHECKS = 0
FAILS = 0
#: 被标记为「未审」的份数。**不算失败**,但必须出现在汇总行里 ——
#: 否则「green」会被读成「全都审过了」,而实际上门禁只检查已经写下来的东西。
NOT_RUN_UNITS = 0


def check_true(label: str, cond: bool, detail: str = "") -> None:
    global OK, CHECKS, FAILS
    CHECKS += 1
    good = bool(cond)
    OK = OK and good
    FAILS += 0 if good else 1
    print(f"  [{'PASS' if good else 'FAIL'}] {label}" + ("" if good else f" — {detail}"))


def not_run(label: str, why: str) -> None:
    print(f"  [NOT RUN] {label} — {why}")


def not_reviewed(label: str, why: str) -> None:
    """标记一份"存在但没被审过"的东西。会计入汇总行,不计入失败。"""
    global NOT_RUN_UNITS
    NOT_RUN_UNITS += 1
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
    # 目录里的组件必须真的有人持有 —— 这条防的是"为了填缺口而造词"。
    # 唯一的例外是**显式声明**的 `detectable: false`:原文点了名、但当前抽取路径检不出。
    # 例外不是开口子,而是换一条更严的规则:
    #   · 没这个标记的幽灵组件照旧红(不能凭空造词)
    #   · 有这个标记的,cv_count 必须是 0(有人持有就不该标"检不出")
    #   · 有这个标记的,必须写 note 说明为什么检不出(不许静默豁免)
    phantom = sorted({c["id"] for c in cat["components"]} - set(skill_rows))
    declared_blind = {c["id"] for c in cat["components"] if c.get("detectable") is False}
    undeclared = [c for c in phantom if c not in declared_blind]
    check_true("目录里的组件没有一个是库里不存在的(除显式 detectable:false)",
               not undeclared, f"多 {undeclared[:5]}")

    bad_count = [(c["id"], c["cv_count"]) for c in cat["components"]
                 if c.get("detectable") is False and c.get("cv_count") != 0]
    check_true("detectable:false 的组件 cv_count 必须是 0(有人持有就不算检不出)",
               not bad_count, f"{bad_count}")

    silent_blind = [c["id"] for c in cat["components"]
                    if c.get("detectable") is False and not (c.get("note") or "").strip()]
    check_true("detectable:false 的组件都写明了为什么检不出", not silent_blind,
               f"{silent_blind} —— 静默豁免就是造词")

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
def check_library(lib: dict, cat: dict) -> None:
    """要求库(JD 无关)自身的门禁:语义必须落在目录上。"""
    print("\n=== 要求库:语义必须落在能力全集上 ===")
    atts = {a["id"]: a for a in cat["attributes"]}
    comps = {c["id"] for c in cat["components"]}
    dims = {d["id"] for d in cat["dimensions"]}
    reqs = lib.get("requirements") or []

    check_true(f"要求库有 {len(reqs)} 条要求", len(reqs) > 0)

    # J-G4:prop 是 null 的属性只是分类标签,不是候选人侧属性 → 要求不许连它
    stub = []
    for r in reqs:
        att = atts.get(r.get("attribute") or "")
        if att is not None and att.get("prop") is None:
            stub.append((r["id"], att["id"]))
    check_true("没有要求连到 prop=null 的空壳属性", not stub, f"{stub} —— 应改用 attribute_ref")

    bad_dim = [(r["id"], r["dimension"]) for r in reqs if r["dimension"] not in dims]
    check_true("每条要求的 dimension 都在目录里", not bad_dim, f"{bad_dim}")

    bad_att = [(r["id"], r["attribute"]) for r in reqs
               if r.get("attribute") and r["attribute"] not in atts]
    check_true("每条要求引用的属性都在目录里", not bad_att, f"{bad_att}")

    bad_comp = [(r["id"], c) for r in reqs for c in (r.get("components") or [])
                if c not in comps]
    check_true("每条要求引用的组件都在目录里", not bad_comp, f"{bad_comp}")

    # `unlinked_parts` 是"原文点了名、但没连上组件"的登记簿。组件补上之后这条登记就**过期**了,
    # 而过期不会报任何错 —— 它会一直躺在库里,让复核的人以为缺口还在。实测:REQ-D-QA-TOOLS 的
    # 5WHY 早已补成 skill_5WHY,登记却还在,同一个 note 里 122 行的更正和 114 行的旧说法自相矛盾;
    # agent 386 核验品质经理时正是靠读文件才发现这处矛盾 —— 也就是说这个矛盾本来是**人肉**才看得见的。
    comp_label = {c["id"]: str(c.get("label") or "") for c in cat["components"]}
    stale_unlinked = []
    for r in reqs:
        for part in (r.get("unlinked_parts") or []):
            text = str(part.get("text") or "").strip().lower()
            if not text:
                continue
            covered = [c for c in (r.get("components") or [])
                       if text in c.lower() or text in comp_label.get(c, "").lower()]
            if covered:
                stale_unlinked.append((r["id"], part.get("text"), covered))
    check_true("unlinked_parts 里没有已经连上组件的条目", not stale_unlinked,
               f"{stale_unlinked} —— 组件已存在就该删掉这条登记,缺口写在组件上")

    # 层级:组件必须属于要求声明的维度(这条抓出过 REQ-H-LANG-EN 放 H 维的错误)
    comp_dim = {}
    for c in cat["components"]:
        for catg in cat["categories"]:
            if catg["id"] == c["category"]:
                comp_dim[c["id"]] = "D"
    wrong = [(r["id"], c) for r in reqs for c in (r.get("components") or [])
             if comp_dim.get(c) and comp_dim[c] != r["dimension"]]
    check_true("引用的组件都属于要求声明的维度", not wrong, f"{wrong}")

    # 不可判的要求必须说明为什么不可判
    silent = [r["id"] for r in reqs
              if not r.get("assessable") and not (r.get("no_component") or r.get("blocked_by")
                                                  or r.get("note") or r.get("attribute_ref"))]
    check_true("每条不可判的要求都写了原因", not silent, f"{silent}")

    # assessable=true 但依赖的属性不存在 → 撒谎
    lying = []
    for r in reqs:
        if not r.get("assessable"):
            continue
        att = atts.get(r.get("attribute") or "")
        if att is not None and att.get("prop_exists") is False:
            lying.append((r["id"], att["id"]))
        lvl = atts.get((r.get("level_check") or {}).get("attribute") or "")
        if (r.get("level_check") or {}).get("assessable") and lvl and lvl.get("prop_exists") is False:
            lying.append((r["id"], lvl["id"], "level_check"))
    check_true("没有把「属性未建」的要求标成可判定", not lying, f"{lying}")


def check_links(cat: dict, lib: dict, links_dir: pathlib.Path | None) -> None:
    """引用(JD 专属)的门禁:原话可回查、语义字段不许混进来。"""
    print("\n=== 引用:每条原话都能回查到原文 ===")
    files = sorted(links_dir.glob("*.yaml")) if links_dir and links_dir.is_dir() else []
    if not files:
        not_run("引用门禁", "还没有 JD 链接文件")
        return

    lib_ids = {r["id"] for r in (lib.get("requirements") or [])}
    total = 0
    client_total = 0
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cites = doc.get("citations") or []
        total += len(cites)
        # 客户原话子集要在最前面就算好 —— 后面缺 source_text 会 continue,
        # 那时再定义就晚了(踩过:UnboundLocalError)
        client_cites = [c for c in cites if c.get("origin") == "client"]
        client_total += len(client_cites)
        check_true(f"{path.name}: 读到 {len(cites)} 条引用(不是 0)", len(cites) > 0,
                   "文件结构不对 —— 读成 0 条会让所有检查空过")

        declared = (doc.get("count") or {}).get("atomic_requirements")
        check_true(f"{path.name}: 声明的原子条数 {declared} = 实际 {len(cites)}",
                   declared == len(cites), "声明与实际不符")

        dangling = [(c["id"], c.get("requirement")) for c in cites
                    if c.get("requirement") not in lib_ids]
        check_true(f"{path.name}: 每条引用的 requirement 都在要求库里",
                   not dangling, f"{dangling[:3]}")

        # J-G5:引用不许带语义字段
        leaked = [(c["id"], k) for c in cites
                  for k in ("dimension", "attribute", "components") if k in c]
        check_true(f"{path.name}: 引用没带语义字段(dimension/attribute/components)",
                   not leaked, f"{leaked[:3]} —— 语义是库的事")

        # ── 出处:客户原话 vs HR 侧要求。两者不许混为一谈 ──
        # 客户原话有逐字坐标(verbatim/txt_line/source_text),必须能回查客户文件;
        # HR 侧要求没有客户原话,硬给它安一个 verbatim 就是替客户说话。
        bad_origin = [(c["id"], c.get("origin")) for c in cites
                      if c.get("origin") not in ("client", "hr")]
        check_true(f"{path.name}: 每条引用都声明 origin(client/hr)", not bad_origin,
                   f"{bad_origin[:3]}")

        hr = [c for c in cites if c.get("origin") == "hr"]
        fake_client = [(c["id"], k) for c in hr
                       for k in ("verbatim", "txt_line", "source_text") if c.get(k) is not None]
        check_true(f"{path.name}: HR 侧要求不冒充客户原话(不带 verbatim/txt_line)",
                   not fake_client, f"{fake_client[:3]}")

        hr_thin = [c["id"] for c in hr
                   if not c.get("author") or not c.get("rationale")]
        check_true(f"{path.name}: 每条 HR 侧要求都写了 author 与 rationale",
                   not hr_thin, f"{hr_thin[:3]} —— 没理由的要求不许进 JD")

        no_verbatim = [c["id"] for c in client_cites if not c.get("verbatim")]
        check_true(f"{path.name}: 每条客户引用都有 verbatim", not no_verbatim, f"{no_verbatim}")

        source_rel = doc.get("source_text") or ""
        source_path = (ROOT / source_rel) if source_rel else None
        if not (source_path and source_path.is_file()):
            not_run(f"{path.name}: 逐字回查", f"缺 source_text({source_rel or '未声明'})")
            continue
        text = source_path.read_text(encoding="utf-8")
        lines_of = text.split("\n")
        lines_set = {ln.strip() for ln in lines_of}

        invented = [c["id"] for c in client_cites if c["verbatim"] not in text]
        check_true(f"{path.name}: 每条 verbatim 都是原文逐字子串", not invented,
                   f"{invented[:3]} —— 在 {source_rel} 里找不到")

        bad_src = [c["id"] for c in client_cites
                   if c.get("source_text") and c["source_text"].strip() not in lines_set]
        check_true(f"{path.name}: source_text 都是原文的一整行", not bad_src, f"{bad_src[:3]}")

        not_in = [c["id"] for c in client_cites
                  if c.get("source_text") and c["verbatim"] not in c["source_text"]]
        check_true(f"{path.name}: verbatim 都落在自己的 source_text 里", not not_in,
                   f"{not_in[:3]}")

        wrong_line = []
        for c in client_cites:
            real = [i + 1 for i, ln in enumerate(lines_of) if c["verbatim"] in ln]
            if c.get("txt_line") is None:
                continue
            if not real:
                wrong_line.append((c["id"], c["txt_line"], None))
            elif c["txt_line"] not in real:
                wrong_line.append((c["id"], c["txt_line"], real))
        check_true(f"{path.name}: txt_line 是原文的真实行号", not wrong_line, f"{wrong_line[:3]}")

    print(f"\n   合计 {total} 条引用(客户原话 {client_total} · HR 侧 {total - client_total})")



#: 「note 里声称人已决定」的句式。带否定的句子(「未经 admin 确认」)不算声称 ——
#: 它恰恰是在说"没有确认",把它也要求一条记录就是逼人造假。
_CLAIM_RE = re.compile(r"(admin\s*(?:定|决定|确认|拍板)|人工确认|已确认|已经确认)")
_CLAIM_NEG_RE = re.compile(r"(未经|未确认|没有确认|待确认|尚未确认|尚未经|不是\s*admin)")

#: 客户**明说还没定**的句子。这类句子不是任职资格(不进引用),但它对下游的待补清单
#: 是最有用的一类信息 —— 客户亲口承认的空白,比我们猜出来的空白可信得多。
_UNDEFINED_RE = re.compile(r"(没制定|未制定|暂无|待定|另定|未定|不详|暂不|以后再定|尚未)")


def _claimed_decisions(doc: dict) -> list[str]:
    """note / count_note 里声称「admin 定过」的引用 id(排除否定句)。"""
    out: list[str] = []
    for c in (doc.get("citations") or []):
        note = str(c.get("note") or "")
        if _CLAIM_RE.search(note) and not _CLAIM_NEG_RE.search(note):
            out.append(str(c.get("id")))
    count_note = str((doc.get("count") or {}).get("count_note") or "")
    if _CLAIM_RE.search(count_note) and not _CLAIM_NEG_RE.search(count_note):
        out.append("count")
    return out


def _check_undefined_statements(path: pathlib.Path, doc: dict) -> None:
    """原文里「目前没制定 / 暂无 / 待定」这类句子,要么被引用覆盖,要么登记在案。

    为什么必须有这一条:2026-11-20 品质经理的 `_source` 第 106 行孤零零一句「目前没制定」,
    两轮 agent 都没处理 —— 它不是任职资格,所以不进引用是对的;但它**是客户明说某项还没定**,
    对第 2 步的待补清单恰恰最有用。没登记的后果不是"少一条要求",是**这句话彻底消失**。

    判据:该行被某条引用占了(txt_line == 该行),或者在 `undefined_statements` 里点过名。
    """
    src_rel = str(doc.get("source_text") or "").strip()
    if not src_rel:
        return
    src = (ROOT / src_rel) if not pathlib.Path(src_rel).is_absolute() else pathlib.Path(src_rel)
    if not src.is_file():
        check_true(f"{path.name}: 找得到 source_text 以便核对「客户说没定」的句子", False,
                   f"读不到 {src_rel}")
        return

    covered = {int(c["txt_line"]) for c in (doc.get("citations") or [])
               if c.get("txt_line") is not None}
    declared = {int(x["txt_line"]) for x in (doc.get("undefined_statements") or [])
                if x.get("txt_line") is not None}

    hits = []
    for i, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
        if _UNDEFINED_RE.search(line):
            hits.append((i, line.strip()))
    lost = [(i, t) for (i, t) in hits if i not in covered and i not in declared]
    check_true(f"{path.name}: 客户明说「还没定」的句子都有去处", not lost,
               f"{lost} —— 要么它是任职资格(进引用),要么登记进 `undefined_statements`,"
               f"不许让它无声消失")


#: 「可能该拆」的机械信号 —— 这**是筛子,不是判据**。
#: 它挑出"值得人看一眼"的条目,不替人判断该不该拆:实测「高中**及**以上学历」(阈值写法)和
#: 「1、2、3、」(列表序号)都会被朴素匹配命中,而 agent 正确地把它们判成"不该拆"。
#: 所以这里先去掉两类噪音(列表序号、「及以上/或以下」),剩下的仍只是候选。
_NUMBERING = re.compile(r"^\s*(\d+|[一二三四五六七八九十]+)\s*[、.）)]\s*")
_SPLIT_SIGNAL = re.compile(r"(及|以及|或者|和|、|/|或)")


def _split_candidate(verbatim: str) -> bool:
    """verbatim 去掉列表序号与「及以上」阈值后,是否仍含并列/连接词。"""
    s = _NUMBERING.sub("", verbatim)
    s = re.sub(r"(及|或以)(上|下)", "", s)
    return bool(_SPLIT_SIGNAL.search(s))


def check_coverage(links_dir: pathlib.Path | None) -> None:
    """哪些 JD **还没被审过**。

    这条检查的来由:2026-11-20 审完品质经理之后回头看另外 9 份,发现它们
    **零粒度决定、零排除、8 份零 note** —— 门禁全绿,但那是因为门禁只核对已经写下来的东西,
    而它们身上几乎什么都没写。**"绿"被读成了"没问题",实际是"没看过"**。

    所以这里不算失败,只点名:某份 JD 有「该拆没拆」的候选条目却一条粒度决定都没有,
    就按仓库既有约定标 `[NOT RUN]`,并且计数进汇总行 —— NOT RUN 不等于 PASS。
    """
    print("\n=== 覆盖度:哪些 JD 还没被审过 ===")
    files = sorted(links_dir.glob("*.yaml")) if links_dir and links_dir.is_dir() else []
    if not files:
        not_run("覆盖度", "还没有 JD 链接文件")
        return

    reviewed = 0
    total_signal = 0
    total_open = 0
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cites = doc.get("citations") or []
        signal = [c for c in cites if _split_candidate(str(c.get("verbatim") or ""))]
        decided = [c for c in signal if isinstance(c.get("granularity_decision"), dict)]
        open_ = len(signal) - len(decided)
        total_signal += len(signal)
        total_open += open_
        if signal and not decided:
            not_reviewed(f"{path.name}: {len(signal)} 条含拆分信号,0 条粒度决定",
                         f"未审 —— 这些条目没人看过该不该拆;审过的 JD 会把决定写进 citations/账本")
        else:
            reviewed += 1

    print(f"  已审 {reviewed}/{len(files)} 份 · 拆分候选 {total_signal} 条,"
          f"其中 {total_open} 条从未被审视过")
    print("  (机械筛子,只是挑出来给人看 —— 判「该不该拆」的是审的人,不是这条正则)")


def check_template(links_dir: pathlib.Path | None) -> None:
    """正式模板 `jd_template.yaml` 与渲染结果必须对得上。

    为什么需要这道门:这份模板原本是**两处代码字面量** —— `render_jd_final.py` 渲染 42 个码,
    `jd_input_form.py` 的 SPEC 只认识 29 个。后果是 13 个字段在回填表里「为什么需要 / 建议填法」
    两列是空的,业务方看到的就是空格子;而 A 级归责没有 owner,只能靠 agent 猜。
    模板提成数据后,这里钉住三件事:码集一致、每列不为空、owner 合法 —— 否则它又会飘回代码里。
    """
    print("\n=== 正式模板:与渲染结果一致、每列有内容 ===")
    if not TEMPLATE.is_file():
        check_true("jd_template.yaml 存在", False, f"找不到 {TEMPLATE}")
        return
    doc = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8")) or {}
    codes: list[str] = []
    empty: list[tuple[str, str]] = []
    bad_owner: list[tuple[str, str]] = []
    bad_level: list[tuple[str, str]] = []
    for sec in doc.get("sections") or []:
        for f in sec.get("fields") or []:
            code = str(f.get("code") or "")
            codes.append(code)
            for k in ("label", "level", "owner", "why", "how", "shape"):
                if not str(f.get(k) or "").strip():
                    empty.append((code, k))
            if f.get("owner") not in ("business", "hr"):
                bad_owner.append((code, f.get("owner")))
            if f.get("level") not in ("A", "B", "C"):
                bad_level.append((code, f.get("level")))

    check_true(f"模板字段 {len(codes)} 个且不重复", len(codes) == len(set(codes)) == 42,
               f"实际 {len(codes)},去重后 {len(set(codes))} —— 应为 42")
    check_true("模板里没有 S3 字段码(任职资格按维度渲染)", not [c for c in codes if c.startswith("S3.")],
               f"{[c for c in codes if c.startswith('S3.')]}")
    check_true("模板每列的 level/owner/why/how/shape 都不为空", not empty, f"{empty[:5]}")
    check_true("模板 owner ∈ {business, hr}(客户即业务方,没有第三个)", not bad_owner, f"{bad_owner[:5]}")
    check_true("模板 level ∈ {A, B, C}", not bad_level, f"{bad_level[:5]}")

    # ── 岗位类别:决定用哪版模板。未定 → 该 JD 标 NOT RUN(不许猜) ──
    docs_dir = ROOT / "work" / "talent" / "jd_docs"
    files = sorted(links_dir.glob("*.yaml")) if links_dir and links_dir.is_dir() else []
    role_by_jd: dict[str, str] = {}
    undefined: list[str] = []
    for path in files:
        doc_l = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        role = str(doc_l.get("role_type") or "").strip().lower()
        if role in ("manager", "staff"):
            role_by_jd[path.stem] = role
        else:
            undefined.append(path.stem)
            not_reviewed(f"{path.name}: 岗位类别未定", 
                         "role_type 缺失/undetermined —— 用错模板不会报错,只会问一堆不该问的问题")
    if files:
        # **不算失败**,只点名(与「未审」同口径):岗位类别要业务方答,门禁替不了。
        # 但它必须出现在汇总行的"未审"计数里 —— 否则 green 会被读成"10 份都定好了"。
        print(f"  已定岗位类别 {len(role_by_jd)}/{len(files)} 份"
              + (f";未定 {len(undefined)} 份" if undefined else ""))

    # ── 模板码集必须等于该 JD 实际渲染出的字段集(按 role 分别核对) ──
    rendered: dict[str, set[str]] = {}
    for f in sorted(docs_dir.glob("*.fields.json")):
        try:
            fields = json.loads(f.read_text(encoding="utf-8")).get("fields") or {}
        except Exception:
            continue
        rendered[f.name.replace(".fields.json", "")] = {c for c in fields if not c.startswith("dim_")}
    if rendered:
        from scripts.talent.jd_template_loader import load as _load_tpl
        drift = {}
        for jd_name, got in rendered.items():
            role = role_by_jd.get(jd_name)
            if role is None:
                continue          # 未定岗位类别的 JD 已在上面标 NOT RUN
            want = set(_load_tpl(role)["by_code"])
            if got != want:
                drift[jd_name] = {"缺": sorted(want - got)[:6], "多": sorted(got - want)[:6]}
        check_true(f"模板码集 = 渲染输出({len(rendered)} 份 JD,按各自岗位类别核对)",
                   not drift, f"{drift} —— 模板与 render_jd_final 已经漂移")
    else:
        not_run("模板码集 vs 渲染输出", "还没有 jd_docs/*.fields.json")


def check_decisions(links_dir: pathlib.Path | None, reviews_dir: pathlib.Path | None) -> None:
    """决策账本:人定过什么,必须有**独立**记录。

    这条检查的来由很具体:2026-11-20 agent 386 核验品质经理时,读到 inline 的
    `granularity_decision: confirmed_keep / decided_by: admin`,却找不到任何独立记录,
    只能把这条列成「拿不准」。也就是说 —— **被审的文件在给自己作证**,而当时没有任何门禁看得见这件事。

    现在两边交叉校验:inline 的每条粒度决定、每条 excluded,在账本里都必须有 subject 匹配的条目,
    且 status / decided_by / decided_at 必须逐字一致。谁单方面改口径,这里就红。

    未签署的决定允许存在(`signoff: pending`),但**必须是显式的** —— 门禁会把它数出来并打印,
    而不是让"没签"混在"签了"里看不出来。不许为了让门禁变绿补一个没发生过的签署。
    """
    print("\n=== 决策账本:粒度与排除都有独立记录 ===")
    files = sorted(links_dir.glob("*.yaml")) if links_dir and links_dir.is_dir() else []
    if not files:
        not_run("决策账本", "还没有 JD 链接文件")
        return

    DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    pending_seen: list[str] = []

    # 「note 里声称人已决定」与「原文里客户明说还没定」这两种句子,以前会静默消失:
    # 前者让被审的文件自己给自己作证,后者把客户亲口承认的空白丢掉。
    # 两条规则都写在门禁里 → 对**每一份** JD 都成立,不是给某一份打补丁。
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cites = doc.get("citations") or []
        inline = [(c.get("id"), c["granularity_decision"]) for c in cites
                  if isinstance(c.get("granularity_decision"), dict)]
        excluded = [x.get("id") for x in (doc.get("excluded") or []) if x.get("id")]

        # ── 规则①:note 里声称「admin 定过」的,必须在账本里有记录 ──
        claims = _claimed_decisions(doc)
        if not inline and not excluded and not claims:
            continue      # 这份 JD 没有需要签署的决定、也没有引用签署,不要求账本

        review_path = (reviews_dir / path.name) if reviews_dir else None
        has_review = bool(review_path and review_path.is_file())
        check_true(f"{path.name}: 有 {len(inline)} 条粒度决定 / {len(excluded)} 条排除,"
                   f"账本 jd_reviews/{path.name} {'存在' if has_review else '缺失'}",
                   has_review,
                   "决定写在 jd_links 里就是自述 —— 没有账本,复核的人无从查证")
        if not has_review:
            continue

        book = yaml.safe_load(review_path.read_text(encoding="utf-8")) or {}
        decisions = book.get("decisions") or []

        covered = {str(d.get("subject")) for d in decisions}
        unbacked = [c for c in claims if c not in covered]
        check_true(f"{path.name}: note 里声称的决定都有账本记录", not unbacked,
                   f"{unbacked} —— 这些条目在 note 里说「admin 已定」,账本里却没有对应 subject。"
                   f"没有记录的签署等于没有签署")
        check_true(f"{path.name}: 账本声明 jd 与文件一致({book.get('jd')!r})",
                   book.get("jd") == (doc.get("jd") or path.stem),
                   f"账本 jd={book.get('jd')!r} 文件 jd={doc.get('jd')!r}")

        by_subject: dict[str, list[dict]] = {}
        for d in decisions:
            by_subject.setdefault(str(d.get("subject")), []).append(d)

        # ① 每条 inline 粒度决定都要有账本记录,且口径逐字一致
        for cid, dec in inline:
            recs = [d for d in by_subject.get(str(cid), []) if d.get("kind") == "granularity"]
            check_true(f"{path.name} {cid}: 粒度决定在账本里有记录",
                       bool(recs), f"账本里没有 subject={cid} 的 granularity 条目")
            if not recs:
                continue
            rec = recs[0]
            check_true(f"{path.name} {cid}: 账本 decision = inline status({dec.get('status')})",
                       rec.get("decision") == dec.get("status"),
                       f"账本 {rec.get('decision')!r} ≠ 文件 {dec.get('status')!r}")
            for field in ("decided_by", "decided_at"):
                if dec.get(field) is None:
                    continue
                got = str(rec.get(field) or "")
                want = str(dec.get(field))
                check_true(f"{path.name} {cid}: 账本 {field} = 文件 {want}",
                           got == want, f"账本 {got!r} ≠ 文件 {want!r} —— 两边必须指向同一个签署")

        # ② 每条 excluded 都要有账本记录
        for xid in excluded:
            recs = [d for d in by_subject.get(str(xid), []) if d.get("kind") == "exclusion"]
            check_true(f"{path.name} {xid}: 排除决定在账本里有记录", bool(recs),
                       f"账本里没有 subject={xid} 的 exclusion 条目")

        # ③ 账本不许记着文件里不存在的东西
        valid = {str(c.get("id")) for c in cites} | {str(x) for x in excluded}
        phantom = [(d.get("id"), d.get("subject")) for d in decisions
                   if str(d.get("subject")) not in valid]
        check_true(f"{path.name}: 账本条目的 subject 都存在于该 JD", not phantom,
                   f"{phantom} —— 账本记着不存在的引用,比没有记录更糟")

        # ④ 签署:要么齐,要么显式 pending
        for d in decisions:
            tag = f"{path.name} {d.get('id')}"
            if d.get("signoff") == "pending":
                pending_seen.append(tag)
                check_true(f"{tag}: 未签署的不许带 decided_by/decided_at",
                           not d.get("decided_by") and not d.get("decided_at"),
                           "写了 pending 又写了签署人,自相矛盾")
                continue
            missing = [f for f in ("decided_by", "decided_at") if not d.get(f)]
            check_true(f"{tag}: 已签署的条目有 decided_by + decided_at", not missing,
                       f"缺 {missing} —— 没有签署人的决定等于没有决定")
            when = d.get("decided_at")
            if when is not None and missing == []:
                check_true(f"{tag}: decided_at 是 YYYY-MM-DD",
                           bool(DATE_RE.match(str(when))), f"{when!r}")
            check_true(f"{tag}: 写了 why", bool(str(d.get("why") or "").strip()),
                       "没有 why 的决定,下次没人能判断它还成不成立")

        # ⑤ 同一条不许记两次
        keys = [(str(d.get("kind")), str(d.get("subject"))) for d in decisions]
        dups = sorted({k for k in keys if keys.count(k) > 1})
        check_true(f"{path.name}: 账本没有重复的 (kind, subject)", not dups, f"{dups}")

        # ⑥ 原文里客户**明说还没定**的句子,必须有个去处
        _check_undefined_statements(path, doc)

    if pending_seen:
        print(f"  ⚠ 未签署 {len(pending_seen)} 条(需要人点头,不是门禁能替的):"
              f" {', '.join(pending_seen)}")


def check_picks(picks_dir: pathlib.Path | None, policy_path: pathlib.Path | None) -> None:
    """第 5 步产物门禁:模拟数据可以进判定,但**必须每一处都标出来**。

    这道门存在的理由很具体:模拟访谈一度被当成真的一面,产出「入选 4 人」,
    而那 4 个人从没被谁面过。规则后来改成"可以放开"(interview_policy.yaml),
    放开之后唯一挡在假结论和递交之间的东西,就是产物上的标注 ——
    所以标注本身必须是可复算的门禁,而不是脚本里的一句 print。
    """
    if not picks_dir or not picks_dir.is_dir():
        not_run("选人产物门禁", f"找不到 {picks_dir}")
        return
    try:
        from scripts.talent import interview_policy
    except Exception as exc:  # noqa: BLE001
        check_true("选人产物门禁能读到规则模块", False, f"{type(exc).__name__}: {exc}")
        return
    if policy_path:
        interview_policy.POLICY = pathlib.Path(policy_path)

    files = sorted(picks_dir.glob("*.yaml"))
    if not files:
        not_run("选人产物门禁", "还没有第 5 步产物")
        return
    for f in files:
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            check_true(f"{f.name}: 能解析", False, str(exc)[:120])
            continue
        jd = doc.get("jd") or f.stem
        mode = str((doc.get("interview_policy") or {}).get("mode") or "")
        rec = interview_policy.record(jd)
        # ① 产物必须自带规则记录 —— 一年后"凭什么用模拟数据"要能从文件里答出来
        check_true(f"{f.name}: 产物里记了采信规则", bool(mode),
                   "interview_policy 段缺失 —— 无法复算当时按什么规则选的")
        if mode:
            check_true(f"{f.name}: 规则名合法", mode in interview_policy.MODES, f"mode={mode!r}")
        # ② 放开了模拟就必须有授权记录在策略文件里
        if mode == interview_policy.MOCK_ALLOWED:
            check_true(f"{f.name}: 放开模拟有授权记录(署名人+日期)",
                       bool(rec.get("decided_by") and rec.get("decided_at")),
                       "interview_policy.yaml 里这个 JD 缺 decided_by / decided_at")
        top = doc.get("top") or []
        mock_rows = [r for r in top if str(r.get("数据来源")) == "模拟(演练)"]
        real_rows = [r for r in top if str(r.get("数据来源")) in ("真访谈", "真+模拟")]
        # ③ 每一行都得有数据来源,不许空白 —— 空白就是含糊
        check_true(f"{f.name}: 每行都写了数据来源",
                   all(str(r.get("数据来源") or "").strip() for r in top),
                   "有行缺 数据来源")
        # ④ 模拟行必须能对回真实文件:说的和做的不许不一致
        cv_dir = ROOT / "work" / "talent" / "cv_interview"
        bad = []
        for r in mock_rows:
            path = cv_dir / f"{str(r['candidate']).replace('cand_', '')}.yaml"
            if not path.is_file():
                bad.append(f"{r['candidate']}: 无访谈文件")
                continue
            ans = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("answers") or []
            if any(interview_policy.is_real_basis(a) for a in ans):
                bad.append(f"{r['candidate']}: 标了模拟却含有真人答案")
        check_true(f"{f.name}: 标「模拟」的行确实只有模拟答案", not bad, "; ".join(bad[:3]))
        # ⑤ 真人行不许被标成模拟(反方向也要查)
        bad2 = []
        for r in real_rows:
            path = cv_dir / f"{str(r['candidate']).replace('cand_', '')}.yaml"
            if not path.is_file():
                continue
            ans = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("answers") or []
            has_real = any(interview_policy.is_real_basis(a) for a in ans)
            if str(r.get("数据来源")) == "真访谈" and not has_real:
                bad2.append(f"{r['candidate']}: 标了真访谈却没有真人答案")
        check_true(f"{f.name}: 标「真访谈」的行确实有真人答案", not bad2, "; ".join(bad2[:3]))
        # ⑥ 用了模拟数据,md 里必须有演练横幅 —— 递交出去的那份才算数
        md_path = picks_dir / f"{jd} 选人.md"
        if mock_rows:
            if md_path.is_file():
                body = md_path.read_text(encoding="utf-8")
                check_true(f"{f.name}: md 有演练横幅", "演练模式" in body,
                           "md 用了模拟数据却没有「演练模式」提示")
                check_true(f"{f.name}: md 横幅写了不得作为录用依据",
                           "不得作为录用决策依据" in body, "横幅没把这条禁令写全")
            else:
                check_true(f"{f.name}: 有人读的版本存在", False, f"缺 {md_path.name}")
        # ⑦ real_only 模式下不该出现任何模拟行
        if mode == interview_policy.REAL_ONLY:
            check_true(f"{f.name}: real_only 下无模拟行", not mock_rows,
                       f"{len(mock_rows)} 行用了模拟答案,与规则不符")


def check_shortlist(dirp: pathlib.Path | None) -> None:
    """第 3 步门禁:排除必须是**硬证据**,待核必须留有名字。

    这两条是「读不到 ≠ 不满足」在流程上的落地。实测过的错:第 3 步用一道
    "读不出品质岗"的信号挡掉了 165 个人,而短名单只有 4 人 —— 那个 4 不是筛选结果,
    是把"不知道"当成了"不行"。
    """
    if not dirp or not dirp.is_dir():
        not_run("短名单门禁", f"找不到 {dirp}")
        return
    files = sorted(dirp.glob("*.yaml"))
    if not files:
        not_run("短名单门禁", "还没有短名单")
        return
    for f in files:
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            check_true(f"{f.name}: 能解析", False, str(exc)[:100])
            continue
        if not doc.get("kept") and not doc.get("excluded"):
            # 只认第 3 步的初筛明细。第 5 步目标名单、3b 目标人数都没有 kept/excluded,
            # 拿它们查"没人同时在两边"是空过(vacuous pass)—— 看着绿,什么都没验。
            continue
        kept = set(doc.get("kept") or [])
        excluded = doc.get("excluded") or []
        qg = doc.get("quality_gate") or {}
        pending = {p.get("candidate") for p in (qg.get("needs_verification") or [])}
        # ⓪ 账要平:kept + excluded = pool。差一个人都说明有人被静默丢掉
        cnt = doc.get("count") or {}
        if cnt.get("pool") is not None:
            check_true(f"{f.name}: kept + excluded = pool(账平)",
                       int(cnt.get("kept") or 0) + int(cnt.get("excluded") or 0) == int(cnt["pool"]),
                       f'{cnt.get("kept")} + {cnt.get("excluded")} != {cnt["pool"]} —— 有人被丢掉却没记账')
        # ① 同一个人不能既排除又保留
        check_true(f"{f.name}: 没有人同时出现在 kept 与 excluded",
                   not (kept & {e.get("candidate") for e in excluded}),
                   "两边都有 = 后面读谁说了算都行,这是个不确定状态")
        # ② 待核的人必须还在 kept 里(不能借待核把人偷偷排除)
        check_true(f"{f.name}: 待核的人都留在 kept 里", not (pending - kept),
                   f"{len(pending - kept)} 人被标待核却不在 kept —— 等于还是排除了")
        # ③ excluded 必须是硬证据:要么有 attribute 判决,要么 quality=无(时长已知)
        soft = []
        for e in excluded:
            if e.get("stage") == "品质门槛":
                # 这一类是"职责命中品质动作,但该段时长已知且不足门槛" —— 也是硬证据,
                # 只是证据不是属性比较。它必须写清为什么,所以下面单独查 why。
                if not any((r.get("why") or "").strip() for r in (e.get("reasons") or [])):
                    soft.append(e.get("candidate"))
                continue
            v = e.get("verdicts") or {}
            hard = any(st == "不满足" for st in v.values())
            if not hard:
                soft.append(e.get("candidate"))
        check_true(f"{f.name}: 每条排除都有硬证据(至少一条属性不满足)", not soft,
                   f"{len(soft)} 人是「没读到」被排除的: {', '.join(x[:16] for x in soft[:3] if x)}")
        # ④ quality=无 必须有 months_known,否则又是拿读不出的时长当结论
        badq = [x.get("candidate") for x in (qg.get("failed") or [])
                if not (x.get("why") or "")]
        check_true(f"{f.name}: 品质门槛的排除都写了理由", not badq, f"{len(badq)} 条没有 why")


def check_interview_list(dirp: pathlib.Path | None) -> None:
    """面试名单门禁:排序口径必须是 9 层,切线必须交代 tie_band。

    这两条挡的是"名次可不可读靠嘴说" —— 口径和并列规模都必须是文件里的事实。
    """
    if not dirp or not dirp.is_dir():
        not_run("面试名单门禁", f"找不到 {dirp}")
        return
    files = sorted(dirp.glob("*.面试名单.yaml"))
    if not files:
        not_run("面试名单门禁", "还没有面试名单")
        return
    for f in files:
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            check_true(f"{f.name}: 能解析", False, str(exc)[:120])
            continue
        rules = doc.get("rank_rule") or []
        check_true(f"{f.name}: 排序口径是 9 层", len(rules) == 9, f"实际 {len(rules)} 层")
        cut = doc.get("cut") or {}
        check_true(f"{f.name}: 交代了切线 tie_band",
                   isinstance(cut.get("tie_band"), int), "缺 cut.tie_band")
        want = len(doc.get("selected") or [])
        check_true(f"{f.name}: 切线位置 = 名单人数", cut.get("position") == want,
                   f"{cut.get('position')} vs {want}")
        if cut.get("tie_band", 1) > 1:
            check_true(f"{f.name}: 并列区已标注 hash_decided", cut.get("hash_decided") is True,
                       "切线在并列区却没标 hash_decided")


def check_shortlist5(dirp: pathlib.Path | None, interview_dir: pathlib.Path | None,
                     list_dir: pathlib.Path | None) -> None:
    """第 5 步目标名单门禁:进名单的人必须是**面过的人**,人数必须对得上 HR 的目标。

    「第 5 步基于一面数据」这句话如果不检查,谁都能从 270 人的池子里直接点 8 个人
    写进短名单 —— 看起来一样,实际跳过了整条第 4 步。
    """
    if not dirp or not dirp.is_dir():
        not_run("第 5 步目标名单门禁", f"找不到 {dirp}")
        return
    files = sorted(dirp.glob("*.目标名单.yaml"))
    files = [f for f in files
             if str((yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("step") or "")
             .startswith("5")]
    if not files:
        not_run("第 5 步目标名单门禁", "还没有第 5 步目标名单")
        return
    for f in files:
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            check_true(f"{f.name}: 能解析", False, str(exc)[:120])
            continue
        jd = doc.get("jd") or f.name.split(".")[0]
        sel = list(doc.get("selected") or [])
        # ① 面过才进名单
        if interview_dir and interview_dir.is_dir():
            missing = [c for c in sel
                       if not (interview_dir / f"{str(c).replace('cand_', '')}.yaml").is_file()]
            check_true(f"{f.name}: 进名单的人都有一面记录", not missing,
                       f"{len(missing)} 人没有 cv_interview 记录 —— 等于跳过了第 4 步")
        # ② 名单里的人必须出自面试名单
        lp = (list_dir / f"{jd}.面试名单.yaml") if list_dir else None
        if lp and lp.is_file():
            listed = set(yaml.safe_load(lp.read_text(encoding="utf-8")).get("selected") or [])
            outside = [c for c in sel if c not in listed]
            check_true(f"{f.name}: 名单里的人都在面试名单里", not outside,
                       f"{len(outside)} 人不在这份 JD 的面试名单 —— 池子被绕过")
        # ③ 人数口径
        tgt = doc.get("target") or {}
        lo, hi = int(tgt.get("min") or 0), int(tgt.get("max") or 0)
        short = int(doc.get("shortfall") or 0)
        check_true(f"{f.name}: 人数在 min~max 内,或如实记了差额",
                   (lo <= len(sel) <= hi) or (len(sel) < lo and short == lo - len(sel)),
                   f"{len(sel)} 人 vs {lo}~{hi}(shortfall={short})")
        # ④ 切线要交代
        cut = doc.get("cut") or {}
        check_true(f"{f.name}: 交代了切线 tie_band", isinstance(cut.get("tie_band"), int),
                   "缺 cut.tie_band")
        check_true(f"{f.name}: 切线位置 = 名单人数", cut.get("position") == len(sel),
                   f"{cut.get('position')} vs {len(sel)}")
        if (cut.get("tie_band") or 1) > 1:
            check_true(f"{f.name}: 并列区已标 hash_decided", cut.get("hash_decided") is True,
                       "切线在并列区却没标 hash_decided")
        # ⑤ 排序口径九层,且第一层必须是硬证据(不是"分数")
        rules = doc.get("rank_rule") or []
        check_true(f"{f.name}: 排序口径是 9 层", len(rules) == 9, f"实际 {len(rules)} 层")
        check_true(f"{f.name}: 第 1 层是硬证据项数",
                   bool(rules) and "硬证据" in str(rules[0]), str(rules[0])[:50] if rules else "空")
        # ⑥ 带客户门槛不满足却进名单的,必须记进 relaxations(要人点头)
        flagged = {x.get("candidate") for x in (doc.get("flags") or [])}
        relaxed = {x.get("candidate") for x in (doc.get("relaxations") or [])}
        check_true(f"{f.name}: 带门槛不满足的人若进名单已记账", flagged <= (relaxed | flagged),
                   "有 flags 却没写 relaxations(缺谁点头)")
        # ⑦ 最终名单:必须是短名单的真子集,人数 ≤ final_max,而且**明显更少**
        fin = doc.get("final") or {}
        fids = list(fin.get("ids") or [])
        fmax = int(fin.get("max") or 0)
        check_true(f"{f.name}: 最终名单是短名单的子集", set(fids) <= set(sel),
                   f"{len(set(fids) - set(sel))} 人不在短名单里")
        check_true(f"{f.name}: 最终名单人数 ≤ 上限({fmax})",
                   bool(fmax) and len(fids) <= fmax, f"{len(fids)} 人 vs 上限 {fmax}")
        check_true(f"{f.name}: 最终名单比短名单明显更少",
                   len(fids) < len(sel) or len(sel) <= 1,
                   f"最终 {len(fids)} / 短名单 {len(sel)} —— 两道闸没起作用")
        # ⑧ 最终名单里的人必须真的满足三条硬条件(从 rows 里核,不信自报)
        rows = {r.get("candidate"): r for r in (doc.get("rows") or [])}
        bad = []
        for c in fids:
            r = rows.get(c)
            if not r:
                bad.append(f"{str(c)[:14]}(不在 rows 里)")
                continue
            if r.get("gate_fails"):
                bad.append(f"{str(c)[:14]}(硬门槛不满足)")
            elif (r.get("hard_hits") or 0) < int(fin.get("min_hard") or 1):
                bad.append(f"{str(c)[:14]}(无硬证据)")
            elif (r.get("未知") or 0) > int(fin.get("unknown_max") or 3):
                bad.append(f"{str(c)[:14]}(未知过多)")
        check_true(f"{f.name}: 最终名单每人都过了硬条件", not bad, "、".join(bad[:3]))
        # ⑧.5 显示姓名必须是人名,不能是脱敏残留(____ / ** / 纯英文短名)
        try:
            sys.path.insert(0, str(ROOT / "backend"))
            from scripts.talent import names as _nm
            import re as _re
            masked = [c for c in sel
                      if _re.search(r"\S_{2,}|\*\*", _nm.name_of(c))]
            check_true(f"{f.name}: 名单里的人都换成了完整姓名", not masked,
                       f"{len(masked)} 人还是脱敏写法 —— 看起来像数据坏了;"
                       f"先跑 fake_names 再重生成名单")
        except Exception as _exc:  # noqa: BLE001
            check_true(f"{f.name}: 姓名映射可读", False, f"{type(_exc).__name__}: {_exc}")
        # ⑨ 演练必须自曝
        mode = str((doc.get("interview_policy") or {}).get("mode") or "")
        sim_only = doc.get("simulated_interview_only") or []
        if mode == "mock_allowed" and sim_only:
            check_true(f"{f.name}: 全是模拟一面的人在产物里点名了",
                       len(sim_only) >= 1, "标了 mock_allowed 却没写 simulated_interview_only")


def check_verdicts(vdir: pathlib.Path | None) -> None:
    """判定说明门禁 —— 回答「为什么这个人没过」的那份文件,不能是散文。

    HR 拿去见业务领导的东西,只要有一句站不住,整套系统的可信度就没了。
    所以这里逐行查四件事,并且**查它有没有过期**:

    ① 四态合法,且「不可判」没有被写成结论
    ② 每条「不满足」都必须带齐:客户原文 + 行号 + 数据项 + 他的值 + 阈值 + 值来源
       (少一样,这句话就追不到底)
    ③ 每条「未知」必须写清为什么没读到 —— 空着就等于含糊
    ④ 指纹必须和当前输入一致:JD 原文/阈值/词表/简历事实/一面记录任何一样改过,
       旧说明就是**过期文件**,必须重生成,不许继续挂在墙上
    """
    if not vdir or not vdir.is_dir():
        not_run("判定说明门禁", f"找不到 {vdir}")
        return
    try:
        from scripts.talent import explain_rejection as EX
        from scripts.talent.evaluate import (load_candidates, overlay_hr, overlay_interview,
                                             overlay_llm, overlay_mock)
        from scripts.talent import interview_policy
    except Exception as exc:  # noqa: BLE001
        check_true("判定说明门禁能加载依赖", False, f"{type(exc).__name__}: {exc}")
        return

    cv, hr = EX.load_facts()
    try:
        lib = {r["id"]: r for r in
               (yaml.safe_load(LIBRARY.read_text(encoding="utf-8")).get("requirements") or [])}
    except Exception:  # noqa: BLE001
        lib = {}
    cands = load_candidates()
    overlay_llm(cands)
    overlay_hr(cands)
    # **不并 cv_mock**:生成说明那边已经停用(2026-11-23)。指纹要按同一份输入算,
    # 一边并 mock、一边不并,结果就是"267 份全部过期"这种假红。
    by_id = {c["id"]: c for c in cands}
    n_files = 0
    for jd_dir in sorted(p for p in vdir.iterdir() if p.is_dir()):
        jd = jd_dir.name
        files = sorted(jd_dir.glob("*.yaml"))
        if not files:
            not_run(f"{jd}: 判定说明门禁", "还没有说明文件")
            continue
        mode, _src = interview_policy.mode_for(jd)
        overlay_interview(cands, allow_simulated=mode == interview_policy.MOCK_ALLOWED)
        by_id = {c["id"]: c for c in cands}
        check_true(f"{jd}: 有总览 _index.md", (jd_dir / "_index.md").is_file(),
                   "没有总览,HR 得一个个点开")
        stale, bad_row, bad_unknown, bad_evidence = [], [], [], []
        for f in files:
            n_files += 1
            try:
                doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                check_true(f"{jd}/{f.name}: 能解析", False, str(exc)[:100])
                continue
            cid = doc.get("candidate")
            cand = by_id.get(cid)
            if not cand:
                check_true(f"{jd}/{f.name}: 候选人还在库里", False, "库里找不到这个人")
                continue
            # ④ 过期检查:输入指纹
            fp = EX.fingerprint(cid, jd, cand, cv, hr)
            if doc.get("fingerprint") != fp:
                stale.append(f.name)
            rows = doc.get("rows") or []
            for r in rows:
                st = r.get("state")
                if st not in EX.STATES:
                    bad_row.append(f"{f.name}:{r.get('clause')} 状态非法 {st!r}")
                    continue
                if st == "不满足":
                    # 客户原话要求必须能追到行号;我方(HR)提的要求没有行号,改追 rationale 文本
                    need = ["client_text", "data_item", "value", "threshold"]
                    if (r.get("origin") or "client") == "client":
                        need.append("client_line")
                    miss = [k for k in need if r.get(k) in (None, "", [])]
                    if miss:
                        bad_row.append(f"{f.name}:{r.get('clause')} 缺 {miss}")
                    src = r.get("source") or {}
                    if not src or src.get("kind") in (None, "", "无"):
                        # 组件类要求:要么有命中的来源,要么有否定证据(读完了、里面没有)
                        ab = r.get("absence") or {}
                        if not (r.get("sources") or []) and not ab.get("checked"):
                            bad_row.append(f"{f.name}:{r.get('clause')} 没有值来源也没有否定证据")
                if st == "未知" and not str(r.get("why") or "").strip():
                    bad_unknown.append(f"{f.name}:{r.get('clause')}")
                # 能力类的"满足"必须写清是案例还是自述 —— 只写"满足"等于把自述当实据
                if st == "满足":
                    req = (lib.get(r.get("requirement")) or {}) if isinstance(lib, dict) else {}
                    if req.get("data_class") == "capability":
                        ev = str(r.get("evidence") or "")
                        if ev not in ("案例/实测", "仅自述"):
                            bad_evidence.append(f"{f.name}:{r.get('clause')} 证据强度缺失")
        check_true(f"{jd}: {len(files)} 份说明的输入指纹都是当前的", not stale,
                   f"{len(stale)} 份过期(输入已变,必须重生成): {', '.join(stale[:3])}")
        check_true(f"{jd}: 「不满足」每行都能追到原文与来源", not bad_row,
                   "; ".join(bad_row[:3]))
        check_true(f"{jd}: 「未知」每行都写了为什么没读到", not bad_unknown,
                   "; ".join(bad_unknown[:3]))
        check_true(f"{jd}: 能力类的「满足」都标了证据强度(案例/自述)", not bad_evidence,
                   "; ".join(bad_evidence[:3]))
    if n_files == 0:
        not_run("判定说明门禁", "目录里没有 yaml")


def check_standard_templates() -> None:
    """公司标准模板（`work/talent/templates/standard_{jd,cv}_template.yaml`）。

    客户模板（`field_schema`）回答"10 份 JD 实际长什么样";标准模板回答"应该长什么样"。
    这两件事混在一起过一次,结果是 80 个字段里 25 个在客户 JD 里出现 0 次 —— 于是有人
    想删掉它们。**错了**:那是客户漏填,不是标准不需要。所以标准模板单独存在,并用
    "每条可判要求必须落到某个字段"来证明它够用。

    这里守的六件事,每一件都能真的红:
      ST-G1 文件在、能解析、版本与目标字段数写在文件里(不许靠记忆)
      ST-G2 实际字段数 == 目标字段数(40 / 26)
      ST-G3 code 不重复
      ST-G4 可判字段四件套齐全(JD 侧门槛形状 / CV 侧值形状)—— 缺一项这条要求就判不了
      ST-G5 缺数据时的口径只能是「未知」或「不可判」——
            **混进「不满足」是把没读到当成不合格**,这是本仓库最贵的那个 bug
      ST-G6 条件字段必须写清 conditional_on(否则它就是个永远不触发的装饰)
      ST-G7 每条 assessable 要求的数据项,必须两个模板里都有落脚字段
      ST-G8 BLOCKING 要求对应的 JD 标准字段必须是 required
      ST-G9 已删字段(F.JD_PAGE_COUNT / F.JD_APPROVERS)不得出现;
           已降级字段(职责权重/职级/职业编码)必须存在且是 optional
    """
    print("\n── 公司标准模板（JD 40 / CV 26）──")
    tdir = ROOT / "work" / "talent" / "templates"
    paths = {"jd": tdir / "standard_jd_template.yaml", "cv": tdir / "standard_cv_template.yaml"}
    docs: dict[str, dict] = {}
    for which, p in paths.items():
        ok = p.is_file()
        check_true(f"ST-G1 {p.name} 存在", ok, str(p))
        if not ok:
            return
        try:
            docs[which] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:  # noqa: BLE001
            check_true(f"ST-G1 {p.name} 可解析", False, str(exc)[:120])
            return
        check_true(f"ST-G1 {p.name} 有版本与目标字段数",
                   isinstance(docs[which].get("version"), int)
                   and isinstance(docs[which].get("field_count_target"), int),
                   "缺 version / field_count_target")

    rows = {w: [dict(f, _sec=s.get("code"))
                for s in docs[w].get("sections") or [] for f in (s.get("fields") or [])]
            for w in docs}

    # ST-G2 规模
    for w in ("jd", "cv"):
        n, tgt = len(rows[w]), docs[w].get("field_count_target")
        check_true(f"ST-G2 {'JD' if w == 'jd' else 'CV'} 模板字段数 == 目标 {tgt}",
                   n == tgt, f"实际 {n}")

    # ST-G3 code 唯一（两个模板内各自唯一;跨模板允许同名 —— 性别/学历就是同一条数据项）
    for w in ("jd", "cv"):
        codes = [r["code"] for r in rows[w]]
        dup = sorted({c for c in codes if codes.count(c) > 1})
        check_true(f"ST-G3 {'JD' if w == 'jd' else 'CV'} 字段 code 唯一", not dup, "重复: " + ", ".join(dup))

    # ST-G4 / ST-G5 / ST-G6 标注完整性
    miss_annot, bad_missing, bad_cond = [], [], []
    for w in ("jd", "cv"):
        for r in rows[w]:
            if r.get("assessable") == "judgeable":
                shape = r.get("threshold_shape") if w == "jd" else r.get("value_shape")
                if not (r.get("data_item") and shape and r.get("evidence_required")
                        and r.get("missing_means")):
                    miss_annot.append(f"{w}:{r['code']}")
                if r.get("missing_means") not in ("未知", "不可判"):
                    bad_missing.append(f"{w}:{r['code']}={r.get('missing_means')}")
            if r.get("requirement_level") == "conditional" and not r.get("conditional_on"):
                bad_cond.append(f"{w}:{r['code']}")
    check_true("ST-G4 可判字段四件套齐全(data_item/形状/证据/缺了算)", not miss_annot,
               ", ".join(miss_annot[:8]))
    check_true("ST-G5 缺数据时只许「未知」或「不可判」", not bad_missing, ", ".join(bad_missing[:8]))
    check_true("ST-G6 条件字段都写了 conditional_on", not bad_cond, ", ".join(bad_cond[:8]))

    # ST-G7 每条可判要求 → 两个模板都落到字段
    lib_path = LIBRARY
    if not lib_path.is_file():
        not_run("ST-G7 要求覆盖", f"找不到 {lib_path}")
        return
    lib = yaml.safe_load(lib_path.read_text(encoding="utf-8")) or {}
    reqs = lib.get("requirements") or []
    items = {w: {r.get("data_item") for r in rows[w] if r.get("data_item")} for w in ("jd", "cv")}
    uncovered = []
    for r in reqs:
        if not r.get("assessable"):
            continue
        need = "skill_*" if r.get("components") else r.get("attribute")
        if need not in items["jd"] or need not in items["cv"]:
            uncovered.append(f"{r['id']}({need})")
    n_assess = sum(1 for r in reqs if r.get("assessable"))
    check_true(f"ST-G7 可判要求 {n_assess} 条全部落到两个模板", not uncovered,
               "未落: " + ", ".join(uncovered[:8]))

    # ST-G8 BLOCKING 要求必须 required（否则 JD 漏写这一条,闸门就拦不到人）
    blocking = ("REQ-A-AGE-RANGE", "REQ-B-EDU-LEVEL", "REQ-HR-NOTICE", "REQ-HR-TENURE",
                "REQ-HR-STABILITY", "REQ-HR-SALARY", "REQ-HR-COMMUTE")
    jd_reqs = {rid: r for r in rows["jd"] for rid in (r.get("source_requirement") or [])}
    not_req = []
    for rid in blocking:
        r = jd_reqs.get(rid)
        if r is None:
            not_req.append(f"{rid}: 标准模板里没有字段")
        elif r.get("requirement_level") != "required":
            not_req.append(f"{rid}: {r['code']} 是 {r.get('requirement_level')}")
    check_true(f"ST-G8 BLOCKING {len(blocking)} 条在标准模板里都是必需", not not_req,
               "; ".join(not_req))

    # ST-G9 删的删干净、降级的真的降了、没进模板的都交代了去处
    jd_codes = {r["code"] for r in rows["jd"]}
    dropped: dict[str, str] = {}
    for d in docs["jd"].get("dropped") or []:
        for code in str(d.get("code") or "").split(" / "):
            dropped[code.strip()] = d.get("why") or ""
    must_be_absent = {"F.JD_PAGE_COUNT", "F.JD_APPROVERS"}
    leaked = sorted(must_be_absent & jd_codes)
    check_true("ST-G9 已删字段(页数/核准审核制订)不在标准模板里", not leaked, ", ".join(leaked))
    # 降级为可选、或干脆不进模板 —— 两条都行，但**必须有交代**：不许悄悄消失
    must_be_opt = {"F.JD_JOB_GRADE", "F.JD_OCCUPATION_CODE"}
    wrong = []
    for code in must_be_opt:
        r = next((x for x in rows["jd"] if x["code"] == code), None)
        if r is None:
            if not dropped.get(code):
                wrong.append(f"{code}: 既不进模板也没写进 dropped")
        elif r.get("requirement_level") != "optional":
            wrong.append(f"{code}: {r.get('requirement_level')}")
    check_true("ST-G9 降级/不进的字段有交代(职级可选 · 职业编码写进 dropped)", not wrong,
               "; ".join(wrong))
    # 职责权重不是降级而是**折进**「职责条目」:标准模板不为一个 0 出现率的子字段单开一行,
    # 但也不许它悄悄消失 —— 折进去必须在目标字段里写明,否则下一个人不知道它去哪了。
    merged = {"F.JD_DUTY_WEIGHT": "F.JD_DUTY_ITEMS"}
    bad_merge = []
    for src, dst in merged.items():
        if src in jd_codes:
            bad_merge.append(f"{src}: 说好折进 {dst},却还单列着")
            continue
        d = next((x for x in rows["jd"] if x["code"] == dst), None)
        if d is None or "权重" not in (d.get("note") or ""):
            bad_merge.append(f"{dst}: 没有写明吸收了 {src}")
    check_true("ST-G9 折并字段(职责权重→职责条目)写明了去处", not bad_merge, "; ".join(bad_merge))

    # ST-G10 「基于 field_schema」不是口号：名字与段号必须与它逐字相同
    fs_path = ROOT / "work" / "talent" / "field_schema.yaml"
    if not fs_path.is_file():
        not_run("ST-G10 字段名与 field_schema 一致", f"找不到 {fs_path}")
        return
    fs = yaml.safe_load(fs_path.read_text(encoding="utf-8")) or {}
    fs_rows = fs["fields"] if isinstance(fs.get("fields"), list) else list(fs["fields"].values())
    fs_by = {f["id"]: f for f in fs_rows}
    bad_label, bad_sec = [], []
    for w in ("jd", "cv"):
        for r in rows[w]:
            if not r.get("in_field_schema"):
                continue
            src = fs_by.get(r["code"])
            if src is None:
                bad_label.append(f"{w}:{r['code']} 声称在 field_schema、其实不在")
                continue
            if src.get("label") != r.get("label_zh"):
                bad_label.append(f"{w}:{r['code']} 叫「{r.get('label_zh')}」,"
                                 f"field_schema 叫「{src.get('label')}」")
            side = src.get(w) or {}
            if side and side.get("section") and side.get("section") != r.get("_sec"):
                bad_sec.append(f"{w}:{r['code']} 在 {r.get('_sec')},field_schema 在 {side['section']}")
    check_true("ST-G10 取自 field_schema 的字段,名称与段号逐字一致", not bad_label,
               "; ".join(bad_label[:6]))
    check_true("ST-G10 取自 field_schema 的字段,段号未被重新分组", not bad_sec,
               "; ".join(bad_sec[:6]))

    # ST-G11 新增字段:必须真的不在 field_schema,而且必须是为推理加的(带 data_item)
    fake_new = [f"{w}:{r['code']}" for w in ("jd", "cv") for r in rows[w]
                if r.get("new_in_standard") and r["code"] in fs_by
                and (fs_by[r["code"]].get(w))]
    no_item = [f"{w}:{r['code']}" for w in ("jd", "cv") for r in rows[w]
               if r.get("new_in_standard") and not r.get("data_item")]
    check_true("ST-G11 新增字段确实不在 field_schema(不重复造词)", not fake_new,
               ", ".join(fake_new[:6]))
    check_true("ST-G11 新增字段都是推理所需(带 data_item)", not no_item, ", ".join(no_item[:6]))

    # ── Phase 1：上传 → 抽取 → 缺口 md；以及"单 JD 作用域"──
    try:
        import sys as _sys2
        if str(ROOT / "backend") not in _sys2.path:
            _sys2.path.insert(0, str(ROOT / "backend"))
        from services.talent_gap import known_jds, text_gap_for  # noqa: PLC0415

        ups = ROOT / "work" / "talent" / "uploads"
        jd_dirs = sorted(p for p in ups.glob("*") if p.is_dir()) if ups.is_dir() else []
        orphans, bad_gap, no_md = [], [], []
        if not jd_dirs:
            # 没有上传件时说"通过"是撒谎：这条门禁这时什么也没验。
            not_run("ST-G16 上传→抽取→缺口 md", "还没有上传过 JD（uploads/ 为空）")
        for d in jd_dirs:
            jd_name = d.name
            src = ROOT / "work" / "talent" / "jd_links" / "_source" / f"{jd_name}.txt"
            md = ROOT / "work" / "talent" / "jd_docs" / f"{jd_name}.缺口.md"
            extracted = ROOT / "work" / "talent" / "jd_extracted" / f"{jd_name}.yaml"
            originals = [p for p in d.glob("original*") if p.is_file()]
            if not originals or not src.is_file():
                orphans.append(jd_name)          # 有上传目录却没有原件或正文
                continue
            if not md.is_file():
                no_md.append(jd_name)
            try:
                g = text_gap_for(jd_name)
                if (len(g["fields"]) != g["template_fields"]
                        or sum(g["tally"].values()) != g["template_fields"]):
                    bad_gap.append(jd_name)
                if not extracted.is_file():
                    orphans.append(f"{jd_name}(缺抽取件)")
            except Exception as exc:  # noqa: BLE001
                bad_gap.append(f"{jd_name}: {type(exc).__name__}")
        if jd_dirs:                      # 没有上传件时只说 NOT RUN，不印一堆空通过
            check_true("ST-G16 每份上传的 JD 都有原件 + 正文(没有孤儿目录)", not orphans,
                       ", ".join(orphans[:5]))
            check_true("ST-G16 每份上传的 JD 都生成了缺口 md", not no_md, ", ".join(no_md[:5]))
            check_true("ST-G16 每份上传的 JD 缺口格数与 tally 自洽", not bad_gap,
                       ", ".join(bad_gap[:5]))

        # 单 JD 作用域：JD 产物里不许出现"属于另一份 JD"的路径，也不许夹全局文档
        from api.talent.routes import LAYER_ORDER, _global_files, _jd_files  # noqa: PLC0415

        glob_paths = {f["path"] for f in _global_files()}
        bad_scope = []
        for jd_name in known_jds():
            files = _jd_files(jd_name)
            for f in files:
                path = f["path"]
                if f.get("scope") != "jd":
                    bad_scope.append(f"{jd_name}: {path} 没标 scope=jd")
                if path in glob_paths:
                    bad_scope.append(f"{jd_name}: {path} 是全局文档，混进了 JD 产物链")
                if path.startswith("@"):
                    continue
                # JD 名字必须出现在路径里（每份 JD 的产物是它自己的）
                if jd_name not in path and not path.startswith(("jd_reviews/", "collection/")):
                    bad_scope.append(f"{jd_name}: {path} 路径里没有 JD 名")
        check_true("ST-G17 浏览器是单 JD 作用域(每份 JD 只列自己的产物，不含全局文档)",
                   not bad_scope, "; ".join(bad_scope[:5]))

        # ST-G18 定稿属于**第 2 步**（HR 与业务定稿），不是第 3 步；层序必须按业务顺序排
        wrong_step, wrong_order = [], []
        for jd_name in known_jds():
            files = _jd_files(jd_name)
            for f in files:
                pth, layer = f["path"], f["layer"]
                if pth.endswith((".定稿.md", ".定稿.docx")) and not layer.startswith("2 "):
                    wrong_step.append(f"{jd_name}: {pth} 在「{layer}」")
            order = [LAYER_ORDER.index(fl["layer"]) for fl in files
                     if fl["layer"] in LAYER_ORDER]
            if order != sorted(order):
                wrong_order.append(jd_name)
        check_true("ST-G18 定稿类产物都在第 2 步（HR 与业务定稿）", not wrong_step,
                   "; ".join(wrong_step[:4]))
        check_true("ST-G18 产物层序按业务顺序（1→5）排列", not wrong_order,
                   ", ".join(wrong_order[:4]))

        # ST-G19 每份 JD 都有「标准 40 格定稿」，且 AI 模拟逐格标出（不进判定的那几格必须看得见）
        missing_final, bad_mock, mock_mismatch = [], [], []
        for jd_name in known_jds():
            md = ROOT / "work" / "talent" / "jd_docs" / f"{jd_name}.定稿(标准40格).md"
            if not md.is_file():
                missing_final.append(jd_name)
                continue
            text_md = md.read_text(encoding="utf-8")
            draft_p = ROOT / "work" / "talent" / "jd_draft" / f"{jd_name}.draft.json"
            if not draft_p.is_file():
                bad_mock.append(f"{jd_name}: 没有 draft.json")
                continue
            dd = json.loads(draft_p.read_text(encoding="utf-8"))
            want = sum(1 for r in dd.get("rows") or [] if r.get("state") == "我方建议·待确认")
            got = text_md.count("**AI 模拟**")
            if got != want:
                mock_mismatch.append(f"{jd_name}: 定稿标了 {got} 格，草稿有 {want} 格")
            if want and "AI 模拟清单" not in text_md:
                bad_mock.append(f"{jd_name}: 有 {want} 格 AI 模拟，却没有「AI 模拟清单」一节")
        check_true("ST-G19 每份 JD 都有「标准 40 格定稿」", not missing_final,
                   ", ".join(missing_final[:5]))
        check_true("ST-G19 定稿里 AI 模拟逐格标出，且与草稿数量一致", not mock_mismatch,
                   "; ".join(mock_mismatch[:4]))
        check_true("ST-G19 有 AI 模拟的定稿都带「AI 模拟清单」", not bad_mock,
                   "; ".join(bad_mock[:4]))

        # ST-G20 最终 5 人必须各有一份「业务面问题清单」（业务拿它去面）
        miss_bq, bad_bq = [], []
        for jd_name in known_jds():
            tgt_p = ROOT / "work" / "talent" / "shortlist" / f"{jd_name}.目标名单.yaml"
            bq = ROOT / "work" / "talent" / "picks" / f"{jd_name}.业务面问题.md"
            if not tgt_p.is_file():
                continue
            tgt = yaml.safe_load(tgt_p.read_text(encoding="utf-8")) or {}
            ids = list((tgt.get("final") or {}).get("ids") or [])
            if not ids:
                continue
            if not bq.is_file():
                miss_bq.append(jd_name)
                continue
            txt = bq.read_text(encoding="utf-8")
            names_p = ROOT / "work" / "talent" / "fake_names.yaml"
            nm = {}
            if names_p.is_file():
                nd = yaml.safe_load(names_p.read_text(encoding="utf-8")) or {}
                for k, v in (nd.get("names") or {}).items():
                    nm[str(k)] = str(v.get("name")) if isinstance(v, dict) else str(v)
            missing = [cid for cid in ids if nm.get(cid) and nm[cid] not in txt]
            if missing:
                bad_bq.append(f"{jd_name}: {len(missing)} 人没有对应问题段")
            for seg in ("A. 能力项", "B. 当面确认", "C. 岗位必答"):
                if seg not in txt:
                    bad_bq.append(f"{jd_name}: 缺少「{seg}」段")
        check_true("ST-G20 有最终名单的 JD 都生成了「业务面问题清单」", not miss_bq,
                   ", ".join(miss_bq[:4]))
        check_true("ST-G20 清单覆盖最终 5 人，且三段齐全(能力/当面确认/岗位必答)", not bad_bq,
                   "; ".join(bad_bq[:4]))
    except Exception as exc:  # noqa: BLE001
        check_true("ST-G16/G17 上传与作用域门禁跑完了(崩溃 = 红)", False,
                   f"{type(exc).__name__}: {exc}")

    # ── 缺口接口：数字必须与文件一致，且必须强制带 jd ─────────────────────
    try:
        import sys as _sys
        if str(ROOT / "backend") not in _sys.path:
            _sys.path.insert(0, str(ROOT / "backend"))
        from services.talent_gap import gap_for, default_jd, known_jds  # noqa: PLC0415

        dj = default_jd()
        check_true("ST-G15 默认 JD 有来源且是真实的 JD", dj in known_jds(),
                   f"default_jd()={dj!r}")
        jd_inputs_defaults = []
        for ip in (ROOT / "work" / "talent" / "jd_inputs").glob("*.yaml"):
            try:
                spec = yaml.safe_load(ip.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if spec.get("default") is True:
                jd_inputs_defaults.append(ip.stem)
        check_true("ST-G15 只有一个 JD 标了 default: true", len(jd_inputs_defaults) == 1,
                   f"标了 default 的: {jd_inputs_defaults}")
        if jd_inputs_defaults:
            check_true("ST-G15 default_jd 与配置一致", dj == jd_inputs_defaults[0],
                       f"{dj} vs {jd_inputs_defaults[0]}")
        bad_tally = []
        for jd_name in known_jds():
            g = gap_for(jd_name)
            n_fields = len(g["fields"])
            sum_tally = sum(g["tally"].values())
            if n_fields != g["template_fields"] or sum_tally != n_fields:
                bad_tally.append(f"{jd_name}: {n_fields} 格 vs tally 合计 {sum_tally}")
            if g["in_judging"] != sum(1 for f in g["fields"] if f["in_judging"]):
                bad_tally.append(f"{jd_name}: in_judging 与字段不符")
        check_true("ST-G15 每份 JD 的缺口格数与 tally 自洽", not bad_tally,
                   "; ".join(bad_tally[:4]))
        # 面板与草稿/试填是同一份数据：能判格数必须等于 JSON 里 in_judging 的个数
        draft_json = ROOT / "work" / "talent" / "jd_draft" / f"{dj}.draft.json"
        if draft_json.is_file():
            dd = json.loads(draft_json.read_text(encoding="utf-8"))
            want = sum(1 for r in dd.get("rows") or [] if r.get("in_judging"))
            got = gap_for(dj)["in_judging"]
            check_true("ST-G15 缺口面板的能判格数 == 定稿草稿", got == want, f"{got} vs {want}")
        # 没有 jd 必须报错，而不是返回空表（空表会被读成"没有缺口"）
        try:
            gap_for("")
            check_true("ST-G15 不传 jd 会报错(不是返回空表)", False, "gap_for('') 没报错")
        except ValueError:
            check_true("ST-G15 不传 jd 会报错(不是返回空表)", True)
    except Exception as exc:  # noqa: BLE001
        check_true("ST-G15 缺口接口门禁跑完了(崩溃 = 红)", False,
                   f"{type(exc).__name__}: {exc}")

    # ── 定稿草稿：拿一份真 JD 逐格填（品质经理是试点）────────────────────
    draft_dir = ROOT / "work" / "talent" / "jd_draft"
    drafts = sorted(p for p in draft_dir.glob("*.draft.json")) if draft_dir.is_dir() else []
    if not drafts:
        not_run("ST-G14 定稿草稿", f"{draft_dir} 里还没有 *.draft.json")
    for dp in drafts:
        jd_name = dp.name.replace(".draft.json", "")
        try:
            import subprocess as _sp6
            _c6 = _sp6.run([sys.executable, "-m", "scripts.talent.draft_jd", "--jd", jd_name,
                            "--check"], cwd=str(ROOT / "backend"), capture_output=True,
                           text=True, env={k: v for k, v in os.environ.items() if k != "PGPORT"})
            _o6 = ((_c6.stdout or "") + (_c6.stderr or "")).strip()
            check_true(f"ST-G14 {jd_name}: 草稿是最新的", _c6.returncode == 0,
                       _o6.splitlines()[-1][:140] if _o6 else "没有输出")
        except Exception as exc:  # noqa: BLE001
            check_true(f"ST-G14 {jd_name}: 校验跑完了(崩溃 = 红)", False, f"{type(exc).__name__}: {exc}")
        try:
            dd = json.loads(dp.read_text(encoding="utf-8"))
            rows_d = dd.get("rows") or []
            states = {"客户原文", "HR 侧", "原文·空值", "我方建议·待确认", "待客户给",
                      "待客户确认", "不适用", "HR 模拟确认"}
            codes_t = [r["code"] for r in rows["jd"]]
            check_true(f"ST-G14 {jd_name}: 模板每个字段都填了（{len(codes_t)} 格）",
                       [r["code"] for r in rows_d] == codes_t,
                       f'实际 {len(rows_d)} 格')
            bad_state = [r["code"] for r in rows_d if r.get("state") not in states]
            check_true(f"ST-G14 {jd_name}: 每格状态合法(8 种)", not bad_state, ", ".join(bad_state[:6]))
            no_ev = [r["code"] for r in rows_d
                     if r.get("state") in ("客户原文", "HR 侧") and not r.get("evidence")]
            bad_hrmock = [r["code"] for r in rows_d
                          if r.get("state") == "HR 模拟确认" and not r.get("why")]
            check_true(f"ST-G14 {jd_name}: HR 模拟确认的格子都写了 HR 的回复理由", not bad_hrmock,
                       ", ".join(bad_hrmock[:6]))
            check_true(f"ST-G14 {jd_name}: 进判定的格子都有依据(引用/原文行)", not no_ev,
                       ", ".join(no_ev[:6]))
            no_why = [r["code"] for r in rows_d
                      if r.get("state") in ("我方建议·待确认", "待客户给", "待客户确认", "原文·空值")
                      and not (r.get("why") and r.get("needs"))]
            check_true(f"ST-G14 {jd_name}: 建议/待补的格子都写了理由与确认方", not no_why,
                       ", ".join(no_why[:6]))
            bad_na = [r["code"] for r in rows_d if r.get("state") == "不适用"
                      and (r.get("level") != "conditional")]
            check_true(f"ST-G14 {jd_name}: 「不适用」只在条件字段上", not bad_na, ", ".join(bad_na[:6]))
            check_true(f"ST-G14 {jd_name}: 自检没有遗留问题", not dd.get("problems"),
                       "; ".join((dd.get("problems") or [])[:4]))
        except Exception as exc:  # noqa: BLE001
            check_true(f"ST-G14 {jd_name}: 草稿可解析", False, f"{type(exc).__name__}: {exc}")

    # ── 试填：拿 5 份客户 JD 真填一遍，看模板够不够用 ──────────────────────
    fill_json = ROOT / "work" / "talent" / "template_fill" / "fill.json"
    if not fill_json.is_file():
        not_run("ST-G13 5 份 JD 试填", "还没有 template_fill/fill.json")
    else:
        try:
            import subprocess as _sp5
            _c5 = _sp5.run([sys.executable, "-m", "scripts.talent.check_template_fill", "--check"],
                           cwd=str(ROOT / "backend"), capture_output=True, text=True,
                           env={k: v for k, v in os.environ.items() if k != "PGPORT"})
            _o5 = ((_c5.stdout or "") + (_c5.stderr or "")).strip()
            check_true("ST-G13 试填结果是最新的(客户原文/引用改了要重跑)", _c5.returncode == 0,
                       _o5.splitlines()[-1][:140] if _o5 else "没有输出")
        except Exception as exc:  # noqa: BLE001
            check_true("ST-G13 试填校验跑完了(中途崩溃 = 红)", False, f"{type(exc).__name__}: {exc}")
        try:
            fd = json.loads(fill_json.read_text(encoding="utf-8"))
            n_fields = fd.get("template_fields") or 0
            jds = fd.get("jds") or []
            cells = [c for j in jds for c in j.get("cells") or []]
            base = len(rows["jd"])
            check_true("ST-G13 试填覆盖了模板的每一个字段",
                       n_fields == base and len(cells) == base * len(jds),
                       f"{len(cells)} 格 = {n_fields} × {len(jds)},模板 {base}")
            states = {"原文", "原文·空值", "HR 侧", "缺", "不适用"}
            bad = [f"{j['jd']}:{c['code']}={c['state']}" for j in jds for c in j.get("cells") or []
                   if c.get("state") not in states]
            check_true("ST-G13 每格状态都在 5 种之内(不许自己发明状态/合并)", not bad,
                       ", ".join(bad[:6]))
            jd_by_code = {r["code"]: r for r in rows["jd"]}
            bad_na = [f"{j['jd']}:{c['code']}" for j in jds for c in j.get("cells") or []
                      if c.get("state") == "不适用"
                      and (jd_by_code.get(c["code"]) or {}).get("requirement_level") != "conditional"]
            check_true("ST-G13 「不适用」只出现在条件字段上", not bad_na, ", ".join(bad_na[:6]))
            # 缺字段必须是可判要求记得住「缺了算」的 —— 否则补的时候没有口径
            bad_missing = [c["code"] for c in cells
                           if c.get("state") in ("缺", "原文·空值")
                           and c.get("assessable") == "judgeable"
                           and not (jd_by_code.get(c["code"]) or {}).get("missing_means")]
            check_true("ST-G13 缺的值都能追到「缺了算什么」", not bad_missing,
                       ", ".join(sorted(set(bad_missing))[:6]))
        except Exception as exc:  # noqa: BLE001
            check_true("ST-G13 试填结果可解析", False, f"{type(exc).__name__}: {exc}")

    # ST-G12 模板与生成器一致(手改 YAML 会被这里判红)
    try:
        import subprocess as _sp4
        _c4 = _sp4.run([sys.executable, "-m", "scripts.talent.build_templates", "--check"],
                       cwd=str(ROOT / "backend"), capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if k != "PGPORT"})
        _o4 = ((_c4.stdout or "") + (_c4.stderr or "")).strip()
        check_true("ST-G12 模板与 build_templates 生成结果一致(未被手改)", _c4.returncode == 0,
                   _o4.splitlines()[-1][:140] if _o4 else "没有输出")
    except Exception as exc:  # noqa: BLE001
        check_true("ST-G12 一致性校验跑完了(中途崩溃 = 红)", False, f"{type(exc).__name__}: {exc}")

    print(f"  · JD {len(rows['jd'])} 字段 · CV {len(rows['cv'])} 字段 · "
          f"可判要求 {n_assess} 条全覆盖")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-db", action="store_true", help="只跑结构与自洽,不连库")
    # 引用门禁必须默认就跑 —— 之前默认空字符串,等于 122 条逐字回查从来没在常规检查里跑过。
    # 一个"要记得加参数才跑"的门禁,和没有这道门是一个效果。
    ap.add_argument("--links", default=str(ROOT / "work" / "talent" / "jd_links"),
                    help="JD 链接文件目录(默认就是正式目录;传空串可跳过)")
    ap.add_argument("--library", default=str(LIBRARY), help="要求库 yaml")
    ap.add_argument("--reviews", default=str(ROOT / "work" / "talent" / "jd_reviews"),
                    help="决策账本目录(默认就是正式目录;传空串可跳过)")
    # --catalog 让变异测试可以在副本上跑:一个只在真文件上能跑的门禁是没法证明自己有牙齿的
    ap.add_argument("--catalog", default=str(CATALOG), help="默认读 work/talent/component_catalog.yaml")
    ap.add_argument("--picks", default=str(ROOT / "work" / "talent" / "picks"),
                    help="第 5 步产物目录(默认正式目录;传空串可跳过)")
    ap.add_argument("--policy", default=str(ROOT / "work" / "talent" / "interview_policy.yaml"),
                    help="一面采信规则(默认正式文件)")
    ap.add_argument("--verdicts", default=str(ROOT / "work" / "talent" / "verdicts"),
                    help="判定说明目录(默认正式目录;传空串可跳过)")
    ap.add_argument("--interview-dir", default=str(ROOT / "work" / "talent" / "cv_interview"),
                    help="一面记录目录(第 5 步门禁用它核「进名单的人都面过」)")
    ap.add_argument("--interview-list", default=str(ROOT / "work" / "talent" / "shortlist"),
                    help="面试名单目录(默认同 shortlist;传空串可跳过)")
    ap.add_argument("--shortlist", default=str(ROOT / "work" / "talent" / "shortlist"),
                    help="短名单目录(默认正式目录;传空串可跳过)")
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
    lib_path = pathlib.Path(args.library).resolve()
    if lib_path.is_file():
        lib = yaml.safe_load(lib_path.read_text(encoding="utf-8")) or {}
        check_library(lib, cat)
        try:
            check_links(cat, lib, pathlib.Path(args.links) if args.links else None)
        except Exception as exc:
            # 一处 YAML 写坏(实测:跨行纯量里含「冒号+空格」→ ScannerError)会让整个
            # 引用门禁**中断**,而它前面的 PASS 已经打印了。汇总行不出现时 tail 看着
            # 完全正常。所以异常必须折成红,并把"哪一门没跑完"说出来。
            check_true("引用门禁跑完了(中途崩溃 = 红,不是通过)",
                       False, f"{type(exc).__name__}: {exc}")
        try:
            check_template(pathlib.Path(args.links) if args.links else None)
        except Exception as exc:
            check_true("模板门禁跑完了(中途崩溃 = 红,不是通过)", False,
                       f"{type(exc).__name__}: {exc}")
        try:
            check_coverage(pathlib.Path(args.links) if args.links else None)
        except Exception as exc:
            check_true("覆盖度检查跑完了(中途崩溃 = 红,不是通过)",
                       False, f"{type(exc).__name__}: {exc}")
        try:
            check_decisions(pathlib.Path(args.links) if args.links else None,
                            pathlib.Path(args.reviews) if args.reviews else None)
        except Exception as exc:
            check_true("决策账本门禁跑完了(中途崩溃 = 红,不是通过)",
                       False, f"{type(exc).__name__}: {exc}")
        try:
            check_picks(pathlib.Path(args.picks) if args.picks else None,
                        pathlib.Path(args.policy) if args.policy else None)
        except Exception as exc:
            check_true("选人产物门禁跑完了(中途崩溃 = 红,不是通过)",
                       False, f"{type(exc).__name__}: {exc}")
        try:
            check_shortlist(pathlib.Path(args.shortlist) if args.shortlist else None)
        except Exception as exc:
            check_true("短名单门禁跑完了(中途崩溃 = 红,不是通过)",
                       False, f"{type(exc).__name__}: {exc}")
        # 标准目录:分类/组件/模板的数字过期就红(它读三份 YAML,改一份没重跑必红)
        try:
            check_standard_templates()
        except Exception as exc:  # noqa: BLE001
            check_true("标准模板门禁跑完了(中途崩溃 = 红,不是通过)",
                       False, f"{type(exc).__name__}: {exc}")
        try:
            import subprocess as _sp3
            _c = _sp3.run([sys.executable, "-m", "scripts.talent.build_catalog", "--check"],
                          cwd=str(ROOT / "backend"), capture_output=True, text=True,
                          env={k: v for k, v in os.environ.items() if k != "PGPORT"})
            _out3 = ((_c.stdout or "") + (_c.stderr or "")).strip()
            check_true("标准目录(catalog.json / CATALOG.md)是最新的", _c.returncode == 0,
                       _out3.splitlines()[-1][:140] if _out3 else "没有输出")
        except Exception as exc:  # noqa: BLE001
            check_true("标准目录校验跑完了(中途崩溃 = 红)", False, f"{type(exc).__name__}: {exc}")

        # 教程 v2:数字过期、手写数字、反证失效都在里面查(它自己也是可失败的)
        try:
            import re as _re2
            import subprocess as _sp2
            _r = _sp2.run([sys.executable, "-m", "scripts.talent.check_tutorial"],
                          cwd=str(ROOT / "backend"), capture_output=True, text=True,
                          env={k: v for k, v in os.environ.items() if k != "PGPORT"})
            _out = (_r.stdout or "") + (_r.stderr or "")
            _sum = next((ln.strip() for ln in reversed(_out.splitlines())
                         if "checks ·" in ln), "")
            check_true("教程 v2 门禁跑完了(数字不过期/无手写数字/反证有效)",
                       bool(_sum) and " 0 failed" in _sum,
                       _sum or "没有汇总行 = 没跑完：" + _out.strip().splitlines()[-1][:120]
                       if _out.strip() else "没有输出")
        except Exception as exc:  # noqa: BLE001
            check_true("教程 v2 门禁跑完了(中途崩溃 = 红)", False,
                       f"{type(exc).__name__}: {exc}")

        try:
            check_shortlist5(
                pathlib.Path(args.shortlist) if args.shortlist else None,
                pathlib.Path(args.interview_dir) if args.interview_dir else None,
                pathlib.Path(args.shortlist) if args.shortlist else None)
        except Exception as exc:
            check_true("第 5 步目标名单门禁跑完了(中途崩溃 = 红,不是通过)",
                       False, f"{type(exc).__name__}: {exc}")
        try:
            check_interview_list(pathlib.Path(args.interview_list) if args.interview_list else None)
        except Exception as exc:
            check_true("面试名单门禁跑完了(中途崩溃 = 红,不是通过)",
                       False, f"{type(exc).__name__}: {exc}")
        try:
            check_verdicts(pathlib.Path(args.verdicts) if args.verdicts else None)
        except Exception as exc:
            check_true("判定说明门禁跑完了(中途崩溃 = 红,不是通过)",
                       False, f"{type(exc).__name__}: {exc}")
    else:
        not_run("要求库门禁", f"找不到 {lib_path}")

    # 「看不到汇总行就不算绿」—— 这句话要由脚本自己保证:一组检查都没产出结果时,
    # 说绿是撒谎。NOT RUN 不算失败,但「零检查」一定是错的。
    if CHECKS == 0:
        check_true("门禁至少跑了一项检查", False, "零检查 = 什么都没验")
    # 「检查数暴跌 = 门禁没覆盖到东西」必须吼出来:
    # 清空交付物后 gate 仍会打印 green,但只查了 49 项(正常是 500+)——
    # 那个 green 只说明"没有反例",不说明"流程成立"。
    cov = 0
    if args.links:
        lp = pathlib.Path(args.links)
        if lp.is_dir():
            cov = len([x for x in lp.glob("*.yaml") if not x.name.startswith("_")])
    if cov < 5 and not args.no_db:
        print(f"\n⚠ 门禁只覆盖了 {cov} 份 JD 的引用文件 —— 这个结果**不代表流程成立**,"
              "只代表「没有反例」。先跑第 1 步把 jd_links 做出来,再看门禁。")
    tail = f" · {NOT_RUN_UNITS} 项未审(见 [NOT RUN])" if NOT_RUN_UNITS else ""
    print(f"\n{CHECKS} checks · {FAILS} failed · {'green' if OK else 'RED'}{tail}")
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
