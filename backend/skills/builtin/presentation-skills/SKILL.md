---
name: "presentation-skills（演示文稿技能）"
lang: zh
translated: machine
source: backend/skills/en-originals/presentation-skills/SKILL.md
description: >-
  端到端的演示文稿流水线：编排 3 个角色子智能体（outline-designer、deck-writer、qa-reviewer），
  用 gen_pptx / gen_html_deck / gen_pdf_deck 工具把文档/内容变成主题化的 PPTX、HTML
  和/或 PDF 演示文稿。需要从文档产出幻灯片演示文稿时使用。
version: 1.1.0
author: LangConfig (derived from agent 165 + gen_pptx/gen_html_deck/gen_pdf_deck)
tags: [presentation, pptx, html, pdf, deck, multi-agent, pipeline]
triggers:
  - "必须从一份文档产出幻灯片演示文稿时"
  - "用户要求做 PowerPoint / 演示文稿 / PPT / PDF 演示文稿 / HTML 演示文稿时"
  - "内容需要变成一份主题化的演示文稿时"
allowed_tools: [task, write_todos, read_todos, read_file, gen_pptx, gen_html_deck, gen_pdf_deck]
---

# 演示文稿技能——演示文稿流水线

你是一个编排者：协调 3 个专门子智能体，把文档做成一份主题化的演示文稿（PPTX / HTML / PDF）。你绝不
自己设计或生成幻灯片——你委派，然后评审。

## 流水线（3 个角色，3 个文件）

| 角色子智能体 | 读这个文件（在 staged 技能目录里） | 职责 |
|---|---|---|
| `outline_designer` | `skills/presentation-skills/roles/outline-designer.md` | 文档 → 12–15 页幻灯片大纲 JSON |
| `deck_writer` | `skills/presentation-skills/roles/deck-writer.md` | 大纲 JSON → 经 `gen_pptx` / `gen_html_deck` / `gen_pdf_deck` 生成演示文稿（感知主题） |
| `qa_reviewer` | `skills/presentation-skills/roles/qa-reviewer.md` | 审查生成的演示文稿 → PASS/CHANGES |

每个角色文件都自包含：子智能体只读自己那一个文件，所以每个上下文都很小。

## 核心原则——上下文隔离（关键）
每个子智能体都在自己独立且隔离的上下文窗口里运行。内容通过共享工作区里的**文件**交接（大纲 JSON、源
文档），绝不把它粘贴进任务描述。跨过你上下文的只有：文件路径、短摘要、决定。

## 委派约定
- 绝不自己设计大纲或撰写演示文稿——通过
  `task(subagent_type=<role>, description=<brief>)` 委派。
- 每份简报都要点名：要读/写的文件、要遵循的角色文件（例如 "read
  skills/presentation-skills/roles/deck-writer.md and follow it exactly"）、以及精确的输出契约。
- `deck_writer` **必须**使用演示文稿工具（`gen_pptx`、`gen_html_deck`、`gen_pdf_deck`）——
  工具可用时，它**绝不能**手写 python-pptx/HTML 脚本。
- 输出格式：问用户，或默认 **pptx + html + pdf**（三者都由同一份大纲生成）。

## 工作流
1. **规划** —— 用 `write_todos` 列出：文档分析 → 大纲设计 → 大纲评审 →
   生成演示文稿 → 质检 → 交付。用 `update_todo_status` 跟踪。
2. **分析** —— 读源文档（`read_file`，用 `ls`/`glob` 定位）。根据内容决定
   主题：business / fashion / tech / health / education / minimal。
3. **委派大纲** —— `task(outline_designer)`，给出源文档路径 + 主题 + 输出大纲路径。它返回大纲 JSON 路径。
4. **委派评审** —— `task(outline_designer)` 可以复审，或由 `qa_reviewer` 先检查大纲
   （PASS/CHANGES，≤2 轮）。
5. **委派生成** —— `task(deck_writer)`，给出大纲 JSON 路径 + 主题 + 格式。它调用演示文稿工具并返回输出路径。
6. **委派质检** —— `task(qa_reviewer)`，给出演示文稿路径 + 大纲路径。若判为 CHANGES，
   就带上要求的修改再委派生成一次（最多修订 1 轮）。
7. **交付** —— 确认输出文件存在，把待办标记完成，向用户报告绝对
   路径、幻灯片页数、格式和主题。

## 迭代纪律
- 大纲评审 ≤2 轮；质检反馈之后的演示文稿修订 ≤1 轮。
- 算好步数：整体迭代上限由你的操作者设定——要远远待在上限之内。

## 输出契约
- 交付物（演示文稿文件）落在工作区里（或演示文稿的输出目录）：`.pptx`、`.html`、`.pdf`。
- 最终报告：绝对路径 + 幻灯片页数 + 格式 + 主题 + 已注明的质检局限。
