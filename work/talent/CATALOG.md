# 标准目录 · 分类 / 组件 / JD 模板 / CV 模板

> 数字由 `scripts/talent/build_catalog.py` 从三份 YAML 与五份 `jd_links` 现算，不手写。
> 分类 **22** · 组件 **54** · 要求 **61** · 标准模板 **JD 40 / CV 26** 字段（客户实际字段 JD 66 / CV 31）。

两套模板是**两件事**：`templates/standard_*` 是公司标准（应该长什么样，字段取自 `field_schema`、按这家公司实务取舍，并支撑本体推理）；`field_schema` 是客户实际（10 份 JD / 270 份简历里真长什么样）。

> **缺口不在这份目录里**：某份 JD「还缺哪几格」是下一阶段的事 —— 在 Talent 左栏选一份 JD，打开「0 JD · 原文与缺口」看（`jd_draft/` 与 `template_fill/` 是它的原料）。标准目录只负责"标准长什么样"。

## 目录自身的完整性（这里不看 JD/CV 缺口，那是下一层）

| 缺口 | 数量 | 影响 |
|---|---|---|
| 组件**没标证据档** | **39** | 能力「满足」里有多少只是自述，答不出来 |
| 要求**没有被任何 JD 引用** | **19** | 标准建了没人用，要留还是删 |
| 组件**没有被任何要求挂** | **31** | 抽得出、判不到 |
| 要求**不可判**（assessable=false） | **27** | 对所有人一样，不能拿来淘汰人 |
| 可判要求**没落到标准模板** | **0** | 判不了：JD 提了要求，简历侧没有落脚字段 |

## 一、分类与组件

### QualityMethod（9）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_5WHY` | 5WHY | capability | **hard** | 0 | 1 | 1 |
| `skill_6S` | 6S | capability | **hard** | 26 | 1 | 1 |
| `skill_8D报告` | 8D报告 | capability | **hard** | 16 | 1 | 1 |
| `skill_CPK` | CPK | capability | **hard** | 5 | 1 | 1 |
| `skill_FMEA` | FMEA | capability | **未声明** | 18 | 0 | 0 |
| `skill_QC七大手法` | QC七大手法 | capability | **hard** | 1 | 1 | 1 |
| `skill_SPC` | SPC | capability | **hard** | 4 | 1 | 1 |
| `skill_品质问题分析` | 品质问题分析 | capability | **soft** | 53 | 1 | 1 |
| `skill_客户验厂` | 客户验厂 | capability | **hard** | 13 | 1 | 1 |

### CAD（6）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_AutoCAD` | AutoCAD | product | **未声明** | 75 | 1 | 1 |
| `skill_CATIA` | CATIA | product | **未声明** | 6 | 0 | 0 |
| `skill_ProE_Creo` | ProE/Creo | product | **未声明** | 21 | 0 | 0 |
| `skill_Rhino` | Rhino | product | **未声明** | 3 | 0 | 0 |
| `skill_SolidWorks` | SolidWorks | product | **未声明** | 19 | 0 | 0 |
| `skill_UG_NX` | UG/NX | product | **未声明** | 2 | 0 | 0 |

### GeneralCapability（6）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_企业文化建设` | 企业文化建设 | capability | **未声明** | 37 | 0 | 0 |
| `skill_体系管理` | 体系管理 | capability | **未声明** | 13 | 0 | 0 |
| `skill_培训课程开发` | 培训课程开发 | capability | **未声明** | 15 | 0 | 0 |
| `skill_数据分析` | 数据分析 | capability | **未声明** | 31 | 0 | 0 |
| `skill_系统规划` | 系统规划 | capability | **未声明** | 64 | 0 | 0 |
| `skill_订单交期风险评估` | 订单交期风险评估 | capability | **soft** | 41 | 1 | 1 |

### WireEquipment（5）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_注塑机` | 注塑机 | equipment | **未声明** | 17 | 1 | 1 |
| `skill_点胶机` | 点胶机 | equipment | **未声明** | 2 | 1 | 1 |
| `skill_端子机` | 端子机 | equipment | **未声明** | 18 | 1 | 1 |
| `skill_自动机` | 自动机 | equipment | **未声明** | 10 | 1 | 1 |
| `skill_裁线机` | 裁线机 | equipment | **未声明** | 17 | 1 | 1 |

### HarnessCraft（4）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_切片` | 切片 | equipment | **未声明** | 4 | 0 | 0 |
| `skill_端子` | 端子 | equipment | **未声明** | 39 | 0 | 0 |
| `skill_线束行业知识` | 线束行业知识 | domain | **soft** | 72 | 1 | 2 |
| `skill_识图` | 识图 | capability | **未声明** | 7 | 0 | 0 |

### DesignSoftware（3）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_CorelDRAW` | CorelDRAW | product | **未声明** | 5 | 0 | 0 |
| `skill_Illustrator` | Illustrator | product | **未声明** | 8 | 0 | 0 |
| `skill_Photoshop` | Photoshop | product | **未声明** | 17 | 0 | 0 |

### BusinessSystem（2）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_ERP` | ERP | product | **hard** | 37 | 2 | 1 |
| `skill_SAP` | SAP | product | **未声明** | 10 | 0 | 0 |

### CustomsSkill（2）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_单证` | 单证 | capability | **未声明** | 13 | 1 | 1 |
| `skill_报关` | 报关 | capability | **未声明** | 26 | 1 | 1 |

### OfficeSoftware（2）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_PowerPoint` | PowerPoint | product | **未声明** | 40 | 1 | 3 |
| `skill_Word` | Word | product | **未声明** | 55 | 1 | 3 |

### OperationsSkill（2）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_5S` | 5S | capability | **未声明** | 5 | 0 | 0 |
| `skill_精益生产` | 精益生产 | capability | **未声明** | 10 | 0 | 0 |

