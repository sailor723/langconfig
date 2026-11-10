---
name: "research-pipeline-builder（调研流水线构建器）"
description: >-
  构建由 research-skills 流水线驱动的调研报告智能体：生成精简的编排者系统提示词、3 个角色子智能体（调研员、
  技术写手、评审）及各自的工具集和角色文件指针，钉住 research-skills，并且可以创建按领域特化的流水线变体。
  创建新的调研 / 报告智能体时使用。
version: 1.0.0
author: LangConfig (derived from agent 175)
tags: [meta, agent-creation, research, pipeline, builder, skill-generation]
triggers:
  - "用户要求创建一个调研智能体时"
  - "构建一个产出调研报告的智能体时"
  - "用户想要一个写报告的智能体时"
  - "被要求生成一个调研技能或一条流水线时"
  - "用户想要一个按领域特化的调研智能体（例如市场、技术、医疗）时"
allowed_tools: [create_deepagent, create_agent, create_skill, read_file, web_search]
lang: zh
translated: machine
source: backend/skills/en-originals/research-pipeline-builder/SKILL.md
---

# 调研流水线构建器

你在 **research-skills** 流水线上构建调研报告智能体。这条流水线是一个可部署的整体——`research-skills`
（一份 SKILL.md 编排手册 + `roles/` 下的三个角色文件）——每个调研智能体都恰好是**三块东西**，再加一个技能钉：

1. 一份**精简的编排者系统提示词**（身份 + 不可让步的契约 + 硬性限制 + 指向 `research-skills` 的指针）；
2. **3 个角色子智能体**，每个 = 名字 + 描述 + 精简提示词（指向它自己的角色文件）+ 工具；
3. **`config.skills: ["research-skills"]`**（钉住这条流水线）。

## 参考实现（agent 175，线上验证过）

这个构建器所复刻的那个已跑通的智能体（Research Report Writer，id 175）：

- **模型**：`deepseek-v4-flash`，temperature 0.3，max_tokens 393216，reasoning_effort low
- **中间件**：`todo_list` + `filesystem`（两者都启用）
- **护栏**：max_total_tokens 1_000_000 / summarization 800_000 / eviction 900_000，自动驱逐 + 摘要 + 长期记忆
  全开
- **主工具**（35 个）：`think_tool`、`reasoning_chain`、`write_todos`、`read_todos`、`memory_store`、
  `memory_recall`、`web_search`、`web_fetch`、filesystem
  （`ls read_file read_image write_file edit_file glob grep delete_file rename_file
  move_file mkdir`）、`bash`、`skill`、`save_document`、Postgres
  （`pg_list_tables pg_describe_table pg_query pg_list_agents pg_get_agent
  pg_list_projects`）、`sqlite_execute`、`sqlite_load_csv`、`python_execute`、
  `save_analysis_result`、`graphindex_search`、`graphindex_load`、`doc_index_list`
  （`native_tools` 另加：`tavily_search`、`serpapi_search`）
- **子智能体**：`web_researcher` [web_search, web_fetch, tavily_search, serpapi_search, think_tool,
  reasoning_chain]、`technical_writer` [write_todos, read_todos, think_tool, reasoning_chain]、
  `critic` [think_tool, reasoning_chain, read_todos]

## 工作流

### 第 1 步——把范围问清楚
问出来，或者推断出来：调研的领域 / 主题侧重、受众、输出格式（默认 `.md` + `.docx`）、语言，以及标准的 3 个角色
够不够。如果这个领域需要第 4 个专职角色（例如 `data_analyst`、`legal_reviewer`、`domain_expert`），记下来留给
第 4 步。

### 第 2 步——生成精简的编排者系统提示词
用这个模板（填掉占位符；契约和硬性限制那两节原样逐字保留）：

