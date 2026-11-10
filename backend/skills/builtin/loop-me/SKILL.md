---
name: Loop Me（盘问我的循环）
lang: zh
translated: machine
source: backend/skills/en-originals/loop-me/SKILL.md
description: 就我想构建的工作流，在这个工作区里把我盘问出规格来。
tags:
- loop
- me
- mattpocock
- requirements
triggers:
- 要就某条工作流被盘问出规格、且唯一产出是规格时
- 想把一个模糊的工作流想法逼成可执行规格时
allowed_tools:
- read_file
- grep
- glob
- write_file
- edit_file
- bash
- skill
author: mattpocock (MIT), adapted for LangConfig
version: '1.0'
---

## Instructions（指令）

> **来源说明。** 改编自 `mattpocock/skills → skills/in-progress/loop-me`（MIT，原样收录于
> `vendor/upstream-skills/mattpocock/skills/in-progress/loop-me/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


跑一场有状态的 `grilling` 技能会话，唯一产出是**工作流**规格。用 grilling 的纪律（不依不饶、一次问一轮、每个问题都附上建议答案），对准下面这套词汇与目标。随着盘问逐步厘清，相应地创建、编辑、删除规格。

## The loop lens（循环视角）

**循环（loop）** 是用户生活里反复出现的模式：他的职业、他的一周、他的早晨、某一件反复做的活动。把生活看成层层嵌套的循环，就能看出其中的活动其实相当可预测，而这也正是它们值得**委派**出去的原因。用这个视角找出值得写成规格的循环，并主动提出用户自己还没注意到的那些。

**工作流（workflow）** 是一个循环落到实处的规格。你在一个循环上运行工作流：循环就是它运行中的实例。工作流住在 `workflows/*.md` 里，是事实来源。

## Vocabulary（词汇）

一套共享语言，只在某个工作流确实需要时才取用：永远不是一张清单。**不要强加任何结构性设定**：一个工作流不必然需要 AI、不需要检查点、也不需要定时，除非盘问表明它确实需要。

- **触发器（Trigger）**：什么触发每一次运行——一个**事件**（新邮件、新 issue）或一个**定时**（每天早上）。事件触发通常更高效。
- **检查点（Checkpoint）**：人在环中的一点，用户在这里被要求核实或做决定。有些工作流一个检查点都没有、全自动跑；有些则完全不用 AI。
- **右推（Push right）**：把检查点尽量往后推。在把人拉进来之前把能做的活做到最多，这样他只在很晚的时候被问一次，而且一切都已备好。
- **简报（Brief）**：检查点呈现的东西——一份紧凑、可直接决策的摘要（产出了什么、为什么，以及一条指向资产本身的链接），绝不是原始输出。用户读的是简报，不是草稿。审阅速度是硬要求。

## Definition of done（完成的定义）

一份工作流规格，做到某个实现者智能体不用再问任何一个问题就能把它建起来，才算完成。盘问到那一步为止；只要还剩一个问题，就什么都没完成。

## The workspace（工作区）

- `workflows/*.md`：一个工作流一份规格。
- `NOTES.md`：关于用户世界的原始笔记——他用哪些工具、处理哪些渠道，以及他对这两者的自有叫法。当它是空的或太薄时，先就他的世界做访谈，再去写任何规格。随着模糊的说法浮出来，就把它们磨成规范说法，并记在这里。

## This repository's floor（本仓库的底线）

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  一份文档库报告）。后端套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能
  做出的断言。用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句结论，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 脚手架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `lc-ecosystem-primer` 规则——并优先选
  能胜任的最高层。
