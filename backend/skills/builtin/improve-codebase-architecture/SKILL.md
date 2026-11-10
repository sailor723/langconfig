---
name: "Improve Codebase Architecture（改进代码库架构）"
lang: zh
translated: machine
source: backend/skills/en-originals/improve-codebase-architecture/SKILL.md
description: "扫描代码库，找出加深机会，把它们做成一份可视化的 HTML 报告，然后把你选中的那一个反复推敲到底。"
tags:
  - "improve"
  - "codebase"
  - "architecture"
  - "mattpocock"
triggers:
  - "当被要求暴露架构摩擦并提出**加深机会**——也就是把浅模块变成深模块的重构——时"
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

> **来源说明。** 改编自 `mattpocock/skills → skills/engineering/improve-codebase-architecture`（MIT，原样
> 收录于 `vendor/upstream-skills/mattpocock/skills/engineering/improve-codebase-architecture/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。

## Instructions（指令）

# 改进代码库架构

暴露架构摩擦，并提出**加深机会**：把浅模块变成深模块的重构。目标是可测试性与 AI 可导航性。

本命令_以_项目的领域模型_为依据_，并建立在一套共用的设计词汇之上：

- 用 `skill` 工具读那个技能（id：`codebase-design`），取得架构词汇（**模块**、**接口**、**深度**、**接缝**、
  **适配器**、**杠杆**、**局部性**）与它的原则（删除测试、“接口就是测试面”、“一个适配器 = 假想接缝，
  两个 = 真接缝”）。每一条建议里都精确使用这些术语，不要漂向“组件”“服务”“API”或“边界”。
- `GLOSSARY.md` 里的领域语言为好接缝提供名字；`docs/adr/` 里的 ADR 记着本命令不该重新翻案的决定。

## 流程

### 1. 探索

**先定范围，再扫描：YAGNI。** 加深一个模块的回报，是让将来对它的改动更容易，所以给代码库里最近改过的那部分
额外加权。看之前先决定*去哪儿*看：

- 用户已经点了方向（一个模块、一个子系统、一个痛点），就照它走，跳过下面的推断。
- 否则，往回翻一大段提交历史（`git log --oneline`），找出代码库的热点——那些反复出现的文件和区域——先让
  这些路径把注意力拉过去。如果改动是散的、没有明显热点，就把网撒大一些。

先读项目的领域词汇表（`GLOSSARY.md`），以及你要动的那个领域的 ADR。

然后起一个带全新上下文窗口的子智能体去走代码库。不要死守固定的启发式；有机地探索，并记录你在哪里感到摩擦：

- 哪里为了理解一个概念，要在许多小模块之间来回弹？
- 哪些模块**浅**，接口复杂得几乎跟实现一样？
- 哪里为了可测试性抽出了纯函数，而真正的缺陷藏在它们被调用的方式里（没有**局部性**）？
- 哪些紧耦合的模块从各自的接缝往外漏？
- 代码库的哪些部分没有测试，或者很难通过它们当前的接口去测？

对你怀疑是浅的任何东西套用**删除测试**：删掉它会把复杂度集中起来，还是只是把它挪个位置？“是的，会集中”就是
你要的信号。

### 2. 把候选做成一份 HTML 报告

把一份自包含的 HTML 文件写到操作系统临时目录，这样仓库里不会落东西。临时目录从 `$TMPDIR` 解析，取不到就退回
到 `tmp` 技能（Windows 上是 `%TEMP%`），写到 `<tmpdir>/architecture-review-<timestamp>.html`，让每次运行都
得到一个全新的文件。替用户把它打开（Linux 上 `xdg-open <path>`，macOS 上 `open <path>`，Windows 上
`start <path>`），并告诉他们绝对路径。

报告用 **CDN 上的 Tailwind** 做布局和样式，用 **CDN 上的 Mermaid** 画图——只在图 / 流程 / 时序能可靠传达结构
的地方用。把 Mermaid 与手写的 CSS/SVG 视觉混着来：关系是图形状的（调用图、依赖、时序）用 Mermaid；想要更有
编辑感的东西（体量图、剖面图、塌陷动画）就用手搭的 div/SVG。每个候选都要有一张**前后对比可视化**。要视觉化。

每个候选渲染一张卡片，包含：

- **文件**：涉及哪些文件 / 模块
- **问题**：当前架构为什么在制造摩擦
- **方案**：用平实的话说明会改什么
- **收益**：用局部性和杠杆来讲，以及测试会怎么变好
- **前后对比图**：左右并排、自己画的，画出那个“浅”和加深之后的样子
- **推荐强度**：`Strong`、`Worth exploring`、`Speculative` 三者之一，渲染成一个徽标

报告最后加一节**首要推荐**：你会先动哪个候选，为什么。

**领域用 GLOSSARY.md 的词汇，架构用 `codebase-design` 技能的词汇。** 如果 `GLOSSARY.md` 定义了“Order”，
就说“Order 接收模块”，而不要说“FooBarHandler”，也不要说“Order 服务”。

**ADR 冲突**：如果一个候选与现有 ADR 相矛盾，只有当摩擦真实到值得重开那个 ADR 时才提出来。在卡片里标清楚
（例如一个警告块：_“与 ADR-0007 冲突，但值得重开，因为……”_）。不要把 ADR 禁止的每一种理论重构都列出来。

完整的 HTML 骨架、图示模式和样式指引见 [HTML-REPORT.md](HTML-REPORT.md)。

**先不要**提接口方案。文件写完之后问用户：“这些里面你想深入看哪一个？”

### 3. 反复推敲的循环

用户选定候选之后，用 `skill` 工具读那个技能（id：`grilling`），和他们一起走决策树：约束、依赖、加深后模块的
形状、接缝后面放什么、哪些测试能活下来。

决定一旦成形，副作用就当场做；用 `skill` 工具读那个技能（id：`domain-modeling`），边走边让领域模型保持最新：

- **加深后的模块要按一个 `GLOSSARY.md` 里没有的概念命名？** 把这个词加进 `GLOSSARY.md`。文件不存在就惰性
  创建。
- **对话里把一个模糊的词磨清楚了？** 就地更新 `GLOSSARY.md`。
- **用户用一个承重的理由否掉了这个候选？** 提议写一条 ADR，措辞是：_“要不要我把这条记成 ADR，好让将来的
  架构评审不再重提它？”_ 只有当将来的探索者真的需要这个理由才能避免重复建议时才提议；临时性的理由
  （“现在不值得做”）和不言自明的理由都跳过。
- **想为加深后的模块探索替代接口？** 用 `skill` 工具读那个技能（id：`codebase-design`），用它的
  design-it-twice 并行子智能体套路。

## 本仓库的底线

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  一份文档库报告）。后端测试套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能做出的
  宣称。用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句判词，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 框架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `ecosystem-primer` 规则——并优先选
  能胜任的最高层。
