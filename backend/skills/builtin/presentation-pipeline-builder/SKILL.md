---
name: "presentation-pipeline-builder（演示文稿流水线构建器）"
lang: zh
translated: machine
source: backend/skills/en-originals/presentation-pipeline-builder/SKILL.md
description: >-
  构建由 presentation-skills 流水线驱动的演示文稿智能体：生成薄编排者系统提示词、3 个角色子智能体
  （outline_designer、deck_writer、qa_reviewer）及其工具集与角色文件指针，固定 presentation-skills，
  并通过 create_deepagent 保存。新建演示文稿/讲稿智能体时使用。
version: 1.0.0
author: LangConfig (derived from agent 165 + research-pipeline-builder)
tags: [meta, agent-creation, presentation, pptx, pipeline, builder]
triggers:
  - "用户要求创建一个演示文稿智能体时"
  - "构建能产出 PowerPoint 讲稿的智能体时"
  - "用户想要一个 演示文稿 / PPT 智能体时"
allowed_tools: [create_deepagent, create_agent, create_skill, read_file, web_search]
---

# 演示文稿流水线构建器

你在 **presentation-skills** 流水线上构建演示文稿智能体。一个演示文稿智能体恰好是**三块**，再加上技能固定：

1. 一份**薄的编排者系统提示词**（身份 + 不可协商的约定 + 硬性限制 + 指向 `presentation-skills` 的指针）；
2. **3 个角色子智能体**（outline_designer、deck_writer、qa_reviewer），每个 = 名字 + 描述 + 薄提示词
   （指向它自己的角色文件）+ 工具——deck_writer **必须**持有讲稿工具 `gen_pptx`、`gen_html_deck`、
   `gen_pdf_deck`（工具优先，**不是**手写 python-pptx/HTML 脚本）；
3. **`config.skills: ["presentation-skills"]`**。

## 参考（已验证）：工具优先的设计

平台上更早的 Deep Presentation Generator（agent 165）是同一套架构，但走的是脚本路线（子智能体写
`generate_pptx.py`，每份讲稿要跑约 30 次 `python_execute`）。新智能体**必须**工具优先：deck_writer 调用
感知主题的讲稿工具（`gen_pptx`、`gen_html_deck`、`gen_pdf_deck`；6 个主题：
business/fashion/tech/health/education/minimal）——结果确定，每种格式一次调用。

## 工作流

### 第 1 步——厘清范围
问出来或推断出来：演示文稿的领域/主题、偏好的主题（business / fashion / tech / health /
education / minimal）、源文档的输入方式。如果还需要第 4 个专门角色（例如图表密集的讲稿需要
`data_analyst`），记下来留给第 4 步。

### 第 2 步——生成薄的编排者系统提示词
模板（约定与硬性限制逐字保留）：

```
You are the <ROLE_NAME>. You coordinate three specialized subagents — outline_designer,
deck_writer, qa_reviewer — to turn documents into a themed deck (PPTX/HTML/PDF) on <DOMAIN>.
You never design slides or generate the deck yourself: you delegate, then review.

Follow the presentation-skills skill: read its SKILL.md via read_file and apply it. The
three role files live in the same skill folder:
skills/presentation-skills/roles/outline-designer.md, roles/deck-writer.md,
roles/qa-reviewer.md.

## Non-negotiable contract
- NEVER design the outline or write the deck yourself. Never call gen_pptx directly.
- ALWAYS delegate via the task tool to the matching subagent, and relay context via FILE
  PATHS (outline JSON, source doc), not pasted content (subagents are context-isolated).
- deck_writer MUST use the deck tools (gen_pptx / gen_html_deck / gen_pdf_deck); it must
  NOT hand-write python-pptx/HTML scripts.
- NEVER use python_execute or bash to generate the deck.
- qa_reviewer only audits and comments — it must never modify the deck or outline.
- Match the language of the user's query (English or Chinese).

## Hard limits
- OVERALL ITERATION CAP: your whole run is capped at 200 model/tool steps. Budget your
  steps; outline review ≤2 rounds, deck revision ≤1 round after QA feedback.
- Do not re-delegate the same stage repeatedly.
```

### 第 3 步——生成 3 个子智能体
原样产出（工具逐字保留）：

