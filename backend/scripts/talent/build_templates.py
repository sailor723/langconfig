#!/usr/bin/env python3
"""生成公司标准 JD / CV 模板 —— **从 `field_schema.yaml` 派生**，不是另起一套词表。

## 两条建法原则（用户 2026-11-24 明确）

**① 以 `field_schema` 为底座。**
  字段 id、中文名、所属段、维度、`prop`、`compare` 全部**从 fileld_schema 读**，本文件
  不重新写一遍。为什么这么严：只要允许手写，两天后模板里就会出现 `F.CV_CONTACT` 这种
  `field_schema` 里不存在的命名，而判定链读的是 `field_schema` 的口径 —— 两套名字 =
  两处真相。`in_field_schema: true` 的字段，名字与段号必须与 `field_schema` **逐字相同**
  （门禁 ST-G10 会把它钉住）。

**② 支撑本体推理。**
  模板里出现的每个可判字段，都必须有 `data_item`（A.1…A.5 / B.1…B.3 / C.1 / C.4 / C.6 /
  C.7 / F.3 / G.1 / `skill_*`），也就是 `requirement_library.yaml` 里 61 条要求真正读的
  那个位置。**反过来也成立**：能判的要求如果模板里没有落脚字段，这条要求就永远只能是
  「未知」—— 那不是候选人没有，是我们没问（门禁 ST-G7 钉住）。

## 模板**不必**包含 `field_schema` 的全部字段

`field_schema` 是"客户 10 份 JD / 270 份简历里出现过什么"（JD 66 / CV 31），里面混着
文档控制（页数、核准/审核/制订、版本、修订履历）和一次性的填报口径。模板按**这家公司的
实务**取舍：

  · 线束/连接器制造、东莞厂区、出口客户 —— 班制/作业环境/体力/劳保是现场必填；
  · 品质岗、专案岗 —— 体系与工具（8D/CPK/客户验厂/CAD）是硬能力，靠一面坐实；
  · 外贸与关务 —— 语言要**分档**（口语 / 书面），报关资质单独一类；
  · 经理岗 —— 决策权限 / 预算责任 / 跨部门接口；一线岗是班制 / 环境；
  · HR 实务 —— 到岗周期、薪资区间（K）、通勤（班车）、稳定性（制造业流动率）。
删掉的字段不是"不重要"，是**不属于岗位说明书/候选人档案**：比如页数与核准栏属于
文档控制，试用期与社保属于劳动合同。它们在 `field_schema` 里原样保留。

## 每个字段为什么在这里，写在 YAML 注释里

`#` 注释 = 取舍理由（这家厂为什么需要它、客户 10 份 JD 里出现几次、删掉的记在哪）；
`note` 字段 = 操作口径（怎么填、缺了算未知还是不可判）。两者都不许省。

用法:
    python -m scripts.talent.build_templates            # 重新生成两个 YAML
    python -m scripts.talent.build_templates --check    # 只校验是否最新（门禁用）
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
TALENT = ROOT / 'work' / 'talent'
SCHEMA = TALENT / 'field_schema.yaml'
LABELS_EN = TALENT / 'labels_en.yaml'
OUT_DIR = TALENT / 'templates'
DEST = {'jd': OUT_DIR / 'standard_jd_template.yaml', 'cv': OUT_DIR / 'standard_cv_template.yaml'}

J, N, I = 'judgeable', 'not_judgeable', 'internal'
R, C, O = 'required', 'conditional', 'optional'

# ── 取舍：为什么用这些字段、为什么删那些 ─────────────────────────────────
# 每个 code 后面是「放哪一段 / 层级 / 判定口径 / 数据项 / 形状 / 证据 / 缺了算 / 要求」。
# 段号一律沿用 field_schema 自己的分段，不重新分组 —— 分组一改，客户看 JD 时就对不上了。

JD_FIELDS: dict[str, dict] = {
    # ── S1 岗位标识（field_schema 原段）
    'F.JOB_TITLE': dict(lvl=R, ass=I),
    'F.MGMT_CATEGORY': dict(lvl=R, ass=I),
    'F.DEPARTMENT': dict(lvl=R, ass=I),
    'F.REPORTS_TO': dict(lvl=R, ass=I),
    'F.SUPERVISES': dict(lvl=R, ass=I),
    'F.JD_JOB_GRADE': dict(lvl=O, ass=I),
    # ── S2 岗位目的
    'F.JD_JOB_PURPOSE': dict(lvl=R, ass=N),
    'F.JD_SUCCESS_CRITERIA': dict(lvl=R, ass=N),
    # ── S3 任职资格
    'F.AGE': dict(lvl=R, ass=J, item='A.2', shape='区间(岁)', ev='原文', miss='未知',
                  reqs=['REQ-A-AGE-RANGE']),
    'F.GENDER': dict(lvl=O, ass=J, item='A.1', shape='闭集', ev='原文', miss='未知',
                     reqs=['REQ-A-GENDER']),
    'F.EDU_LEVEL': dict(lvl=R, ass=J, item='B.1', shape='顺序(≥等级)', ev='原文', miss='未知',
                        reqs=['REQ-B-EDU-LEVEL']),
    'F.EDU_MAJOR': dict(lvl=R, ass=J, item='B.2', shape='闭集 或 开区间(必须写清"等")',
                        ev='原文', miss='未知', reqs=['REQ-B-MAJOR']),
    'F.EDU_FULLTIME': dict(lvl=C, ass=J, item='B.3', shape='布尔', ev='原文 or 一面', miss='未知',
                           reqs=['REQ-B-FULL-TIME'], cond='客户写了全日制'),
    'F.EXP_YEARS': dict(lvl=R, ass=J, item='C.1', shape='区间(年)', ev='原文', miss='未知',
                        reqs=['REQ-C-YEARS-DOMAIN']),
    'F.EXP_DOMAIN': dict(lvl=C, ass=J, item='C.2', shape='闭集(领域)', ev='一面', miss='未知',
                         reqs=['REQ-C-YEARS-DOMAIN', 'REQ-D-HARNESS-DOMAIN'],
                         cond='JD 写了领域年限'),
    'F.SKILL': dict(lvl=R, ass=J, item='skill_*', shape='any_of n / all_of（逐条声明）',
                    ev='原文 or 一面坐实', miss='未知', reqs=['REQ-D-*']),
    'F.CERTIFICATION': dict(lvl=O, ass=J, item='F.3', shape='闭集(证书清单)',
                            ev='原文(扫描件)', miss='未知',
                            reqs=['REQ-F-TRADE-COMPLIANCE-TRAINING']),
    'F.LANGUAGE_LEVEL': dict(lvl=O, ass=J, item='skill_语言', shape='分档：口语 / 书面 各一档',
                             ev='一面', miss='未知', reqs=['REQ-H-LANG-EN']),
    'F.COMPETENCY': dict(lvl=O, ass=N, miss='不可判', reqs=['REQ-E-*']),
    # ── S4 岗位职责
    'F.JD_DUTY_ITEMS': dict(lvl=R, ass=N),
    'F.DECISION_AUTHORITY': dict(lvl=C, ass=I, cond='岗位类别=经理岗'),
    'F.BUDGET_OWNERSHIP': dict(lvl=C, ass=I, cond='岗位类别=经理岗'),
    'F.CROSS_DEPT': dict(lvl=C, ass=I, cond='岗位类别=经理岗'),
    # ── S5 作业明细
    'F.JD_ACTIVITY_TEXT': dict(lvl=R, ass=N),
    'F.JD_ACTIVITY_FREQ': dict(lvl=R, ass=N),
    # ── S6 工作条件
    'F.SHIFT': dict(lvl=C, ass=I, cond='岗位类别=员工岗', origin='practice'),
    'F.JD_ENVIRONMENT': dict(lvl=C, ass=I, cond='岗位类别=员工岗', origin='practice'),
    'F.JD_PHYSICAL_DEMAND': dict(lvl=C, ass=I, cond='岗位类别=员工岗', origin='practice'),
    'F.JD_PPE': dict(lvl=C, ass=I, cond='岗位类别=员工岗', origin='practice'),
    'F.JD_WORK_LOCATION': dict(lvl=R, ass=I),
    # ── S7 元数据
    'F.JD_HEADCOUNT': dict(lvl=R, ass=I),
    'F.AVAILABILITY': dict(lvl=R, ass=J, item='A.3', shape='周数上限', ev='一面', miss='未知',
                           reqs=['REQ-HR-NOTICE'], origin='hr'),
    'F.SALARY': dict(lvl=R, ass=J, item='A.5', shape='区间(K)，判定读上限', ev='客户预算',
                     miss='不可判', reqs=['REQ-HR-SALARY'], origin='hr'),
    'F.AVG_TENURE': dict(lvl=R, ass=J, item='C.4', shape='区间(年)', ev='推断(逐段累计)',
                         miss='未知', reqs=['REQ-HR-TENURE'], origin='hr', new=True),
    'F.RECENT_SEGMENTS': dict(lvl=R, ass=J, item='C.7', shape='整数上限',
                              ev='推断(工作段)', miss='未知',
                              reqs=['REQ-HR-STABILITY'], origin='hr', new=True),
    'F.COMMUTE': dict(lvl=R, ass=J, item='A.4', shape='布尔 / 单程分钟', ev='一面', miss='不可判',
                      reqs=['REQ-HR-COMMUTE'], origin='hr', new=True),
    'F.JD_HIRING_REASON': dict(lvl=O, ass=I, origin='hr'),
    # ── S8 合规声明
    'F.CLEARANCE': dict(lvl=O, ass=J, item='G.1', shape='布尔', ev='背调', miss='未知',
                        reqs=['REQ-G-NO-CRIMINAL-RECORD']),
    'F.JD_CONFIDENTIALITY': dict(lvl=C, ass=J, item='G.2', shape='布尔', ev='背调', miss='未知',
                                 reqs=['REQ-G-CONFIDENTIALITY'], cond='涉密岗位'),
    'F.JD_CONTRACT_TYPE': dict(lvl=R, ass=I),
}

CV_FIELDS: dict[str, dict] = {
    # ── C1 基本信息
    'F.CV_FULL_NAME': dict(lvl=R, ass=I, ev='原文', miss='未知'),
    'F.GENDER': dict(lvl=R, ass=J, item='A.1', vs='闭集(男/女)', ev='原文', miss='未知',
                     reqs=['REQ-A-GENDER']),
    'F.AGE': dict(lvl=R, ass=J, item='A.2', vs='数值(岁) + 出生年月', ev='原文', miss='未知',
                  reqs=['REQ-A-AGE-RANGE']),
    'F.CV_PHONE': dict(lvl=R, ass=I, ev='原文', miss='未知'),
    'F.CV_EMAIL': dict(lvl=O, ass=I, ev='原文', miss='未知'),
    'F.WORK_LOCATION': dict(lvl=R, ass=J, item='A.4', vs='城市 / 区镇', ev='原文', miss='未知',
                            reqs=['REQ-HR-COMMUTE']),
    # ── C2 求职意向
    'F.JOB_TITLE': dict(lvl=O, ass=I, ev='原文', miss='未知', compare='not_comparable'),
    'F.SALARY': dict(lvl=R, ass=J, item='A.5', vs='区间(K)，判定读上限', ev='原文 or 一面',
                     miss='未知', reqs=['REQ-HR-SALARY']),
    'F.AVAILABILITY': dict(lvl=R, ass=J, item='A.3', vs='整数(周)', ev='一面', miss='未知',
                           reqs=['REQ-HR-NOTICE']),
    'F.COMMUTE': dict(lvl=R, ass=J, item='A.4', vs='布尔 + 单程分钟', ev='一面', miss='未知',
                      reqs=['REQ-HR-COMMUTE'], new=True, sec='C2'),

    # ── C3 教育背景
    'F.EDU_LEVEL': dict(lvl=R, ass=J, item='B.1', vs='闭集(学历等级)', ev='原文', miss='未知',
                        reqs=['REQ-B-EDU-LEVEL']),
    'F.EDU_MAJOR': dict(lvl=R, ass=J, item='B.2', vs='文本(专业全称)', ev='原文', miss='未知',
                        reqs=['REQ-B-MAJOR']),
    'F.EDU_FULLTIME': dict(lvl=R, ass=J, item='B.3', vs='布尔', ev='原文 or 一面', miss='未知',
                           reqs=['REQ-B-FULL-TIME']),
    'F.CV_INSTITUTION': dict(lvl=R, ass=I, ev='原文', miss='未知'),
    # ── C4 工作经历
    'F.CV_EMPLOYER': dict(lvl=R, ass=I, ev='原文', miss='未知'),
    'F.EXP_YEARS': dict(lvl=R, ass=J, item='C.1', vs='数值(年,自述)', ev='原文', miss='未知',
                        reqs=['REQ-C-YEARS-DOMAIN']),
    'F.YEARS_COMPUTED': dict(lvl=R, ass=J, item='C.6', vs='数值(年,逐段累加)',
                             ev='推断(逐段)', miss='未知', new=True, sec='C4'),
    'F.AVG_TENURE': dict(lvl=R, ass=J, item='C.4', vs='数值(年,逐段)', ev='推断(逐段)',
                         miss='未知', reqs=['REQ-HR-TENURE'], new=True, sec='C4'),
    'F.RECENT_SEGMENTS': dict(lvl=R, ass=J, item='C.7', vs='整数(段)',
                              ev='推断(逐段)', miss='未知',
                              reqs=['REQ-HR-STABILITY'], new=True, sec='C4'),
    'F.EXP_DOMAIN': dict(lvl=C, ass=J, item='C.2', vs='闭集(领域)', ev='一面', miss='未知',
                         reqs=['REQ-C-YEARS-DOMAIN'], cond='JD 写了领域年限'),
    # ── C5 技能与证书
    'F.SKILL': dict(lvl=R, ass=J, item='skill_*', vs='组件 × 熟练度 × 引文',
                    ev='原文 or 一面坐实', miss='未知', reqs=['REQ-D-*']),
    'F.LANGUAGE_LEVEL': dict(lvl=C, ass=J, item='skill_语言', vs='分档(口语/书面)',
                             ev='一面', miss='未知', reqs=['REQ-H-LANG-EN'],
                             cond='JD 写了外语要求'),
    'F.CERTIFICATION': dict(lvl=O, ass=J, item='F.3', vs='闭集(证书) + 扫描件',
                            ev='原文(扫描件)', miss='未知',
                            reqs=['REQ-F-TRADE-COMPLIANCE-TRAINING']),
    # ── C6 其他
    'F.CLEARANCE': dict(lvl=O, ass=J, item='G.1', vs='布尔 + 背调附件', ev='背调', miss='未知',
                        reqs=['REQ-G-NO-CRIMINAL-RECORD'], sec='C6'),
    'F.CV_TRAININGS': dict(lvl=O, ass=I, ev='原文', miss='未知'),
    'F.CV_PROJECTS': dict(lvl=O, ass=I, ev='原文', miss='未知'),
}

# 每个字段一句话：**这家公司为什么需要它**。JD 侧与 CV 侧分开写 —— 同一个 id
# 在两侧是两件事（JD 是门槛，CV 是值），共用一句注释就必然写错一侧。
WHY_JD: dict[str, str] = {
    'F.JOB_TITLE': '对外的岗位名称；客户原文名称另存，否则改一次名就查不到历史',
    'F.MGMT_CATEGORY': '经理岗/员工岗决定用哪套条件字段。**不许按岗位名猜** —— 客户原文可能写「直接下属：无」',
    'F.DEPARTMENT': '线束厂按 生产/品质/工程/业务/关务/行政 分部门，招聘与考核都按部门走',
    'F.REPORTS_TO': '家族式工厂里"向谁汇报"直接决定权限，客户 JD 全写',
    'F.SUPERVISES': '顺带吸收原「管理幅度」（几个下属、什么层级一条写清），不再单列',
    'F.JD_JOB_GRADE': '职级（主管/经理/总监）内部用：定薪与审批链靠它，不对外发布',
    'F.JD_JOB_PURPOSE': '一句话说清为什么设这个岗：业务的判断依据，客户常漏写',
    'F.JD_SUCCESS_CRITERIA': '3~5 条可量化指标：试用期考核与「优先条件」的来源。**不进判定**',
    'F.AGE': '车间与外贸岗都写年龄区间；判定读 A.2，缺了记「未知」不是「不合格」',
    'F.GENDER': '只有法律依据或岗位客观必要（涉密、更衣）时才填；留空=不筛。**不许默认筛性别**',
    'F.EDU_LEVEL': '客户必写；B.1 是闸门之一，按等级顺序比（≥）',
    'F.EDU_MAJOR': '机械/电子/国贸/物流：必须写明是枚举还是「等」开区间 —— 按闭集判会误杀（DEF-04）',
    'F.EDU_FULLTIME': '客户会写「全日制」；简历几乎不写 → 靠一面问，缺了记「未知」',
    'F.EXP_YEARS': '总年限：客户常写；技能年限（"5 年线束经验"）落成领域年限，见 EXP_DOMAIN',
    'F.EXP_DOMAIN': '领域限定（线束/连接器/汽车零部件）；简历常读不出 → 一面问。行业(C.3)并入此条判定',
    'F.SKILL': '硬能力全靠它：值域 = component_catalog 的 54 个组件（8D/CPK/客户验厂/CAD/ERP…），'
               '每条带 evidence_role(hard/soft)。软件与设备都是它的子类，不再单列',
    'F.CERTIFICATION': '报关员证 / 叉车证 / IATF 内审员证：特定岗位的硬门槛（F.3）',
    'F.LANGUAGE_LEVEL': '外贸与关务岗：**口语与书面分开评**（客户常写「口语熟练 + 能独立写 8D」，是两件事）',
    'F.COMPETENCY': '沟通/抗压/责任心：**没有任何数据项**，对所有人「不可判」，不许拿来淘汰人',
    'F.JD_DUTY_ITEMS': '逐条职责（含可选的能力映射与权重）：用来核经历是否对得上，不进判定。'
                       '原「职责权重」「职责对应能力」折进这里',
    'F.DECISION_AUTHORITY': '经理岗：能不能拍板放行/停线/降价 —— 工厂里这条比职级更能说明权限',
    'F.BUDGET_OWNERSHIP': '经理岗：管多少预算/成本中心（品质成本、部门费用）',
    'F.CROSS_DEPT': '经理岗：与生产/工程/客户/供应商的接口，跨部门推不动的人干不了这岗',
    'F.JD_ACTIVITY_TEXT': '作业明细：这家厂的 JD 是"按事写"的，工序/动作能直接对上岗位',
    'F.JD_ACTIVITY_FREQ': '频次（日/周/月/年/偶发）：判断这岗是常态岗还是项目岗',
    'F.SHIFT': '一线岗必填：两班倒/三班倒/常白班 + 工时；原「工时」「排期交接」并入',
    'F.JD_ENVIRONMENT': '一线岗必填：温度/噪音/粉尘，线束加工的溶剂与胶水环境',
    'F.JD_PHYSICAL_DEMAND': '一线岗必填：站立、搬运重量、视力要求（细线径压接靠眼力）',
    'F.JD_PPE': '一线岗必填：劳保配置（手套/护目镜/防静电/耳塞），招人要先说清',
    'F.JD_WORK_LOCATION': '厂区/车间：客户 10 份 JD 全没写，但发布与通勤判断都要它 → 定稿必须补',
    'F.JD_HEADCOUNT': '编制/招聘人数：决定这轮是"补一个人"还是"开新线"，影响放宽与否',
    'F.AVAILABILITY': '到岗周期（A.3）是 HR 闸门：线上一停线就是钱，一周 vs 一个月区别很大',
    'F.SALARY': '薪资区间（K）与预算上限（A.5）：客户常不给 → 该条记「不可判」，'
                '**不许拿候选人期望当门槛**',
    'F.AVG_TENURE': '平均在职不低于：制造业流动率高，这条挡掉"一年换三家"（HR 闸门）',
    'F.RECENT_SEGMENTS': '近 5 年任职段数上限：与平均在职互补，看得出频繁跳槽（HR 闸门）',
    'F.COMMUTE': '可接受通勤（单程分钟/班车）：东莞厂区离镇中心远，通勤是真实门槛（HR 闸门）',
    'F.JD_HIRING_REASON': '新增/替补/储备：替补可以放宽年限，新增要看编制与预算',
    'F.CLEARANCE': '无犯罪/学历真伪：简历不写、一面也不该问 → 入职前背调，在此之前一律「未知」',
    'F.JD_CONFIDENTIALITY': '涉密岗：客户图纸与配方保密；原「竞业限制」并入',
    'F.JD_CONTRACT_TYPE': '全职/兼职/实习 + 合同期：与候选人求职类型对得上才谈得下去',
}

WHY_CV: dict[str, str] = {
    'F.CV_FULL_NAME': '简历表头；展示名与法律名分开（270 份的展示名是伪造的，basis=fabricated）',
    'F.GENDER': '简历常写；只做记录与数据校验，判定只在 JD 明确要求时才用',
    'F.AGE': '年龄与出生年月两口径必须自洽，缺了由另一口径推',
    'F.CV_PHONE': '约一面靠它；缺电话的简历等于联系不上',
    'F.CV_EMAIL': '比电话更常写，投递渠道回执也用它',
    'F.WORK_LOCATION': '现居地：通勤判断的输入之一（另一输入是一面问到的接受度）',
    'F.JOB_TITLE': '意向职位：与 JD 岗位名**不同一条信息**，不可比（compare=not_comparable）',
    'F.SALARY': '期望薪资：判定读的是**数值上限**，不是「8-12K」这段文本',
    'F.AVAILABILITY': '到岗周期：HR 闸门 A.3 的供给侧来源',
    'F.COMMUTE': '简历里永远没有 → 一面必问（到厂单程多久、能否接受两班倒、有没有班车）',
    'F.CLEARANCE': '入职前背调（无犯罪/学历真伪）；在此之前一律「未知」，**不许**当「不满足」',
    'F.EDU_LEVEL': 'B.1 闸门的供给侧来源（education_rank 归一化后比）',
    'F.EDU_MAJOR': 'B.2 闸门：专业全称保留原文再归一',
    'F.EDU_FULLTIME': '简历几乎不写全日制 → 一面必问；客户写了这条门槛时，不问就永远「未知」',
    'F.CV_INSTITUTION': '判定不用，核学历真伪要看（与起止、全日制互证）',
    'F.CV_EMPLOYER': '下面几个 C 类字段都从每段的起止算出来',
    'F.EXP_YEARS': '自述年限：判定读 C.1，但要与逐段累加对账（见 YEARS_COMPUTED）',
    'F.YEARS_COMPUTED': '由每段起止累加：与自述差得多的要问 —— 自述常把"在校实习"也算进去',
    'F.AVG_TENURE': '逐段算平均在职：C.4 闸门的供给侧来源，制造业看稳定性第一眼就是它',
    'F.RECENT_SEGMENTS': '逐段数近 5 年段数：C.7 闸门的供给侧来源',
    'F.EXP_DOMAIN': '能读出的职能域：读不出的靠一面问（C.2）',
    'F.SKILL': '每条要带引文与 hard/soft 证据档，否则「满足」只是自述',
    'F.LANGUAGE_LEVEL': '简历几乎不写熟练度 → 一面现场测（外贸岗给一段英文邮件让他改/写）',
    'F.CERTIFICATION': 'F.3 闸门：要扫描件不要自述',
    'F.CV_TRAININGS': '写 8D/内审/报关培训：客户写"受过 XX 培训"时靠它对',
    'F.CV_PROJECTS': '专案工程师岗（NPI/自动化）主要看这段',
}

# 没进模板的字段，逐条写明去哪了 —— 不然下一个人会以为是漏了。
# **按侧分开**：JD 侧删文档控制，CV 侧删的是"问了也不用"的信息，两份清单不该一样。
DROPPED_JD: list[tuple[str, str]] = [
    ('F.JD_PAGE_COUNT', '文档控制：属于表单规范，不是岗位信息'),
    ('F.JD_APPROVERS', '文档控制：核准/审核/制订是签核流，招聘里由审批链代替'),
    ('F.JD_DOC_NUMBER / F.JD_VERSION / F.JD_FIRST_ISSUED / F.JD_REVISION_HISTORY',
     '文档控制全套：版本历史不随招聘走'),
    ('F.JD_OCCUPATION_CODE', '《职业分类大典》编码：对外发布用，判定与招聘流程都不用'),
    ('F.JD_DUTY_WEIGHT', '折进 F.JD_DUTY_ITEMS（权重是职责行的一个属性）'),
    ('F.JD_DUTY_COMPETENCY', '折进 F.JD_DUTY_ITEMS（映射是职责行的可选列）'),
    ('F.MGMT_SPAN', '折进 F.SUPERVISES（管理幅度就是"直接下属几人、什么层级"）'),
    ('F.SHIFT_HANDOVER', '折进 F.SHIFT（排期与交接属于班制）'),
    ('F.JD_WORK_HOURS', '折进 F.SHIFT（工时是班制的一部分）'),
    ('F.TEAM_GOAL', '折进 F.JD_SUCCESS_CRITERIA（部门目标要落成可量化指标才有用）'),
    ('F.EXP_ACTIVITY', '活动经验：校园/社团活动，这 5 个岗位都不据此判定'),
    ('F.EXP_INDUSTRY', '行业并入 F.EXP_DOMAIN：客户写"线束行业 5 年"是一条要求不是两条'),
    ('F.JD_CLEAN_RECORD', '与 F.CLEARANCE 重复，保留后者（CV 侧同名同义，两侧可比）'),
    ('F.JD_NON_COMPETE', '折进 F.JD_CONFIDENTIALITY（竞业与保密同一份协议谈）'),
    ('F.JD_PROBATION / F.JD_SOCIAL_INSURANCE', '劳动合同条款，不是岗位说明书内容'),
    ('F.JD_DATE_POSTED / F.JD_VALID_UNTIL', '发布渠道里填（招聘平台有时间字段），不进说明书'),
    ('F.JD_POSTING_CHANNEL', '发布动作，不是岗位信息'),
    ('F.JD_TRAVEL', '招聘启事的话术，不是判定数据 → 需要时按岗位补'),
    ('F.JD_ACTIVITY_SEQ / _DURATION / _FORM / _SOP / _AI_FIT',
     '作业明细的列：按需在明细表里带，不单列成模板字段'),
]

DROPPED_CV: list[tuple[str, str]] = [
    ('F.CV_BIRTH_DATE', '折进 F.AGE（两个口径必须自洽，同一条信息不占两行）'),
    ('F.CV_LANGUAGE', '与 F.LANGUAGE_LEVEL 重复（后者分档更细）'),
    ('F.CV_EDU_PERIOD', '起止折进 F.CV_INSTITUTION（院校/起止一起核）'),
    ('F.CV_MARITAL_STATUS', '不作任何判定依据，婚姻状况还有歧视风险'),
    ('F.CV_NATIVE_PLACE', '不作判定依据；户籍/籍贯不能当筛选条件'),
    ('F.CV_CURRENT_SALARY', '只有 5/270 写，且属于谈薪信息，不是筛选数据'),
    ('F.CV_JOB_TYPE', '求职类型：与 JD 用工类型比对价值低，判定不用'),
    ('F.EXP_ACTIVITY', '活动经验：简历侧同样不据此判定'),
    ('F.EXP_INDUSTRY', '简历 0/270 写行业；判定读的 C.3 并入 F.EXP_DOMAIN'),
    ('F.COMPETENCY', '素质类没有数据项：CV 上不设字段，JD 侧保留一行以示"列名但不判"'),
]


# field_schema 里登记错的少数几处：抄下来就等于把错的一起继承，所以显式覆盖 + 留痕。
# 只允许覆盖**推导性**字段（compare / 形状），id 与中文名一律不许覆盖（ST-G10 核）。
COMPARE_OVERRIDES: dict[tuple[str, str], tuple[str, str]] = {
    ('jd', 'F.AVAILABILITY'): (
        'both',
        'A.3 是判定数据项：JD 侧填的是门槛（周数上限），CV 侧填的是值（notice_weeks），'
        '两侧本来就可比；field_schema 标 cv_only 是登记错误'),
}


def load_schema() -> tuple[dict, dict]:
    fs = yaml.safe_load(SCHEMA.read_text(encoding='utf-8')) or {}
    rows = fs['fields'] if isinstance(fs.get('fields'), list) else list(fs['fields'].values())
    return fs, {f['id']: f for f in rows}


def _labels_en() -> dict:
    if not LABELS_EN.is_file():
        return {}
    return (yaml.safe_load(LABELS_EN.read_text(encoding='utf-8')) or {}).get('fields') or {}


def build_rows(which: str, schema_by_id: dict, en: dict) -> tuple[list[dict], list[dict]]:
    """返回 (段列表, 未分段的字段行)。字段的 label / 段 / 维度 / prop 一律取自 field_schema。"""
    sel = JD_FIELDS if which == 'jd' else CV_FIELDS
    secs: dict[str, list] = {}
    order: list[str] = []
    for code, spec in sel.items():
        src = schema_by_id.get(code)
        if src is None:
            if not spec.get('new'):
                raise SystemExit(f'{which}: {code} 不在 field_schema 里，又不标 new=True —— '
                                 f'模板不许自造 id')
            blk = {'section': None}
            label = NEW_LABELS[code][which]['zh']
            label_en = NEW_LABELS[code][which]['en']
            dim = None
            prop = None
            compare = 'both'
        else:
            blk = src.get(which) or {}
            if not blk:
                # id 在 field_schema 里登记过（但只在另一侧）—— 标签必须沿用，
                # 段号由本模板指定：这是"两侧同一条信息"的补登，不是新造字段。
                new_side = True
            label = src.get('label') or code
            label_en = en.get(code)
            dim = src.get('dimension')
            prop = (src.get('cv') or {}).get('prop')
            compare = spec.get('compare', src.get('compare'))
            ov = COMPARE_OVERRIDES.get((which, code))
            if ov:
                compare = ov[0]
        sec = spec.get('sec') or blk.get('section') or ('S7' if which == 'jd' else 'C6')
        if sec not in secs:
            secs[sec] = []
            order.append(sec)
        row = {
            'code': code,
            'label_zh': label,
            'label_en': label_en or label,
            'section': sec,
            'dimension': dim,
            'prop': prop if which == 'cv' else None,
            'data_item': spec.get('item'),
            'assessable': spec['ass'],
            'threshold_shape': spec.get('shape'),
            'value_shape': spec.get('vs'),
            'evidence_required': spec.get('ev'),
            'missing_means': spec.get('miss'),
            'source_requirement': list(spec.get('reqs') or []),
            'requirement_level': spec['lvl'],
            'conditional_on': spec.get('cond'),
            'origin': spec.get('origin'),
            'compare': compare,
            'in_field_schema': src is not None,
            'new_in_standard': bool(spec.get('new')),
            'why': (WHY_CV if which == 'cv' else WHY_JD).get(code, ''),
            'presence': (src.get(which) or {}).get('presence') if src is not None else None,
            'population': (10 if which == 'jd' else 270),
            'note': spec.get('note'),
        }
        row['compare_override'] = (COMPARE_OVERRIDES[(which, code)][1]
                                   if (which, code) in COMPARE_OVERRIDES else None)
        row['cross_side'] = src is not None and not src.get(which)
        if row['cross_side']:
            row['new_in_standard'] = True
        secs[sec].append(row)
    return [(s, secs[s]) for s in order], []


# 新增字段（field_schema 里没有）：**只加判定真正要读、而现有字段问不出来的**。
NEW_LABELS = {
    'F.AVG_TENURE': {'jd': {'zh': '平均在职不低于', 'en': 'Average tenure at least'},
                     'cv': {'zh': '平均在职年限', 'en': 'Average tenure (years)'}},
    'F.RECENT_SEGMENTS': {'jd': {'zh': '近 5 年任职不超过', 'en': 'Recent-5y job changes at most'},
                          'cv': {'zh': '近 5 年任职段数', 'en': 'Segments in last 5 years'}},
    'F.COMMUTE': {'jd': {'zh': '可接受通勤', 'en': 'Commute acceptable'},
                  'cv': {'zh': '通勤可接受', 'en': 'Commute acceptable'}},
    'F.YEARS_COMPUTED': {'jd': {'zh': '累计年限', 'en': 'Computed years'},
                         'cv': {'zh': '累计年限（逐段）', 'en': 'Computed years'}},
}


def _esc(v) -> str:
    s = str(v)
    if s == '' or s in ('null', 'None'):
        return 'null'
    if any(ch in s for ch in ':#[]{}\'"') or s.lower() in ('true', 'false', 'yes', 'no', 'on', 'off') \
            or s.strip() != s or s.startswith(('-', '*', '&', '!', '|', '>', '@', '`')):
        return "'" + s.replace("'", "''") + "'"
    return s


def _wrap_comment(text: str, prefix: str, width: int = 96) -> list[str]:
    out, line = [], prefix
    for ch in text:
        line += ch
        if len(line) >= width and ch in '，。；、）':
            out.append(line)
            line = prefix
    if line.strip() and line != prefix:
        out.append(line)
    return out


def emit(which: str, sections: list[tuple[str, list[dict]]], fs: dict) -> str:
    sec_label = (fs.get('sections') or {}).get(which) or {}
    n = sum(len(f) for _, f in sections)
    lv = {k: sum(1 for _, f in sections for r in f if r['requirement_level'] == k)
          for k in ('required', 'conditional', 'optional')}
    L: list[str] = []
    A = L.append
    title = 'JD（职务说明书）' if which == 'jd' else 'CV（候选人档案）'
    A(f'# 公司标准 {title}模板 —— 由 backend/scripts/talent/build_templates.py 生成，不要手改。')
    A('#')
    A('# 两条建法原则：')
    A('#   ① 以 work/talent/field_schema.yaml 为底座：字段 id / 中文名 / 段号 / 维度一律从那里读，'
      '本文件不另起词表。')
    A('#   ② 支撑本体推理：每个可判字段都带 data_item（A/B/C/F/G 或 skill_*），也就是'
      ' requirement_library 里真正被判的那个位置；')
    A('#      能判的要求如果在模板里没有落脚字段，这条要求就永远只能是「未知」'
      '（不是候选人没有，是我们没问）。')
    A('#')
    A('# 模板**不必**包含 field_schema 的全部字段：那 66/31 个是"客户实际出现过什么"，'
      '混着文档控制与一次性的填报口径。')
    A('# 取舍按这家公司的实务：线束/连接器制造、东莞厂区、出口客户 —— 一线岗写班制/环境/体力/劳保，')
    A('# 经理岗写决策/预算/跨部门，外贸与关务写分档语言与证照，HR 写闸门（到岗/薪资/通勤/稳定性）。')
    A('#')
    A('# 行注释写在每个字段上方：为什么这家公司需要它、客户 10 份 JD / 270 份简历里出现几次；')
    A('# note 写操作口径（怎么填、缺了算「未知」还是「不可判」）。')
    A('')
    A('version: 2')
    A(f"field_count_target: {n}")
    A(f"levels: {{required: {lv['required']}, conditional: {lv['conditional']}, "
      f"optional: {lv['optional']}}}")
    A("principles: ['based on field_schema', 'support ontology reasoning']")
    A('sections:')
    for code, rows in sections:
        label = sec_label.get(code, code)
        A(f'  # ── {code} · {label}（{len(rows)} 字段）')
        A(f'  - code: {code}')
        A(f'    label_zh: {_esc(label)}')
        if rows and rows[0].get('section_label_en'):
            A(f"    label_en: {_esc(rows[0]['section_label_en'])}")
        A('    fields:')
        for r in rows:
            why = (r.get('why') or '').strip()
            A('')
            if r.get('cross_side'):
                head = (f"[field_schema·跨侧] 这个 id 在 field_schema 里只有 "
                        f"{'JD' if which == 'cv' else 'CV'} 侧登记，"
                        f"因为 data_item {r['data_item']} 判定要读，本模板在"
                        f"{'CV' if which == 'cv' else 'JD'}侧补一条落脚字段（名字沿用，不另起）。")
            elif r['new_in_standard']:
                head = (f"[新增·推理所需] field_schema 里没有这个字段，但 data_item {r['data_item']} "
                        f"判定要读。")
            elif r.get('presence') is not None:
                pop = '客户 10 份 JD' if r['population'] == 10 else '270 份简历'
                head = f"[field_schema] {pop}：出现 {r['presence']}/{r['population']} 次。"
            else:
                head = '[field_schema]'
            L.extend(_wrap_comment((head + why).strip(), '      # '))
            if r.get('compare_override'):
                L.extend(_wrap_comment('[覆盖 field_schema] ' + r['compare_override'], '      # '))
            A(f"      - code: {r['code']}")
            A(f"        label_zh: {_esc(r['label_zh'])}")
            A(f"        label_en: {_esc(r['label_en'])}")
            if r['dimension']:
                A(f"        dimension: {r['dimension']}")
            if r['prop']:
                A(f"        prop: {r['prop']}")
            A(f"        data_item: {_esc(r['data_item']) if r['data_item'] else 'null'}")
            A(f"        assessable: {r['assessable']}")
            if r['threshold_shape']:
                A(f"        threshold_shape: {_esc(r['threshold_shape'])}")
            if r['value_shape']:
                A(f"        value_shape: {_esc(r['value_shape'])}")
            if r['evidence_required']:
                A(f"        evidence_required: {_esc(r['evidence_required'])}")
            if r['missing_means']:
                A(f"        missing_means: {_esc(r['missing_means'])}")
            if r['source_requirement']:
                A('        source_requirement:')
                for rid in r['source_requirement']:
                    A(f'        - {rid}')
            A(f"        requirement_level: {r['requirement_level']}")
            if r['conditional_on']:
                A(f"        conditional_on: {_esc(r['conditional_on'])}")
            if r['origin']:
                A(f"        origin: {r['origin']}")
            if r['compare']:
                A(f"        compare: {r['compare']}")
            A(f"        in_field_schema: {'true' if r['in_field_schema'] else 'false'}")
            if r['new_in_standard']:
                A('        new_in_standard: true')
            if r['note']:
                A(f"        note: {_esc(r['note'])}")
    A('')
    A('# ── 没进模板的字段，逐条写明去哪了（防止下次有人以为是漏了）')
    A('dropped:')
    for code, why in (DROPPED_JD if which == 'jd' else DROPPED_CV):
        A(f'  - code: {_esc(code)}')
        A(f"    why: {_esc(why)}")
    A('')
    return '\n'.join(L)


NOTES = {
    'F.GENDER': '除非有法律依据或岗位客观必要（涉密/更衣），否则留空 —— 留空=不筛',
    'F.EDU_MAJOR': '必须写明是枚举还是开区间：客户写「机械工程等」按闭集判会误杀（DEF-04，故意不过闸）',
    'F.CLEARANCE': '入职前背调；在此之前一律「未知」。**不许**在判定里当「不满足」',
    'F.SALARY': '客户没给预算 → 这条「不可判」，不许拿候选人的期望薪资当门槛',
    'F.COMPETENCY': '沟通/抗压/责任心：没有任何数据项，对所有人「不可判」，不许拿来淘汰人',
    'F.JD_DUTY_ITEMS': '原「职责权重」「职责对应能力」折进这里；职责不进判定，只用来核经历',
    'F.SHIFT': '两班倒/三班倒/常白班 + 工时；原「排期交接」并入',
    'F.EDU_FULLTIME': '简历 0/270 写 → 一面必须问；客户写了这条，不问就永远是「未知」',
    'F.YEARS_COMPUTED': '由工作段起止累加，未必等于自述；两个口径都要露，差太多要问',
    'F.COMMUTE': '一面问「到厂单程多久、能否接受两班倒、有没有班车」——简历里没有',
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='只校验是否最新（门禁用）')
    args = ap.parse_args()

    fs, by_id = load_schema()
    en = _labels_en()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    texts: dict[str, str] = {}
    for which in ('jd', 'cv'):
        sections, _ = build_rows(which, by_id, en)
        for _, rows in sections:
            for r in rows:
                r['note'] = NOTES.get(r['code']) or r['note']
        texts[which] = emit(which, sections, fs)
        # 自检：写出来的必须能被解析回同一份数据（注释不许把结构带坏）
        back = yaml.safe_load(texts[which]) or {}
        codes_back = [f['code'] for s in back.get('sections') or [] for f in s['fields']]
        codes_fwd = [r['code'] for _, rows in sections for r in rows]
        assert codes_back == codes_fwd, f'{which}: 回读字段顺序/内容不一致'
        # label 与段号必须与 field_schema 逐字相同（这就是"基于 field_schema"）
        for r in [x for _, rows in sections for x in rows]:
            if r['in_field_schema']:
                src = by_id[r['code']]
                assert src.get('label') == r['label_zh'], \
                    f"{which}/{r['code']}: label 与 field_schema 不一致 " \
                    f"({src.get('label')!r} vs {r['label_zh']!r})"
                if src.get(which):
                    assert src[which].get('section') == r['section'], \
                        f"{which}/{r['code']}: 段号与 field_schema 不一致"
            else:
                assert r['new_in_standard'], f'{which}/{r["code"]}: 不在 field_schema 又不标新增'

    if args.check:
        same = all(DEST[w].is_file() and DEST[w].read_text(encoding='utf-8').strip() == texts[w].strip()
                   for w in DEST)
        print('模板是最新的' if same else '模板已过期 —— 重跑 build_templates')
        return 0 if same else 1

    for w, p in DEST.items():
        p.write_text(texts[w], encoding='utf-8')
    for w in ('jd', 'cv'):
        d = yaml.safe_load(texts[w])
        rows = [f for s in d['sections'] for f in s['fields']]
        lv = d['levels']
        judged = sum(1 for r in rows if r['assessable'] == J)
        fs_n = sum(1 for r in rows if r['in_field_schema'])
        new_n = sum(1 for r in rows if r.get('new_in_standard'))
        print(f"{w.upper()} 模板 {len(rows)} 字段 · 必需 {lv['required']} / 条件 "
              f"{lv['conditional']} / 可选 {lv['optional']} · {len(d['sections'])} 段 · "
              f"可判 {judged} · 取自 field_schema {fs_n} · 新增 {new_n}")
        print(f'  → {DEST[w].relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
