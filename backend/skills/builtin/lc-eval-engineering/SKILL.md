---
name: "Eval Engineering（评测工程）"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-eval-engineering/SKILL.md
description: >-
  检视一个智能体仓库和可选轨迹，访谈用户，写出经过评审的 Task Spec，构建并审计 Harbor Task，并引导出
  可复用的项目 World Knowledge 技能。适用于智能体评测、基准设计、Task 生成、受控 Environment、合成数据、
  Verifier、Harbor 运行、校准，以及持续的基准维护。
tags:
  - "eval"
  - "engineering"
  - "langchain-skills"
  - "review"
  - "requirements"
  - "skills"
triggers:
  - "智能体评测、基准设计、Task 生成、受控 Environment、合成数据、Verifier、Harbor 运行"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
  - "skill"
author: "langchain-skills (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/eval-engineering`（MIT，原样收录于 `vendor/upstream-skills/langchain-skills/skills/eval-engineering/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


# Eval Engineering（评测工程）

## Flow（流程）

- 先检视全部输入：仓库、Harness、可选的轨迹、现有的 Task 与运行、现有的 World knowledge，以及
  人的目标。在提出任何工作之前，先找出适用的源文件与技能引用。
- 用这些输入里可复用的事实，创建或更新那个小的项目 World Knowledge 技能。用它提出一个有据可依的
  Task。
- 同时起草 Task Spec 与 World 技能。把两者都给用户看，精确的 Task 事实只留在 `Task.md` 里，
  反复打磨两者直到用户批准。
- 实现已批准的 Task，验证它的 Environment 与 Verifier，跑真实的 Harness，检视完整证据，
  只修与智能体无关的失败。
- 用这次运行证明到的东西校正 World 技能，然后对下一个 Task 重复这套流程。

## Terms（术语）

- **Task Spec：** `Task.md`，描述一个 Task 的输入、相关的智能体条件、Environment、评分、公平性
  与待决事项。
- **Task：** 可运行的指令、Environment 与 Verifier。
- **Harness：** Harbor 运行的那个完整智能体，包括提示词、模型循环、工具、钩子、记忆、会话与
  适配器。
- **Environment：** Harness 周围的文件、数据、服务、身份、权限、网络、时钟与可变状态。
- **Verifier：** 独立的检查，为结果评分，或把一次运行判为无效。
- **World Knowledge Skill：** 仓库本地的技能，承载可复用的项目专属知识、参考、脚本、资产与测试，
  用来帮忙生成 Task Spec、构建后续的 Task。
- **Spec2Task：** 把经过评审的 Task Spec 变成带审计的可运行 Task 的完整闭环。它的具体构建顺序与
  参考路由见 [Task implementation](references/task-implementation.md)。

## Reference routing（参考路由）

每个决定出现时，再读对应的参考：

| 需要 | 读 |
|---|---|
| 检视源码、轨迹、Harness、依赖、访问与现有评测 | [Discovery](references/discovery.md) |
| 引导或更新可复用的项目知识 | [World knowledge](references/world-knowledge.md) |
| 提出 Task 并写出唯一那份 Task Spec | [Task design](references/task-design.md) |
| 构建数据、服务、访问、状态与重置 | [Environment building](references/environment-building.md) |
| 生成结构化或自然语言数据 | [Synthetic data](references/synthetic-data.md) |
| 定义独立的证据与评分 | [Verifier design](references/verifier-design.md) |
| 应用 Spec2Task，把已评审的 Spec 变成带审计的 Task | [Task implementation](references/task-implementation.md) |
| 比较模型运行并给失败归类 | [Calibration](references/calibration.md) |
| 打包并运行 Harbor task | [Harbor](references/harbor.md) |
| 改编一个已知的基准设计 | [Benchmark patterns](references/patterns.md) |
| 构建多轮对话 | [Multi-turn simulation](references/multi-turn-simulation/guide.md) |
| 看跨两个 Task 沉淀下来的 World knowledge | [Service-desk example](references/examples/service-desk.md) |

可复用的实现资源：

