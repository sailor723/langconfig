---
name: "talent-jd-final（步2·业务与 HR 一起把 JD 定下来）"
description: >-
  客户 JD 已经拆成原子要求后，业务方和 HR 要一起把它定稿时使用：客户写了的照抄，客户没写的标「未写」，
  我方建议只能进附录。同时把空白字段按"不填会怎样"分成 A/B/C 三级，变成一张业务方真会填的回填表，
  HR 从招聘视角补的要求单独成章、并记清是谁提的、为什么提。
tags: [talent, jd, finalize, blanks, hr-requirements]
triggers:
  - "客户 JD 有大量空白字段（班制、时长、频次），要变成一张能填的表时"
  - "我方对 JD 有补充意见，但客户原文不能改时"
  - "HR 提出「稳定一点」「到岗要快」这类要求，需要落成一条可判定要求时"
allowed_tools: [bash, read_file, write_file, edit_file, grep, glob, skill]
author: LangConfig
version: "1.0"
---

你负责**把一份客户 JD 变成可执行的定稿**，并且把"客户没写的"和"我们想加的"分得干干净净。

产物三份：`work/talent/jd_docs/<JD>.定稿.md`、`<JD>.fields.json`、`<JD>.待补清单.md`。

## 第 0 步——环境

```bash
cd <repo>/backend && set -a && source ../.env; set +a
env -u PGPORT .venv/bin/python -m scripts.talent.render_jd_final --jd <JD>
env -u PGPORT .venv/bin/python -m scripts.talent.jd_input_form  --jd <JD>
```

**两条都要跑。** `render_jd_final` 只写「定稿.md」和「fields.json」,**不会更新待补清单**;
少跑第二条,回填表就停在上一次的样子,而你以为它是新的。这条是一个真跑过的 agent 发现的。

## 第 1 步——三种来源必须分开放

定稿里每一个字段只可能来自三处，**混在一处就是整份文档不可信**：

| 来源 | 怎么标 | 规矩 |
|---|---|---|
| 客户写了 | 直接给值 + 原文位置 | 照抄，不改写 |
| 客户没写 | 「未写」 | 不许用常识补，不许用别的 JD 类推 |
| 我方建议 | **只进附录 F** | 不许写进正文，不许用客户口吻 |

这条是我犯过的错：把「我方建议」直接写进定稿正文，客户读到会以为是他自己写的。
所以现在正文里出现任何建议性文字，都是缺陷。

## 第 2 步——空白字段按影响分级问

`jd_input_form` 把空白分成三级，因为它们**责任不同**：

- **A 阻断**：不填这岗就招不了人（班制、工作环境、每日频次）。必须问，而且要问业务方不是 HR。
- **B 解释**：能算匹配，但解释不了"为什么这个岗要这样的人"。
- **C 归档**：只影响文档完整性（文件编号、核准人）。

**混在一张表里问，客户会全都不填。** 所以回填表按级分块，A 级放最前面并写明"不填会怎样"。

## 第 3 步——HR 的要求要单独成章

HR 从招聘视角提的要求（到岗时间、稳定性、通勤、薪资）**也是要求**，走同一套判定，
但必须满足三条，否则门禁会红：

```yaml
- id: HR-01
  origin: hr                     # 必填
  requirement: REQ-HR-NOTICE
  author: HR                     # 必填：谁提的
  rationale: "交接期超过一个月，岗位就空太久了"   # 必填：为什么提
  value: {num: 4}
  # 注意：hr 引用**不许**带 verbatim / txt_line / source_text
```

那三个字段是客户原文的坐标。HR 没有客户原话，给它安一个就是替客户说话。

**取值拿不到就别编**：客户 JD 没写薪资预算，这条的 `value` 就留空。
留空的结果是判定如实报「不可判」，编一个数出来的结果是判错人。

## 第 4 步——过门禁，然后如实交代

```bash
cd <repo>/backend && set -a && source ../.env; set +a
env -u PGPORT .venv/bin/python -m scripts.talent.check_component_catalog
```

要 `N checks · 0 failed · green`。然后报告：

- 客户原文 N 条 / 未写 M 条 / 不适用 K 条 / 我方建议 J 项
- A 级空白有几条，分别是谁的责任（业务方 / 客户 / HR）
- HR 侧要求几条，其中**几条缺取值**（缺取值的那几条现在判不了，要客户补）

## 绝对不要做

- 不要在正文里写我方建议（只能进附录 F）
- 不要用常识替客户补字段
- 不要给 HR 要求编一个客户原话
- 不要因为"这条暂时判不了"就把它从定稿里删掉（判不了要留，并写明卡在哪）

## 交付前回检（**不许跳**）

写结论之前,把**打算写进报告**的每个数字现场重算一遍,并把命令贴出来。

```bash
cd <repo>/backend && set -a && source ../.env; set +a
env -u PGPORT .venv/bin/python -m scripts.talent.render_jd_final --jd <JD>
env -u PGPORT .venv/bin/python -m scripts.talent.jd_input_form  --jd <JD>
env -u PGPORT .venv/bin/python -m scripts.talent.verify_jd_report --jd <JD>
env -u PGPORT .venv/bin/python -m scripts.talent.check_component_catalog
```
四条都要跑。`verify_jd_report` 报的每一行,都要和你要写进报告的数字一致。

### 为什么必须跑

我交过一份报告,里面真话和假话同时存在:
门禁 161 checks 全绿(真)、HermiT 影响面 114→108→99(真),
但「`_source` 7 行」(实际 48)、「有一行含『主导内审』」(这份 JD 没有)、
「excluded 是抬头标题」(实际是 IATF16949)—— **三句假话**。

它们有同一个来源:**从记忆里写**,而记忆来自另一份 JD 或上一轮。
所以规矩是:**每个数字现场重算,每句"原文有 X"现场 grep。记忆不算证据。**

### 三条自查

1. 这个数字我是刚跑出来的,还是记得的?—— 记得的一律重跑
2. 这句话我能指出在文件的哪个位置吗?—— 指不出就是没读
3. 我是不是把**别处**的内容混进来了?—— 报告里的每一句,都要能在**这一份**产物里找到

### 两条"看着像绿的红"

- **门禁没有汇总行 = 没跑完,不算通过。** 一处 YAML 写坏会让门禁中断,
  而它前面的 PASS 已经打印了 —— `tail` 看着完全正常。只认 `N checks · M failed` 那一行。
- **写完不等于写对。** `write_file` 成功之后必须重跑校验,不能凭"它没报错"。
