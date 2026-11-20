r"""从 JD 证据里长出来的技能抽取模式 —— **扩展层，不改动 `parse.py` 的生产词表**。

为什么单独一个模块：`parse.py:SKILL_PATTERNS` 是 29 条手写正则，实测对 10 份 JD 的 44 个
要求词只覆盖 6 个（14%）。这份文件补上缺的，**每一条都带着它在 JD 里的原话**——没有出处的
模式不许进来（见 `work/talent/component_catalog.yaml` 的规矩、`grill.md` 的"先抽取、后概括"）。
旧的 `work/talent/skill_map.yaml` 已于 2026-11-20 删除 —— 零消费者、且在 HEAD 里就是坏 YAML，退役说明与它独有的 22 个词见 `work/talent/_retired/README.md`。

为什么先不并进生产：一旦并进 `parse.py`，`talent_v1` 的 ABox 全部要重建、`candidate_skill`
换一套、`check_abox_sync` 立刻变红。先用探针证明它值得，再谈采纳。

每条的结构：
    (canonical, category, pattern, evidence)
      canonical —— 技能规范名，`skill_` 前缀由调用方补（与库里现有一致）
      category  —— 所属类别（须是本体的一个类，见 talent_v1/reasoning.ttl）
      pattern   —— 容忍 OCR 噪声的正则
      evidence  —— (JD 文件名, 原话)。**这是它进表的唯一理由。**

OCR 的真实噪声（本语料实测）：`Solidworks`→`Solitvedks`、`coreldraw`→`cone\w*dw`、
中英混排、全角括号、技能之间用"、"或"/"分隔。所以模式一律 case-insensitive、
允许中间夹空格、对易混字符用字符组。
"""
from __future__ import annotations