- 多轮的 [runner](references/multi-turn-simulation/runner.py)、[model user](references/multi-turn-simulation/model_user.py) 与 [Harbor adapter example](references/multi-turn-simulation/harbor_example.py)
- [Tool-schema comparison](scripts/compare_tool_schemas.py)：比较给定的 schema 片段，但不解析外部 `$ref` 目标
- [Read-only SQLite state snapshot](scripts/snapshot_sqlite_state.py)

## 1. Inspect inputs and existing World knowledge（检视输入与现有 World knowledge）

在提出任何 Task 之前，先评审用户提供的每一个输入。按手上有哪些输入，取用对应的指引：

- 有仓库、Harness、轨迹或依赖 → 读 [Discovery](references/discovery.md)。
- 有现有 Task 与运行 → 检视它们的指令、Environment、Verifier、奖励、轨迹与最终状态。当运行质量
  或失败原因会影响新设计时，读 [Calibration](references/calibration.md)。
- 有现存的项目 World 技能 → 读 [World knowledge](references/world-knowledge.md)，再核对会影响新
  Task 的源文件与可复用方法。
- 有人的目标与约束 → 读 [Task design](references/task-design.md)。
- 有相关基准示例 → 用 [Benchmark patterns](references/patterns.md) 里的领域索引与源码指引。

凡是源码与测试能回答的问题，先检视仓库再开口问。沿活跃的 Harness 追一遍提示词、模型、工具、
服务、状态、副作用与针对性的测试。检视现有 Task 的指令、解析器、Verifier、奖励路径与运行证据。

用户提供轨迹时，评审完整的运行或会话。用轨迹了解真实请求、依赖行为、状态形状、错误与失败条件。
不要把某条轨迹里的答案当作独立真相。

如果 `backend/skills/builtin/<project>-world/SKILL.md` 存在，读它。只按它的路由取用与当前 Task
相关的知识。当它引用的仓库路径、命令与脚本的准确性影响设计时，逐个核对。

## 2. Propose and select a Task（提出并选定一个 Task）

读 [Task design](references/task-design.md)，并用 [Benchmark patterns](references/patterns.md) 的
索引找到相关领域与源码指引。聚焦那个领域，除非这个 Task 跨越了另一个领域。在检视之后的第一次面向
用户的设计回复里，提出一个有据的 Task——依据可以是仓库证据、提供的轨迹、既有覆盖，或人的优先级。
说明：

- 真实的工作与能力；
- 让这个用例不平凡的那个条件；
- 它需要的 Environment 与独立证据；
- 它能检测到的重要失败；
- 它与现有 Task 的差别；以及
- 主要的待决事项。

在同一条回复里，展示相关的当前 World 技能内容，以及这个 Task 建议的具体增补或修正。如果一份
World 技能都没有，就展示一小段初始内容，用来帮忙创建这个 Task 和以后的 Task。把 Task 的精确
请求、焦点记录、预期结果、隐藏真相与精确评分规则挡在 World 技能之外。

在实现之前，让用户把 Task 提案与 World knowledge 一起改。只有当真实存在的用户选择会改变设计时，
才给备选方案。

## 3. Write and review the Task Spec and World Skill（写出并评审 Task Spec 与 World 技能）

把 [Task 模板](assets/task/Task.md.template) 复制到 `evals/<suite>/tasks/<task-id>/Task.md`。
所有 Task 专属的设计都放进这一个文件。同时按 [World knowledge](references/world-knowledge.md) 创建
或更新项目 World 技能。确定活跃智能体与仓库支持的项目技能位置。
`backend/skills/builtin/<project>-world/SKILL.md` 与 `.claude/skills/<project>-world/SKILL.md` 是
常见的落点。项目已有约定时按约定来。否则先说明建议的位置，取得用户确认后再创建技能。需要时从
[World 技能模板](assets/world-skill/SKILL.md.template) 起步。

每个 `Task.md` 都放在它所描述的那个 Harbor task 旁边：

