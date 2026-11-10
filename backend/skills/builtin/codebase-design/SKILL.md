---
name: "Codebase Design（代码库设计）"
lang: zh
translated: machine
source: backend/skills/en-originals/codebase-design/SKILL.md
description: >-
  设计深模块的共用词汇。当用户想设计或改进某个模块的接口、寻找加深的机会、决定接缝放在哪里、让代码更易测或更
  便于 AI 导航，或当另一个技能需要深模块这套词汇时使用。
tags:
  - "codebase"
  - "design"
  - "mattpocock"
  - "testing"
  - "skills"
triggers:
  - "用户想设计或改进某个模块的接口、寻找加深的机会、决定接缝放在哪里、让代码更易测或更便于 AI 导航"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
  - "task"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `mattpocock/skills → skills/engineering/codebase-design`（MIT，原样收录于
> `vendor/upstream-skills/mattpocock/skills/engineering/codebase-design/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


# 代码库设计

设计**深模块**：把大量行为藏在一个小接口后面，落在一条干净的接缝上，并且能通过那个接口测出来。凡是在设计或
重构代码的地方，都用这套语言和这些原则。目标是：给调用方杠杆，给维护者局部性，给所有人可测试性。

## 术语表

精确使用这些术语：不要换成“组件”“服务”“API”或“边界”。统一的语言就是这件事的全部意义。

**模块（Module）**：任何有接口也有实现的东西。刻意与尺度无关：一个函数、一个类、一个包，或横跨多层的切片。
_避免_：unit、component、service。

**接口（Interface）**：调用方要正确使用这个模块所必须知道的一切：类型签名，还有不变式、顺序约束、错误模式、
必需的配置，以及性能特征。_避免_：API、signature（太窄——它们只指类型层面的那个表面）。

**实现（Implementation）**：模块里面的东西，它的代码体。与**适配器**不同：一个东西可以是一个小适配器配一个
大实现（一个 Postgres 仓储），也可以是一个大适配器配一个小实现（一个内存假件）。谈的是接缝，就用“适配器”；
否则用“实现”。

**深度（Depth）**：接口上的杠杆。调用方（或测试）每学会一单位接口，能行使多少行为。大量行为藏在接口后面时，
模块是**深**的；接口复杂得跟实现差不多了，模块就是**浅**的。

**接缝（Seam）** _（Michael Feathers）_：一处你可以在不编辑那个位置的前提下改变行为的地方；也就是模块接口
所处的*位置*。接缝放在哪里本身是一项设计决策，与它后面放什么无关。_避免_：boundary（与 DDD 的限界上下文
一词撞车）。

**适配器（Adapter）**：在接缝上满足某个接口的具体东西。它描述的是*角色*（填哪个槽），不是实质（里面是什么）。

**杠杆（Leverage）**：调用方从深度里拿到的东西。每学会一单位接口，换来更多能力。一份实现，在 N 个调用点和
M 个测试身上回本。

**局部性（Locality）**：维护者从深度里拿到的东西。改动、缺陷、知识、验证都集中在一处，而不是摊到各个调用方
身上。修一次，处处已修。

## 深 vs 浅

**深模块** = 小接口 + 大量实现：

```
┌─────────────────────┐
│   Small Interface   │  ← Few methods, simple params
├─────────────────────┤
│                     │
│  Deep Implementation│  ← Complex logic hidden
│                     │
└─────────────────────┘
```

**浅模块** = 大接口 + 少量实现（要避免）：

```
┌─────────────────────────────────┐
│       Large Interface           │  ← Many methods, complex params
├─────────────────────────────────┤
│  Thin Implementation            │  ← Just passes through
└─────────────────────────────────┘
```

设计一个接口时，问：

- 能把方法数量减下来吗？
- 能把参数简化吗？
- 能把更多复杂度藏进里面吗？

## 原则

- **深度是接口的性质，不是实现的性质。** 深模块内部可以由小的、可打桩的、可替换的部件拼成；它们只是不属于
  接口。一个模块可以有**内部接缝**（对它的实现私有，供它自己的测试使用），也可以有接口处的**外部接缝**。
- **删除测试。** 想象把这个模块删掉。复杂度如果消失了，它原本就是个直通件。复杂度如果在 N 个调用方那里重新
  冒出来，它就挣到了自己的位置。
- **接口就是测试面。** 调用方和测试跨过同一条接缝。如果你想*越过*接口去测，那这个模块的形状大概是错的。
- **一个适配器意味着假想的接缝，两个适配器才意味着真正的接缝。** 除非真的有什么东西在接缝两侧变化，否则不要
  引入接缝。

## 为可测试性而设计

好的接口让测试变得自然：

1. **接收依赖，不要自己造依赖。**

   ```typescript
   // Testable
   function processOrder(order, paymentGateway) {}

   // Hard to test
   function processOrder(order) {
     const gateway = new StripeGateway();
   }
   ```

2. **返回结果，不要产生副作用。**

   ```typescript
   // Testable
   function calculateDiscount(cart): Discount {}

   // Hard to test
   function applyDiscount(cart): void {
     cart.total -= discount;
   }
   ```

3. **表面积要小。** 方法越少 = 需要的测试越少。参数越少 = 测试准备越简单。

## 关系

- 一个**模块**恰好有一个**接口**（它呈现给调用方和测试的那个面）。
- **深度**是**模块**的性质，相对它的**接口**来度量。
- **接缝**是**模块**的**接口**所在之处。
- **适配器**坐落在**接缝**上，并满足那个**接口**。
- **深度**为调用方带来**杠杆**，为维护者带来**局部性**。

## 被否决的提法

- **把深度当成实现行数与接口行数之比**（Ousterhout）：这会奖励给实现灌水。我们改用“深度即杠杆”。
- **把“接口”当成 TypeScript 的 `interface` 关键字，或一个类的公开方法**：太窄——这里的接口包含调用方必须
  知道的每一条事实。
- **“边界”（boundary）**：与 DDD 的限界上下文撞车。请说**接缝**或**接口**。

## 再往深处走

- **给定依赖关系去加深一组模块**，见 [DEEPENING.md](DEEPENING.md)：依赖的类别、接缝纪律，以及“替换而不是
  叠层”的测试法。
- **探索替代接口**，见 [DESIGN-IT-TWICE.md](DESIGN-IT-TWICE.md)：并行放出几个子智能体，用几种截然不同的
  方式设计接口，然后按深度、局部性和接缝位置做比较。

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
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `lc-ecosystem-primer` 规则——并优先选
  能胜任的最高层。
