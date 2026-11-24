# 标准模板 × 5 份客户 JD：试填汇总

> 模板 **40** 字段 × **5** 份京东 = **200** 格，由 `scripts/talent/check_template_fill.py` 现算，不手写。

| 状态 | 格数 | 占 |
|---|---|---|
| 原文 | **71** | 35.5% |
| 原文·空值 | **4** | 2.0% |
| HR 侧 | **5** | 2.5% |
| 缺 | **105** | 52.5% |
| 不适用 | **15** | 7.5% |

## 一、每份 JD 的填空情况

| JD | 岗位类别 | 引用 | 原文 | 原文·空值 | HR 侧 | 缺 | 不适用 |
|---|---|---|---|---|---|---|---|
| 专案工程师 | staff | 9 | 10 | 0 | 0 | 27 | 3 |
| 业务跟单 | staff | 9 | 14 | 0 | 0 | 23 | 3 |
| 关务报关员 | staff | 17 | 15 | 2 | 0 | 20 | 3 |
| 副总助理 | staff | 16 | 18 | 0 | 0 | 19 | 3 |
| 品质经理 | staff | 15 | 14 | 2 | 5 | 16 | 3 |

## 二、5 份 JD **全都填不出来**的字段（这就是标准模板的价值）

共 **10** 个。客户从来不写，但定稿/管理要用 —— 由我方按标准补齐：

| 段 | 字段 | 名称 | 层级 | 判定 | 数据项 |
|---|---|---|---|---|---|
| S1 | `F.JD_JOB_GRADE` | 职级 | optional | internal | — |
| S2 | `F.JD_JOB_PURPOSE` | 岗位目的 | required | not_judgeable | — |
| S6 | `F.SHIFT` | 班制 | conditional | internal | — |
| S6 | `F.JD_ENVIRONMENT` | 环境(噪音/粉尘/温度) | conditional | internal | — |
| S6 | `F.JD_PHYSICAL_DEMAND` | 体力/站立/搬运 | conditional | internal | — |
| S6 | `F.JD_PPE` | 劳保/防护 | conditional | internal | — |
| S6 | `F.JD_WORK_LOCATION` | 工作地点/厂区 | required | internal | — |
| S7 | `F.JD_HEADCOUNT` | 编制/招聘人数 | required | internal | — |
| S7 | `F.JD_HIRING_REASON` | 招聘原因 | optional | internal | — |
| S8 | `F.JD_CONTRACT_TYPE` | 用工类型/合同 | required | internal | — |

另有 **3** 个条件字段在这 5 份京东里没触发（都是经理岗字段，而 5 份京东按原文「直接下属无」全判员工岗）：`F.DECISION_AUTHORITY`、`F.BUDGET_OWNERSHIP`、`F.CROSS_DEPT`

## 三、客户**写了栏目却留空**的字段（补的优先级最高）

| 段 | 字段 | 名称 | 几份空 | 说明 |
|---|---|---|---|---|
| S1 | `F.DEPARTMENT` | 隶属部门 | 1/5 | 关务报关员 |
| S1 | `F.SUPERVISES` | 直接下属 | 1/5 | 关务报关员 |
| S5 | `F.JD_ACTIVITY_TEXT` | 内容 | 1/5 | 品质经理 |
| S5 | `F.JD_ACTIVITY_FREQ` | 频次(日/周/月/年/偶发) | 1/5 | 品质经理 |

## 四、HR 侧 5 条闸门：5 份 JD 里各有几份有数据

| 字段 | 名称 | HR 侧有 | 缺 |
|---|---|---|---|
| `F.AVAILABILITY` | 到岗日期 | 1/5 | 4/5 |
| `F.SALARY` | 薪资 | 1/5 | 4/5 |
| `F.AVG_TENURE` | 平均在职不低于 | 1/5 | 4/5 |
| `F.RECENT_SEGMENTS` | 近 5 年任职不超过 | 1/5 | 4/5 |
| `F.COMMUTE` | 可接受通勤 | 1/5 | 4/5 |
