---
name: Handoff（移交）
lang: zh
translated: machine
source: backend/skills/en-originals/handoff/SKILL.md
description: "把当前对话压缩成一份移交文档，交给另一个智能体接手。"
tags:
  - "handoff"
  - "mattpocock"
triggers:
  - "当被要求写一份总结当前对话的移交文档，好让一个全新的智能体接着干时"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "skill"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
---

> **出处。** 改编自 `mattpocock/skills → skills/productivity/handoff`（MIT，收录于
> `vendor/upstream-skills/mattpocock/skills/productivity/handoff/SKILL.md`）。为本仓库所做的改动：
> frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` / `version`），路径约定
> （`docs/specs`、`docs/tickets`、`work/<scope>`），工具名（`read_file` / `write_file` / `edit_file` /
> `bash` / `grep` / `glob` / `task`），以及一节验证地板。上游的 `disable-model-invocation` 在这里没有
> 对应物——每个技能都能通过 `skill` 工具被发现，所以直接去掉，而不是仿造一个。

## Instructions（指令）

写一份**移交文档**，总结当前对话，好让一个全新的智能体接着干。存到用户操作系统的临时目录（`$TMPDIR`，没有就用 `tmp` 技能；Windows 上是 `%TEMP%`）——不要存到当前工作区。

文档里要有一节"建议技能"，点名下一个智能体该用 `skill` 工具去调哪些技能。

不要重复已经落在其他产物里的内容（规格、计划、ADR、issue、提交、diff）。改用路径或 URL 引用它们。

对任何敏感信息脱敏，例如 API key、密码、个人身份信息。

如果用户传了参数，就把它们当成对下一次会话聚焦点的描述，并据此裁剪这份移交文档。

## 本仓库的地板

- **用真实命令验证，而不是靠眼睛看**：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  文档库报告）。后端全套加 `--full-suite`。
- **后端测试套件有 20 个既有失败。** "不比那个基线更差"才是这里诚实的判据；"测试是绿的"这句话在本仓库你
  说不出口。对照方式：
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`，
  把 `FAILED` 行与记录的基线做 diff。
- **规格、工单与笔记都落在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天里的结论，下一个回合就丢了。
- **生态层级**：智能体代码是 LangChain（`create_agent`）跑在 LangGraph 运行时里，通常外面套一层 Deep Agents
  harness（`deepagents`）。动手前先决定这次改动属于哪一层——`ecosystem-primer` 的规则——并优先用能完成任务的
  最高那一层。
