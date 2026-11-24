---
name: "talent-jd-draft（步1·把客户 JD 拆成原子要求）"
description: >-
  拿到一份客户职务说明书，要把它变成"一条一条能指着原话说'这条我写的'"的原子要求时使用。
  产物是引用文件：每条要求带客户原话、行号、原文整行，并且能逐字回查到原文。
  这不是"抄一份 JD"，也不是"理解客户意思然后重写"——客户原话一个字都不许改。
tags: [talent, jd, extraction, verbatim, requirements]
triggers:
  - "一份新的客户 JD（xlsx/docx/pdf）到手，要落成可判定的原子要求时"
  - "同一句话里有两个约束（「英语熟练及独立书写 8D 报告」）要拆成两条时"
  - "客户原话与要求库里的某条对不上，需要判断是新建还是复用一条要求时"
allowed_tools: [bash, read_any_file, write_file, edit_file, grep, list_files, glob, skill]
author: LangConfig
version: "1.0"
---

你负责**把客户写的岗位要求，变成一条一条可回查的原子要求**。

产物是 `work/talent/jd_links/<JD>.yaml` 和 `work/talent/jd_links/_source/<JD>.txt`。
判断你做完没有，只看一件事：**随便挑一条要求，能不能说出它在原文第几行、并且那一行里真的有那几个字。**


> **这一步由 `Talent · 1 JD 起草` 负责。** 相邻那一步是 `Talent · 2 JD 定稿` —— 遇到不属于本步的活(比如让你出定稿/出回填表),说清该谁做,不要顺手做掉。

## 第 0 步——先确认环境，再动手

```bash
cd <repo>/backend && set -a && source ../.env; set +a
env -u PGPORT .venv/bin/python -c "import psycopg2, rdflib, yaml; print('ok')"
```

`env -u PGPORT` 不是可选的：当前 shell 会导出 `PGPORT=5432`，把默认端口劫持掉，
于是脚本以为库不在。**所有 talent 脚本都要带这个前缀。**

## 第 1 步——原文落盘，保留行号

把客户文件抽成纯文本存到 `jd_links/_source/<JD>.txt`：

```bash
# xlsx：一个 sheet 一个 csv，注意 openpyxl 读不到合并单元格的语义
# docx：textutil -convert txt（macOS）/ pandoc（其他）
# 抽完先 head -40 看一眼，OCR 错字、表格错位都要**留着**，不许修
```

**原文一个字都不改。** OCR 把「年以上」写成「午以上」、把「及」写成「3」，照留。
理由：后面所有判定都要能回查到这一行；你顺手改一个错字，就等于把判定的依据换掉了。

## 第 2 步——切原子要求

一条原子要求 = 客户能指着说「这句是我写的」的最小单位。

- 一句话里两个约束，拆两条：「英语口语熟练及具备独立书写英文8D报告的能力」→
  ① 口语熟练 ② 独立书写英文 8D 报告。因为这两条一个人可能只满足一半。
- 「等」「相关」「优先」**原样保留**，不许替客户把「等工程类专业」扩写成一张清单。
  扩写了就是替客户做决定，而且下游会拿你的清单去排除人。
- 带数字阈值的，把数值记进 `value`（`{num: 3}` / `{min: 25, max: 40}`）；
  没有阈值的（「具备…能力」）就**不要编一个阈值**，`value` 留空。

写进 yaml 的每条引用至少要这些字段：

```yaml
- id: C-05                      # 本文件内唯一
  origin: client                # 客户原话；HR 提的写 hr 并带 author/rationale
  requirement: REQ-C-YEARS-DOMAIN   # 挂到要求库的哪一条
  verbatim: "3年以上品质管理工作经验"   # 必须是原文的**逐字子串**
  source_text: "3年以上品质管理工作经验，熟识线束行业相关产品；"  # 原文的整行
  txt_line: 18                  # verbatim 在 _source 里的真实行号
  section_index: 5
  value: {num: 3, domain: 品质管理}
```

## 第 3 步——挂到要求库，而不是就地发明

`work/talent/requirement_library.yaml` 是 **JD 无关**的要求库（61 条）。顺序是：

1. 先找有没有能复用的。宁可复用一条，也不要为这份 JD 造一条同义要求。
   判据：语义相同、只是阈值不同 → 复用（阈值写在引用上，不写在要求上）。
2. 确实没有，才新建。新建必须带 `rationale`（为什么需要这条）和 `source`。
3. 新建之后跑门禁，门禁会检查「assessable=true 但属性不存在」这类谎话。

**要求库里不许出现"某份 JD 专属"的东西**：阈值、行业、岗位名都在引用里，
要求本身只描述"要比什么"。

