---
name: "Software Factory（软件工厂）"
lang: zh
translated: machine
source: backend/skills/en-originals/software-factory/SKILL.md
description: "设计软件工厂时共用的那套语言：它运行哪些任务，又接入哪些服务。"
tags:
  - "software"
  - "factory"
  - "mattpocock"
  - "design"
triggers:
  - "要设计一个 software factory（把工单、PR 与排期变成已合并代码的智能体系统）时"
  - "要确定工厂里任务与服务共用的那套语言时"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
  - "skill"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `mattpocock/skills → skills/in-progress/software-factory`（MIT，原样收录于 `vendor/upstream-skills/mattpocock/skills/in-progress/software-factory/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


**software factory（软件工厂）** 是一套智能体系统，把工单、PR 与排期变成已合并的代码，跑在用户选定的远程基础设施上。本技能就是设计它时用的那套语言。讨论或白板画一个工厂时，只用下面这些术语，别的不用；用户如果伸手去用 _避免_ 里的词，就把规范词点出来。

## 任务与运行

**Task（任务）**：
工厂执行的一类工作，只定义一次、可运行多次：review、explore、implement、ratchet。一个任务可以作用于一张工单、一个 PR，或者整个代码库。
_避免_：job、workflow、action

**Trigger（触发器）**：
启动一次运行的事件：工单跟踪器或 git host 里的一次变更、编排器里的一个时钟，或者另一次运行。

**Run（运行）**：
一个任务在一个 runner 上的一次执行，从它的触发到它的结束，整体当作黑盒。一次运行会引发后续的运行——要么直接引发，要么经由编排器里的逻辑，要么靠改动工单跟踪器或 git host 来引发。运行从不等人：它结束，而人之后对工单跟踪器或 git host 的改动触发一次新的运行。
_避免_：session

**Runner（运行器）**：
运行在其上执行的一次性机器。机器上什么都不跨运行存活，即使这台机器本身是长期存在的：一次运行对先前运行的唯一记忆，就是工单跟踪器、git host 和编排器。
_避免_：server、host、box、compute、sandbox

## 服务

**Ticket tracker（工单跟踪器）**：
工单存放的地方，也是工厂的人机界面：人靠建工单来安排工作，在工单评论里与智能体对话，而他们对工单的改动会触发运行。
_避免_：`docs/tickets/`、ticket manager、project board

**Ticket source（工单来源）**：
工厂之外、但会在工单跟踪器里建工单的一切东西：一个反馈按钮、一个监控、一个错误追踪器、一个收件箱。
_避免_：data source、trigger source、intake

**Git host（git 托管）**：
分支、PR 与评审存放的地方。
_避免_：code host、forge、repo

**Orchestrator（编排器）**：
接收触发器、在 runner 上启动运行、并记录哪些运行在排队、在飞、已完成的那个组件。
_避免_：dispatcher、scheduler、control plane

**Observability platform（可观测性平台）**：
runner 把日志、trace 和状态发过去的地方，人由此看见每次运行内部发生了什么。可选的：占了 runner 或编排器槽位的那个产品，往往自己就显示得够多。运行从不依据它做决定，除非有东西把它写进工单跟踪器或 git host。
_避免_：observability、logs、monitoring、dashboard

## 设计一个工厂

一份设计有两半：**服务**——每个都是一个槽位，由一个产品填上；以及**任务**——它们的运行把工作推过这些服务。

从用户的问题出发，而不是从工厂出发：没人分诊的工单、排着队等自动评审的 PR、要迁移过去的一套更严的自动检查、没人读的 bug。用户点出一个问题、或者根本不知道要建什么时，去读 [EXAMPLE-TASKS.md](EXAMPLE-TASKS.md)，那里是按常见问题对应的任务。

### 慢起步

每一个触发器都是加速器。没有刹车的加速器，就是一台乱喷垃圾的加农炮。刹车有三种：

- **自动检查**：确定性的门禁（类型、lint、测试），每次运行都必须通过。
- **自动评审**：一次独立的运行，冷读 diff，对照代码库的标准，以及（如果有的话）工单。
- **人工评审**：合并前由人读 PR；它抓到的东西，会变成新的自动检查和更锋利的自动评审。

一次只加一个自动触发器，一开始先节流（十条 bug 报告只取一条、定时一天一次），并且每个 PR 都上人工评审。随着刹车赢得信任再松开油门；每一串运行循环，都要在交给人之前封顶几次尝试。

### 填满每个槽位

每个服务都是一个槽位。一个产品可以填几个槽位，一台服务器可以托管几个服务。三种设计并排看：

| 服务 | 全部落在 GitHub 上 | 用 Linear 管工单 | 自建跟踪器 |
| ---------------------- | ------------------------------- | ------------------------------ | ------------------------ |
| 工单跟踪器 | GitHub Issues | Linear | 自建应用 |
| 工单来源 | 反馈按钮 | 反馈按钮、监控 | 反馈按钮、监控 |
| git 托管 | GitHub | GitHub | GitHub |
| 编排器 | GitHub Actions | 自建服务器 + 数据库 | 自建应用 |
| 运行器 | Actions runner | Actions、E2B、Daytona 或一台 VPS | 自建应用，或沙箱 |
| 可观测性平台 | 无：Actions 的运行页面就够了 | 一个 LLM 追踪平台 | 自建应用 |

用户在为某个槽位挑产品时，先读那个槽位的调研把方向摸清，然后自己去找当前可选的方案；每份调研都按类型给选项分组，并列出决定这个槽位的问题：

- [TICKET-TRACKERS.md](TICKET-TRACKERS.md)
- [GIT-HOSTS.md](GIT-HOSTS.md)
- [RUNNERS.md](RUNNERS.md)
- [OBSERVABILITY-PLATFORMS.md](OBSERVABILITY-PLATFORMS.md)

服务买现成的，任务自己建：任务承载用户的设计，服务是通用的。工单跟踪器优先选开箱即用的：它皮实，大家本来就会用，外部用户也容易请进来。

### 逐项追问每个任务

对每个任务，回答：

1. 什么触发它？
2. 它做什么，读写哪些服务？
3. 它接下来触发什么？
4. 人在哪里重新介入？
5. 什么能阻止两次运行做同一件事？

对每个工单来源，回答：什么能阻止它把同一张工单建两次？

当每个槽位都点名了一个产品（可观测性平台这个槽位可以是刻意的“无”），并且每个任务和每个工单来源对每个问题都有答案时，设计才算完成。

## 本仓库的底线

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  一份文档库报告）。后端测试套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能做出的宣称。用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句判词，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 框架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `ecosystem-primer` 规则——并优先选
  能胜任的最高层。