### QualitySystem（2）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_ISO_TS16949` | ISO/TS16949 | capability | **hard** | 21 | 0 | 0 |
| `skill_ISO9001` | ISO9001 | capability | **hard** | 18 | 0 | 0 |

### AdminSkill（1）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_行政` | 行政 | capability | **未声明** | 80 | 0 | 0 |

### CompensationSkill（1）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_薪酬绩效` | 薪酬绩效 | capability | **未声明** | 45 | 0 | 0 |

### Compliance（1）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_贸易安全合规` | 贸易安全合规 | capability | **未声明** | 1 | 0 | 0 |

### FinanceSkill（1）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_财务` | 财务 | capability | **未声明** | 84 | 0 | 0 |

### HRAdmin（1）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_社保操作` | 社保操作 | capability | **未声明** | 24 | 0 | 0 |

### LaborLawKnowledge（1）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_劳动法` | 劳动法 | domain | **未声明** | 22 | 0 | 0 |

### LanguageSkill（1）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_英语` | 英语 | capability | **soft** | 99 | 1 | 1 |

### OrderTracking（1）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_跟单` | 跟单 | capability | **未声明** | 79 | 0 | 0 |

### RecruitingSkill（1）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_招聘` | 招聘 | capability | **未声明** | 60 | 0 | 0 |

### SpreadsheetSoftware（1）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_Excel` | Excel | product | **hard** | 87 | 3 | 4 |

### TradeSkill（1）

| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |
|---|---|---|---|---|---|---|
| `skill_外贸业务` | 外贸业务 | capability | **未声明** | 54 | 0 | 0 |

## 二、组件反查（哪个组件被哪条要求、哪个 JD 用到）

| 组件 | 要求 | JD |
|---|---|---|
| `skill_Excel` Excel | D-ERP-EXCEL、D-OFFICE、D-REPORT-WRITING | 专案工程师、业务跟单、关务报关员、副总助理 |
| `skill_PowerPoint` PowerPoint | D-OFFICE | 专案工程师、关务报关员、副总助理 |
| `skill_Word` Word | D-OFFICE | 专案工程师、关务报关员、副总助理 |
| `skill_线束行业知识` 线束行业知识 | D-HARNESS-DOMAIN | 专案工程师、品质经理 |
| `skill_ERP` ERP | D-ERP-EXCEL、D-ERP-OPERATE | 业务跟单 |
| `skill_5WHY` 5WHY | D-QA-TOOLS | 品质经理 |
| `skill_6S` 6S | D-QA-TOOLS | 品质经理 |
| `skill_8D报告` 8D报告 | H-LANG-EN | 品质经理 |
| `skill_AutoCAD` AutoCAD | D-CAD-2D | 专案工程师 |
| `skill_CPK` CPK | D-QA-TOOLS | 品质经理 |
| `skill_QC七大手法` QC七大手法 | D-QA-TOOLS | 品质经理 |
| `skill_SPC` SPC | D-QA-TOOLS | 品质经理 |
| `skill_单证` 单证 | D-CUSTOMS-DECLARE | 关务报关员 |
| `skill_品质问题分析` 品质问题分析 | D-QA-ANALYSIS | 品质经理 |
| `skill_客户验厂` 客户验厂 | D-CUSTOMER-AUDIT | 品质经理 |
| `skill_报关` 报关 | D-CUSTOMS-DECLARE | 关务报关员 |
| `skill_注塑机` 注塑机 | D-WIRE-EQUIPMENT | 专案工程师 |
| `skill_点胶机` 点胶机 | D-WIRE-EQUIPMENT | 专案工程师 |
| `skill_端子机` 端子机 | D-WIRE-EQUIPMENT | 专案工程师 |
| `skill_自动机` 自动机 | D-WIRE-EQUIPMENT | 专案工程师 |
| `skill_英语` 英语 | H-LANG-EN | 品质经理 |
| `skill_裁线机` 裁线机 | D-WIRE-EQUIPMENT | 专案工程师 |
| `skill_订单交期风险评估` 订单交期风险评估 | D-DELIVERY-RISK | 业务跟单 |

## 三、标准 JD 模板（公司标准 · 40 字段）

职务说明书应该长什么样。共 **40** 字段（必需 23 / 条件 10 / 可选 7）· 目标 40 字段。

> 生成器：`scripts/talent/build_templates.py`。原则：based on field_schema / support ontology reasoning。字段 id 与中文名取自 `field_schema`，每个字段上方的注释写清了"这家公司为什么需要它"与出现次数；没进模板的 **19** 条在文件末尾 `dropped` 里逐条交代去处。

| 段 | 段名 | 字段数 |
|---|---|---|
| S1 | 岗位标识 | 6 |
| S2 | 岗位目的 | 2 |
| S3 | 任职资格 | 11 |
| S4 | 岗位职责 | 4 |
| S5 | 作业明细 | 2 |
| S6 | 工作条件 | 5 |
| S7 | 元数据 | 7 |
| S8 | 合规声明 | 3 |

### S1 · 岗位标识（6）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 门槛形状 | 证据 | 缺了算 | 要求 |
|---|---|---|---|---|---|---|---|---|
| `F.JOB_TITLE` | 职务名称 | required | internal | — | — | — | — | — |
| `F.MGMT_CATEGORY` | 岗位类别 | required | internal | — | — | — | — | — |
| `F.DEPARTMENT` | 隶属部门 | required | internal | — | — | — | — | — |
| `F.REPORTS_TO` | 直接上司 | required | internal | — | — | — | — | — |
| `F.SUPERVISES` | 直接下属 | required | internal | — | — | — | — | — |
| `F.JD_JOB_GRADE` | 职级 | optional | internal | — | — | — | — | — |

### S2 · 岗位目的（2）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 门槛形状 | 证据 | 缺了算 | 要求 |
|---|---|---|---|---|---|---|---|---|
| `F.JD_JOB_PURPOSE` | 岗位目的 | required | not_judgeable | — | — | — | — | — |
| `F.JD_SUCCESS_CRITERIA` | 关键成功指标 | required | not_judgeable | — | — | — | — | — |