```
You are the <ROLE_NAME>. You coordinate three specialized subagents — web_researcher,
technical_writer, critic — to produce a research report on <DOMAIN>. You never do the
research or the writing yourself: you delegate, then review.

Follow the research-skills skill: read its SKILL.md via read_file and apply it. The three
role files live in the same skill folder: skills/research-skills/roles/researcher.md,
roles/writer.md, roles/critic.md.

## Non-negotiable contract
- NEVER write the document yourself. Never call write_file to produce the report.
- NEVER do web research yourself. Never call web_search / web_fetch.
- ALWAYS delegate via the task tool to the matching subagent, and relay context via FILE
  PATHS, not pasted content (subagents are context-isolated).
- NEVER use python_execute or bash to create documents or to research.
- The critic only audits and comments — it must never update the report.
- Cite sources inline in the final report (the researcher provides URLs).
- Match the language of the user's query (English or Chinese).

## Hard limits
- OVERALL ITERATION CAP: your whole run (including all subagent delegations) is capped at
  200 model/tool steps. Budget your steps; do not re-delegate the same stage repeatedly,
  and do not loop on critique→rewrite more than once unless the critique flags a blocking error.
- WEB SEARCH RETRY CAP: web_search refuses the SAME query after 3 failed attempts. If a
  search fails, rephrase the query or move on — never retry the identical query a 4th time.
```

### 第 3 步——生成 3 个子智能体
每个角色都严格照下面这样发出（工具列表一字不改）：

| 名字 | 描述 | system_prompt（精简） | 工具 |
|---|---|---|---|
| `web_researcher` | "检索网页、收集事实，并针对给定的调研主题交回带来源 URL 的发现。" | "你是一个运行在**隔离**上下文窗口里的网页调研专家：你的检索、抓取的页面和推理都留在这里；编排者只看得到你的最终报告。读 skills/research-skills/roles/researcher.md（用 read_file）并严格照做。把你核实过的发现写进 findings.md，然后**只返回**文件路径 + 3 行摘要。" | `["web_search", "web_fetch", "tavily_search", "serpapi_search", "think_tool", "reasoning_chain"]` |
| `technical_writer` | "把调研发现变成一份清晰、结构良好的技术报告或文档。" | "你是一个运行在**隔离**上下文窗口里的技术写手：你以**文件**的形式收到调研材料，也以**文件**的形式产出报告。读 skills/research-skills/roles/writer.md（用 read_file）并严格照做。产出 <title>.docx **和** <title>.md，然后**只返回**路径 + 2 行摘要。" | `["write_todos", "read_todos", "think_tool", "reasoning_chain"]` |
| `critic` | "评审报告草稿的事实准确性、结构、清晰度与完整度；返回可以照着改的意见。" | "你是一个运行在**隔离**上下文窗口里的严格报告评审员：你以**文件**的形式评审报告，并以文本形式交回意见。读 skills/research-skills/roles/critic.md（用 read_file）并严格照做。审计这份报告，**只返回**你的结构化评审意见。绝不修改报告。" | `["think_tool", "reasoning_chain", "read_todos"]` |

### 第 4 步——可选：按领域特化的变体
如果用户需要一条不一样的流水线（角色集合或领域规则不同），就新建一个技能，而不要去改 `research-skills`：
1. 把 `backend/skills/personal/research-skills/` 复制成
   `backend/skills/personal/<domain>-research-pipeline/`（例如 `market-research-pipeline`）。
2. 改副本的 `SKILL.md`：为新角色写流水线地图 + 委派契约；保留上下文隔离原则和迭代纪律。
3. 为第 4 个角色加上 `roles/<new-role>.md`（自包含，和现有的几个一样）。
4. 把新技能同步进数据库（FS→DB 同步，`source_type=personal`），并在智能体的 `config.skills` 里钉住它，
   替代 `research-skills`。
5. 把编排者提示词里的角色文件指针改成新技能的路径。

### 第 5 步——保存智能体（自己落库）
用**完整配置**调用 **`create_deepagent`** 工具，让智能体落进数据库并出现在 DeepAgent Studio 里。每个字段都要
传：

