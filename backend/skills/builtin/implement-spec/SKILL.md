---
name: "Implement Spec（实现规格）"
lang: zh
translated: machine
source: backend/skills/en-originals/implement-spec/SKILL.md
description: "把 `to-spec` 技能与 `to-tickets` 技能产出的结果实现成代码。"
tags:
  - "implement"
  - "spec"
  - "mattpocock"
  - "requirements"
  - "planning"
  - "skills"
triggers:
  - "有人给了你一份规格时。这份规格应当配着工单，描述如何"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
  - "task"
  - "skill"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `mattpocock/skills → skills/engineering/implement-spec`（MIT，原样收录于
> `vendor/upstream-skills/mattpocock/skills/engineering/implement-spec/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


有人给了你一份规格。这份规格应当配着一批工单，工单描述这份规格要怎么实现。

这项工作的工单放在 `docs/tickets/`；如果那里一份都没有，就如实说出来并索要规格，而不是自己编一个。

目标是整份规格都落在**一条集成分支**上实现完，每张工单都按 `docs/tickets/` 收尾工作的方式结清。

工单不是一份步骤清单。它们是一张带阻塞关系的**任务图**。这意味着永远存在一个**前沿**，上面是随时可以领走的工单。

每个子智能体都从全新的上下文窗口开始。

与子智能体之间的通信应当稀疏。主要通过**上下文指针**沟通：指向规格、工单、调研笔记和之前的提交。已经能靠指针取到的信息，不要再复述一遍。

**实现者子智能体**在可能的情况下应当放到后台跑，以求最大并发。

## Steps（步骤）

1. 读规格与工单，弄清这张任务图。

2. （可选）用一个**探索子智能体**去做工单要求的探索——相关的代码库文件或外部文档。确认探索子智能体能够保存文件：它应当把自己的 markdown 笔记存到仓库之外的一个目录，让之后所有子智能体都能取到。这样**实现者子智能体**就能专心实现，而不必再做探索。

3. 建集成分支。如果 `docs/tickets/` 是通过 PR 收尾工作的，或者用户要求了，就在第 5 步第一次合并之后开一个草稿 PR（一个还没有超出 main 的提交的分支开不了 PR），标注它会关闭这份规格与这些工单。

4. 每张工单用一个全新的**实现者子智能体**，各自在自己的 worktree、自己的分支上。每个实现者子智能体：
   - 动手之前先确认自己的 worktree 是基于集成分支的，若不是就 reset 到它上面；
   - 调用 `skill` 工具并传入 `tdd` 来建这张工单；
   - 报告完成之前，把集成分支的最新提交合并进自己的分支

5. 一个**实现者子智能体**完成后，用一个**合并子智能体**把它的成果合进集成分支。

6. 如果这改变了可领工单的**前沿**，就再放出一些**实现者子智能体**去做新出现的工单。这样才能拿到最大并发。

7. 所有工单都完成后，在集成分支上调用 `skill` 工具并传入 `code-review`。用一个全新的**实现者子智能体**把代码评审提出的问题一次修完。

8. 如果存在草稿 PR，就把它标记为可以评审。否则，按 `docs/tickets/` 收尾工作的方式逐张结清工单，并汇报集成分支。

9. 清理所有**实现者子智能体**的 worktree。

## This repository's floor（本仓库的底线）

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  一份文档库报告）。后端测试套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能做出的宣称。
  用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句判词，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 框架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `ecosystem-primer` 规则——并优先选
  能胜任的最高层。