#: (canonical, category, pattern, (jd, quote))
EXTENDED_SKILL_PATTERNS: list[tuple[str, str, str, tuple[str, str]]] = [
    # ── 质量体系（解开"品质经理恒为 0"的关键，JD 里最硬的一类） ──────────────
    ("QC七大手法", "QualityMethod", r"qc\s*七|七大手法|品管七大手法|qc七大",
     ("12.品质经理职务说明书", "懂QC七大手法、5WHY、SPC、CPK、6S工具")),
    ("5WHY", "QualityMethod", r"5\s*why|五问|五个为什么|why\s*why",
     ("12.品质经理职务说明书", "懂QC七大手法、5WHY、SPC、CPK、6S工具")),
    ("SPC", "QualityMethod", r"(?<![a-z0-9])spc(?![a-z0-9])|统计过程控制",
     ("12.品质经理职务说明书", "懂QC七大手法、5WHY、SPC、CPK、6S工具")),
    ("CPK", "QualityMethod", r"(?<![a-z0-9])cpk(?![a-z0-9])|(?<![a-z0-9])cp(?![a-z0-9])|工序能力|过程能力",
     ("12.品质经理职务说明书", "懂QC七大手法、5WHY、SPC、CPK、6S工具")),
    ("6S", "QualityMethod", r"(?<![a-z0-9])[56]s(?![a-z0-9])|六s|五s|７s|６s|５s",
     ("12.品质经理职务说明书", "…CPK、6S工具")),
    ("8D报告", "QualityMethod", r"8\s*d(?![a-z0-9])|八d|eight\s*disciplines|纠正预防|客诉处理",
     ("12.品质经理职务说明书", "具备独立书写英文8D报告的能力")),
    ("FMEA", "QualityMethod", r"(?<![a-z0-9])[pd]?fmea(?![a-z0-9])|失效模式",
     ("专案工程师职务说明书", "主导PFMEA研讨会议。并整理修订")),
    ("客户验厂", "QualityMethod", r"验厂|客户审核|供应商稽核|audit\s*客户",
     ("12.品质经理职务说明书", "具备接待客户验厂经验")),
    ("品质问题分析", "QualityMethod", r"品质问题|质量异常|不良分析|客诉|投诉处理|持续改善|8d分析",
     ("12.品质经理职务说明书", "具备品质问题分析、改善的能力")),

    # ── 线束/连接器工艺（客户口中的"懂行"） ────────────────────────────────
    ("线束行业知识", "HarnessCraft", r"线束|连接器|wire\s*harness|connector|端子线|排线",
     ("12.品质经理职务说明书", "3年以上品质管理工作经验，熟识线束行业相关产品")),
    ("识图", "HarnessCraft",
     r"识图|看图纸|图纸信息|线材规格|端子型号|胶壳料号|回路标识|图纸材质|线径",
     ("工程文员职务说明书", "能识别图纸基本信息：线材规格、端子型号、胶壳料号、回路标识等")),
    ("端子", "HarnessCraft", r"端子|terminal|端子机|压接|铆压|crimp",
     ("专案工程师职务说明书", "负责将未制作铆压标准的端子进行样品及切片安排")),
    ("切片", "HarnessCraft", r"切片|金相|microsection|研磨",
     ("专案工程师职务说明书", "…端子进行样品及切片安排")),

    # ── 设备操作（O*NET 的 Tools & Technology，不是 Skills） ────────────────
    ("裁线机", "WireEquipment", r"裁线机|裁线|剥线机|cut(?:ting)?\s*machine",
     ("专案工程师职务说明书", "对电线加工设备：裁线机、端子机…功能熟知并有一定的操作能力")),
    ("端子机", "WireEquipment", r"端子机|压着机|压端机|crimp(?:ing)?\s*machine|terminal\s*machine",
     ("专案工程师职务说明书", "对电线加工设备：…端子机…功能熟知")),
    ("自动机", "WireEquipment", r"自动机|自动化设备|auto\s*machine|组装机",
     ("专案工程师职务说明书", "对电线加工设备：…自动机…功能熟知")),
    ("注塑机", "WireEquipment", r"注塑机|射出机|injection\s*mold|成型机",
     ("专案工程师职务说明书", "对电线加工设备：…注塑机…功能熟知")),
    ("点胶机", "WireEquipment", r"点胶机|灌胶机|dispens(?:ing)?\s*machine|涂胶",
     ("专案工程师职务说明书", "对电线加工设备：…点胶机…功能熟知")),

    # ── 通用能力 / 职能 ───────────────────────────────────────────────────
    ("数据分析", "GeneralCapability",
     r"数据分析|统计分析|数据分[析据]|数据敏感|数据处理|报表分析|excel\s*数据",
     ("人资专员-职务说明书", "具备很好的数据统计分析能力")),
    ("订单交期风险评估", "GeneralCapability",
     r"交期(?:风险)?评估|交期管理|交付风险|排程|生管|物控|mc\b|生产计划",
     ("2. 业务跟单职务说明书", "具备订单交期风险评估能力")),
    ("体系管理", "GeneralCapability",
     r"体系管理|iso\s*体系|质量体系|管理体系建设|推行体系",
     ("管理课长职务说明书", "…体系管理能力、系统规划能力…")),
    ("培训课程开发", "GeneralCapability",
     r"培训(?:课程)?开发|课程设计|内部讲师|培训体系|课件",
     ("管理课长职务说明书", "…培训课程开发能力…")),
    ("系统规划", "GeneralCapability",
     r"系统规划|流程规划|制度建设|规章|标准化",
     ("管理课长职务说明书", "…系统规划能力…")),
    ("企业文化建设", "GeneralCapability",
     r"企业文化|员工关系|团队建设|组织氛围",
     ("管理课长职务说明书", "…企业文化建设能力")),
    ("社保操作", "HRAdmin",
     r"社保|社会保险|增员|减员|补缴|公积金|考勤核算",
     ("人资专员-职务说明书", "熟悉社会保险（增/减/补缴）等操作流程")),

    # ── 合规（不可评，但必须能识别出来并标记为"需证明文件"） ──────────────
    ("贸易安全合规", "Compliance",
     r"贸易安全|合规培训|海关处罚|aEO|认证经营者|无犯罪",
     ("关务报关员职务说明书", "通过基础贸易安全合规培训考核，无海关行政处罚、犯罪记录")),
]

#: 这些类别落进"不可评"——识别出来只用于标记，不参与计分
NON_ASSESSABLE_CATEGORIES = {"Compliance", "SoftSkill"}
