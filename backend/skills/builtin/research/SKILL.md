---
name: Research（调研）
lang: zh
translated: machine
source: backend/skills/en-originals/research/SKILL.md
description: >-
  针对高可信度的一手来源调研一个问题，并把发现记录成仓库里的 Markdown 文件。当用户希望调研某个主题、收集文档或
  API 事实，或把阅读的跑腿活交给一个后台智能体时使用。
tags:
  - "research"
  - "mattpocock"
triggers:
  - "用户希望调研某个主题、收集文档或 API 事实，或把阅读的跑腿活交给一个后台智能体"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "task"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
---

> **出处。** 改编自 `mattpocock/skills → skills/engineering/research`（MIT，收录于
> `vendor/upstream-skills/mattpocock/skills/engineering/research/SKILL.md`）。为本仓库所做的改动：
> frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` / `version`），路径约定
> （`docs/specs`、`docs/tickets`、`work/<scope>`），工具名（`read_file` / `write_file` / `edit_file` /
> `bash` / `grep` / `glob` / `task`），以及一节验证地板。上游的 `disable-model-invocation` 在这里没有
> 对应物——每个技能都能通过 `skill` 工具被发现，所以直接去掉，而不是仿造一个。

## Instructions（指令）

起一个**后台智能体**去做调研，这样它读材料的时候你还能继续干活。给它一个全新的上下文窗口。

它的任务是：

1. 针对**一手来源**（官方文档、源码、规格、第一方 API）调研这个问题，而不是去看对它们的二手转述。把每一条论断都追溯回拥有它的那个来源。
2. 把发现写进单个 Markdown 文件，逐条标注论断的来源。
3. 存到仓库本来就放这类笔记的地方；沿用已有的约定，如果没有约定，就放在一个说得过去的位置，并说明放在了哪儿。

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
  harness（`deepagents`）。动手前先决定这次改动属于哪一层——`lc-ecosystem-primer` 的规则——并优先用能完成任务的
  最高那一层。
