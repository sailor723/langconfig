# 标准目录 · Phase 0（标准定义层）

> 这一层**不对应任何具体 JD 或简历**：只有分类、组件、要求，以及公司标准的 JD / CV 模板。
> 数字由 `scripts/talent/build_catalog.py` 现算，不手写。

> 分类 **22** · 组件 **54** · 要求 **61** · 标准 JD 模板 **40** 字段 · 标准 CV 模板 **26** 字段

> **版式统一**：所有 JD 共用同一份 40 字段版式（standard_templates.jd）；所有简历共用同一份 26 字段版式（standard_templates.cv）。具体某份 JD 的取值与缺口属于下一层，不在本目录里。

## 目录自身的完整性

| 检查 | 数量 | 影响 |
|---|---|---|
| 组件**没标证据档** | **39** | 能力「满足」里有多少只是自述，答不出来 |
| 组件**没有被任何要求挂** | **22** | 抽得出、判不到 |
| 要求**不可判**（assessable=false） | **27** | 对所有人一样，不能拿来淘汰人 |
| 可判要求**没落到标准模板** | **0** | 判不了：要求提了，模板里没有落脚字段 |

## 一、分类与组件

### QualityMethod（9）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_5WHY` | 5WHY | capability | **hard** | 1 |
| `skill_6S` | 6S | capability | **hard** | 1 |
| `skill_8D报告` | 8D报告 | capability | **hard** | 1 |
| `skill_CPK` | CPK | capability | **hard** | 1 |
| `skill_FMEA` | FMEA | capability | **未声明** | 0 |
| `skill_QC七大手法` | QC七大手法 | capability | **hard** | 1 |
| `skill_SPC` | SPC | capability | **hard** | 1 |
| `skill_品质问题分析` | 品质问题分析 | capability | **soft** | 1 |
| `skill_客户验厂` | 客户验厂 | capability | **hard** | 1 |

### CAD（6）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_AutoCAD` | AutoCAD | product | **未声明** | 1 |
| `skill_CATIA` | CATIA | product | **未声明** | 0 |
| `skill_ProE_Creo` | ProE/Creo | product | **未声明** | 0 |
| `skill_Rhino` | Rhino | product | **未声明** | 0 |
| `skill_SolidWorks` | SolidWorks | product | **未声明** | 0 |
| `skill_UG_NX` | UG/NX | product | **未声明** | 0 |

### GeneralCapability（6）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_企业文化建设` | 企业文化建设 | capability | **未声明** | 1 |
| `skill_体系管理` | 体系管理 | capability | **未声明** | 1 |
| `skill_培训课程开发` | 培训课程开发 | capability | **未声明** | 1 |
| `skill_数据分析` | 数据分析 | capability | **未声明** | 1 |
| `skill_系统规划` | 系统规划 | capability | **未声明** | 1 |
| `skill_订单交期风险评估` | 订单交期风险评估 | capability | **soft** | 1 |

### WireEquipment（5）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_注塑机` | 注塑机 | equipment | **未声明** | 1 |
| `skill_点胶机` | 点胶机 | equipment | **未声明** | 1 |
| `skill_端子机` | 端子机 | equipment | **未声明** | 1 |
| `skill_自动机` | 自动机 | equipment | **未声明** | 1 |
| `skill_裁线机` | 裁线机 | equipment | **未声明** | 1 |

### HarnessCraft（4）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_切片` | 切片 | equipment | **未声明** | 0 |
| `skill_端子` | 端子 | equipment | **未声明** | 0 |
| `skill_线束行业知识` | 线束行业知识 | domain | **soft** | 1 |
| `skill_识图` | 识图 | capability | **未声明** | 1 |

### DesignSoftware（3）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_CorelDRAW` | CorelDRAW | product | **未声明** | 0 |
| `skill_Illustrator` | Illustrator | product | **未声明** | 0 |
| `skill_Photoshop` | Photoshop | product | **未声明** | 0 |

### BusinessSystem（2）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_ERP` | ERP | product | **hard** | 2 |
| `skill_SAP` | SAP | product | **未声明** | 0 |

### CustomsSkill（2）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_单证` | 单证 | capability | **未声明** | 1 |
| `skill_报关` | 报关 | capability | **未声明** | 1 |