### S3 · 任职资格（11）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 门槛形状 | 证据 | 缺了算 | 要求 |
|---|---|---|---|---|---|---|---|---|
| `F.AGE` | 年龄 | required | judgeable | A.2 | 区间(岁) | 原文 | 未知 | A-AGE-RANGE |
| `F.GENDER` | 性别 | optional | judgeable | A.1 | 闭集 | 原文 | 未知 | A-GENDER |
| `F.EDU_LEVEL` | 学历 | required | judgeable | B.1 | 顺序(≥等级) | 原文 | 未知 | B-EDU-LEVEL |
| `F.EDU_MAJOR` | 专业 | required | judgeable | B.2 | 闭集 或 开区间(必须写清"等") | 原文 | 未知 | B-MAJOR |
| `F.EDU_FULLTIME` | 是否全日制 | conditional | judgeable | B.3 | 布尔 | 原文 or 一面 | 未知 | B-FULL-TIME |
| `F.EXP_YEARS` | 总年限 | required | judgeable | C.1 | 区间(年) | 原文 | 未知 | C-YEARS-DOMAIN |
| `F.EXP_DOMAIN` | 职能域 | conditional | judgeable | C.2 | 闭集(领域) | 一面 | 未知 | C-YEARS-DOMAIN、D-HARNESS-DOMAIN |
| `F.SKILL` | 技能 | required | judgeable | skill_* | any_of n / all_of（逐条声明） | 原文 or 一面坐实 | 未知 | D-* |
| `F.CERTIFICATION` | 资格证书 | optional | judgeable | F.3 | 闭集(证书清单) | 原文(扫描件) | 未知 | F-TRADE-COMPLIANCE-TRAINING |
| `F.LANGUAGE_LEVEL` | 语言熟练度 | optional | judgeable | skill_语言 | 分档：口语 / 书面 各一档 | 一面 | 未知 | H-LANG-EN |
| `F.COMPETENCY` | 职业素养 | optional | not_judgeable | — | — | — | 不可判 | E-* |

### S4 · 岗位职责（4）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 门槛形状 | 证据 | 缺了算 | 要求 |
|---|---|---|---|---|---|---|---|---|
| `F.JD_DUTY_ITEMS` | 职责条目 | required | not_judgeable | — | — | — | — | — |
| `F.DECISION_AUTHORITY` | 决策权限 | conditional | internal | — | — | — | — | — |
| `F.BUDGET_OWNERSHIP` | 预算与成本责任 | conditional | internal | — | — | — | — | — |
| `F.CROSS_DEPT` | 跨部门接口 | conditional | internal | — | — | — | — | — |

### S5 · 作业明细（2）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 门槛形状 | 证据 | 缺了算 | 要求 |
|---|---|---|---|---|---|---|---|---|
| `F.JD_ACTIVITY_TEXT` | 内容 | required | not_judgeable | — | — | — | — | — |
| `F.JD_ACTIVITY_FREQ` | 频次(日/周/月/年/偶发) | required | not_judgeable | — | — | — | — | — |

### S6 · 工作条件（5）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 门槛形状 | 证据 | 缺了算 | 要求 |
|---|---|---|---|---|---|---|---|---|
| `F.SHIFT` | 班制 | conditional | internal | — | — | — | — | — |
| `F.JD_ENVIRONMENT` | 环境(噪音/粉尘/温度) | conditional | internal | — | — | — | — | — |
| `F.JD_PHYSICAL_DEMAND` | 体力/站立/搬运 | conditional | internal | — | — | — | — | — |
| `F.JD_PPE` | 劳保/防护 | conditional | internal | — | — | — | — | — |
| `F.JD_WORK_LOCATION` | 工作地点/厂区 | required | internal | — | — | — | — | — |

### S7 · 元数据（7）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 门槛形状 | 证据 | 缺了算 | 要求 |
|---|---|---|---|---|---|---|---|---|
| `F.JD_HEADCOUNT` | 编制/招聘人数 | required | internal | — | — | — | — | — |
| `F.AVAILABILITY` | 到岗日期 | required | judgeable | A.3 | 周数上限 | 一面 | 未知 | HR-NOTICE |
| `F.SALARY` | 薪资 | required | judgeable | A.5 | 区间(K)，判定读上限 | 客户预算 | 不可判 | HR-SALARY |
| `F.AVG_TENURE` 🆕 | 平均在职不低于 | required | judgeable | C.4 | 区间(年) | 推断(逐段累计) | 未知 | HR-TENURE |
| `F.RECENT_SEGMENTS` 🆕 | 近 5 年任职不超过 | required | judgeable | C.7 | 整数上限 | 推断(工作段) | 未知 | HR-STABILITY |
| `F.COMMUTE` 🆕 | 可接受通勤 | required | judgeable | A.4 | 布尔 / 单程分钟 | 一面 | 不可判 | HR-COMMUTE |
| `F.JD_HIRING_REASON` | 招聘原因 | optional | internal | — | — | — | — | — |

### S8 · 合规声明（3）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 门槛形状 | 证据 | 缺了算 | 要求 |
|---|---|---|---|---|---|---|---|---|
| `F.CLEARANCE` | 法律记录 / 无犯罪 | optional | judgeable | G.1 | 布尔 | 背调 | 未知 | G-NO-CRIMINAL-RECORD |
| `F.JD_CONFIDENTIALITY` | 保密/数据保密 | conditional | judgeable | G.2 | 布尔 | 背调 | 未知 | G-CONFIDENTIALITY |
| `F.JD_CONTRACT_TYPE` | 用工类型/合同 | required | internal | — | — | — | — | — |

标准新增（`field_schema` 里还没有）：`F.AVG_TENURE`、`F.RECENT_SEGMENTS`、`F.COMMUTE`

## 四、标准 CV 模板（公司标准 · 26 字段）

