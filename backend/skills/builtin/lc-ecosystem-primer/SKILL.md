---
name: "Ecosystem Primer（生态入门）"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-ecosystem-primer/SKILL.md
description: >-
  任何 LangChain / LangGraph / Deep Agents 智能体构建项目，都要在查阅其他技能、动笔写任何智能体代码之前
  先调用本技能。要拿到框架选型（LangChain vs LangGraph vs Deep Agents vs 混合组合）、智能体模式、安装、
  环境配置，以及下一步该加载哪个技能的最新信息，都必须从这里起步。
tags:
  - "ecosystem"
  - "primer"
  - "langchain-skills"
  - "skills"
  - "langgraph"
  - "langchain"
triggers:
  - "在 LangChain、LangGraph 或 Deep Agents 项目里动笔写第一行智能体代码之前"
  - "需要判断该用 LangChain、LangGraph、Deep Agents 还是混合组合时"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
  - "task"
  - "skill"
author: "langchain-skills (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/ecosystem-primer`（MIT，原样收录于 `vendor/upstream-skills/langchain-skills/skills/ecosystem-primer/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


<overview>
LangChain 公司维护着用于构建智能体的三层开源工具，外加 LangSmith 负责可观测性。整个栈自上而下是这样：

- **Deep Agents**（顶层，*脚手架*）——建在 LangChain + LangGraph 之上的开箱即用工具箱。规划、文件管理、子智能体派生与记忆，全都随箱自带。
- **LangGraph**（中层，*运行时*）——面向持久化执行、自定义控制流与有状态工作流的底层编排。LangChain 智能体就跑在 LangGraph 之上。
- **LangChain**（底层，*框架*）——模型、工具与智能体循环的抽象。与模型提供方无关，最容易上手。
- **LangSmith**（横切）——可观测性与评测平台。与框架无关；无论用上面哪一层，都建议一并配上。

上层依赖下层，但你并不需要直接使用下层。Deep Agents 让你不必写图代码，也能拿到 LangGraph 的持久化执行；
LangChain 让你不必打理图的边，也能拿到模型和工具。
</overview>

---

## 第 1 步——选你的工具

<decision-table>

按顺序逐条判断，命中第一个就停下：

1. 任务需要规划、跨长会话的文件管理、持久记忆、子智能体委派，或按需加载技能 → **Deep Agents**
2. 否则，任务需要自定义控制流（确定性循环、分支逻辑）→ **LangGraph**
3. 否则，是一组固定工具的单一用途智能体 → **LangChain**（`create_agent` 函数）
4. 否则，是纯模型调用、检索流水线，或不带智能体循环的简单提示词链 → **LangChain**（直接调模型 / 链）

这就是你的**层**。但事情还没完：到第 4 步时，写任何智能体代码之前，你**必须**加载该层对应的技能。

</decision-table>

---

## 工具画像

<langchain-profile>

### LangChain——智能体框架

**最适合：**
- 工具集固定不变的单一用途智能体
- RAG 流水线与文档问答
- 模型调用、提示词模板、结构化输出

**不适合：**
- 智能体需要跨很多步做规划，或要管理大上下文
- 控制流是条件式的、迭代式的或并行的
- 状态必须跨会话保留下来

所有 LangChain 智能体都用 `create_agent(model, tools=[...])`。

</langchain-profile>

<langgraph-profile>

### LangGraph——智能体运行时

**最适合：**
- 自定义控制流——确定性循环、反思循环、并行扇出
- 确定性步骤与智能体步骤混在一起的复杂工作流
- 带精确中断点与恢复点的人在回路
- 必须扛过故障、或跨长会话存活的状态

**不适合：**
- 你想要开箱即用的规划、文件管理与子智能体委派（那就用 Deep Agents）
- 工作流简单到一条直白的工具循环就够

所有 LangGraph 图都用 `StateGraph(State)`，配上显式的节点、边与条件边。

</langgraph-profile>

<deep-agents-profile>

### Deep Agents——智能体脚手架

**最适合：**
- 需要规划与任务分解的长跑任务
- 在整个会话里读写文件、管理文件的智能体
- 把子任务委派给专门的子智能体
- 跨会话的持久记忆
- 按需加载领域专用的技能

**不适合：**
- 任务简单到一个单一用途智能体就够
- 你需要对每一条图的边做精确的手工控制（那就直接用 LangGraph）

所有 Deep Agents 都用 `create_deep_agent(model, tools=[...])`。

</deep-agents-profile>

