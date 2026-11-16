#!/usr/bin/env python3
"""STAGE（不 apply）：把**扩展词表**装进 `talent_v1` 的候选 ABox，跑门禁，出前后对比。

走的是仓库自己的规矩：`services/ontology_publish.stage()` —— 写进隐藏暂存目录、在暂存副本上
跑门禁与编译、返回报告与 staged id。**安装目录一个字节都不动**，apply 需要人确认。

三种修改，全部有出处：
  1. abox.ttl  —— 用 `build_abox.build()` 重生成：把 `skill_patterns_ext.py` 里 26 条
                  扩展技能并入每个候选的 `hasSkill`（证据来自 OCR 缓存，548 条片段）
  2. reasoning.ttl —— 补上这些技能所属的**类别类**（否则门禁 A1 会红：
                  "no individual carries a type the TBox does not declare"）
  3. 都不改岗位公理 —— 公理是业务声明（"要求什么"），不是词表问题；
                  改它需要 N1（客户定技能优先级），不在这一步里。

所以预期：技能个体与断言变多，但**蕴含数几乎不变**——因为岗位公理还没引用新类别。
这份报告把这一点明写出来，免得把"没变化"当成"成功"。

用法：
    python -m scripts.talent.stage_extended_vocab            # stage + 报告
    python -m scripts.talent.stage_extended_vocab --dry-run   # 只生成文件，不调 stage
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from scripts.talent import build_abox  # noqa: E402
from scripts.talent.skill_patterns_ext import EXTENDED_SKILL_PATTERNS  # noqa: E402

PROFILE = BACKEND / "features" / "ontology" / "profiles" / "talent_v1"

STRUCTURE_ADDITION = """
# ─────────────────────────────────────────────────────────────────────────────
# 引擎台账（2026-11-16 追加）—— 不是本体的数据表，是**评分与证据的账本**。
# 声明它们是为了让 check_structure 的『没有一张表被悄悄漏掉』成立：
# 一个不声明的表就是一个没人负责的表。
# ─────────────────────────────────────────────────────────────────────────────
:Requirement a owl:Class ;
    rdfs:label "岗位要求" ;
    :physicalTable "requirement" ;
    :primaryKey "id" ;
    :rowCount 31 ;
    :businessDescription "一行 = 一条岗位要求，从 10 份职务说明书的【资格要求】段抽出。26 条 essential + 5 条 desirable。verbatim 存 JD 原话、source_jd 存文件名：没有出处的行不许进表。" .
:requirementId a owl:DatatypeProperty ; rdfs:label "要求键" ; rdfs:domain :Requirement ; :physicalColumn "id" ;
    :businessDescription "形如 req_001_副总助理 / des_001_业务跟单 的稳定键。" .
:requirementKind a owl:DatatypeProperty ; rdfs:label "要求类型" ; rdfs:domain :Requirement ; :physicalColumn "kind" ;
    :businessDescription "capability | product | equipment | composite | soft | compliance。composite 是『一句话里的复合要求』，评分时算一个要求项——把它拍平成多个合取项，就是副总助理 0 人合格的原因。" .
:requirementTier a owl:DatatypeProperty ; rdfs:label "层级" ; rdfs:domain :Requirement ; :physicalColumn "tier" ;
    :businessDescription "essential | desirable。只有 JD 原文写了『优先』的才降为 desirable——技能优先级不许我们发明。" .
:requirementVerbatim a owl:DatatypeProperty ; rdfs:label "JD 原话" ; rdfs:domain :Requirement ; :physicalColumn "verbatim" ;
    :businessDescription "该要求出自职务说明书的那句话，逐字。" .

:RequirementSkill a owl:Class ;
    rdfs:label "要求的技能构成" ;
    :physicalTable "requirement_skill" ;
    :primaryKey "requirement_id, skill" ;
    :rowCount 34 ;
    :businessDescription "一行 = 一条要求包含的一个技能部件。复合要求（如 Office = Word+Excel+PPT）在这里拆成多行，覆盖率 = 命中数 / 部件数。" .
:requirementSkillSkill a owl:DatatypeProperty ; rdfs:label "技能" ; rdfs:domain :RequirementSkill ; :physicalColumn "skill" ;
    :businessDescription "带 skill_ 前缀，与 candidate_skill.skill 同一套命名。" .