### OfficeSoftware（2）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_PowerPoint` | PowerPoint | product | **未声明** | 2 |
| `skill_Word` | Word | product | **未声明** | 2 |

### OperationsSkill（2）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_5S` | 5S | capability | **未声明** | 0 |
| `skill_精益生产` | 精益生产 | capability | **未声明** | 0 |

### QualitySystem（2）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_ISO_TS16949` | ISO/TS16949 | capability | **hard** | 0 |
| `skill_ISO9001` | ISO9001 | capability | **hard** | 0 |

### AdminSkill（1）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_行政` | 行政 | capability | **未声明** | 0 |

### CompensationSkill（1）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_薪酬绩效` | 薪酬绩效 | capability | **未声明** | 0 |

### Compliance（1）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_贸易安全合规` | 贸易安全合规 | capability | **未声明** | 0 |

### FinanceSkill（1）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_财务` | 财务 | capability | **未声明** | 0 |

### HRAdmin（1）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_社保操作` | 社保操作 | capability | **未声明** | 1 |

### LaborLawKnowledge（1）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_劳动法` | 劳动法 | domain | **未声明** | 1 |

### LanguageSkill（1）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_英语` | 英语 | capability | **soft** | 1 |

### OrderTracking（1）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_跟单` | 跟单 | capability | **未声明** | 0 |

### RecruitingSkill（1）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_招聘` | 招聘 | capability | **未声明** | 3 |

### SpreadsheetSoftware（1）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_Excel` | Excel | product | **hard** | 4 |

### TradeSkill（1）

| 组件 | 标签 | kind | 证据档 | 挂几条要求 |
|---|---|---|---|---|
| `skill_外贸业务` | 外贸业务 | capability | **未声明** | 0 |

## 二、组件 → 要求反查

| 组件 | 要求 |
|---|---|
| `skill_Excel` Excel | D-ERP-EXCEL、D-OFFICE、D-OFFICE-NETWORK、D-REPORT-WRITING |
| `skill_招聘` 招聘 | D-RECRUIT-CHANNEL、D-RECRUIT-KNOWLEDGE、D-RECRUIT-SKILL |
| `skill_ERP` ERP | D-ERP-EXCEL、D-ERP-OPERATE |
| `skill_PowerPoint` PowerPoint | D-OFFICE、D-OFFICE-NETWORK |
| `skill_Word` Word | D-OFFICE、D-OFFICE-NETWORK |
| `skill_5WHY` 5WHY | D-QA-TOOLS |
| `skill_6S` 6S | D-QA-TOOLS |
| `skill_8D报告` 8D报告 | H-LANG-EN |
| `skill_AutoCAD` AutoCAD | D-CAD-2D |
| `skill_CPK` CPK | D-QA-TOOLS |
| `skill_QC七大手法` QC七大手法 | D-QA-TOOLS |
| `skill_SPC` SPC | D-QA-TOOLS |
| `skill_企业文化建设` 企业文化建设 | D-CULTURE-BUILD |
| `skill_体系管理` 体系管理 | D-SYSTEM-MGMT |
| `skill_劳动法` 劳动法 | D-LABOR-LAW |
| `skill_单证` 单证 | D-CUSTOMS-DECLARE |
| `skill_品质问题分析` 品质问题分析 | D-QA-ANALYSIS |
| `skill_培训课程开发` 培训课程开发 | D-TRAINING-DEV |
| `skill_客户验厂` 客户验厂 | D-CUSTOMER-AUDIT |
| `skill_报关` 报关 | D-CUSTOMS-DECLARE |
| `skill_数据分析` 数据分析 | D-DATA-ANALYSIS |
| `skill_注塑机` 注塑机 | D-WIRE-EQUIPMENT |
| `skill_点胶机` 点胶机 | D-WIRE-EQUIPMENT |
| `skill_社保操作` 社保操作 | D-SOCIAL-INSURANCE |
| `skill_端子机` 端子机 | D-WIRE-EQUIPMENT |
| `skill_系统规划` 系统规划 | D-SYSTEM-PLANNING |
| `skill_线束行业知识` 线束行业知识 | D-HARNESS-DOMAIN |
| `skill_自动机` 自动机 | D-WIRE-EQUIPMENT |
| `skill_英语` 英语 | H-LANG-EN |
| `skill_裁线机` 裁线机 | D-WIRE-EQUIPMENT |
| `skill_订单交期风险评估` 订单交期风险评估 | D-DELIVERY-RISK |
| `skill_识图` 识图 | D-DRAWING-READ |