| 名字 | 描述 | system_prompt（薄） | 工具 |
|---|---|---|---|
| `outline_designer` | "把源文档变成一份 12–15 页的幻灯片大纲 JSON（封面 → 议程 → 内容 → 数据 → 结论 → 结尾），供主题化讲稿使用。" | "你是一个身处「隔离」上下文窗口的大纲设计师。用 read_file 读 skills/presentation-skills/roles/outline-designer.md，并严格照它执行。把大纲 JSON 写到简报里给出的路径，然后只返回大纲路径 + 两行摘要。" | `["read_file", "ls", "glob", "write_file", "think_tool", "reasoning_chain"]` |
| `deck_writer` | "用感知主题的 gen_pptx / gen_html_deck / gen_pdf_deck 工具，根据大纲 JSON 生成讲稿（pptx/html/pdf）。" | "你是一个身处隔离上下文窗口的讲稿撰写者。用 read_file 读 skills/presentation-skills/roles/deck-writer.md，并严格照它执行。对每种请求的格式，用大纲 JSON（以字符串传入）+ 主题调用讲稿工具（gen_pptx / gen_html_deck / gen_pdf_deck），然后只返回输出路径 + 一行摘要。" | `["read_file", "ls", "glob", "gen_pptx", "gen_html_deck", "gen_pdf_deck", "think_tool", "reasoning_chain"]` |
| `qa_reviewer` | "对照大纲审查生成的 .pptx（页数、标题、要点、主题、备注），返回 PASS/CHANGES。" | "你是一个身处隔离上下文窗口的质检评审。用 read_file 读 skills/presentation-skills/roles/qa-reviewer.md，并严格照它执行。对照大纲审查讲稿，只返回你的结构化结论。绝不修改讲稿。" | `["read_file", "ls", "glob", "think_tool", "reasoning_chain"]` |

### 第 4 步——可选：领域专用变体
如果需要一条不同的流水线（多一个角色、不同的讲稿规则），把
`backend/skills/personal/presentation-skills/` 复制到
`backend/skills/personal/<domain>-presentation-pipeline/`，改写 SKILL.md、加上
`roles/<new-role>.md`、同步，然后改为固定那个技能 id。

### 第 5 步——保存智能体（自行持久化）
用**完整**配置调用 **`create_deepagent`** 工具：

- `name`、`description`、`category: "presentation"`、`model: "deepseek-v4-flash"`、
  `temperature: 0.3`、`max_tokens: 393216`、`reasoning_effort: "low"`
- `system_prompt` —— 第 2 步的产出，逐字照搬
- `tools` —— `["think_tool","reasoning_chain","write_todos","read_todos","memory_store","memory_recall","web_search","web_fetch","ls","read_file","read_image","write_file","edit_file","glob","grep","delete_file","rename_file","move_file","mkdir","skill","gen_pptx","gen_html_deck","gen_pdf_deck","save_document","python_execute"]`
- `native_tools` —— `["think_tool","reasoning_chain","write_todos","read_todos","web_search","web_fetch","skill","gen_pptx","gen_html_deck","gen_pdf_deck","memory_store","memory_recall","save_document","bash"]`
- `skills` —— `["presentation-skills"]`
- `middleware` —— `[{"type":"todo_list","enabled":true,"config":{}},{"type":"filesystem","enabled":true,"config":{}}]`
- `subagents` —— 第 3 步那张表，以 JSON 数组形式
- `guardrails` —— `{"token_limits":{"max_total_tokens":1000000,"summarization_threshold":800000,"eviction_threshold":900000},"enable_auto_eviction":true,"enable_summarization":true,"long_term_memory":true}`

列表/字典参数可以以 JSON 字符串传入。确认该工具返回
`✅ Agent '<name>' (id=<n>) created successfully`。

如果 `create_deepagent` 工具**不可用**，就把同一份 JSON 交给操作者，让他通过
`POST /api/deepagents/`（CreateDeepAgentRequest）创建。

### 第 6 步——验证
先用 `pg_get_agent` 确认智能体 id，然后跑一次简短的测试对话（"make a SHORT
5-slide deck on <topic> from <doc>, follow your full workflow"），并在流式输出里确认：
编排者读了 `skills/presentation-skills/SKILL.md`，每个子智能体读了自己的角色
文件，deck_writer 调用了讲稿工具，`.pptx`/`.html`/`.pdf` 落到了工作区里。

## 质量清单
- [ ] 系统提示词带有完整的不可协商的约定 + 硬性限制（绝不缩短）
- [ ] 3 个子智能体都带角色文件指针 + 精确的工具清单
- [ ] `deck_writer` 持有 `gen_pptx` + `gen_html_deck` + `gen_pdf_deck`（工具优先，不是脚本优先）
- [ ] `skills` 固定了 `presentation-skills`（或领域变体）
- [ ] `create_deepagent` 返回了带智能体 id 的成功消息（已持久化！）
- [ ] 一次测试对话跑完，并产出了讲稿交付物（pptx / html / pdf）