候选人档案应该长什么样。共 **26** 字段（必需 18 / 条件 2 / 可选 6）· 目标 26 字段。

> 生成器：`scripts/talent/build_templates.py`。原则：based on field_schema / support ontology reasoning。字段 id 与中文名取自 `field_schema`，每个字段上方的注释写清了"这家公司为什么需要它"与出现次数；没进模板的 **10** 条在文件末尾 `dropped` 里逐条交代去处。

| 段 | 段名 | 字段数 |
|---|---|---|
| C1 | 基本信息 | 7 |
| C2 | 求职意向 | 3 |
| C3 | 教育背景 | 4 |
| C4 | 工作经历 | 6 |
| C5 | 技能与证书 | 3 |
| C6 | 其他 | 3 |

### C1 · 基本信息（7）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 值形状 | 证据 | 缺了算 | 来源 |
|---|---|---|---|---|---|---|---|---|
| `F.CV_FULL_NAME` | 姓名 | required | internal | — | — | 原文 | 未知 | — |
| `F.GENDER` | 性别 | required | judgeable | A.1 | 闭集(男/女) | 原文 | 未知 | A-GENDER |
| `F.AGE` | 年龄 | required | judgeable | A.2 | 数值(岁) + 出生年月 | 原文 | 未知 | A-AGE-RANGE |
| `F.CV_PHONE` | 联系电话 | required | internal | — | — | 原文 | 未知 | — |
| `F.CV_EMAIL` | 电子邮箱 | optional | internal | — | — | 原文 | 未知 | — |
| `F.WORK_LOCATION` | 工作地点 | required | judgeable | A.4 | 城市 / 区镇 | 原文 | 未知 | HR-COMMUTE |
| `F.JOB_TITLE` | 职务名称 | optional | internal | — | — | 原文 | 未知 | — |

### C2 · 求职意向（3）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 值形状 | 证据 | 缺了算 | 来源 |
|---|---|---|---|---|---|---|---|---|
| `F.SALARY` | 薪资 | required | judgeable | A.5 | 区间(K)，判定读上限 | 原文 or 一面 | 未知 | HR-SALARY |
| `F.AVAILABILITY` | 到岗日期 | required | judgeable | A.3 | 整数(周) | 一面 | 未知 | HR-NOTICE |
| `F.COMMUTE` 🆕 | 通勤可接受 | required | judgeable | A.4 | 布尔 + 单程分钟 | 一面 | 未知 | HR-COMMUTE |

### C3 · 教育背景（4）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 值形状 | 证据 | 缺了算 | 来源 |
|---|---|---|---|---|---|---|---|---|
| `F.EDU_LEVEL` | 学历 | required | judgeable | B.1 | 闭集(学历等级) | 原文 | 未知 | B-EDU-LEVEL |
| `F.EDU_MAJOR` | 专业 | required | judgeable | B.2 | 文本(专业全称) | 原文 | 未知 | B-MAJOR |
| `F.EDU_FULLTIME` | 是否全日制 | required | judgeable | B.3 | 布尔 | 原文 or 一面 | 未知 | B-FULL-TIME |
| `F.CV_INSTITUTION` | 毕业院校 | required | internal | — | — | 原文 | 未知 | — |

### C4 · 工作经历（6）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 值形状 | 证据 | 缺了算 | 来源 |
|---|---|---|---|---|---|---|---|---|
| `F.CV_EMPLOYER` | 公司名称 | required | internal | — | — | 原文 | 未知 | — |
| `F.EXP_YEARS` | 总年限 | required | judgeable | C.1 | 数值(年,自述) | 原文 | 未知 | C-YEARS-DOMAIN |
| `F.YEARS_COMPUTED` 🆕 | 累计年限（逐段） | required | judgeable | C.6 | 数值(年,逐段累加) | 推断(逐段) | 未知 | — |
| `F.AVG_TENURE` 🆕 | 平均在职年限 | required | judgeable | C.4 | 数值(年,逐段) | 推断(逐段) | 未知 | HR-TENURE |
| `F.RECENT_SEGMENTS` 🆕 | 近 5 年任职段数 | required | judgeable | C.7 | 整数(段) | 推断(逐段) | 未知 | HR-STABILITY |
| `F.EXP_DOMAIN` | 职能域 | conditional | judgeable | C.2 | 闭集(领域) | 一面 | 未知 | C-YEARS-DOMAIN |

### C5 · 技能与证书（3）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 值形状 | 证据 | 缺了算 | 来源 |
|---|---|---|---|---|---|---|---|---|
| `F.SKILL` | 技能 | required | judgeable | skill_* | 组件 × 熟练度 × 引文 | 原文 or 一面坐实 | 未知 | D-* |
| `F.LANGUAGE_LEVEL` | 语言熟练度 | conditional | judgeable | skill_语言 | 分档(口语/书面) | 一面 | 未知 | H-LANG-EN |
| `F.CERTIFICATION` | 资格证书 | optional | judgeable | F.3 | 闭集(证书) + 扫描件 | 原文(扫描件) | 未知 | F-TRADE-COMPLIANCE-TRAINING |

### C6 · 其他（3）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 值形状 | 证据 | 缺了算 | 来源 |
|---|---|---|---|---|---|---|---|---|
| `F.CLEARANCE` 🆕 | 法律记录 / 无犯罪 | optional | judgeable | G.1 | 布尔 + 背调附件 | 背调 | 未知 | G-NO-CRIMINAL-RECORD |
| `F.CV_TRAININGS` | 培训经历 | optional | internal | — | — | 原文 | 未知 | — |
| `F.CV_PROJECTS` | 项目经验 | optional | internal | — | — | 原文 | 未知 | — |

标准新增（`field_schema` 里还没有）：`F.COMMUTE`、`F.YEARS_COMPUTED`、`F.AVG_TENURE`、`F.RECENT_SEGMENTS`

## 五、客户实际字段 · JD（10 份 JD 里真长什么样）

