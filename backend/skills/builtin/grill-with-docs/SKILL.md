---
name: "Grill with Docs（边追问边写文档）"
description: "一场不留情面的访谈，把计划或设计磨得更锋利；过程中还会顺手写出文档（ADR 与术语表）。"
tags:
  - "grill"
  - "with"
  - "docs"
  - "mattpocock"
  - "design"
triggers:
  - "被要求调用两次 `skill` 工具，分别用于 \"grilling\" 和 \"domain-modeling\" 时"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "skill"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
lang: zh
translated: machine
source: backend/skills/en-originals/grill-with-docs/SKILL.md
---

> **来源。** 改编自 `mattpocock/skills → skills/engineering/grill-with-docs`（MIT，取自 `vendor/upstream-skills/mattpocock/skills/engineering/grill-with-docs/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节校验底线。
> 上游的 `disable-model-invocation` 在这里没有对应物 —— 每个技能都能通过 `skill` 工具被发现，
> 所以它被直接丢弃，而不是勉强模仿。

## Instructions（指令）

调用 `skill` 工具两次，分别用于 "grilling" 和 "domain-modeling"。

## 本仓库的底线

- **用真实命令校验**，不要靠眼睛看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` +
  `vite build` + 一份文档库报告）。加上 `--full-suite` 就跑后端测试套件。
- **后端套件有 20 个先前就存在的失败。** 诚实的标准是"不比这个基线更差"；"测试全绿"在这里
  不是你能下的结论。用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  做对比，并把 `FAILED` 行与记录的基线 diff 一遍。
- **规格、工单和笔记都落在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、
  `work/<scope>/`。写在聊天消息里的结论，下一轮就丢了。
- **生态层**：智能体代码是跑在 LangGraph 运行时里的 LangChain（`create_agent`），通常再由
  Deep Agents 脚手架（`deepagents`）包一层。动手之前先定下这个改动属于哪一层 —— 这就是
  `lc-ecosystem-primer` 规则 —— 并且优先选能解决问题的最高层。
