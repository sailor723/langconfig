#!/usr/bin/env python3
"""生成教程 v2 —— `work/talent/tutorial/TUTORIAL_v2.md`。

## 三条规矩（都由 `check_tutorial.py` 机器检查）

1. **正文里不许出现手写数字。** 每个阿拉伯数字都从 `facts.json` 注入；
   模板里写死一个数字，检查就红。步骤编号因此用中文数字（第一步、第二步…）。
2. **每一步都要有一个能变红的反证**，且反证要在 `facts['falsify']` 里有实测的 before/after。
3. **每一步都要说清它拒绝什么。** 这一条是从旧教程学来的：拒绝要点名缺哪条声明，
   不是给一个空盒子。

## 为什么另起 v2，而不是改 v1

`talent_v1` 的 8 步教程讲的是**本体自身**（个体、类别、定义类、蕴含、指标）。
这几周真实跑出来的东西——四态判定、证据档次、本体与 LLM 的分工、一个数两个来源、
名单两道闸、重放——在 v1 里没有位置，硬塞进去会把「本体是什么」讲糊。
所以 v1 原样保留（教材），v2 讲**这套系统实际怎么工作**，并明确写出本体在哪一层。

用法:
    python -m scripts.talent.build_tutorial_v2      # 先跑 tutorial_facts 生成 facts.json
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TALENT = ROOT / 'work' / 'talent'
FACTS = TALENT / 'tutorial' / 'facts.json'
DEST = TALENT / 'tutorial' / 'TUTORIAL_v2.md'

CN = ('零', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十',
      '十一', '十二', '十三', '十四')


def flat(facts: dict) -> dict:
    """把 facts 拍平成一个 {点路径: 值} 的字典，模板只从它取值。"""
    out: dict[str, object] = {}

    def walk(node, prefix):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f'{prefix}.{k}' if prefix else str(k))
        elif isinstance(node, list):
            out[prefix] = node
        else:
            out[prefix] = node

    walk(facts, '')
    return out


def pct(x) -> str:
    """比例 → 百分数字面（不带 % 也算同一个数，校验脚本会把它算进允许集合）。"""
    return f'{round((x or 0) * 100)}%'


def render(facts: dict) -> str:
    f = flat(facts)          # 给"按点路径取一个数"用
    s1, s2 = facts['step1_records'], facts['step2_individuals']
    s3, s4 = facts['step3_categories'], facts['step4_missing']
    s5, s6 = facts['step5_gates'], facts['step6_threshold_owner']
    s7, s8 = facts['step7_states'], facts['step8_evidence']
    s9, s10 = facts['step9_division'], facts['step10_two_sources']
    s11, s12 = facts['step11_lists'], facts['step12_refusals']
    s13, s14 = facts['step13_replay'], facts['step14_questions']
    fx = facts['falsify']

    L: list[str] = []
    A = L.append

    A('# 教程 v2 · 从一份扫描件走到一个判定')
    A('')
    A('> 这一步一步讲的是**这套系统实际怎么工作**，不是"本体应该是什么"。')
    A('> 每个数字都由 `scripts/talent/tutorial_facts.py` 从产物里算出来，'
      '正文一个数字都不许手写；每步都给一个**能变红**的反证。')
    A('')
    A('## 一句话')
    A('')
    A('**本体给事实与闸门，LLM 给判定，冲突按类处置，任何一步都能按名拒绝，任何结论都能重放。**')
    A('')
    A('这五段之间有三条边界，必须先说清楚，否则后面每一步都会被读成"机器替人做了决定"：')
    A('')
    A('| 边界 | 谁负责 | 现在的实现 |')
    A('|---|---|---|')
    A(f'| 事实（人有什么） | 本体 ABox | `abox.ttl`：{s2["candidates"]} 个候选人个体、'
      f'{s2["skill_assertions"]} 条技能断言 |')
    A(f'| 闸门（岗位要什么） | 要求库（YAML） | `requirement_library.yaml`（{s5["library_size"]} 条）'
      f' + `jd_links/`（{s5["client_citations"]} 条客户原文引用） |')
    A(f'| 判定（他够不够） | Python + LLM | `judge_all()` 逐条比阈值；LLM 读语义，冲突进复议 |')
    A('')
    A('---')
    A('')

    # ── 第一步 ──
    A('## 第一步 · 记录从哪来')
    A('')
    A('**一句话**：一份简历先变成一行记录，值必须能追回它来自哪个文件的哪一句。')
    A('')
    A(f'- 源文件 **{s1["source_files"]}** 份，OCR 全文 **{s1["ocr_chars"]}** 字符，'
      f'平均每份 **{s1["avg_chars"]}** 字符。')
    A('- 这一层不做判断：读到什么写什么，读不到的留空。')
    A('')
    A('**反证**：删掉一份源文件，个体数必须随之减少 —— 少不掉说明它本来就不在计数里。')
    A('')
    A('**这一步拒绝**：把「公司产品清单」当成「行业」。原文只有产品行时，行业一律留空，'
      '不用产品名替它充数。')
    A('')

    # ── 第二步 ──
    A('## 第二步 · 记录变成个体')
    A('')
    A('**一句话**：ABox 只写断言，不写推断。')
    A('')
    A(f'- 个体 **{s2["candidates"]}** 个；技能 **{s2["skills"]}** 种；'
      f'技能断言 **{s2["skill_assertions"]}** 条（人均 **{s2["assertions_per_candidate"]}** 条）。')
    A('- 一条断言 = 「此人会此技能」。它既不是候选人也不是技能，所以单独成类，不挂成单值属性。')
    A('')
    A(f'> **这里立刻出现第一个差额**：ABox 有 {s2["candidates"]} 个个体，'
      f'当前能用的 OCR 文本是 {s1["source_files"]} 份 —— 差 '
      f'{s2["candidates"] - s1["source_files"]} 份。ABox 是更早那次快照（含重复简历）建的，'
      '之后清洗掉了。这不是 bug，是「同一件事有两个来源」的第一个实例，第十步会展开。')
    A('')
    A(f'**反证**：在 ABox 里手写一条类型断言（`:matches_品质经理`），门禁必须报 '
      f'`copied answer, not a reasoned one` —— 断言了的答案证明不了任何事。')
    A('')
    A('**这一步拒绝**：读不到技能就说「没有技能」。'
      f'ABox 里技能缺失的有 {s4["abox_marks"]["Skills"]} 人，他们打 `:UnknownSkills` 记号的，'
      '不是被判成「零技能」。')
    A('')

    # ── 第三步 ──
    A('## 第三步 · 技能是个体，类别是类')
    A('')
    A('**一句话**：类别写错了不会报错，只会让你的问题永远是空集。')
    A('')
    A(f'- 用在个体上的类别 **{s3["categories_used"]}** 个；TBox 声明 **{s3["classes_declared"]}** 个类；'
      f'用了但没声明的类别 **{len(s3["undeclared_but_used"])}** 个。')
    A(f'- 最大的几类：' + '、'.join(f'{k}（{v}）' for k, v in s3['top_categories'][:3]) + '。')
    A('')
    A(f'**反证 F1（删掉 `:CAD` 这一类）**：会 CAD 的人 {fx["F1_drop_category_CAD"]["before"]} '
      f'→ {fx["F1_drop_category_CAD"]["after"]}。'
      '推理机一句错话都不会说，页面看起来还很完美。')
    A('')
    A('**这一步拒绝**：把类别手写在脚本里。类别必须从 ABox 用的同一套词表生成 —— '
      '两边一旦各写一份，就会像这样：`AutoCAD` 的要求一个人都匹配不上，而没有任何报错。')
    A('')

    # ── 第四步 ──
    A('## 第四步 · 读不到 ≠ 0')
    A('')
    A('**一句话**：「这个人没有」和「我们没读出来」是两句不同的话，不许并成一个数。')
    A('')
    A('| 缺口 | ABox 记号 | LLM 抽取侧的缺失 |')
    A('|---|---|---|')
    A(f'| 工作年限 | {s4["abox_marks"]["Years"]} 人 | {s4["cv_facts_absent"]["years"]} 人 |')
    A(f'| 学历 | {s4["abox_marks"]["Education"]} 人 | {s4["cv_facts_absent"]["education"]} 人 |')
    A(f'| 技能 | {s4["abox_marks"]["Skills"]} 人 | {s4["cv_facts_absent"]["skills"]} 人 |')
    A('')
    A(f'**反证 F2（把缺失年限当成 0）**：{fx["F2_missing_years_as_zero"]["before"]} 个「未知」'
      f'会变成 {fx["F2_missing_years_as_zero"]["unknown_becomes"]}。'
      '全库曾经就这么错过：把「没读到」判成「不合格」，一次挡掉一百多号人。')
    A('')
    A('**这一步拒绝**：用默认值补缺口（年限默认 0、学历默认大专）。缺就是缺，'
      '补一个没人声明过的值，等于替客户加一条要求。')
    A('')

    # ── 第五步 ──
    A('## 第五步 · 客户原文变成闸门')
    A('')
    A('**一句话**：阈值只有一个来源 —— 客户原文那一行，逐字可回查。')
    A('')
    A(f'- 五个 JD 共 **{s5["client_citations"]}** 条客户原文引用，'
      f'逐字 + 行号复核通过 **{s5["verbatim_ok"]}** 条；'
      f'另有 HR 侧要求 **{s5["hr_side_citations"]}** 条（我方提出，没有原文可回查，单独标注）。')
    A('')
    A('| JD | 引用 | 其中客户 | 其中 HR | 逐字通过 | 可判 |')
    A('|---|---|---|---|---|---|')
    for jd, v in s5['per_jd'].items():
        A(f'| {jd} | {v["citations"]} | {v["client"]} | {v["hr"]} | {v["verbatim_ok"]} | {v["judgeable"]} |')
    A('')
    fx9 = fx['F9_tamper_client_source']
    A(f'**反证 F9（客户原文改一个字）**：业务跟单的逐字回查通过 {fx9["before"]} → {fx9["after"]}。'
      '阈值改不了，因为改了就回查不过 —— 这是"闸门可信"的唯一凭据。')
    A('')
    A('**这一步拒绝**：JD 没写阈值就给个默认阈值。没写 = 不可判，对所有人一样，不进分母。')
    A('')

    # ── 第六步 ──
    A('## 第六步 · 阈值由谁判（这一步要诚实）')
    A('')
    A('**一句话**：招聘链上的阈值判定在 **Python**，不在推理机。')
    A('')
    A(f'- 本体里有 **{s6["dl_defined_classes"]}** 个定义类（{ "、".join(s6["dl_roles"]) }），'
      f'它们服务于教材与 profile 指标。')
    A(f'- 招聘链实际判的是 **{s6["py_requirements_judged"]}** 条引用，全部由 `judge_all()` 逐条比阈值。')
    A('')
    A(f'**反证 F3（删掉全部定义类）**：定义类 {fx["F3_drop_defined_classes"]["before"]} → '
      f'{fx["F3_drop_defined_classes"]["after"]}，而**招聘结论一个都不变**。'
      '这一步本身就是在告诉你：不要把「本体推出的结论」当成招聘结论的来源。')
    A('')
    A('**这一步拒绝**：把带证据档次的要求全部硬塞进 DL 三联式（技能族并集 ∧ 年限 ∧ 学历）。'
      '塞不进去就说塞不进去，不要让读者以为已经塞了。')
    A('')

    # ── 第七步 ──
    A('## 第七步 · 四个判定状态')
    A('')
    A('**一句话**：满足 / 不满足 / **未知** / **不可判**，四种状态永不合并。')
    A('')
    A(f'- 判定说明 **{s7["docs"]}** 份，共 **{s7["total_cells"]}** 格：'
      f'满足 **{s7["counts"]["满足"]}**、不满足 **{s7["counts"]["不满足"]}**、'
      f'未知 **{s7["counts"]["未知"]}**、不可判 **{s7["counts"]["不可判"]}**。')
    A('')
    A('| 状态 | 意思 | 谁造成 | 处置 |')
    A('|---|---|---|---|')
    A('| 满足 | 有明确证据，能引原文 | — | 计入满足率 |')
    A('| 不满足 | 有硬证据否定（阈值比不过 / 一面明确否认） | 候选人 / 材料 | 可作排除依据 |')
    A('| 未知 | 材料里读不到 | 简历没写 / 没问到 | 进待核清单，不许当不合格 |')
    A('| 不可判 | 这条要求没有数据项或没有阈值 | JD / 数据模型 | 不进分母，对所有人一样 |')
    A('')
    A(f'**反证 F4（把「未知」并进「不满足」）**：不满足 {fx["F4_unknown_as_unsatisfied"]["before"]} '
      f'→ {fx["F4_unknown_as_unsatisfied"]["after"]}。'
      '这不是假设，是本仓库真犯过的错：')
    A(f'全库 {s7["total_cells"]} 格里，「未知」占 {s7["counts"]["未知"]} 格 —— '
      '把它们判成不合格，等于把「我们没读到」算成「他不行」。')
    A('')
    A('**这一步拒绝**：用「未知」当排除理由。排除必须有硬证据。')
    A('')

    # ── 第八步 ──
    A('## 第八步 · 证据档次：硬证据与仅自述')
    A('')
    A('**一句话**：能力类的「满足」必须说清是**有载体**还是**只有自述**。')
    A('')
    A(f'- 组件目录 **{s8["components"]}** 个，其中标了证据档的 '
      f'{s8["roles"].get("hard", 0) + s8["roles"].get("soft", 0)} 个：'
      f'硬证据 **{s8["roles"].get("hard", 0)}**、软证据 **{s8["roles"].get("soft", 0)}**；'
      f'**{s8["roles"].get("未声明", 0)}** 个还没标 —— 这本身是个待办。')
    A(f'- 判定说明里能力类「满足」的行有 **{s8["capability_satisfied_rows"]}** 行。')
    A('')
    fx10 = fx['F10_soft_evidence_as_hard']
    A(f'**反证 F10（把「仅自述」的否定也当硬证据）**：可用来排除的格数 {fx10["before"]} → '
      f'{fx10["after"]}。门禁要求「排除必须有硬证据」，挡的就是这个膨胀。')
    A('')
    A('**这一步拒绝**：给「仅自述」的满足打上和「有系统截图/客户审核」一样的权重。')
    A('')

    # ── 第九步 ──
    A('## 第九步 · 本体和 LLM 一起：冲突分四类')
    A('')
    A('**一句话**：冲突不是"谁对"，是"哪一类冲突"。')
    A('')
    A('| 冲突类型 | 长什么样 | 谁赢 |')
    A('|---|---|---|')
    A('| A 数据值 | 同一数据项两个值 | 本体（有来源与引文） |')
    A('| B 阈值/口径 | LLM 自行放宽加严 | 本体（客户原文赢） |')
    A('| C 判定 | 本体词表没命中、LLM 从原文读出同义表达 | **不自动跟本体 → 复议** |')
    A('| D 不可判 | 本体说这条没有数据项 | 本体（LLM 的结论作废） |')
    A('')
    A('历史实验（`work/talent/compare/品质经理·分工对比.yaml`，'
      f'{s9["candidates"]} 人、{s9["truth_cells"]} 格人工核对过的基准）：')
    A('')
    A('| 变体 | 判定质量 | 重放一致 | 重调一致 | 调用次数 |')
    A('|---|---|---|---|---|')
    for name, v in s9['experiment'].items():
        A(f'| {name} | {v["判定质量"]} | '
          f'{pct(v["可复算_重放"])} | {pct(v["可复算_重调"])} | {v["调用次数"]} |')
    A('')
    A('读法：**只看本体 7/31，本体给料 + LLM 判 15/31**。如果"冲突一律跟本体"，'
      '这 8 格的提升会被整个抹掉 —— 这就是 C 类必须复议、不能跟本体的理由。')
    fx8 = fx['F8_c_conflict_follows_ontology']
    A(f'**反证 F8（把 C 类改成「一律跟本体」）**：判定质量 {fx8["before"]} → {fx8["after"]}。'
      '「一律跟本体」等价于回退到只看本体那个变体 —— 提升的那几格正是 LLM 读语义挣来的。')
    A('')
    A(f'当前冲突台账 **{s9["conflicts_now"]}** 格：判定重跑之后 C 类冲突清零，'
      '这既说明口径收敛了，也说明**这份台账现在证明不了 C 类规则还在生效** —— 要留档，不要删。')
    A('')
    A('**这一步拒绝**：把「分工」写成散文。"A/B/D 跟本体、C 复议"必须是可执行规则，'
      '否则下一个人会按自己的理解改回去。')
    A('')

    # ── 第十步 ──
    A('## 第十步 · 一个数两个来源')
    A('')
    A('**一句话**：同一项能力有两个来源、且多数人两边不一样时，「可复算」从哪一刻算起？')
    A('')
    A(f'- ABox 里技能断言 **{s10["abox_assertions"]}** 条；LLM 抽取侧 **{s10["llm_assertions"]}** 条。')
    A(f'- **{s10["candidates"]}** 人里 **{s10["differ"]}** 人两边技能集合不同：'
      f'ABox 独有 **{s10["only_abox"]}** 条，LLM 独有 **{s10["only_llm"]}** 条。')
    A('')
    A(f'**反证 F5（只信 ABox）**：断言 {fx["F5_abox_only"]["before"]} → '
      f'{fx["F5_abox_only"]["after"]}。不定真源，两个人各算一遍会得到两个数，'
      '而且都能自称「可复算」。')
    A('')
    A('**这一步拒绝**：默认「LLM 覆盖 ABox」却不写下来。覆盖规则必须显式、可查，'
      '并且写清哪一侧是权威、另一侧只做交叉核对。')
    A('')

    # ── 第十一步 ──
    A('## 第十一步 · 名单的两道闸')
    A('')
    A('**一句话**：短名单问「谁排前面」，最终名单问「谁没有硬伤」。')
    A('')
    A('| JD | 短名单 | 最终 | 上限 | 切线并列 | 被最终闸挡下 |')
    A('|---|---|---|---|---|---|')
    for jd, v in s11['per_jd'].items():
        A(f'| {jd} | {v["shortlist"]} | {v["final"]} | {v["final_max"]} | {v["tie_band"]} | {v["dropped"]} |')
    A('')
    r = s11.get('rules') or {}
    A(f'最终闸三条硬条件：**硬门槛 0 条不满足 + 至少 {r.get("min_hard")} 项硬证据 + '
      f'未知 ≤ {r.get("unknown_max")} 条**，人数上限 `final_max` = {r.get("final_max")}。'
      '这三条与上限都写在产物里（`目标名单.yaml` 的 `final`），不在这个文档里。')
    A('')
    A(f'**反证 F7（最终名单 = 短名单，不设第二道闸）**：'
      f'{fx["F7_final_without_second_gate"]["before"]} → {fx["F7_final_without_second_gate"]["after"]}。'
      '两道闸没设，等于把「够格排队」当成了「可以送去面」。')
    A('')
    A('**这一步拒绝**：让本体出名单。计算词表没有 `orderBy/limit`，'
      '"名单里排第几是谁"按名拒绝；本体只给人数与分数线，名单是流水线的产物。')
    A('')

    # ── 第十二步 ──
    A('## 第十二步 · 三种按名拒绝')
    A('')
    A('**一句话**：拒绝要点名缺的是哪条声明，不是一个空盒子。')
    A('')
    A('| 拒绝类型 | 实例 | 规模 |')
    A('|---|---|---|')
    A(f'| 没有职务说明书 | { "、".join(n for n, _ in s12["roles_without_jd"]) } | '
      f'{s12["roles_without_jd_candidates"]} 人 |')
    A(f'| 要求库里没有数据项 | `assessable: false` 的客户要求 | '
      f'{len(s12["requirements_without_data_item"])} 条 |')
    thr = s12.get('roles_without_threshold') or []
    A(f'| JD 没写阈值 | ' + '、'.join(f'{n}（{",".join(m)}）' for n, _c, m in thr) + ' | '
      f'{s12.get("roles_without_threshold_candidates")} 人在这些岗位上 |')
    A(f'| 组件全库无人命中 | { "、".join(c.replace("skill_", "") for c in s12["components_zero_holder"]) } | '
      f'{len(s12["components_zero_holder"])} 个组件 |')
    A('')
    f6 = fx['F6_default_years_on_refused_jd']
    A(f'**反证 F6（给「没写年限」的 JD 补一个默认年限）**：'
      f'按名拒绝 {f6["before"]} → 直接给出结论 {f6["after"]}：'
      f'{"、".join(f6.get("roles") or [])} 上会有 {f6["after"]} 人被算进合格率。'
      '补默认值等于替客户加一条要求 —— 这正是教程要禁止的动作。')
    A('')
    A('**这一步拒绝**：分母为 0 时报一个 0。0 会被读成「没人够格」，'
      '而真相是「没人投这个岗」。')
    A('')

    # ── 第十三步 ──
    A('## 第十三步 · 重放，不是重调')
    A('')
    A('**一句话**：「可复算」的定义是**重放**：同一份存档读两次结论相同。重调是再问一次模型。')
    A('')
    A(f'- 存档 **{s13["run_pairs"]}** 对：按人全对 **{s13["same_verdicts"]}** 对'
      f'（{round((s13["replay_rate"] or 0) * 100)}%），漂移 **{s13["reask_drift"]}** 对；')
    A(f'- 按格看：**{s13["cells_compared"]}** 格里一致 **{s13["cells_same"]}** 格'
      f'（{round((s13["cell_agreement"] or 0) * 1000) / 10}%）。')
    A('')
    A('两个口径都要报：按人全对是严格口径（一个人有一格变了就算漂移），'
      '按格才看得出漂移有多碎。**只报一个数都会误导。**')
    A('')
    A('**反证**：把「重放」换成「重调」，同一份材料再问一次模型 —— '
      f'{s13["reask_drift"]} 对结论会变，而每一份看起来都"可复算"。')
    A('')
    A('**这一步拒绝**：把「模型输出存档」当成"可复算"本身。存档只保证读得回，'
      '不保证换模型、换温度、换 prompt 之后还是同一个答案。')
    A('')

    # ── 第十四步 ──
    A('## 第十四步 · 你能问什么、不能问什么')
    A('')
    A('**一句话**：能问人数、分数线、缺口、拒绝清单；不能问「名单里排第几是谁」。')
    A('')
    A(f'- 已编译指标 **{s14["metrics_declared"]}** 条；声明在案按名拒绝 **{s14["refusals_declared"]}** 条；'
      f'已声明空洞 **{s14["holes_declared"]}** 条。')
    A('')
    A('**反证**：问一个没有声明的口径（例如「最近一个月投了多少人」），'
      '必须按名拒绝 —— 库里没有投递时间列，任何相对窗口都会安静返回空。')
    A('')
    A('**这一步拒绝**：给空结果配一个看起来对的数。')
    A('')

    # ── 收尾 ──
    A('---')
    A('')
    A('## 五段边界（背下来这一段就够了）')
    A('')
    A('| 段 | 归谁 | 判据 | 失败长什么样 |')
    A('|---|---|---|---|')
    A('| 事实 | 本体 ABox | 每条断言能追到源文件 | 静默空集（`CAD` 拼成 `CAT`） |')
    A('| 闸门 | 要求库 + `jd_links` | 逐字回查 + 行号真实 | 阈值被悄悄放宽 |')
    A('| 判定 | Python + LLM | 四态 + 证据档次 | 把「未知」当「不满足」 |')
    A('| 冲突 | 规则（A/B/D 跟本体，C 复议） | 冲突台账 + 人工裁决 | 一律跟本体，整批继承本体的错 |')
    A('| 名单 | 流水线 | 两道闸 + 切线 tie_band | 把「够格排队」当成「可以面」 |')
    A('')
    A('## 全部数字的复算方式')
    A('')
    A('```bash')
    A('cd backend && set -a && source ../.env; set +a')
    A('env -u PGPORT .venv/bin/python -m scripts.talent.tutorial_facts    # 重算 facts.json')
    A('env -u PGPORT .venv/bin/python -m scripts.talent.build_tutorial_v2 # 重新生成本文件')
    A('env -u PGPORT .venv/bin/python -m scripts.talent.check_tutorial     # 校验（数字/反证/步数）')
    A('```')
    A('')
    A('## 已知缺口（写在这里，免得被当成已解决）')
    A('')
    A('- **本体没进招聘主链**：定义类与指标层只服务教材与 profile，招聘结论来自 Python。'
      '第六步测的就是这件事。')
    A('- **一个数两个来源没有定真源**：第十步的差异还在，覆盖规则没有写成声明。')
    A(f'- **证据档只标了 {s8["roles"].get("hard", 0) + s8["roles"].get("soft", 0)} / '
      f'{s8["components"]} 个组件**：剩下的没标就等于默认「不分档」，能力类的「满足」里'
      '有多少只是自述，现在答不出来。')
    pt = facts.get('pipeline_truth') or {}
    A(f'- **一面数据全是代拟**：{pt.get("interview_docs")} 份一面记录里，'
      f'真访谈 {pt.get("real_interview_docs")} 份、代拟 {pt.get("simulated_docs")} 份 —— '
      '所以每一份名单都只能当演练看。')
    A('')
    return '\n'.join(L)


def main() -> int:
    if not FACTS.is_file():
        print('先跑: python -m scripts.talent.tutorial_facts')
        return 2
    facts = json.loads(FACTS.read_text(encoding='utf-8'))
    md = render(facts)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(md, encoding='utf-8')
    print(f'写出 {DEST.relative_to(ROOT)} · {len(md.splitlines())} 行')
    return 0


if __name__ == '__main__':
    sys.exit(main())