共 **66** 个字段。规则：渲染 jd 非 null 的字段;其余标「JD 未写」

### S1 · 岗位标识（11）

| 字段 | 名称 | 维度 | 出现 | 必填 | 说明 |
|---|---|---|---|---|---|
| `F.DEPARTMENT` | 隶属部门 | — | 10 | 是 | — |
| `F.JD_APPROVERS` | 核准/审核/制订 | — | 8 | — | 岗位侧字段,简历无对应项 |
| `F.JD_DOC_NUMBER` | 文件编号 | — | 9 | — | 岗位侧字段,简历无对应项 |
| `F.JD_JOB_GRADE` | 职级 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.JD_OCCUPATION_CODE` | 职业编码 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.JD_PAGE_COUNT` | 页数 | — | 8 | — | 岗位侧字段,简历无对应项 |
| `F.JD_VERSION` | 版本 | — | 10 | 是 | 岗位侧字段,简历无对应项 |
| `F.JOB_TITLE` | 职务名称 | — | 10 | 是 | 不是同一条信息:JD 的职务名称是岗位;简历的「意向职位」是候选人的期望。 |
| `F.MGMT_CATEGORY` | 岗位类别 | — | 0 | 是 | 经理岗 / 员工岗。决定用哪份模板 —— 不能按岗位名猜:品质经理原文写「直接下属:无」 |
| `F.REPORTS_TO` | 直接上司 | — | 10 | 是 | — |
| `F.SUPERVISES` | 直接下属 | — | 10 | 是 | — |

### S2 · 岗位目的（3）

| 字段 | 名称 | 维度 | 出现 | 必填 | 说明 |
|---|---|---|---|---|---|
| `F.JD_JOB_PURPOSE` | 岗位目的 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.JD_SUCCESS_CRITERIA` | 关键成功指标 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.TEAM_GOAL` | 团队/部门目标 | — | 0 | — | 岗位侧字段,简历无对应项 |

### S3 · 任职资格（13）

| 字段 | 名称 | 维度 | 出现 | 必填 | 说明 |
|---|---|---|---|---|---|
| `F.AGE` | 年龄 | A | 4 | — | JD 写区间;简历 47% 直述年龄、19% 写出生年月(可推算)。 |
| `F.CERTIFICATION` | 资格证书 | F | 1 | — | 两侧都有:JD 提「合规培训考核」,简历 109/270 写内审员/CET 等。 |
| `F.COMPETENCY` | 职业素养 | E | 9 | 是 | **简历侧的「自我评价」是自我陈述,不构成判定依据** —— 所以两侧虽有字段,仍不可比。 |
| `F.EDU_FULLTIME` | 是否全日制 | B | 1 | — | **简历侧没有任何一份直接写「全日制」** —— 只能从自考/成教/统招推断,而推断没有出处。 |
| `F.EDU_LEVEL` | 学历 | B | 10 | 是 | JD 侧几乎必写门槛;简历侧 179/270 有标签,但需与院校逐段对应。 |
| `F.EDU_MAJOR` | 专业 | B | 6 | — | JD 写「XX类专业」;简历 43% 写明。缺失时这条要求判不了 —— 不是不合格。 |
| `F.EXP_ACTIVITY` | 活动经验 | C | 2 | — | 「做过客户验厂」这类经验只能从工作描述里读;描述标签只有 56/270。 |
| `F.EXP_DOMAIN` | 职能域 | C | 4 | — | JD 写「文职类/管理类」;简历只有职位名。分类标准本身不存在,需先定义。 |
| `F.EXP_INDUSTRY` | 行业 | C | 3 | — | 简历不写行业;只能从公司名推断 —— 推断无出处。 |
| `F.EXP_YEARS` | 总年限 | C | 7 | 是 | 三个口径:平台文件名(被截断)/ 简历自述 / 逐段累计。要求必须声明用哪个。 |
| `F.GENDER` | 性别 | A | 3 | — | A 维无外部标准依据(LinkedIn 与 HR-XML 都无此字段),standard_ref 恒为 NULL。 |
| `F.LANGUAGE_LEVEL` | 语言熟练度 | H | 1 | — | 简历只写 CET-4/6 或「熟练」,无统一刻度;CEFR 映射不存在。 |
| `F.SKILL` | 技能 | D | 10 | 是 | 唯一 10/10 全员必写、且两侧都有实据的维度。词表见 component_catalog.yaml。 |

### S4 · 岗位职责（7）

