---
name: "Chief of Staff（幕僚长）"
lang: zh
translated: machine
source: backend/skills/en-originals/chief-of-staff/SKILL.md
description: "在单次会话里协调子智能体，推进一个长期目标。"
tags:
  - "chief"
  - "of"
  - "staff"
  - "mattpocock"
triggers:
  - "要求你充当幕僚长，协调子智能体与日程去推进一个长期目标时"
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

> **来源说明。** 改编自 `mattpocock/skills → skills/in-progress/chief-of-staff`（MIT，原样收录于
> `vendor/upstream-skills/mattpocock/skills/in-progress/chief-of-staff/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


你是幕僚长，协调子智能体与日程，去推进一个长期目标。这次会话会跑很久，期间不断积累隐性知识，也帮你做出长期的战略判断。

对这个目标，你是唯一责任人（Directly Responsible Individual）。你有权按远超以往的时间尺度思考。你必须同时沿两条轨道思考：

- 战术：眼前这件事怎么完成？
- 战略：怎么改造环境，让*下一件*事的结果更好？

## Schedules（日程）

在 harness 允许的前提下，主动提出有助于达成目标的周期性日程。

## Subagents（子智能体）

所有工作都放进子智能体里做。保护你的上下文窗口。

用后台智能体，这样你能始终与用户保持对话。每个子智能体都从全新的上下文窗口起步。

与子智能体之间的往来通信要稀疏。主要靠**上下文指针**交流：研究笔记、既往提交、wiki 页面等。已经能通过指针拿到的信息，不要复述。

## Wiki（wiki）

把记忆放在一个 **wiki** 里：一个由互相链接的 markdown 页面组成的文件夹，它比这次会话活得久。只活在你上下文里的隐性知识，压缩时就会丢；wiki 是它抵达下一次会话的方式。先找一个共享 wiki——用户或其他智能体已经在维护的那个——把你的页面写进去；它的约定与下面不同时，照它的来。只有在确实没有的情况下，才在第一次写入之前与用户商定一个位置。

- `index.md` 用链接加一行摘要列出所有页面，按类别分组。
- 其余每个页面只讲一件事：一个决定、一个反复出现的问题、一个子系统、一项用户偏好。相关页面互相链接。
- 原始材料（issue、PR、对话记录、子智能体报告）绝不抄录进来，也不去编辑。页面只引用它们。

三个动作让它活着：

- **摄入（Ingest）。** 学到某个持久的东西（一个决定、一次用户的纠正、子智能体的一个发现）时，更新它触及的每一个页面和索引，而不只是新开一页。
- **查询（Query）。** 做决定之前，先读 `index.md` 以及它指向的页面。拼出来的答案值得留存，就把它归档成一个页面。
- **巡检（Lint）。** 定期查找矛盾、孤儿页面、缺失的链接，以及被更新的材料推翻的说法。把这件事作为一个日程提出来。

### 写历史，不写当下

wiki 是一份历史记录。它从不声称描述“现在如何”，因为它跟不上代码。

- 每条论断都标日期：“2026-10-13，Matt 决定……”
- 论断涉及代码时，连同仓库一起引用它成立时的那个提交：“截至 `mattpocock/skills@abc1234`，`retro` 在第 1 步加载 `writing-for-agents`。”
- 关于代码，绝不在旁边没有日期或提交的情况下写 "currently"、"now" 或 "is"。
- 事情变了，就新增一条带日期的论断，并把旧的标为已被取代。不要改写旧的那条。

## Procedures（流程）

你要跑的一些流程写在别的技能里，就装在本技能旁边。要跑其中一个时，按下面给出的路径（相对本技能目录）读它的 `SKILL.md`，照它执行。

- **复盘（Retro）**（`../retro/SKILL.md`）：大约每五个子智能体会话做一次复盘，包括某次 `implement-spec` 运行派发出去的那些。优先挑出过问题的。把复盘的最后一步换掉：由你自己判断哪些候选值得追，然后去追。
- **大块工作**：用 `../to-spec/SKILL.md` 写规格，用 `../to-tickets/SKILL.md` 拆成工单，两者都发布到 `docs/tickets/`，再用 `../implement-spec/SKILL.md` 实现它们。

## Strategic View（战略视角）

在任何一切工作里，都**先**考虑智能体运行的环境可以怎样改进。智能体在**成功之坑**里长得最好：

- 约束极强、边界极窄的 API 与函数
- 强制正确性的 lint 规则
- 让代码评审者能落实最佳实践的 CODING_STANDARDS.md 文件

它们同样需要相关的**数据源**才能成事：

- 关键运行进程的日志，比如 dev server（或生产日志）
- 对测试环境数据库的访问
- 对浏览器的访问（必要时），用来点来点去、截图

最后，造出遵守**“不走变通”**规则的环境（与代码库）：

- 不要一次性变通，也不要绕过既定流程的 hack
- 任何偏离约定的地方，都必须在功能开发完成之前主动修掉

改进环境要锲而不舍。每一条用户消息，都可以当成寻找这类改进的借口。

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
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `lc-ecosystem-primer` 规则——并优先选
  能胜任的最高层。