## 三、标准 JD 模板（所有 JD 共用同一版式）

职务说明书。共 **40** 字段（必需 23 / 条件 10 / 可选 7）· 目标 40 字段。

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

## 四、标准 CV 模板（所有简历共用同一版式）

候选人档案。共 **26** 字段（必需 18 / 条件 2 / 可选 6）· 目标 26 字段。

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

| 字段 | 名称 | 层级 | 判定 | 数据项 | 值形状 | 证据 | 缺了算 | 要求 |
|---|---|---|---|---|---|---|---|---|
| `F.CV_FULL_NAME` | 姓名 | required | internal | — | — | 原文 | 未知 | — |
| `F.GENDER` | 性别 | required | judgeable | A.1 | 闭集(男/女) | 原文 | 未知 | A-GENDER |
| `F.AGE` | 年龄 | required | judgeable | A.2 | 数值(岁) + 出生年月 | 原文 | 未知 | A-AGE-RANGE |
| `F.CV_PHONE` | 联系电话 | required | internal | — | — | 原文 | 未知 | — |
| `F.CV_EMAIL` | 电子邮箱 | optional | internal | — | — | 原文 | 未知 | — |
| `F.WORK_LOCATION` | 工作地点 | required | judgeable | A.4 | 城市 / 区镇 | 原文 | 未知 | HR-COMMUTE |
| `F.JOB_TITLE` | 职务名称 | optional | internal | — | — | 原文 | 未知 | — |

### C2 · 求职意向（3）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 值形状 | 证据 | 缺了算 | 要求 |
|---|---|---|---|---|---|---|---|---|
| `F.SALARY` | 薪资 | required | judgeable | A.5 | 区间(K)，判定读上限 | 原文 or 一面 | 未知 | HR-SALARY |
| `F.AVAILABILITY` | 到岗日期 | required | judgeable | A.3 | 整数(周) | 一面 | 未知 | HR-NOTICE |
| `F.COMMUTE` 🆕 | 通勤可接受 | required | judgeable | A.4 | 布尔 + 单程分钟 | 一面 | 未知 | HR-COMMUTE |

### C3 · 教育背景（4）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 值形状 | 证据 | 缺了算 | 要求 |
|---|---|---|---|---|---|---|---|---|
| `F.EDU_LEVEL` | 学历 | required | judgeable | B.1 | 闭集(学历等级) | 原文 | 未知 | B-EDU-LEVEL |
| `F.EDU_MAJOR` | 专业 | required | judgeable | B.2 | 文本(专业全称) | 原文 | 未知 | B-MAJOR |
| `F.EDU_FULLTIME` | 是否全日制 | required | judgeable | B.3 | 布尔 | 原文 or 一面 | 未知 | B-FULL-TIME |
| `F.CV_INSTITUTION` | 毕业院校 | required | internal | — | — | 原文 | 未知 | — |

### C4 · 工作经历（6）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 值形状 | 证据 | 缺了算 | 要求 |
|---|---|---|---|---|---|---|---|---|
| `F.CV_EMPLOYER` | 公司名称 | required | internal | — | — | 原文 | 未知 | — |
| `F.EXP_YEARS` | 总年限 | required | judgeable | C.1 | 数值(年,自述) | 原文 | 未知 | C-YEARS-DOMAIN |
| `F.YEARS_COMPUTED` 🆕 | 累计年限（逐段） | required | judgeable | C.6 | 数值(年,逐段累加) | 推断(逐段) | 未知 | — |
| `F.AVG_TENURE` 🆕 | 平均在职年限 | required | judgeable | C.4 | 数值(年,逐段) | 推断(逐段) | 未知 | HR-TENURE |
| `F.RECENT_SEGMENTS` 🆕 | 近 5 年任职段数 | required | judgeable | C.7 | 整数(段) | 推断(逐段) | 未知 | HR-STABILITY |
| `F.EXP_DOMAIN` | 职能域 | conditional | judgeable | C.2 | 闭集(领域) | 一面 | 未知 | C-YEARS-DOMAIN |