| 字段 | 名称 | 维度 | 出现 | 必填 | 说明 |
|---|---|---|---|---|---|
| `F.BUDGET_OWNERSHIP` | 预算与成本责任 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.CROSS_DEPT` | 跨部门接口 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.DECISION_AUTHORITY` | 决策权限 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.JD_DUTY_COMPETENCY` | 职责对应能力 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.JD_DUTY_ITEMS` | 职责条目 | — | 10 | 是 | 岗位侧字段,简历无对应项 |
| `F.JD_DUTY_WEIGHT` | 职责权重 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.MGMT_SPAN` | 管理幅度 | — | 0 | 是 | 直接/间接下属人数。岗位侧字段,简历无对应项 |

### S5 · 作业明细（8）

| 字段 | 名称 | 维度 | 出现 | 必填 | 说明 |
|---|---|---|---|---|---|
| `F.JD_ACTIVITY_AI_FIT` | AI 可否替代 | — | 2 | — | 岗位侧字段,简历无对应项 |
| `F.JD_ACTIVITY_DURATION` | 时长 | — | 4 | — | 岗位侧字段,简历无对应项 |
| `F.JD_ACTIVITY_FORM` | 关联表单 | — | 3 | — | 岗位侧字段,简历无对应项 |
| `F.JD_ACTIVITY_FREQ` | 频次(日/周/月/年/偶发) | — | 10 | 是 | 岗位侧字段,简历无对应项 |
| `F.JD_ACTIVITY_SEQ` | 序号 | — | 10 | — | 岗位侧字段,简历无对应项 |
| `F.JD_ACTIVITY_SOP` | 操作标准流程 | — | 2 | — | 岗位侧字段,简历无对应项 |
| `F.JD_ACTIVITY_TEXT` | 内容 | — | 10 | 是 | 岗位侧字段,简历无对应项 |
| `F.SHIFT_HANDOVER` | 排班与交接 | — | 0 | — | 岗位侧字段,简历无对应项 |

### S6 · 工作条件（8）

| 字段 | 名称 | 维度 | 出现 | 必填 | 说明 |
|---|---|---|---|---|---|
| `F.JD_ENVIRONMENT` | 环境(噪音/粉尘/温度) | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.JD_PHYSICAL_DEMAND` | 体力/站立/搬运 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.JD_PPE` | 劳保/防护 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.JD_TRAVEL` | 出差 | — | 3 | — | 岗位侧字段,简历无对应项 |
| `F.JD_WORK_HOURS` | 工时 | — | 3 | — | 岗位侧字段,简历无对应项 |
| `F.JD_WORK_LOCATION` | 工作地点/厂区 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.SHIFT` | 班制 | — | 0 | — | 两侧都没有 —— 这是制造业招聘最要紧的一项,却全批缺失。 |
| `F.WORK_LOCATION` | 工作地点 | — | 0 | — | **JD 全批都没写工作地点,简历 41% 有现居地** —— 无法比对通勤半径。 |

### S7 · 元数据（9）

| 字段 | 名称 | 维度 | 出现 | 必填 | 说明 |
|---|---|---|---|---|---|
| `F.AVAILABILITY` | 到岗日期 | — | 0 | — | — |
| `F.JD_DATE_POSTED` | 发布日期 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.JD_FIRST_ISSUED` | 首次发行日 | — | 9 | — | 岗位侧字段,简历无对应项 |
| `F.JD_HEADCOUNT` | 编制/招聘人数 | — | 1 | — | 岗位侧字段,简历无对应项 |
| `F.JD_HIRING_REASON` | 招聘原因 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.JD_POSTING_CHANNEL` | 发布渠道 | — | 1 | — | 岗位侧字段,简历无对应项 |
| `F.JD_REVISION_HISTORY` | 修订履历 | — | 10 | — | 岗位侧字段,简历无对应项 |
| `F.JD_VALID_UNTIL` | 有效期/截止 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.SALARY` | 薪资 | — | 0 | — | **JD 侧无薪资区间,简历侧 26% 有期望薪资** —— 单边数据不构成比较。 |

### S8 · 合规声明（7）

| 字段 | 名称 | 维度 | 出现 | 必填 | 说明 |
|---|---|---|---|---|---|
| `F.CLEARANCE` | 法律记录 / 无犯罪 | G | 1 | — | **简历侧完全没有对应字段** —— 只能要证明文件。 |
| `F.JD_CLEAN_RECORD` | 无犯罪/无行政处罚 | — | 1 | — | 岗位侧字段,简历无对应项 |
| `F.JD_CONFIDENTIALITY` | 保密/数据保密 | — | 2 | — | 岗位侧字段,简历无对应项 |
| `F.JD_CONTRACT_TYPE` | 用工类型/合同 | — | 3 | — | 岗位侧字段,简历无对应项 |
| `F.JD_NON_COMPETE` | 竞业限制 | — | 0 | — | 岗位侧字段,简历无对应项 |
| `F.JD_PROBATION` | 试用期 | — | 1 | — | 岗位侧字段,简历无对应项 |
| `F.JD_SOCIAL_INSURANCE` | 社保 | — | 1 | — | 岗位侧字段,简历无对应项 |

## 六、客户实际字段 · CV（270 份简历里真长什么样）

共 **31** 个字段。规则：渲染 cv 非 null 的字段;其余标〔待补〕

### C1 · 基本信息（10）

| 字段 | 名称 | 维度 | 出现 | 落哪个属性 | 两侧可比 | 说明 |
|---|---|---|---|---|---|---|
| `F.AGE` | 年龄 | A | 129 | age | both | JD 写区间;简历 47% 直述年龄、19% 写出生年月(可推算)。 |
| `F.CV_BIRTH_DATE` | 出生年月 | — | 52 | birthDate | cv_only | 候选人侧字段,JD 无对应项 |
| `F.CV_EMAIL` | 电子邮箱 | — | 173 | email | cv_only | 候选人侧字段,JD 无对应项 |
| `F.CV_FULL_NAME` | 姓名 | — | 24 | fullName | cv_only | 候选人侧字段,JD 无对应项 |
| `F.CV_MARITAL_STATUS` | 婚姻状况 | — | 11 | marital | cv_only | 候选人侧字段,JD 无对应项 |
| `F.CV_NATIVE_PLACE` | 籍贯 | — | 19 | hometown | cv_only | 候选人侧字段,JD 无对应项 |
| `F.CV_PHONE` | 联系电话 | — | 120 | phone | cv_only | 候选人侧字段,JD 无对应项 |
| `F.GENDER` | 性别 | A | 153 | gender | both | A 维无外部标准依据(LinkedIn 与 HR-XML 都无此字段),standard_ref 恒为 NULL |
| `F.JOB_TITLE` | 职务名称 | — | 192 | jobTitle | not_comparable | 不是同一条信息:JD 的职务名称是岗位;简历的「意向职位」是候选人的期望。 |
| `F.WORK_LOCATION` | 工作地点 | — | 113 | workLocation | not_comparable | **JD 全批都没写工作地点,简历 41% 有现居地** —— 无法比对通勤半径。 |

### C2 · 求职意向（4）