## 第 4 步——过门禁

```bash
cd <repo>/backend && set -a && source ../.env; set +a
env -u PGPORT .venv/bin/python -m scripts.talent.check_component_catalog
```

它默认就会逐字回查所有引用（`--links` 默认指向正式目录）。要报告的是这一行：

```
N checks · 0 failed · green
```

红了先改**你的 yaml**，永远不要改门禁的期望值。门禁红了还交付，等于让后面五步全跑在错的原话上。

## 第 5 步——交付前回检（**不许跳**）

写结论之前,先跑这一条,把你**打算写进报告**的每个数字和每句"原文有 X"过一遍:

**两种跑法,同一个实现(结果必须一致):**

```
# ① 工具(优先)—— 你已经挂上了
talent_verify_jd_report(jd="<JD>")

# ② 命令行 —— 给人复核、或贴进报告当可重跑的旁证
cd <repo>/backend && set -a && source ../.env; set +a
env -u PGPORT .venv/bin/python -m scripts.talent.verify_jd_report --jd <JD>
```

工具最后一行会是 `[PASS]` 或 `[FAIL]`。**只有 `[PASS]` 算过**;
`[FAIL]` 或者「回检没能跑完」都按不通过处理 —— 回检自己崩了不等于干净。

它输出一张「主张 → 实测 → 结论」的表,包含:原文行数、客户/HR 引用条数、
每条 verbatim 是否逐字在原文里、txt_line 是否真实行号、excluded 条目、门禁汇总行。

**对不上的项必须改掉或删掉,不许"解释一下"。** 退出码 1 = 有对不上的。

### 这一步为什么必须存在(不是走形式)

我交过一份报告,里面**真的和假的同时在**:

| 我说的 | 实测 | 性质 |
|---|---|---|
| 门禁 161 checks 全绿 | 161 / 0 failed | 真的 |
| HermiT 影响面 114→108→99 | 探针脚本重跑一致 | 真的 |
| `_source` **7 行** | **48 行** | 假的 |
| 「有一行含『建立/维护质量体系』与『主导内审』」 | 这份 JD **没有这句** | 假的 |
| 「excluded 的是抬头标题类文字」 | 是 **IATF16949** | 假的 |

三类假话有同一个来源:**从记忆里写**,而记忆来自**另一份 JD**或上一轮。
所以规矩是:**每个数字现场重算,每句"原文有 X"现场 grep。** 记忆不算证据。

### 三条自查问句

1. **这个数字我是刚跑出来的,还是记得的?** —— 记得的一律重跑。
2. **这句话我能指出在第几行吗?** —— 指不出就是没读原文。
3. **我是不是把别的 JD 的内容混进来了?** —— 报告里出现的句子,必须能在**这一份**原文里 grep 到。

### 两条"看着像绿的红"

- **门禁没有汇总行 = 没跑完,不算通过。** 一处 YAML 写坏(跨行纯量里含「冒号+空格」)
  会让整个引用门禁中断,而它前面的 PASS 已经打印了 —— `tail` 看着完全正常。
  判据只认 `N checks · M failed` 这一行。
- **`write_file`/`edit_file` 写完不等于写对。** 写完必须重跑门禁 + 回检。

## 第 2.4 步——写 `role_type`：它决定用哪版模板

`jd_links/<JD>.yaml` 顶层要有三个键,少了它们第 2 步会直接 **NOT RUN**
(渲染器拒绝猜模板):

```yaml
role_type: staff            # manager | staff | undetermined
role_basis: 由原文 S1.08 直接下属=「无」推得;S1.11 岗位类别待业务方确认
role_confirmed: false
```

判据**只认原文的「直接下属」**,不认岗位名:

```
直接下属 = 有具体人员(「各部门负责人」「专员、文员、电工」) → manager
直接下属 = 无                                            → staff
直接下属 未写                                            → undetermined(**不许猜**)
```

反例要记住:**「品质经理」名字带经理,但原文写「直接下属:无」→ 它是员工岗**。
按名字套经理岗模板,会去问管理幅度和预算(空问),同时把作业频次/时长降级掉。

`role_confirmed` 先写 `false` —— 这是你从原文推的,等业务方在 S1.11 上确认后再改 `true`。

## 第 2.5 步——客户明说「还没定」的句子，必须登记

原文里会出现**客户自己承认某项还没定**的句子：「目前没制定」「暂无」「待定」这类。
(品质经理的 `_source` 第 106 行就有一句孤零零的「目前没制定」。)

它**不是**任职资格，所以**不进 `citations`**——进引用就等于把"没定"当成一条要求。
但它也**不是噪音**：客户亲口承认的空白，比我们猜出来的空白可信得多，第 2 步的待补清单最该先问它。