---

## 混用各层

<mixing-layers>

这些工具是分层的，所以在同一个项目里可以组合使用。常见模式：

- **Deep Agents 编排者 → LangGraph 子智能体**——主智能体需要规划与记忆，但其中某个子任务需要一张确定性图时。
- **把 LangGraph 图包装成工具或子智能体**——一条专门的流水线（比如 RAG、反思循环）被更外层的智能体调用时。

编译好的 LangGraph 图可以在 Deep Agents 里注册成一个具名子智能体——编排者通过 `task` 工具委派过去，并不需要知道它的内部结构。LangChain 的工具与检索器，在 LangGraph 节点里和 Deep Agents 工具里都能自由使用。

</mixing-layers>

---

## 第 2 步——设置环境变量

为了可观测性，这些变量要始终设置。它们是 LangSmith 当前使用的环境变量名。照原样抄。旧名字已经不再生效。

<environment-variables>
LANGSMITH_API_KEY=<your-key>
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=<project-name>
</environment-variables>

模型提供方与工具专属的键（`ANTHROPIC_API_KEY`、`OPENAI_API_KEY`、`TAVILY_API_KEY` 等）取决于你的栈——按需设置即可。

---

## 第 3 步——文档是怎么组织的

<docs>

所有文档都在 **docs.langchain.com** 上，分成两个顶层板块：

- **OSS**——LangChain、LangGraph、Deep Agents。Python（`/oss/python/`）与 TypeScript（`/oss/javascript/`）两套页面树并行。
- **LangSmith**——可观测性、评测、部署、提示词工程。

每个产品都有自己的页面树：概览 → 快速入门 → 操作指南 → 参考。

### 权威入口页

从这里起步，别从根目录一路翻树（TypeScript 把 `python` 换成 `javascript`）：

- **LangChain**——`/oss/python/langchain/overview`
- **LangGraph**——`/oss/python/langgraph/overview`
- **Deep Agents**——`/oss/python/deepagents/overview`
- **LangSmith**——`/langsmith/home`（不分语言）

### 在智能体上下文里取文档

**如果 LangChain Docs MCP server 已接上**（MCP server 加进来的 `docs-langchain_*` 工具可用），就直接查它：
```
tree /oss/python -L 2                        # explore Python structure
tree /oss/javascript -L 2                    # parallel TypeScript structure
cat /oss/python/langchain/quickstart.mdx     # read a specific page
rg -il "checkpointer" /oss/python/langgraph/ # search by keyword
```

**如果 MCP server 用不了**，就走 `llms.txt` 索引：
1. 抓 `https://docs.langchain.com/llms.txt`——这是带描述的、结构化的全部页面清单
2. 挑出与这个问题最相关的 2–4 页
3. 直接抓那几页，拿到准确、最新的内容

> 永远优先抓线上文档，不要依赖训练数据里的知识——这几个库演进很快，API 也经常变。

</docs>

---

## 第 4 步——接着加载哪个技能

如果用户只想要一个能在本地跑起来的最小智能体（新项目、桩工具、提供方 key），先加载对应的快速入门：

- LangChain → `lc-langchain-python-quickstart` 或 `lc-langchain-typescript-quickstart`
- LangGraph → `lc-langgraph-python-quickstart` 或 `lc-langgraph-typescript-quickstart`
- Deep Agents → `lc-deepagents-python-quickstart` 或 `lc-deepagents-typescript-quickstart`

否则，就加载下面与你第 1 步选定的层相匹配的那个技能。这一步是必须的——该层专属的技能才带着当前 API；光靠本入门指南是不够的。

<next-skills>

### LangChain

- **`lc-langchain-fundamentals`**——构建任何 LangChain 智能体
- **`lc-langchain-rag`**——要加 RAG / 向量库检索
- **`lc-langchain-middleware`**——要用 Pydantic 做结构化输出
- **`lc-langchain-dependencies`**——包版本、安装或依赖管理方面的问题

### LangGraph

- **`lc-langgraph-fundamentals`**——任何 LangGraph 图
- **`lc-langgraph-human-in-the-loop`**——人在回路或审批工作流
- **`lc-langgraph-persistence`**——必须扛过重启的状态，或跨线程记忆

### Deep Agents

**先加载 `lc-deep-agents-core`。** 然后按需加载：

- **`lc-deep-agents-orchestration`**——子智能体委派或编排
- **`lc-deep-agents-memory`**——跨会话的持久记忆

</next-skills>

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