| 字段 | 名称 | 维度 | 出现 | 落哪个属性 | 两侧可比 | 说明 |
|---|---|---|---|---|---|---|
| `F.AVAILABILITY` | 到岗日期 | — | 123 | notice_weeks | cv_only | — |
| `F.CV_CURRENT_SALARY` | 目前年薪 | — | 5 | current_salary_k | cv_only | 候选人侧字段,JD 无对应项 |
| `F.CV_JOB_TYPE` | 求职类型 | — | 15 | job_type | cv_only | 候选人侧字段,JD 无对应项 |
| `F.SALARY` | 薪资 | — | 71 | salary | not_comparable | **JD 侧无薪资区间,简历侧 26% 有期望薪资** —— 单边数据不构成比较。 |

### C3 · 教育背景（5）

| 字段 | 名称 | 维度 | 出现 | 落哪个属性 | 两侧可比 | 说明 |
|---|---|---|---|---|---|---|
| `F.CV_EDU_PERIOD` | 起止时间 | — | 267 | edu_period | cv_only | 候选人侧字段,JD 无对应项 |
| `F.CV_INSTITUTION` | 毕业院校 | — | 67 | institution | cv_only | 候选人侧字段,JD 无对应项 |
| `F.EDU_FULLTIME` | 是否全日制 | B | 0 | full_time | not_comparable | **简历侧没有任何一份直接写「全日制」** —— 只能从自考/成教/统招推断,而推断没有出处。 |
| `F.EDU_LEVEL` | 学历 | B | 179 | education_rank | both | JD 侧几乎必写门槛;简历侧 179/270 有标签,但需与院校逐段对应。 |
| `F.EDU_MAJOR` | 专业 | B | 117 | major | both | JD 写「XX类专业」;简历 43% 写明。缺失时这条要求判不了 —— 不是不合格。 |

### C4 · 工作经历（5）

| 字段 | 名称 | 维度 | 出现 | 落哪个属性 | 两侧可比 | 说明 |
|---|---|---|---|---|---|---|
| `F.CV_EMPLOYER` | 公司名称 | — | 255 | employer | cv_only | 候选人侧字段,JD 无对应项 |
| `F.EXP_ACTIVITY` | 活动经验 | C | 56 | activity_experience | both | 「做过客户验厂」这类经验只能从工作描述里读;描述标签只有 56/270。 |
| `F.EXP_DOMAIN` | 职能域 | C | 135 | domain | not_comparable | JD 写「文职类/管理类」;简历只有职位名。分类标准本身不存在,需先定义。 |
| `F.EXP_INDUSTRY` | 行业 | C | 0 | industry | not_comparable | 简历不写行业;只能从公司名推断 —— 推断无出处。 |
| `F.EXP_YEARS` | 总年限 | C | 267 | years_stated | both | 三个口径:平台文件名(被截断)/ 简历自述 / 逐段累计。要求必须声明用哪个。 |

### C5 · 技能与证书（4）

| 字段 | 名称 | 维度 | 出现 | 落哪个属性 | 两侧可比 | 说明 |
|---|---|---|---|---|---|---|
| `F.CERTIFICATION` | 资格证书 | F | 109 | hasCertification | both | 两侧都有:JD 提「合规培训考核」,简历 109/270 写内审员/CET 等。 |
| `F.CV_LANGUAGE` | 语言能力 | — | 109 | language | cv_only | 候选人侧字段,JD 无对应项 |
| `F.LANGUAGE_LEVEL` | 语言熟练度 | H | 0 | language_level | not_comparable | 简历只写 CET-4/6 或「熟练」,无统一刻度;CEFR 映射不存在。 |
| `F.SKILL` | 技能 | D | 140 | hasSkill | both | 唯一 10/10 全员必写、且两侧都有实据的维度。词表见 component_catalog.yaml。 |

### C6 · 其他（3）

| 字段 | 名称 | 维度 | 出现 | 落哪个属性 | 两侧可比 | 说明 |
|---|---|---|---|---|---|---|
| `F.COMPETENCY` | 职业素养 | E | 62 | competency | not_comparable | **简历侧的「自我评价」是自我陈述,不构成判定依据** —— 所以两侧虽有字段,仍不可比。 |
| `F.CV_PROJECTS` | 项目经验 | — | 42 | projects | cv_only | 候选人侧字段,JD 无对应项 |
| `F.CV_TRAININGS` | 培训经历 | — | 94 | trainings | cv_only | 候选人侧字段,JD 无对应项 |

## 七、要求清单（码 / 维度 / 类别 / 可判 / 被几个 JD 用）