登记进 `jd_links/<JD>.yaml`：

```yaml
undefined_statements:
- txt_line: 106
  text: 目前没制定
  likely_field: 未知（原文没有标签，需要问客户）
```

**门禁会检查**：`_source` 里出现这类句子的那一行，要么被某条引用占了（`txt_line` 相同），
要么在 `undefined_statements` 里点过名。**不登记就是红**——因为它会无声消失。

## 第 2.6 步——note 里不许引用账本里没有的签署

在 `note` 里写「admin 已定」「人工确认过」「已确认」，那条**必须**在
`jd_reviews/<JD>.yaml` 里有对应记录（按引用 id 匹配），否则门禁红。

**没有记录的签署等于没有签署。** 2026-11-20 品质经理的 C-03 就引用了旧账本里的「admin 定」，
而当时的账本里并没有这一条——被审的文件给自己作证，是这条链上最难查的错。

## 复审模式——admin 只给你一个 JD 名或文件路径时

**这是最常见的用法:admin 贴过来一个路径,你不需要再问任何东西,直接开干。**

```
work/talent/jd_links/人资专员.yaml     ← 给了文件,JD 名 = 文件名去掉 .yaml
人资专员                              ← 只给了名字,文件 = work/talent/jd_links/人资专员.yaml
```

路径都是**相对仓库根**的。找不到就直说「`jd_links/<JD>.yaml` 不存在,这份 JD 还没做第 1 步」,
不要自己猜一个近似的名字,更不要凭客户原文重抽。

### 复审只做四件事,一个字都不许重抽

**这不是重做第 1 步。** `verbatim` / `txt_line` / `source_text` / `requirement` / `value`
**一个字都不许改** —— 它们是逐字回查的对象,改了这条链就断了。
`_source/<JD>.txt`、`requirement_library.yaml`、`component_catalog.yaml` 也都不许动。

| # | 做什么 | 写到哪 |
|---|---|---|
| 1 | **粒度**:verbatim 里出现「及 / 以及 / 、 / 或 / 和 / /」的,判断该不该拆 | 该条的 `granularity_decision`(status: `confirmed_keep` / `confirmed_split`)+ `jd_reviews/<JD>.yaml` 一条 `kind: granularity` |
| 2 | **排除**:有没有引用其实是「岗位职责 / 工作内容」段的(不是任职资格) | 移进 `excluded`(写行号、原文、为什么)+ 账本一条 `kind: exclusion` |
| 3 | **客户说没定的句子**:`没制定 / 暂无 / 待定 / 未定 / 尚未` | `undefined_statements`(带 `txt_line` + 原文)。没有就留空,**不要编** |
| 4 | **note**:每条一句 —— 这条拿不准什么、下游判不判得了 | 该条的 `note`。判不了就写判不了 |

三条判断纪律:

- **`signoff: pending`**:你没有 admin 的签字权。账本里一律写 `signoff: pending`,
  **不要写 `decided_by` / `decided_at`** —— 门禁会单独把它们列为"未签署",那是给人看的,不是缺陷。
- **不要为了凑数**:"及"出现在「高中**及**以上学历」里是阈值写法,"、"出现在「1、2、3、」里是列表序号 ——
  **都不是拆分信号**。这两类假信号实测都出现过(工程文员那轮)。
- **只有真落在职责段才排除**。判不准就写进 note 问,不要硬排除。

### 收尾:两条命令 + 汇总行原文

```bash
cd <repo>/backend && set -a && source ../.env; set +a
env -u PGPORT .venv/bin/python -m scripts.talent.check_component_catalog
env -u PGPORT .venv/bin/python -m scripts.talent.verify_jd_report --jd <JD>
```

**把这两条各自的汇总行原文贴出来**(`N checks · M failed` / `N 项 · 不一致 M 项`)。
然后报告:① 几条该拆、你判了什么;② 有没有排除、为什么;③ 有没有登记"客户说没定";
④ 两条汇总行;⑤ 你拿不准、需要 admin 签字的地方。

## 交付时说什么

- 这份 JD 拆出多少条原子要求，其中多少条是复用、多少条是新建
- `N checks · 0 failed`
- **哪几条你拿不准粒度**（比如一句里塞了三个动作），列出来让人确认
- 哪几条客户写得太含糊、下游一定判不了（「良好的沟通能力」这类）

## 绝对不要做

- 不要改客户原文的一个字，包括错字
- 不要把「等」「优先」这类开放词收窄成清单
- 不要把职责段（做什么）混进要求段（要什么）
- 不要给没有阈值的定性要求编一个阈值
- 不要因为一条要求目前判不了就删掉它 —— 判不了要如实保留并标原因