:CandidateSkillEvidence a owl:Class ;
    rdfs:label "技能出处" ;
    :physicalTable "candidate_skill_evidence" ;
    :primaryKey "candidate, skill" ;
    :rowCount 1001 ;
    :businessDescription "一行 = 某个候选人的某个技能从哪来：哪份简历文件、用哪种方式读到（ocr | filename）、命中片段。span 在 OCR 原文未留存时为 NULL——这一列现在填不满，是如实记录，不是遗漏。" .
:evidenceSpan a owl:DatatypeProperty ; rdfs:label "命中片段" ; rdfs:domain :CandidateSkillEvidence ; :physicalColumn "span" ;
    :businessDescription "命中处前后各 18 字的上下文。由 scripts/talent/extract_probe.py 从 OCR 缓存里取出。" .
:evidenceMethod a owl:DatatypeProperty ; rdfs:label "读取方式" ; rdfs:domain :CandidateSkillEvidence ; :physicalColumn "method" ;
    :businessDescription "ocr 表示从简历正文 OCR 得到；filename 表示从文件名解析得到（薪资、年龄走这一路）。" .

:FitComponent a owl:Class ;
    rdfs:label "分数构成" ;
    :physicalTable "fit_component" ;
    :primaryKey "candidate, role, component, requirement_id" ;
    :rowCount 9972 ;
    :businessDescription "一行 = 某候选人某岗位的一个评分分量：要求什么、实际多少、权重、贡献。『为什么他排第 7』这句话的真源；人话句子由它渲染，门禁也能逐行重算。" .
:fitWeight a owl:DatatypeProperty ; rdfs:label "权重" ; rdfs:domain :FitComponent ; :physicalColumn "weight" ;
    :businessDescription "skills 60 · years 25 · education 15。权重是写下来的决定，不是测量。" .
:fitContribution a owl:DatatypeProperty ; rdfs:label "贡献" ; rdfs:domain :FitComponent ; :physicalColumn "contribution" ;
    :businessDescription "权重 × 该项得分。未知项（actual IS NULL）贡献记 0 但不进分母——见 v_shortlist 的 completeness。" .
:fitMet a owl:DatatypeProperty ; rdfs:label "是否满足" ; rdfs:domain :FitComponent ; :physicalColumn "met" ;
    :businessDescription "只对 skills 分量有值：覆盖率是否达到闸门 0.5。years/education 不参与成员判定（决定 D10），为 NULL。" .

:Shortlist a owl:Class ;
    rdfs:label "推荐名单（视图）" ;
    :physicalTable "v_shortlist" ;
    :primaryKey "candidate, role" ;
    :rowCount 2770 ;
    :businessDescription "一行 = 某候选人某岗位在名单里的位置。list_kind：qualified（过闸门）| near（未过但分数≥60）| excluded。list_bucket 把『信息完整』与『部分信息』分成两张名单（决定 O4）——不完整不能因为查不到而排到完整的人前面。" .
:shortlistScore a owl:DatatypeProperty ; rdfs:label "分数" ; rdfs:domain :Shortlist ; :physicalColumn "score" ;
    :businessDescription "各分量贡献之和，0–100。" .
:shortlistCompleteness a owl:DatatypeProperty ; rdfs:label "信息完整度" ; rdfs:domain :Shortlist ; :physicalColumn "completeness" ;
    :businessDescription "观测到的权重占比：100 = 年限学历都读到，85 = 缺一项，60 = 只读到技能。榜首出现 60% 时，那不是『他最好』，是『只看得见他这些』。" .
"""


COLUMN_ADDITION = """
# ── 列的声明：check_structure 要求「每条 :physicalColumn 对应一列真实存在的列」，
#    没声明的列就是一个没人负责的字段。以下 26 列逐个登记。
:reqRole a owl:DatatypeProperty ; rdfs:label "所属岗位" ; rdfs:domain :Requirement ; :physicalColumn "role" ;
    :businessDescription "形如 role_副总助理，与 role.role 同一套命名（注意 candidate_role_fit.role 是裸名，这是历史遗留的不一致）。" .
