---
name: "Wait What（等等，什么？）"
description: "停。上一条消息没传达到：重新讲一遍。"
tags:
  - "wait"
  - "what"
  - "mattpocock"
triggers:
  - "当被告知等一等——我不明白你这里说到哪儿了，要求重新讲一遍、先给一点上文的背景时"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
lang: zh
translated: machine
source: backend/skills/en-originals/wait-what/SKILL.md
---

> **来源。** 改编自 `mattpocock/skills → skills/productivity/wait-what`（MIT，取自 `vendor/upstream-skills/mattpocock/skills/productivity/wait-what/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节校验底线。
> 上游的 `disable-model-invocation` 在这里没有对应物 —— 每个技能都能通过 `skill` 工具被发现，
> 所以它被直接丢弃，而不是勉强模仿。

## Instructions（指令）

等等，我不明白你这里说到哪儿了。重新讲一遍：先给我一点上文的背景，用 ASD-STE100 简化技术英语说话，并且使用 `GLOSSARY.md` 里的通用语言（如果仓库里有不止一份术语表，就按 `GLOSSARY-MAP.md` 找到对的那一份）。

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
  `ecosystem-primer` 规则 —— 并且优先选能解决问题的最高层。