### C5 · 技能与证书（3）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 值形状 | 证据 | 缺了算 | 要求 |
|---|---|---|---|---|---|---|---|---|
| `F.SKILL` | 技能 | required | judgeable | skill_* | 组件 × 熟练度 × 引文 | 原文 or 一面坐实 | 未知 | D-* |
| `F.LANGUAGE_LEVEL` | 语言熟练度 | conditional | judgeable | skill_语言 | 分档(口语/书面) | 一面 | 未知 | H-LANG-EN |
| `F.CERTIFICATION` | 资格证书 | optional | judgeable | F.3 | 闭集(证书) + 扫描件 | 原文(扫描件) | 未知 | F-TRADE-COMPLIANCE-TRAINING |

### C6 · 其他（3）

| 字段 | 名称 | 层级 | 判定 | 数据项 | 值形状 | 证据 | 缺了算 | 要求 |
|---|---|---|---|---|---|---|---|---|
| `F.CLEARANCE` 🆕 | 法律记录 / 无犯罪 | optional | judgeable | G.1 | 布尔 + 背调附件 | 背调 | 未知 | G-NO-CRIMINAL-RECORD |
| `F.CV_TRAININGS` | 培训经历 | optional | internal | — | — | 原文 | 未知 | — |
| `F.CV_PROJECTS` | 项目经验 | optional | internal | — | — | 原文 | 未知 | — |

标准新增（`field_schema` 里还没有）：`F.COMMUTE`、`F.YEARS_COMPUTED`、`F.AVG_TENURE`、`F.RECENT_SEGMENTS`

## 五、要求清单