:reqLabel a owl:DatatypeProperty ; rdfs:label "要求名" ; rdfs:domain :Requirement ; :physicalColumn "label" ;
    :businessDescription "便于阅读的短名，如『Office办公软件(Word/Excel/PPT/AI)』。" .
:reqSourceJd a owl:DatatypeProperty ; rdfs:label "来源 JD" ; rdfs:domain :Requirement ; :physicalColumn "source_jd" ;
    :businessDescription "哪份职务说明书，如『2.副总助理职务说明书』。审计用。" .
:reqMandatory a owl:DatatypeProperty ; rdfs:label "是否必选" ; rdfs:domain :Requirement ; :physicalColumn "mandatory" ;
    :businessDescription "全部为 true：JD 没有写『可选』。" .
:reqAssessable a owl:DatatypeProperty ; rdfs:label "是否可评估" ; rdfs:domain :Requirement ; :physicalColumn "assessable" ;
    :businessDescription "false 表示目前没有可对应的技能部件，无法打分。这是『不可评估』，不是『不合格』。" .
:reqThreshold a owl:DatatypeProperty ; rdfs:label "达标阈值" ; rdfs:domain :Requirement ; :physicalColumn "threshold" ;
    :businessDescription "复合要求的覆盖率门槛，默认 0.5（至少满足一半）。" .
:reqTierEvidence a owl:DatatypeProperty ; rdfs:label "层级依据" ; rdfs:domain :Requirement ; :physicalColumn "tier_evidence" ;
    :businessDescription "为什么是这个 tier。只有 JD 写了『优先』的才有值，其余为空——空的含义是『JD 没说』，不是『我们没查』。" .
:reqSkillCategory a owl:DatatypeProperty ; rdfs:label "技能类别" ; rdfs:domain :RequirementSkill ; :physicalColumn "category" ;
    :businessDescription "技能所属的类别类，冗余存一份便于按类别聚合。" .
:reqSkillRequirementId a owl:DatatypeProperty ; rdfs:label "所属要求" ; rdfs:domain :RequirementSkill ; :physicalColumn "requirement_id" ;
    :businessDescription "指回 requirement.id。" .
:evCandidate a owl:DatatypeProperty ; rdfs:label "候选人" ; rdfs:domain :CandidateSkillEvidence ; :physicalColumn "candidate" ;
    :businessDescription "candidate.id。" .
:evSkill a owl:DatatypeProperty ; rdfs:label "技能" ; rdfs:domain :CandidateSkillEvidence ; :physicalColumn "skill" ;
    :businessDescription "带 skill_ 前缀的技能个体名。" .
:evCategoryCol a owl:DatatypeProperty ; rdfs:label "类别" ; rdfs:domain :CandidateSkillEvidence ; :physicalColumn "category" ;
    :businessDescription "该技能所属类别（来自 skill 表）。" .
:evSourceFile a owl:DatatypeProperty ; rdfs:label "源文件" ; rdfs:domain :CandidateSkillEvidence ; :physicalColumn "source_file" ;
    :businessDescription "证据来自哪份简历文件——这样一句『他会 ERP』可以一路追到那一页扫描件。" .
:fcCandidate a owl:ObjectProperty ; rdfs:label "构成-候选人" ; rdfs:domain :FitComponent ; rdfs:range :Candidate ; :physicalColumn "candidate" ; :references :Candidate ;
    :businessDescription "candidate.id。评分的最小单位是『某人某岗』，因为同一个人可以同时匹配多个岗位。名字不叫 fitCandidate：那个已属于 CandidateRoleFit。" .
:fcRole a owl:ObjectProperty ; rdfs:label "构成-岗位" ; rdfs:domain :FitComponent ; rdfs:range :Role ; :physicalColumn "role" ; :references :Role ;
    :businessDescription "被评分的岗位。" .
:fitComponentName a owl:DatatypeProperty ; rdfs:label "分量" ; rdfs:domain :FitComponent ; :physicalColumn "component" ;
    :businessDescription "skills | years | education。" .
:fitRequirementId a owl:DatatypeProperty ; rdfs:label "对应要求" ; rdfs:domain :FitComponent ; :physicalColumn "requirement_id" ;
    :businessDescription "skills 分量指向 requirement.id；years/education 用空串作哨兵（主键列不能为 NULL）。" .