```text
evals/<suite>/tasks/<task-id>/
├── Task.md              # human-reviewed control-plane spec
├── task.toml             # required Harbor configuration
├── instruction.md        # required agent input
├── environment/          # required Environment definition and visible state
│   ├── Dockerfile        # use this or docker-compose.yaml
│   └── docker-compose.yaml # optional; primary service must be main
├── tests/
│   ├── test.sh           # required Harbor Verifier entry point
│   ├── test_*.py         # optional Verifier helpers
│   └── fixtures/         # optional hidden Verifier data
└── solution/
    └── solve.sh          # optional reference path
```

绝不把 `Task.md` 复制或挂载进被测智能体的工作区或镜像。智能体只拿到 `instruction.md`，以及本次
运行有意给出的那些 Environment 状态。

包含：

- 目的与来源证据；
- 精确的输入与后续轮次；
- 只列与本 Task 相关的 Harness 条件；
- 初始状态、服务、访问、可见性、重置与生产差异；
- 必需的结果、禁止的副作用、可接受的替代做法，以及独立的 Verifier 证据；
- 公平性、泄漏风险与无效运行条件；以及
- 待决事项与假设。

把完整的 Task Spec 与 World 技能改动展示给用户。说明 World 技能里已经有什么、这个 Task 增加或
修正了什么、什么只留在 `Task.md` 里。在同一轮往来里修订两者。只有得到明确批准后，才把 Task Spec
标为已批准。只有用户评审过之后，才把 World 技能改动视为已接受。如果用户要求不要审批暂停、直接
端到端构建，就带着智能体自审的 `Status: Draft` 继续，并把 World 技能改动标为未评审。

如果实现改变了请求、可见信息、实质的 Environment 行为或评分边界，更新 `Task.md` 并把改动展示出来。
把它的状态改回 `Draft`。展示 diff，并在重新设为 `Approved` 之前要求明确的再次批准。

## 4. Apply Spec2Task（应用 Spec2Task）

遵循 [Task implementation](references/task-implementation.md)。它给出构建顺序，并把每个决定路由到
Environment、合成数据、Verifier、Harbor 与校准这几份参考。

既有项目用它钉住或支持的 Harbor 版本。否则用已安装的受支持版本，并记录下来。只有在用户批准、
并说明兼容性理由时才升级。把已安装的 CLI help 当作命令契约。

在一次计分的模型运行之前：

1. 与用户确认模型、试验次数、裁判、超时与最大预期成本，除非用户已经授权过那次运行方案。
2. 完成 [Harbor](references/harbor.md) 里的打包审计。确认这个 Task 所需的每一个文件、入口点、路径、
   权限、配置值、挂载、服务与奖励输出都存在，并且能通过 Harbor 正常工作。确认隐藏的 Task、
   Verifier、solution 与秘密材料都不在智能体可见的镜像与工作区里。
3. 按适合该 Environment 的方式检查初始化与试验隔离。全新的容器或 worktree 可以用替换提供隔离。
   复用的可变服务需要一次经过检查的重置。不可变的冻结数据只需要一次经过检查的加载。见
   [Task implementation](references/task-implementation.md)。
4. 实际演练 Task 依赖的每一个操作。
5. 存在参考路径时，跑一遍参考路径。
6. 用一个明确有效的结果、一个有效的替代结果、一个真实的错误结果、一条捷径、一处被禁止的连带改动，
   以及缺失或损坏的证据，来测试 Verifier。
7. 确认每条走完的 Verifier 路径都写出有效的奖励与有用的证据，且不暴露隐藏真相或秘密。

## 5. Run and audit（运行与审计）

通过 Harbor 跑真实的 Harness。读完整轨迹，而不只是奖励。检视：

- 消息、模型调用、工具调用、结果、重试与错误；
- 初始与最终的 Environment 状态，以及外部副作用；
- 服务、初始化、就绪、重置与清理的证据；
- 每一条 Verifier 判据、它的证据、判定与错误；以及
- 解析出来的 Harness、模型、Environment 与裁判模型配置。

把每一次不成功的运行归类为：智能体能力不足、信息缺失、Harness 缺陷、Environment 缺陷、Verifier
误拒、Verifier 误受、泄漏，或基础设施故障。在使用分数之前，先修掉非智能体的失败。

