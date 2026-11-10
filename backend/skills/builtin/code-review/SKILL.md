---
name: "Code Review（代码评审）"
lang: zh
translated: machine
source: backend/skills/en-originals/code-review/SKILL.md
description: >-
  沿两条轴评审自某个固定点（commit、分支、tag 或 merge-base）以来的改动：标准（代码是否遵循本仓库已文档化的编码标准？）
  与规格（代码是否符合发起它的工单 / 规格所要求的内容？）。两份评审在并行子智能体里跑，并排报告结果。
  当用户想评审一个分支、一个 PR、正在进行的改动，或要求“review since X”时使用。
tags:
  - "code"
  - "review"
  - "mattpocock"
  - "requirements"
triggers:
  - "用户想评审一个分支、一个 PR、正在进行的改动，或要求“review since X”"
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

> **来源说明。** 改编自 `mattpocock/skills → skills/engineering/code-review`（MIT，原样收录于
> `vendor/upstream-skills/mattpocock/skills/engineering/code-review/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


对 `HEAD` 与用户给出的固定点之间的 diff 做两条轴的评审：

- **标准（Standards）**：代码是否符合本仓库已文档化的编码标准？
- **规格（Spec）**：代码是否忠实实现了发起它的工单 / 规格？

两条轴都作为**并行子智能体**运行，这样它们不会污染彼此的上下文，然后由本技能汇总它们的发现。每个子智能体
都从全新的上下文窗口开始。

这项工作的工单放在 `docs/tickets/`；如果那里一份都没有，就如实说出来并索要规格，而不是自己编一个。

## Process

### 1. 钉住固定点

用户说的那个东西就是固定点（一个 commit SHA、分支名、tag、`main`、`HEAD~5` 等）。如果他们没指定，就问。

把 diff 命令记下来一次：`git diff <fixed-point>...HEAD`（三个点，这样比较是相对 merge-base 的）。同时用
`git log <fixed-point>..HEAD --oneline` 记下提交列表。

在往下走之前，先确认这个固定点能解析（`git rev-parse <fixed-point>`）且 diff 非空。坏掉的 ref 或空 diff
应该在这里就失败，而不是在两个并行子智能体里面失败。

### 2. 确定规格来源

按这个顺序找发起它的规格：

1. 提交信息里的 issue 引用（`#123`、`Closes #45`、GitLab 的 `!67` 等），按追踪器文档里记录的工作流取回。
2. 用户作为参数传进来的路径。
3. `docs/`、`specs/` 或 `.scratch/` 下与分支名或特性匹配的规格文件。
4. 什么都没找到，就问用户规格在哪。如果他们说没有，**规格**子智能体将跳过，并报告“没有可用的规格”。

### 3. 确定标准来源

搜索仓库里每一个记录“代码该怎么写”的文件。只要 `CODING_STANDARDS.md` 或 `CONTRIBUTING.md` 存在，它就必须
在清单里。

在仓库已记录的内容之上，标准轴始终携带下面的**坏味道基线**：一组固定的 Fowler 代码坏味道（《重构》第 3 章），
即使仓库什么都没记录，它也照样适用。两条规则约束它：

- **仓库优先。** 已文档化的仓库标准总是赢；凡是它认可、而基线会标记的东西，就抑制那条坏味道。
- **永远只是判断，不是判决。** 每条坏味道都是一个带标签的启发式（“可能的 Feature Envy”），绝不是硬性违规。
  和这里的所有标准一样，工具链已经强制的东西跳过。

每条坏味道的读法是*它是什么* → *怎么修*；拿它去对照 diff：

- **Mysterious Name（神秘命名）**：函数、变量或类型的名字没有揭示它做什么或持有什么。→ 改名；如果找不到一个
  诚实的名字，说明设计本身是模糊的。
- **Duplicated Code（重复代码）**：同一种逻辑形状在本次改动的多个 hunk 或多个文件里出现。→ 抽出共享的形状，
  两处都调用它。
- **Feature Envy（依恋情结）**：一个方法伸手去够另一个对象的数据，比够自己的还多。→ 把方法搬到它所依恋的
  数据上。