| 码 | 名称 | 维度 | kind | 类别 | 可判 | 挂组件 |
|---|---|---|---|---|---|---|
| `A-AGE-RANGE` | 年龄区间 | A | threshold | fact | ✅ | 0 |
| `A-GENDER` | 性别 | A | threshold | fact | — | 0 |
| `B-EDU-LEVEL` | 学历不低于 | B | threshold | fact | ✅ | 0 |
| `B-FULL-TIME` | 全日制 | B | threshold | fact | — | 0 |
| `B-MAJOR` | 专业限定 | B | enumerate | fact | ✅ | 0 |
| `C-YEARS-DOMAIN` | 某领域年限不低于 | C | threshold | fact | ✅ | 0 |
| `D-AI-TOOLS` | AI 工具运用 | D | unmeasurable | soft | — | 0 |
| `D-ATTENDANCE-SYSTEM` | 考勤系统操作 | D | unmeasurable | soft | — | 0 |
| `D-BIZ-ETIQUETTE` | 商务礼仪 | E | unmeasurable | soft | — | 0 |
| `D-CAD-2D` | CAD 二维制图 | D | component | capability | ✅ | 1 |
| `D-CULTURE-BUILD` | 企业文化建设 | D | component | capability | ✅ | 1 |
| `D-CUSTOMER-AUDIT` | 客户验厂经验 | D | component | capability | ✅ | 1 |
| `D-CUSTOMS-DECLARE` | 进出口报关流程 | D | composite | capability | ✅ | 2 |
| `D-DATA-ANALYSIS` | 数据统计分析 | D | component | capability | ✅ | 1 |
| `D-DELIVERY-RISK` | 订单交期风险评估 | D | component | capability | ✅ | 1 |
| `D-DRAWING-READ` | 图纸识别(线材规格/端子型号/胶壳料号/回路标识) | D | component | capability | ✅ | 1 |
| `D-ERP-EXCEL` | ERP 订单模块 + Excel 数据分析 | D | composite | capability | ✅ | 2 |
| `D-ERP-OPERATE` | ERP 系统操作 | D | component | capability | ✅ | 1 |
| `D-HARNESS-DOMAIN` | 线束/连接器行业认知 | D | component | capability | ✅ | 1 |
| `D-LABOR-LAW` | 国家法律法规知识 | D | component | capability | ✅ | 1 |
| `D-NPI-PROCESS` | 新产品报价/样品/转量产流程 | D | unmeasurable | soft | — | 0 |
| `D-OFFICE` | Office 办公软件(Word/Excel/PPT) | D | composite | capability | ✅ | 3 |
| `D-OFFICE-NETWORK` | Office 软件 + 办公室网络 | D | composite | capability | ✅ | 3 |
| `D-QA-ANALYSIS` | 品质问题分析改善能力 | D | component | capability | ✅ | 1 |
| `D-QA-TOOLS` | 品质工具(QC七大手法/5WHY/SPC/CPK/6S) | D | composite | capability | ✅ | 5 |
| `D-RECRUIT-CHANNEL` | 招聘渠道 | D | component | capability | ✅ | 1 |
| `D-RECRUIT-KNOWLEDGE` | 招聘知识 | D | component | capability | ✅ | 1 |
| `D-RECRUIT-SKILL` | 招聘技巧 | D | component | capability | ✅ | 1 |
| `D-REPORT-WRITING` | 报表整理能力 | D | component | capability | ✅ | 1 |
| `D-SOCIAL-INSURANCE` | 社保操作流程 | D | component | capability | ✅ | 1 |
| `D-SYSTEM-MGMT` | 体系管理 | D | component | capability | ✅ | 1 |
| `D-SYSTEM-PLANNING` | 系统规划 | D | component | capability | ✅ | 1 |
| `D-TRAINING-DEV` | 培训课程开发 | D | component | capability | ✅ | 1 |
| `D-WIRE-EQUIPMENT` | 电线加工设备(熟知并会操作) | D | composite | capability | ✅ | 5 |
| `E-ACCOUNTABILITY` | 敢于担当 | E | unmeasurable | soft | — | 0 |
| `E-BIZ-INTENT` | 业务发展意向 | E | unmeasurable | soft | — | 0 |
| `E-CAREFUL` | 细心严谨 | E | unmeasurable | soft | — | 0 |
| `E-COMMUNICATION` | 沟通协调能力 | E | unmeasurable | soft | — | 0 |
| `E-DAILY-CLOSE` | 日清日结 | E | unmeasurable | soft | — | 0 |
| `E-DATA-SENSITIVITY` | 数据敏感 | E | unmeasurable | soft | — | 0 |
| `E-ETHICS` | 职业道德 | E | unmeasurable | soft | — | 0 |
| `E-EXECUTION` | 执行能力 | E | unmeasurable | soft | — | 0 |
| `E-JOB-INTEREST` | 岗位工作兴趣 | E | unmeasurable | soft | — | 0 |
| `E-LOGIC` | 逻辑清晰 | E | unmeasurable | soft | — | 0 |
| `E-OPENNESS` | 性格开朗 | E | unmeasurable | soft | — | 0 |
| `E-PRINCIPLE` | 原则性 | E | unmeasurable | soft | — | 0 |
| `E-PROACTIVE` | 工作积极主动 | E | unmeasurable | soft | — | 0 |
| `E-RESPONSIBILITY` | 责任心 | E | unmeasurable | soft | — | 0 |
| `E-STEADY` | 稳重 | E | unmeasurable | soft | — | 0 |
| `E-STRESS` | 抗压能力 / 多线程处理 | E | unmeasurable | soft | — | 0 |
| `E-STRIVING` | 奋斗精神 | E | unmeasurable | soft | — | 0 |
| `E-TEAMWORK` | 团队合作 | E | unmeasurable | soft | — | 0 |
| `F-TRADE-COMPLIANCE-TRAINING` | 贸易安全合规培训考核 | F | unmeasurable | soft | — | 0 |
| `G-CONFIDENTIALITY` | 数据保密 / 无信息泄露记录 | G | unmeasurable | soft | — | 0 |
| `G-NO-CRIMINAL-RECORD` | 无处罚及犯罪记录 | G | unmeasurable | soft | — | 0 |
| `H-LANG-EN` | 英语(口语 + 独立书写英文8D报告) | D | composite | capability | ✅ | 2 |
| `HR-COMMUTE` | 能接受上班地点 | A | boolean | fact | ✅ | 0 |
| `HR-NOTICE` | 到岗时间不超过 | A | threshold | fact | ✅ | 0 |
| `HR-SALARY` | 期望薪资不超过岗位上限 | A | threshold | fact | ✅ | 0 |
| `HR-STABILITY` | 近 5 年任职不超过 | C | threshold | fact | ✅ | 0 |
| `HR-TENURE` | 平均在职不低于 | C | threshold | fact | ✅ | 0 |

---

下一层（不在这份目录里）：客户 JD 原文 → 这份 JD 的缺口 → 某份简历的缺口。缺口在 Talent 左栏「0 JD · 原文与缺口」看，原料是 `jd_draft/` 与 `template_fill/`。