模型对比是可选的校准策略，不是完成规则。当它真能回答一个真实的不确定性时，再对比一个更弱的模型、
目标模型或更强的模型，并在行为飘忽时重复试验。选出来的每一条轨迹都要读。对比能暴露含糊的输入、
脆弱的初始化、泄漏、捷径或奖励作弊。通过率与模型排序并不能证明 Task 的质量。

完整的审计方法见 [Calibration](references/calibration.md)。

## 6. Reconcile project World knowledge（校正项目 World knowledge）

在 Task 设计、实现与审计的全过程中都用 [World knowledge](references/world-knowledge.md)。当工作
提供了对另一个 Task 有帮助的证据时，增补或修正项目专属知识。这可以包括 Task 模式、Environment
方法、数据创建、Verifier 证据、运行流程、脚本、资产与示例。

审计之后，用已完成的 Task 证明到的东西校正 World 技能。向用户展示：

- 建议的可复用知识；
- 支撑它的证据；
- 另一个 Task 会怎么用它；
- 它应该放在哪里；以及
- 哪些仍然只属于已完成的 Task。

删掉或收窄被这个 Task 否证的想法。如果用户要求不停顿地自动做端到端更新，就做最小幅度、有支撑的
更新，在最终评审里展示出来，并且不要暗示人已经批准了这次泛化。

一开始只创建 `SKILL.md`。只有当真实内容足以支撑时，才添加 `references/`、`scripts/`、`assets/`
或 `tests/`。

已完成 Task 的请求、焦点状态、预期结果与精确判据，留在与它同放的 `Task.md` 里。不要拷贝本技能里
已经讲清楚的通用指引。记录那份指引针对本项目所做的适配。

## 7. Repeat（重复）

用第二个、第三个 Task 检验 World 技能。看它是否减少了重复发现、改善了 Task Spec、保住了重要的
关系、复用了一次已被证明有效的操作，或阻止了一个已知的 Verifier 缺陷。修正缺失的、过时的或过宽的
规则。

当几个实质不同的 Task 已经用上了这些共享知识，且构建与验证的方法都已清晰时，下一轮可以提出多份
彼此独立的 Task Spec：

1. 挖掘新的仓库、轨迹与人的证据。
2. 用 World 技能生成彼此不同的 Task Spec。
3. 让人评审这些 spec。
4. 并行构建各自独立、已获批准的 Task。
5. 逐个审计每一个 Task。
6. 只用可复用的修正去更新 World knowledge。

随着生产行为、用户优先级、智能体与模型变化，持续跑这个闭环。

## Dependencies, access, and safety（依赖、访问与安全）

梳理需要的系统、数据、角色、网络需求与安全的初始化方法。绝不读取、打印、复制、存储秘密值，也绝不
请人把秘密值粘过来。告诉人：需要哪个依赖、为什么需要、项目期望怎样提供访问。默认使用受控的本地、
冻结或模拟依赖。评测期间绝不写生产。把访问、启动、重置、超时、裁判与 Verifier 的失败当作无效运行，
而不是智能体工作失败。

## Complete only when（只有满足这些才算完成）

- `Task.md` 与构建出的指令、Environment 与 Verifier 一致。
- 这个 Task 能从智能体可见或通常可发现的信息解出来。
- Environment 启动可靠，并按恰当的方式（替换、重置或不可变状态）隔离试验，且不泄漏隐藏真相。
- Verifier 的有效与无效用例行为符合预期。
- 至少完整读过一次真实的 Harness 运行。
- 非智能体的失败已修好，或作为未解决的限制报告出来。
- 使用模型对比时，包含轨迹评审，而不只是通过率。
- 项目 World 技能随 Task Spec 一起创建或更新，在工作过程中被评审过，并与最终证据校正过。
- 用户拿到了 Task 路径、运行命令、结果、证据与剩余限制。

## This repository's floor（本仓库的底线）

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  一份文档库报告）。后端测试套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能
  做出的断言。用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句结论，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 脚手架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `lc-ecosystem-primer` 规则——并优先
  选能胜任的最高一层。