- **Data Clumps（数据泥团）**：同样的几个字段或参数总是结伴同行（一个想出生的类型）。→ 把它们打包成一个类型，
  传那个类型。
- **Primitive Obsession（基本类型偏执）**：用一个基本类型或字符串代替了一个本该拥有自己类型的领域概念。
  → 给这个概念一个自己的小类型。
- **Repeated Switches（重复的 switch）**：对同一类型的同一个 `switch`/`if` 级联在本次改动中反复出现。
  → 换成多态，或换成一个两处共用的映射表。
- **Shotgun Surgery（霰弹式修改）**：一次逻辑改动迫使你在 diff 的许多文件里散落地编辑。→ 把一起变化的东西
  聚到一个模块里。
- **Divergent Change（发散式变化）**：一个文件或模块因为几个互不相关的原因被编辑。→ 拆开，让每个模块只因为
  一个原因而变化。
- **Speculative Generality（夸夸其谈的通用性）**：为规格并不存在的需求添加的抽象、参数或钩子。→ 删掉；
  内联回去，直到出现真实的需要。
- **Message Chains（过长的消息链）**：调用方不该依赖的 `a.b().c().d()` 长导航。→ 把这段游走藏到第一个对象上的
  一个方法后面。
- **Middle Man（中间人）**：一个类或函数大部分只是往下转发。→ 砍掉它，直接调用真正的目标。
- **Refused Bequest（被拒绝的遗赠）**：子类或实现者忽略或覆盖了它继承来的大部分东西。→ 放弃继承，改用组合。

### 4. 并行放出两个子智能体

把两个子智能体调用一起发出去，放在前台，然后汇总它们返回的报告。

**标准子智能体的提示词**应包含：

- 完整的 diff 命令与提交列表。
- 第 3 步找到的标准来源文件清单，**外加第 3 步的坏味道基线**完整粘贴进来（子智能体没有别的途径拿到它）。
- 简报：“按文件 / hunk 报告相关之处：(a) diff 违反某条已文档化标准的每一处：引用那条标准（文件 + 规则）；
  (b) 你发现的任何基线坏味道：说出它的名字并引用那个 hunk。区分硬性违规与判断性意见：已文档化标准的违反
  可以是硬性的，但基线坏味道永远只是判断，且已文档化的仓库标准优先于基线。跳过工具链已经强制的东西。
  400 字以内。”

**规格子智能体的提示词**应包含：

- diff 命令与提交列表。
- 规格的路径，或取回后的规格内容。
- 简报：“报告：(a) 规格要求、但缺失或只做了一半的需求；(b) diff 里没被要求的行为（范围蔓延）；
  (c) 看起来实现了、但实现方式看着不对的需求。每条发现都引用规格里的原文那一行。400 字以内。”

如果规格缺失，跳过规格子智能体，并在最终报告里说明这一点。

### 5. 汇总

把两份报告放在 `## Standards` 和 `## Spec` 标题下，逐字或稍作清理地呈现。**不要**合并或重新排序这些发现，
因为两条轴是刻意分开的（见*为什么分成两条轴*）。

用一行总结收尾：每条轴的发现总数，以及*各轴内部*最严重的问题（如果有）。不要跨轴挑出一个总冠军：那正是这种
分离要防止的重新排序。

## Why two axes（为什么分成两条轴）

一次改动可以通过一条轴，而在另一条轴上失败：

- 代码遵循了每一条标准，但实现了错误的东西 → **标准通过，规格失败。**
- 代码恰好做了工单要求的事，但破坏了项目的约定 → **规格通过，标准失败。**

分开报告，才能阻止一条轴掩盖另一条。

## Standards reference（标准参考）

本仓库自己的评审清单就在本文件旁边，名为 `STANDARDS-CHECKLIST.md`（也就是我们认为什么算干净、安全、可维护）。
把它当作下面这条 **Standards** 轴来读——这条轴问的是*这符合我们已经定下的东西吗*，而不是*这符合某个通用的
理想吗*。

## This repository's floor（本仓库的底线）

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  一份文档库报告）。后端测试套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能做出的断言。
  用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句结论，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 脚手架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `lc-ecosystem-primer` 规则——并优先选
  能胜任的最高层。
