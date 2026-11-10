---
name: "Langgraph Fundamentals（LangGraph 基础）"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-langgraph-fundamentals/SKILL.md
description: >-
  写任何 LangGraph 代码时都要调用本技能。涵盖 StateGraph、状态模式、节点、边、Command、Send、invoke、
  流式输出与错误处理。
tags:
  - "langgraph"
  - "fundamentals"
  - "langchain-skills"
  - "skills"
triggers:
  - "要写任何 LangGraph 代码时"
  - "需要 StateGraph、状态模式、节点、边或流式输出时"
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

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/langgraph-fundamentals`（MIT，原样收录于 `vendor/upstream-skills/langchain-skills/skills/langgraph-fundamentals/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


<overview>
LangGraph 把智能体工作流建模成**有向图**：

- **StateGraph**：构建有状态图的主类
- **节点（Nodes）**：执行工作并更新状态的函数
- **边（Edges）**：规定执行顺序（静态边或条件边）
- **START/END**：标记入口与出口的特殊节点
- **带归约器的状态**：控制状态更新如何合并

图必须先 `compile()`，然后才能执行。
</overview>

<design-methodology>

### 设计一个 LangGraph 应用

建一张新图时，按这 5 步走：

1. **划出离散的步骤**——把工作流画成流程图。每一个步骤就是一个节点。
2. **弄清每个步骤做什么**——给节点分个类：LLM 步骤、数据步骤、动作步骤，还是用户输入步骤。逐个确定它的静态上下文（提示词）、动态上下文（来自状态）、重试策略，以及期望得到的结果。
3. **设计状态**——状态是所有节点共享的记忆。把原始数据存进去，提示词在节点内部按需格式化。
4. **实现节点**——把每个步骤写成一个函数：接收状态，返回局部更新。
5. **把它们接起来**——用边把节点连起来，加上条件路由，需要时配一个检查点再编译。

</design-methodology>

<when-to-use-langgraph>

| 什么时候用 LangGraph | 什么时候用替代方案 |
|-------------------|----------------------|
| 需要对智能体编排做细粒度控制 | 想快速做原型 → LangChain 智能体 |
| 要建带分支、带循环的复杂工作流 | 简单的无状态工作流 → 直接用 LangChain |
| 需要人在回路、需要持久化 | 想要开箱即用的功能 → Deep Agents |

</when-to-use-langgraph>

---

## 状态管理

<state-update-strategies>

| 需求 | 方案 | 示例 |
|------|----------|---------|
| 覆盖原值 | 不加归约器（默认行为） | 计数器这类简单字段 |
| 往列表里追加 | 归约器（`operator.add` / concat） | 消息历史、日志 |
| 自定义逻辑 | 自定义归约函数 | 复杂的合并规则 |

</state-update-strategies>

---

## 节点

<node-function-signatures>

节点函数返回的是局部的状态更新。访问配置与运行时的函数签名因语言而异；请查阅对应语言的那份实现参考。

</node-function-signatures>

---

## 边

<edge-type-selection>

| 需求 | 边类型 | 何时使用 |
|------|-----------|-------------|
| 总是去同一个节点 | `add_edge()` | 固定、确定性的流程 |
| 按状态做路由 | `add_conditional_edges()` | 动态分支 |
| 更新状态并同时路由 | `Command` | 把两件事合进单个节点 |
| 扇出到多个节点 | `Send` | 输入是动态的并行处理 |

</edge-type-selection>

---

## Command

Command 把状态更新与路由合并进一个返回值。字段：
- **`update`**：要应用的状态更新（相当于节点返回一个 dict）
- **`goto`**：接下来要去的节点名（可以给多个）
- **`resume`**：`interrupt()` 之后用于恢复的值——见人在回路技能

<command-return-type-annotations>

**Python**：把 `Command[Literal["node_a", "node_b"]]` 用作返回类型标注，声明合法的 goto 目标。

**TypeScript**：给 `addNode` 传第三个参数 `{ ends: ["node_a", "node_b"] }`，声明合法的 goto 目标。

</command-return-type-annotations>

<warning-command-static-edges>

**警告**：`Command` 只添加**动态**边——用 `add_edge` / `addEdge` 定义的静态边照样会执行。如果 `node_a` 返回 `Command(goto="node_c")`，而你又写了 `graph.add_edge("node_a", "node_b")`，那么 `node_b` 和 `node_c` **两个**都会跑。

</warning-command-static-edges>

---

## Send API

用 `Send` 做扇出：在条件边里返回 `[Send("worker", {...})]`，就能派生出一批并行 worker。结果字段上必须配一个归约器。

---

## 运行图：invoke 与流式输出

<invoke-basics>

调用 `graph.invoke(input, config)` 可以让图一路跑到结束，并返回最终状态。

</invoke-basics>

<stream-mode-selection>

| 模式 | 流出的是什么 | 适用场景 |
|------|----------------|----------|
| `values` | 每一步之后的完整状态 | 监控完整状态 |
| `updates` | 状态增量 | 跟踪增量更新 |
| `messages` | LLM 的 token 与元数据 | 聊天界面 |
| `custom` | 用户自定义的数据 | 进度提示 |

</stream-mode-selection>

---

## 错误处理

先把错误归类，再对上正确的处理方式：

<error-handling-table>

| 错误类型 | 谁来修 | 策略 | 示例 |
|---|---|---|---|
| 瞬时故障（网络、限流） | 系统 | `RetryPolicy(max_attempts=3)` | `add_node(..., retry_policy=...)` |
| LLM 能恢复的（工具失败） | LLM | `ToolNode(tools, handle_tool_errors=True)` | 错误作为 ToolMessage 返回 |
| 用户能修的（缺信息） | 人 | `interrupt({"message": ...})` | 收集缺失的信息（见人在回路技能） |
| 意料之外的 | 开发者 | 让它向上冒泡 | `raise` |

</error-handling-table>

---

## 核心边界

- 节点返回局部的状态更新，不要直接去改状态本身。
- 循环要经由一个**具名**节点来路由；`START` 只作入口用。
- 累积型的列表字段要定义归约器；否则后写的会盖掉先写的。
- 用 `Command` 配 `goto` 时，记得算上静态边，因为两条路由都会执行。

## 实现参考

如果要写、改或调试 LangGraph 代码，先从项目现有文件判断它用的是什么语言，然后动手之前读对应的那份参考：

- Python：读 [references/python.md](references/python.md)。
- TypeScript：读 [references/typescript.md](references/typescript.md)。

只有任务同时涉及两种语言时，才把两份都读。纯概念问题不需要写代码，那就哪份参考都不用加载。

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