:fitLabel a owl:DatatypeProperty ; rdfs:label "分量说明" ; rdfs:domain :FitComponent ; :physicalColumn "label" ;
    :businessDescription "渲染成人话时用的那一句，如『ERP订单管理模块 + Excel数据分析』。" .
:fitRequired a owl:DatatypeProperty ; rdfs:label "要求值" ; rdfs:domain :FitComponent ; :physicalColumn "required" ;
    :businessDescription "该分量的要求：技能部件数，或年限/学历门槛。JD 未声明时为空。" .
:fitActual a owl:DatatypeProperty ; rdfs:label "实际值" ; rdfs:domain :FitComponent ; :physicalColumn "actual" ;
    :businessDescription "候选人实际达到的值。**NULL 表示未读到**，不是 0——v_shortlist 的 completeness 正是按它算的。" .
:slCandidate a owl:ObjectProperty ; rdfs:label "名单-候选人" ; rdfs:domain :Shortlist ; rdfs:range :Candidate ; :physicalColumn "candidate" ; :references :Candidate ;
    :businessDescription "candidate.id。名单的最小单位是『某人某岗』。" .
:slRole a owl:ObjectProperty ; rdfs:label "名单-岗位" ; rdfs:domain :Shortlist ; rdfs:range :Role ; :physicalColumn "role" ; :references :Role ;
    :businessDescription "role.role（带 role_ 前缀）。" .
:slScore a owl:DatatypeProperty ; rdfs:label "分数" ; rdfs:domain :Shortlist ; :physicalColumn "score" ;
    :businessDescription "见 shortlistScore。" .
:slCompleteness a owl:DatatypeProperty ; rdfs:label "完整度" ; rdfs:domain :Shortlist ; :physicalColumn "completeness" ;
    :businessDescription "见 shortlistCompleteness。" .
:slFirstGap a owl:DatatypeProperty ; rdfs:label "首个缺口" ; rdfs:domain :Shortlist ; :physicalColumn "first_gap" ;
    :businessDescription "没满足的第一条要求名——『他差哪一项』的答案。" .
:slGaps a owl:DatatypeProperty ; rdfs:label "缺口数" ; rdfs:domain :Shortlist ; :physicalColumn "gaps" ;
    :businessDescription "未满足的要求条数。" .
:slListKind a owl:DatatypeProperty ; rdfs:label "名单类型" ; rdfs:domain :Shortlist ; :physicalColumn "list_kind" ;
    :businessDescription "qualified | near | excluded。" .
:slListBucket a owl:DatatypeProperty ; rdfs:label "名单分组" ; rdfs:domain :Shortlist ; :physicalColumn "list_bucket" ;
    :businessDescription "A_qualified_full | B_qualified_partial | NULL（未过闸门）。把完整信息与部分信息分成两张名单。" .
"""


DISAGREEMENT_DDL = """
:ShortlistDisagreement a owl:Class ;
    rdfs:label "公理与闸门的分歧（视图）" ;
    :physicalTable "v_axiom_vs_gate" ;
    :primaryKey "candidate, role" ;
    :rowCount 2770 ;
    :businessDescription "决定 C 的披露层：公理（必要条件）说合格而闸门说不够、或反之，都必须看得见。verdict = agree_qualified | axiom_only | gate_only | agree_rejected。实测 agree_qualified 38、axiom_only 166、gate_only 261——一致率 13%，这就是两个真源必须分层的证据。" .
:dgRole a owl:ObjectProperty ; rdfs:label "分歧-岗位" ; rdfs:domain :ShortlistDisagreement ; rdfs:range :Role ; :physicalColumn "role" ; :references :Role ;
    :businessDescription "role.role。" .
:dgCandidate a owl:ObjectProperty ; rdfs:label "分歧-候选人" ; rdfs:domain :ShortlistDisagreement ; rdfs:range :Candidate ; :physicalColumn "candidate" ; :references :Candidate ;
    :businessDescription "candidate.id。" .
:dgAxiomEntailed a owl:DatatypeProperty ; rdfs:label "公理是否蕴含" ; rdfs:domain :ShortlistDisagreement ; :physicalColumn "axiom_entailed" ;
    :businessDescription "HermiT 是否推出该候选人在该岗位类里（必要条件判定的结果）。" .
