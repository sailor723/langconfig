---
name: "Prototype（原型）"
lang: zh
translated: machine
source: backend/skills/en-originals/prototype/SKILL.md
description: >-
  写一个用完即弃的原型，用来回答一个设计问题。适用于用户想快速验证某个状态模型或业务逻辑是否
  感觉对路，或者想探一探某个 UI 该长什么样。
tags:
  - "prototype"
  - "mattpocock"
  - "design"
triggers:
  - "用户想快速验证某个状态模型或逻辑是否感觉对路，或想探一探某个 UI 该长什么样"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "bash"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `mattpocock/skills → skills/engineering/prototype`（MIT，原样收录于
> `vendor/upstream-skills/mattpocock/skills/engineering/prototype/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


# 原型

原型是**用完即弃、只为回答一个问题而写的代码**。问题决定它的形状。

## Pick a branch（选一条分支）

先确定要回答的是哪个问题——依据用户的提示词、周围的代码，或者干脆问用户（如果人在）：

- **“这套逻辑 / 状态模型感觉对吗？”** → [LOGIC.md](LOGIC.md)。产出一个可分享的单页 HTML 文件（自由操作按钮 + 分标签的引导式走查），把状态机推进到那些在纸上很难推理的情形，并且让非开发者也能自己驾驶。
- **“它该长什么样？”** → [UI.md](UI.md)。在同一个路由上生成几个差异极大的 UI 变体，靠 URL 查询参数和一个浮动底栏切换。

两条分支产出的东西截然不同，选错就浪费了整个原型。如果问题确实模糊、又联系不上用户，就默认选与周围代码更匹配的那条（后端模块 → 逻辑；页面或组件 → UI），并把这一假设写在原型顶部。

## Rules that apply to both（两条分支都适用的规则）

1. **从第一天起就是用完即弃，并明确标注。** 把原型代码放在它真正会被使用的地方附近（紧挨着它所原型化的模块或页面），上下文才明显；但命名要能让随便一个读者看出这是原型，不是生产代码。用完即弃的 UI 路由，照项目既有的路由约定来，不要另造一套顶层结构。
2. **运行成本要低到可以忽略。** UI 原型用项目任务运行器里的一条命令就能起：`pnpm <name>`、`python <path>`、`bun <path>` 等。逻辑演示是一个双击就能打开的 HTML 文件。总之，启动它不需要动脑。
3. **默认不做持久化。** 状态放在内存里。持久化正是原型要_验证_的东西，而不是它该依赖的东西。如果问题本身明确涉及数据库，就打一个草稿库或一个本地文件，名字写得清清楚楚：“PROTOTYPE, wipe me”。
4. **跳过打磨。** 不写测试，错误处理只做到让原型_跑得起来_为止，不做抽象。要点是快速学到东西。
5. **把状态亮出来。** 每个动作之后（逻辑），或每次切换变体时（UI），把相关的完整状态打印或渲染出来，让用户看见到底变了什么。
6. **做完就把它留档。** 把经过验证的决定并进真实代码，然后把原型本身当作**一手资料**保存：提交到一个用完即弃的分支，从 `main` 上拿出去，并在实现工单里留一条指向该分支的上下文指针。答案（那个结论，以及它解决掉的问题）也一并记进工单或提交里。主分支只保留经过验证的决定。

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