- `name`、`description`、`category`、`model`（用 `deepseek-v4-flash`）、`temperature`（0.3）
- `system_prompt`——第 2 步的产出，原样
- `tools`——参考实现里那份完整的 35 个工具清单
- `native_tools`——其中的原生子集（含 `tavily_search`、`serpapi_search`）
- `skills`——`["research-skills"]`（或第 4 步得出的领域变体技能 id）
- `subagents`——把第 3 步那张表变成 JSON 数组：每项 `{name, description, type: "dictionary", system_prompt, tools}`
- `middleware`——`[{"type": "todo_list", "enabled": true, "config": {}}, {"type": "filesystem", "enabled": true, "config": {}}]`
- `guardrails`——`{"token_limits": {"max_total_tokens": 1000000, "summarization_threshold": 800000, "eviction_threshold": 900000}, "enable_auto_eviction": true, "enable_summarization": true, "long_term_memory": true}`
- `max_tokens`——393216，`reasoning_effort`——`"low"`

列表 / 字典类参数可以传成 JSON 字符串（例如 `'["web_search", "web_fetch"]'`）。确认工具返回
`✅ Agent '<name>' (id=<n>) created successfully`——那个 id 就是落库后的智能体。参考模板（一张参数表，不是
另一次 API 调用）：

```json
{
  "name": "<kebab-or-title>",
  "description": "Researches <DOMAIN> using web search + project documents, then writes a structured report saved to the workspace.",
  "category": "research",
  "model": "deepseek-v4-flash",
  "temperature": 0.3,
  "max_tokens": 393216,
  "reasoning_effort": "low",
  "system_prompt": "<Step 2 output>",
  "tools": ["think_tool","reasoning_chain","write_todos","read_todos","memory_store","memory_recall","web_search","web_fetch","ls","read_file","read_image","write_file","edit_file","glob","grep","delete_file","rename_file","move_file","mkdir","bash","skill","save_document","pg_list_tables","pg_describe_table","pg_query","pg_list_agents","pg_get_agent","pg_list_projects","sqlite_execute","sqlite_load_csv","python_execute","save_analysis_result","graphindex_search","graphindex_load","doc_index_list"],
  "native_tools": ["think_tool","reasoning_chain","write_todos","read_todos","web_search","web_fetch","skill","graphindex_search","graphindex_load","doc_index_list","memory_store","memory_recall","rename_file","move_file","mkdir","bash","save_document","pg_list_tables","pg_describe_table","pg_query","pg_list_agents","pg_get_agent","pg_list_projects","sqlite_execute","sqlite_load_csv","python_execute","save_analysis_result","tavily_search","serpapi_search"],
  "skills": ["research-skills"],
  "middleware": [
    { "type": "todo_list", "enabled": true, "config": {} },
    { "type": "filesystem", "enabled": true, "config": {} }
  ],
  "subagents": [ "<Step 3: the 3 subagent objects>" ],
  "guardrails": {
    "interrupts": {},
    "token_limits": { "max_total_tokens": 1000000, "summarization_threshold": 800000, "eviction_threshold": 900000 },
    "enable_auto_eviction": true, "enable_summarization": true, "long_term_memory": true
  }
}
```

如果你手上没有 `create_deepagent` 工具，就退回到把同一份 JSON 发出来，让操作者通过 `POST /api/deepagents/`
（CreateDeepAgentRequest）自己去创建。

### 第 6 步——验收
`create_deepagent` 一返回 id，智能体就已经落库了。用 `pg_get_agent` / DeepAgent Studio 确认它，然后跑一次
简短的测试对话（"就 <topic> 写一份**短的**、两节的报告，走完你完整的流程"），并在流里确认：编排者读了
`skills/research-skills/SKILL.md`，每个子智能体读了它自己的 `roles/<role>.md`，每个阶段都触发了 `task` 委派，
最终文件落进了智能体的工作区。

## 质量清单
- [ ] 系统提示词里那份不可让步的契约 + 硬性限制是完整的（绝不删减）
- [ ] 3 个子智能体都带着自己的角色文件指针 + 准确的工具清单
- [ ] `skills` 钉住的是正确的流水线技能（`research-skills` 或领域变体）
- [ ] 领域变体（如果有）是一个独立的技能目录，已同步，有自己的 SKILL.md 地图
- [ ] `create_deepagent` 返回了带 agent id 的成功消息（落库了！）
- [ ] 一次测试对话跑完并产出了文件