:dgGateKind a owl:DatatypeProperty ; rdfs:label "闸门结论" ; rdfs:domain :ShortlistDisagreement ; :physicalColumn "gate_kind" ;
    :businessDescription "qualified | near | excluded | not_in_gate。" .
:dgScore a owl:DatatypeProperty ; rdfs:label "分数" ; rdfs:domain :ShortlistDisagreement ; :physicalColumn "score" ;
    :businessDescription "同 v_shortlist.score。" .
:dgCompleteness a owl:DatatypeProperty ; rdfs:label "完整度" ; rdfs:domain :ShortlistDisagreement ; :physicalColumn "completeness" ;
    :businessDescription "同 v_shortlist.completeness。" .
:dgVerdict a owl:DatatypeProperty ; rdfs:label "结论" ; rdfs:domain :ShortlistDisagreement ; :physicalColumn "verdict" ;
    :businessDescription "agree_qualified | axiom_only | gate_only | agree_rejected。" .
"""

NS = "https://cube.local/ontology/talent_v1#"
JSONL = pathlib.Path("/tmp/talent_probe/all.jsonl")
EVIDENCE = pathlib.Path("/tmp/talent_probe/evidence_ext.jsonl")


def _extended_categories() -> dict[str, str]:
    """canonical -> category，只从扩展模式来（模式自带 JD 出处）。"""
    return {canon: category for canon, category, _pat, _ev in EXTENDED_SKILL_PATTERNS}


def _merged_records() -> tuple[list[dict], int]:
    records = [json.loads(line) for line in JSONL.read_text(encoding="utf-8").splitlines() if line.strip()]
    ext: dict[str, set[str]] = collections.defaultdict(set)
    for line in EVIDENCE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        ext[row["candidate"]].add(row["skill"].removeprefix("skill_"))

    added = 0
    for rec in records:
        before = set(rec.get("skills") or [])
        after = before | ext.get(rec["candidate_id"], set())
        added += len(after - before)
        rec["skills"] = sorted(after)
    return records, added


def _abi_patched(records: list[dict]) -> str:
    """在内存里扩展 SKILL_CATEGORY，然后调仓库自己的 build() —— 不改 build_abox.py 一行。"""
    merged = dict(build_abox.SKILL_CATEGORY)
    merged.update(_extended_categories())
    original = build_abox.SKILL_CATEGORY
    build_abox.SKILL_CATEGORY = merged
    try:
        text, stats = build_abox.build(records, None)
    finally:
        build_abox.SKILL_CATEGORY = original
    # build() 留了 {{NS}} 占位符，由 main() 替换 —— 复用模块时必须自己补这一步，
    # 否则 ABox 里是 `@prefix : <{{NS}}>`，门禁会报"没有任何个体带已声明的类"
    text = text.replace("{{NS}}", NS)
    # 把现行 ABox 的 role 段接回去（build() 不生成它，见 _roles_block）
    roles = _roles_block()
    # 判据是"有没有 role 个体声明"，不是"有没有出现 :role_"——后者在 :appliedFor 里天天出现
    if roles and not re.search(r"^:role_\w+ a :Role", text, re.M):
        text = text.rstrip() + "\n\n" + roles
        print(f"  已接回 role 段（{roles.count(':role_')} 个岗位个体）")
    elif roles:
        print("  role 个体已在生成物中，未重复接回")
    print(f"  abox 重建：{stats}")
    return text


def _tbox_necessary_only(text: str) -> tuple[str, int]:
    """决定 C：把岗位公理降为**必要条件** —— 删掉 `∃yearsExperience` 与 `∃educationRank`
    两个 facet，只保留 `:Candidate ⊓ ∃hasSkill.(该岗位类别 OR)`。

    为什么：D10 已定年限/学历退出成员判定；而公理里留着它们，等于替客户发明了一条
    门槛（实测：人资专员/工程文员/关务报关员 的 JD **没写**年限，却被挡成 0 人）。
    删掉之后，公理只回答"能不能"（必要条件），`requirement` 表回答"够不够"（闸门）。

    返回 (新文本, 被删掉的 facet 数)。降级后必须能被 rdflib 解析 —— 调用方负责校验。
    """
    import re as _re
    # 每个 facet 形如：
    #     [ a owl:Restriction ; owl:onProperty :yearsExperience ;
    #       owl:someValuesFrom [ a rdfs:Datatype ; ... ] ]
    facet = _re.compile(
        r"\n\s*\[ a owl:Restriction ; owl:onProperty :(?:yearsExperience|educationRank) ;"
        r".*?\]\s*\]", _re.S)
    out, n = facet.subn("", text)
    return out, n


def _verify_necessary_only(text: str) -> tuple[bool, str]:
    """改完必须自证：能被解析、且没有任何 matches_* 定义再带这两个 facet。"""
    import rdflib
    from rdflib import OWL, URIRef
    try:
        g = rdflib.Graph()
        g.parse(data=text, format="turtle")
    except Exception as exc:                                  # noqa: BLE001
        return False, f"解析失败：{type(exc).__name__}: {exc}"
    bad = [str(s) for s in set(g.subjects(OWL.onProperty, None))
           if str(s).endswith(("yearsExperience", "educationRank"))]
    if bad:
        return False, f"仍有 {len(bad)} 处 facet 残留"
    return True, f"解析通过，{len(g)} 条三元组，facet 已清零"


def _spec_under_option_c(abox_text: str) -> tuple[str, dict]:
    """按决定 C 重写 `reasoning.json` 的 `excluded`。

    旧语义：`excluded` 里的人是「缺技能、缺年限、或学历不够，所以推不出来」——
    那是把年限/学历当门槛时代的话。C 把年限/学历搬到闸门之后，这些人**本来就该**是
    必要条件类的成员，所以旧的排除声明会变成假阳性（门禁 A3 会报"wrongly a member"）。

    新语义：`excluded` 只保留**缺必要条件**（该岗位要求的类别一个都不命中）的人。
    年限/学历造成的"不合格"由 `v_axiom_vs_gate` 披露，不再冒充公理层的排除。
    """
    import json as _json
    import rdflib
    from rdflib import RDF, URIRef

    spec_path = PROFILE / "reasoning.json"
    spec = _json.loads(spec_path.read_text(encoding="utf-8"))

    g = rdflib.Graph()
    g.parse(data=abox_text, format="turtle")
    NS = "https://cube.local/ontology/talent_v1#"

    def cats_of(skill_iri) -> set[str]:
        return {str(t).replace(NS, "") for t in g.objects(skill_iri, RDF.type)
                if str(t) != "SkillTag" and str(t).startswith(NS)}

    role_cats: dict[str, set[str]] = {}
    for s_ in set(g.subjects(URIRef(NS + "requiresSkill"), None)):
        rc: set[str] = set()
        for sk in g.objects(s_, URIRef(NS + "requiresSkill")):
            rc |= cats_of(sk)
        role_cats[str(s_).replace(NS, "")] = rc

    cand_cats: dict[str, set[str]] = {}
    for c in set(g.subjects(RDF.type, URIRef(NS + "Candidate"))):
        cc: set[str] = set()
        for sk in g.objects(c, URIRef(NS + "hasSkill")):
            cc |= cats_of(sk)
        cand_cats[str(c).replace(NS, "")] = cc

    kept, dropped = 0, 0
    for block in spec.get("excluded") or []:
        cls = block.get("class", "")
        role = "role_" + cls[len("matches_"):] if cls.startswith("matches_") else cls
        need = role_cats.get(role, set())
        survivors = []
        for ind in block.get("individuals") or []:
            lacks = not (cand_cats.get(ind, set()) & need)
            if lacks:
                survivors.append(ind); kept += 1
            else:
                dropped += 1
        block["individuals"] = survivors
        block["why"] = ("lacks every skill category this role requires — a necessary-condition "
                        "failure, not a years/floor failure")
    spec["excluded"] = [b for b in (spec.get("excluded") or []) if b.get("individuals")]
    return _json.dumps(spec, ensure_ascii=False, indent=1), {"kept": kept, "dropped": dropped}


def _roles_block() -> str:
    """从**现行** ABox 里原样取出 role 个体段。

    为什么必须做这一步：`build_abox.build()` 只写候选人、技能与 `:appliedFor`；role 个体
    （`:requiredYears` / `:requiredEducationRank` / `:requiresSkill`）是**业务声明**，
    由另一支脚本追加进 abox.ttl。整份重建会把这 10 个 role 个体连同 28 条 requiresSkill
    一起丢掉——实测后果是 materialize 报 `roles 0 / ranked 0`，名单直接空掉。
    """
    live = (PROFILE / "abox.ttl").read_text(encoding="utf-8")
    marker = "# ── roles and what the client's job description states for them"
    if marker not in live:
        return ""
    return live[live.index(marker):].rstrip() + "\n"


def _tbox_with_categories() -> str:
    live = (PROFILE / "reasoning.ttl").read_text(encoding="utf-8")
    new_categories = sorted(set(_extended_categories().values()))
    have = {c for c in new_categories if f":{c} a owl:Class" in live}
    missing = [c for c in new_categories if c not in have]
    if not missing:
        print("  reasoning.ttl：类别已齐，无需追加")
        return live
    block = ["", "# ── extended skill categories (staged 2026-11-16) ──",
             "# 每个类别都能追到一份 JD 的资格要求原话，见 scripts/talent/skill_patterns_ext.py"]
    block += [f":{c} a owl:Class ; rdfs:subClassOf :SkillTag ." for c in missing]
    print(f"  reasoning.ttl：追加 {len(missing)} 个类别 {missing}")
    return live.rstrip() + "\n" + "\n".join(block) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只生成文件，不调用 stage")
    ap.add_argument("--out-dir", default="/tmp/talent_stage")
    args = ap.parse_args()

    for p, label in ((JSONL, "extract.py 输出"), (EVIDENCE, "探针证据")):
        if not p.is_file():
            print(f"缺少 {label}：{p}\n先跑 extract.py 和 extract_probe.py")
            return 2

    records, added = _merged_records()
    print(f"候选 {len(records)} 份，新增技能断言 {added} 条")

    abox = _abi_patched(records)
    tbox = _tbox_with_categories()
    tbox, n_facets = _tbox_necessary_only(tbox)
    ok, msg = _verify_necessary_only(tbox)
    print(f"  公理降为必要条件：删除 {n_facets} 个年限/学历 facet —— {msg}")
    if not ok:
        raise SystemExit("公理降级失败，未继续")
    live_structure = (PROFILE / "ontology" / "01-structure.ttl").read_text(encoding="utf-8")
    if "physicalTable \"v_axiom_vs_gate\"" in live_structure:
        structure = live_structure
        print("  01-structure.ttl：引擎台账已声明，无需追加")
    else:
        structure = (live_structure.rstrip() + "\n" + STRUCTURE_ADDITION + "\n"
                     + COLUMN_ADDITION + "\n" + DISAGREEMENT_DDL)
        print("  01-structure.ttl：追加 6 个引擎对象声明（5 台账 + 1 分歧视图）")

    spec_text, spec_stats = _spec_under_option_c(abox)
    print(f"  reasoning.json：excluded 重写 —— 保留 {spec_stats['kept']}、"
          f"移出 {spec_stats['dropped']}（后者改为由闸门披露）")

    out = pathlib.Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "abox.ttl").write_text(abox, encoding="utf-8")
    (out / "reasoning.ttl").write_text(tbox, encoding="utf-8")
    (out / "01-structure.ttl").write_text(structure, encoding="utf-8")
    (out / "reasoning.json").write_text(spec_text, encoding="utf-8")
    print(f"候选文件已落盘：{out}/")

    if args.dry_run:
        print("\n--dry-run：未调用 stage()")
        return 0

    from services import ontology_publish
    print("\n调用 ontology_publish.stage('talent_v1', …) ——  在暂存副本上跑门禁")
    result = ontology_publish.stage(
        "talent_v1",
        {"abox.ttl": abox, "reasoning.ttl": tbox,
         "ontology/01-structure.ttl": structure, "reasoning.json": spec_text},
        actor="dsh:stage_extended_vocab",
        note=("决定 C：扩展词表并入 ABox；岗位公理降为必要条件（删 13 个年限/学历 facet）；"
              "excluded 按新语义重写；结构层补登 6 个引擎对象"),
    )
    print(json.dumps(result, ensure_ascii=False, indent=1)[:2500])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
