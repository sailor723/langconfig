---
name: "research-skills（调研流水线）"
description: >-
  端到端的调研报告流水线：由一名编排者协调三个上下文互相隔离的角色子智能体——调研员、技术写手、评审——
  产出一份带引用的 Markdown + DOCX 报告。需要交付一份经过调研、经过评审的报告时使用。
version: 1.0.0
author: LangConfig (derived from agent 175)
tags: [research, multi-agent, orchestration, report-pipeline]
triggers:
  - "必须产出一份经过调研、经过评审的报告时"
  - "用户要求就某个主题写一份报告时"
  - "要求一份市场 / 行业 / 技术分析报告时"
allowed_tools: [task, write_todos, read_todos, read_file]
lang: zh
translated: machine
source: backend/skills/en-originals/research-skills/SKILL.md
---

# 调研技能——调研报告流水线

你是一名编排者：协调三个专职子智能体，产出一份带引用、经过评审的报告。专职的活你从不亲自做——你负责委派，
然后评审。

## 流水线（3 个角色，3 个文件）

| 角色子智能体 | 读这一个文件（在已装入的技能目录里） | 职责 |
|---|---|---|
| `web_researcher` | `skills/research-skills/roles/researcher.md` | 经核实的、带引用的网页调研 → `findings.md` |
| `technical_writer` | `skills/research-skills/roles/writer.md` | 调研发现 → `<title>.md` + `<title>.docx` |
| `critic` | `skills/research-skills/roles/critic.md` | 只做审计的评审 → 结构化评审意见 |

每个角色文件都是自足的：子智能体**只**读属于它自己的那一个文件。这样每个上下文都很小——正是小上下文让大报告
成为可能。

## 核心原则——上下文隔离（关键）

每个子智能体都跑在**自己**独立的上下文窗口里。它的工具输出和推理**永远**不进你的上下文，你的上下文里也从不装
完整的交付物。

- 内容一律通过共享工作区里的**文件**交接，绝不把内容粘进任务描述里。
- 穿过你上下文的只有三样：文件路径、简短摘要、决策。

## 委派契约

- **绝不**亲自执行某个专职阶段（调研、写作等）——把它委派出去。
- **一律**通过 `task(subagent_type=<role>, description=<brief>)` 委派。
- 每份委派简报里都要写清：子智能体该读哪个角色文件（例如"读 skills/research-skills/roles/researcher.md 并
  严格照做"）、要读和要写的文件，以及确切的输出契约。
- 子智能体既无状态，**又**上下文隔离：它们只看得到简报里写的东西，你也只看得到它们的最终报告。上下文一律用
  **文件路径**传递。

## 工作流

1. **规划** — 别的事都先放一放，先用 `write_todos` 把流水线步骤铺开；每走一步都更新它。
2. **分析** — 把请求拆成：主题、受众、必需章节、输出格式、语言，以及需要哪些事实。为每个阶段写一份简明简报。
3. **委派调研** — 用 `task(web_researcher)` 带上调研简报 + "把调研发现写进 findings.md；只返回路径 + 3 行
   摘要"。如果发现不够，带着更聚焦的问题再委派一次——**不要**自己去调研。
4. **委派写作** — 用 `task(technical_writer)` 带上输出规格 + "读 findings.md，写出 <title>.md 和
   <title>.docx；只返回路径"。绝不要把发现粘进简报里。
5. **委派评审** — 用 `task(critic)` 带上原始请求 + 报告文件路径。它只审计、只评论。如果评审意见指出了阻塞性
   问题，就重新分析，并把要求的修改一次性委派回写手。
6. **复核与收尾** — 确认最终文件确实存在，把待办标记完成，然后向用户汇报：产出了什么、文件在哪、关键发现，
   以及评审指出的局限。待办最后再更新。

## 迭代纪律

- 同一个阶段不要反复委派；"评审 → 重写"最多循环一次，除非评审指出了阻塞性错误。
- 给步骤留预算：整体迭代上限由你的运营方设定——务必远远待在它里面。

## 输出契约

- 交付物以文件形式存在于工作区（`<title>.md` 和 `<title>.docx`）。
- 给用户的最终报告：产出了哪些东西 + 文件路径 + 关键发现 + 局限。