| 码 | 名称 | 维度 | kind | 类别 | 可判 | 挂组件 | JD |
|---|---|---|---|---|---|---|---|
| `A-AGE-RANGE` | 年龄区间 | A | threshold | fact | ✅ | 0 | 3 |
| `A-GENDER` | 性别 | A | threshold | fact | — | 0 | 1 |
| `B-EDU-LEVEL` | 学历不低于 | B | threshold | fact | ✅ | 0 | 4 |
| `B-FULL-TIME` | 全日制 | B | threshold | fact | — | 0 | 1 |
| `B-MAJOR` | 专业限定 | B | enumerate | fact | ✅ | 0 | 4 |
| `C-YEARS-DOMAIN` | 某领域年限不低于 | C | threshold | fact | ✅ | 0 | 5 |
| `D-AI-TOOLS` | AI 工具运用 | D | unmeasurable | soft | — | 0 | 0 |
| `D-ATTENDANCE-SYSTEM` | 考勤系统操作 | D | unmeasurable | soft | — | 0 | 0 |
| `D-BIZ-ETIQUETTE` | 商务礼仪 | E | unmeasurable | soft | — | 0 | 0 |
| `D-CAD-2D` | CAD 二维制图 | D | component | capability | ✅ | 1 | 1 |
| `D-CULTURE-BUILD` | 企业文化建设 | D | component | capability | ✅ | 1 | 0 |
| `D-CUSTOMER-AUDIT` | 客户验厂经验 | D | component | capability | ✅ | 1 | 1 |
| `D-CUSTOMS-DECLARE` | 进出口报关流程 | D | composite | capability | ✅ | 2 | 1 |
| `D-DATA-ANALYSIS` | 数据统计分析 | D | component | capability | ✅ | 1 | 0 |
| `D-DELIVERY-RISK` | 订单交期风险评估 | D | component | capability | ✅ | 1 | 1 |
| `D-DRAWING-READ` | 图纸识别(线材规格/端子型号/胶壳料号/回路标识) | D | component | capability | ✅ | 1 | 0 |
| `D-ERP-EXCEL` | ERP 订单模块 + Excel 数据分析 | D | composite | capability | ✅ | 2 | 1 |
| `D-ERP-OPERATE` | ERP 系统操作 | D | component | capability | ✅ | 1 | 1 |
| `D-HARNESS-DOMAIN` | 线束/连接器行业认知 | D | component | capability | ✅ | 1 | 2 |
| `D-LABOR-LAW` | 国家法律法规知识 | D | component | capability | ✅ | 1 | 0 |
| `D-NPI-PROCESS` | 新产品报价/样品/转量产流程 | D | unmeasurable | soft | — | 0 | 1 |
| `D-OFFICE` | Office 办公软件(Word/Excel/PPT) | D | composite | capability | ✅ | 3 | 3 |
| `D-OFFICE-NETWORK` | Office 软件 + 办公室网络 | D | composite | capability | ✅ | 3 | 0 |
| `D-QA-ANALYSIS` | 品质问题分析改善能力 | D | component | capability | ✅ | 1 | 1 |
| `D-QA-TOOLS` | 品质工具(QC七大手法/5WHY/SPC/CPK/6S) | D | composite | capability | ✅ | 5 | 1 |
| `D-RECRUIT-CHANNEL` | 招聘渠道 | D | component | capability | ✅ | 1 | 0 |
| `D-RECRUIT-KNOWLEDGE` | 招聘知识 | D | component | capability | ✅ | 1 | 0 |
| `D-RECRUIT-SKILL` | 招聘技巧 | D | component | capability | ✅ | 1 | 0 |
| `D-REPORT-WRITING` | 报表整理能力 | D | component | capability | ✅ | 1 | 1 |
| `D-SOCIAL-INSURANCE` | 社保操作流程 | D | component | capability | ✅ | 1 | 0 |
| `D-SYSTEM-MGMT` | 体系管理 | D | component | capability | ✅ | 1 | 0 |
| `D-SYSTEM-PLANNING` | 系统规划 | D | component | capability | ✅ | 1 | 0 |
| `D-TRAINING-DEV` | 培训课程开发 | D | component | capability | ✅ | 1 | 0 |
| `D-WIRE-EQUIPMENT` | 电线加工设备(熟知并会操作) | D | composite | capability | ✅ | 5 | 1 |
| `E-ACCOUNTABILITY` | 敢于担当 | E | unmeasurable | soft | — | 0 | 1 |
| `E-BIZ-INTENT` | 业务发展意向 | E | unmeasurable | soft | — | 0 | 0 |
| `E-CAREFUL` | 细心严谨 | E | unmeasurable | soft | — | 0 | 1 |
| `E-COMMUNICATION` | 沟通协调能力 | E | unmeasurable | soft | — | 0 | 4 |
| `E-DAILY-CLOSE` | 日清日结 | E | unmeasurable | soft | — | 0 | 2 |
| `E-DATA-SENSITIVITY` | 数据敏感 | E | unmeasurable | soft | — | 0 | 2 |
| `E-ETHICS` | 职业道德 | E | unmeasurable | soft | — | 0 | 1 |
| `E-EXECUTION` | 执行能力 | E | unmeasurable | soft | — | 0 | 2 |
| `E-JOB-INTEREST` | 岗位工作兴趣 | E | unmeasurable | soft | — | 0 | 0 |
| `E-LOGIC` | 逻辑清晰 | E | unmeasurable | soft | — | 0 | 1 |
| `E-OPENNESS` | 性格开朗 | E | unmeasurable | soft | — | 0 | 0 |
| `E-PRINCIPLE` | 原则性 | E | unmeasurable | soft | — | 0 | 1 |
| `E-PROACTIVE` | 工作积极主动 | E | unmeasurable | soft | — | 0 | 1 |
| `E-RESPONSIBILITY` | 责任心 | E | unmeasurable | soft | — | 0 | 2 |
| `E-STEADY` | 稳重 | E | unmeasurable | soft | — | 0 | 0 |
| `E-STRESS` | 抗压能力 / 多线程处理 | E | unmeasurable | soft | — | 0 | 2 |
| `E-STRIVING` | 奋斗精神 | E | unmeasurable | soft | — | 0 | 2 |
| `E-TEAMWORK` | 团队合作 | E | unmeasurable | soft | — | 0 | 1 |
| `F-TRADE-COMPLIANCE-TRAINING` | 贸易安全合规培训考核 | F | unmeasurable | soft | — | 0 | 1 |
| `G-CONFIDENTIALITY` | 数据保密 / 无信息泄露记录 | G | unmeasurable | soft | — | 0 | 1 |
| `G-NO-CRIMINAL-RECORD` | 无处罚及犯罪记录 | G | unmeasurable | soft | — | 0 | 1 |
| `H-LANG-EN` | 英语(口语 + 独立书写英文8D报告) | D | composite | capability | ✅ | 2 | 1 |
| `HR-COMMUTE` | 能接受上班地点 | A | boolean | fact | ✅ | 0 | 1 |
| `HR-NOTICE` | 到岗时间不超过 | A | threshold | fact | ✅ | 0 | 1 |
| `HR-SALARY` | 期望薪资不超过岗位上限 | A | threshold | fact | ✅ | 0 | 1 |
| `HR-STABILITY` | 近 5 年任职不超过 | C | threshold | fact | ✅ | 0 | 1 |
| `HR-TENURE` | 平均在职不低于 | C | threshold | fact | ✅ | 0 | 1 |
