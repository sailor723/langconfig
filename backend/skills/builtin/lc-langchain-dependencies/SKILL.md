---
name: "Langchain Dependencies（LangChain 依赖）"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-langchain-dependencies/SKILL.md
description: >-
  新建项目时、或被问到 LangChain、LangGraph、LangSmith、Deep Agents 的包版本、安装与依赖管理时，
  都要调用本技能。覆盖所需包、最低版本、环境要求、版本管理最佳实践，以及 Python 与 TypeScript
  两侧常用的社区工具包。
tags:
  - "langchain"
  - "dependencies"
  - "langchain-skills"
  - "skills"
  - "langgraph"
  - "deepagents"
triggers:
  - "新建 LangChain、LangGraph、LangSmith 或 Deep Agents 项目时"
  - "被问到包版本、安装方式或依赖管理时"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "bash"
  - "skill"
author: "langchain-skills (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/langchain-dependencies`（MIT，原样收录于
> `vendor/upstream-skills/langchain-skills/skills/langchain-dependencies/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


<overview>
LangChain 生态被拆成多个职责单一、各自独立定版本的包。弄清楚你需要哪些包、以及它们的版本约束，可以避开不兼容，并让升级变得可预期。

**关键原则：**
- **LangChain 1.0 是当前的 LTS 版本。** 新项目一律从 1.0+ 起。LangChain 0.3 是遗留维护版——新工作不要用它。
- **langchain-core** 是共享的地基：永远把它和其他任何包一起显式安装。
- **langchain-community**（仅 Python）不遵循语义化版本；要保守地钉住版本。
- **LangGraph 还是 Deep Agents：** 按你的使用场景选**一种**编排方式——它们是二选一的替代品，不是必须叠起来的栈（见下文[框架选择](#框架选择)）。
- 模型提供方、向量库、工具这些集成是分开安装的，所以只引入你实际用到的部分。
</overview>

---

## 环境要求

<environment-requirements>

| 要求 | Python | TypeScript / Node |
|-------------|--------|-------------------|
| 运行时最低版本 | **Python 3.10+** | **Node.js 20+** |
| LangChain | **1.0+（LTS）** | **1.0+（LTS）** |
| LangSmith SDK | >= 0.3.0 | >= 0.3.0 |

</environment-requirements>

---

## 框架选择

<framework-choice>
只挑**一层**智能体编排。你不需要两个都要。

| 框架 | 什么时候用 | 核心附加包 |
|-----------|-------------|--------------------|
| **LangGraph** | 需要对图做细粒度控制、自定义工作流、循环或分支 | `langgraph` / `@langchain/langgraph` |
| **Deep Agents** | 想要开箱即用的规划、记忆、文件上下文和技能 | `deepagents`（依赖 LangGraph，作为传递依赖一并装上） |

两者都坐在 `langchain` + `langchain-core` + `langsmith` 之上。
</framework-choice>

---

## 核心包

<python-packages>

### Python——始终必需

| 包 | 作用 | 最低版本 |
|---------|------|-------------|
| `langchain` | 智能体、链、检索 | 1.0 |
| `langchain-core` | 基础类型与接口（对等依赖） | 1.0 |
| `langsmith` | 追踪、评测、数据集 | 0.3.0 |

### Python——编排（选一个）

| 包 | 什么时候用 | 最低版本 |
|---------|----------|-------------|
| `langgraph` | 直接构建自定义图 | 1.0 |
| `deepagents` | 使用 Deep Agents 框架 | 最新 |

### Python——模型提供方（用哪个装哪个）

| 包 | 提供方 |
|---------|----------|
| `langchain-openai` | OpenAI (GPT-4o, o3, …) |
| `langchain-anthropic` | Anthropic (Claude) |
| `langchain-google-genai` | Google (Gemini) |
| `langchain-mistralai` | Mistral |
| `langchain-groq` | Groq (fast inference) |
| `langchain-cohere` | Cohere |
| `langchain-fireworks` | Fireworks AI |
| `langchain-together` | Together AI |
| `langchain-huggingface` | Hugging Face Hub |
| `langchain-ollama` | Ollama (local models) |
| `langchain-aws` | AWS Bedrock |
| `langchain-azure-ai` | Azure AI Foundry |

### Python——常用工具与检索包

这些包的兼容性要求更紧——除非有明确理由，否则用当前可用的最新版本。

| 包 | 增加什么 | 说明 |
|---------|------|-------|
| `langchain-tavily` | Tavily 网页搜索（`TavilySearch`） | 专用集成包；优先用最新版 |
| `langchain-text-splitters` | 文本分块工具 | 走 semver，保持较新 |
| `langchain-community` | 1000+ 集成（兜底） | **不是 semver——钉到次版本系列** |
| `faiss-cpu` | FAISS 向量库（本地） | 经由 `langchain-community`；用最新版 |
| `langchain-chroma` | Chroma 向量库 | 专用集成包；优先用最新版 |
| `langchain-pinecone` | Pinecone 向量库 | 专用集成包；优先用最新版 |
| `langchain-qdrant` | Qdrant 向量库 | 专用集成包；优先用最新版 |
| `langchain-weaviate` | Weaviate 向量库 | 专用集成包；优先用最新版 |
| `langsmith[pytest]` | LangSmith 的 pytest 插件 | 要求 langsmith >= 0.3.4 |

> **langchain-community 的稳定性提醒：** 这个包不走语义化版本。次版本发布就可能带破坏性改动。只要有专用集成包（例如 `langchain-chroma`、`langchain-tavily`）就用它——那些包独立定版本，也更稳定。

</python-packages>

<typescript-packages>

### TypeScript——始终必需

| 包 | 作用 | 最低版本 |
|---------|------|-------------|
| `@langchain/core` | 基础类型与接口（对等依赖） | 1.0 |
| `langchain` | 智能体、链、检索 | 1.0 |
| `langsmith` | 追踪、评测、数据集 | 0.3.0 |

### TypeScript——编排（选一个）

| 包 | 什么时候用 | 最低版本 |
|---------|----------|-------------|
| `@langchain/langgraph` | 直接构建自定义图 | 1.0 |
| `deepagents` | 使用 Deep Agents 框架 | 最新 |

### TypeScript——模型提供方（用哪个装哪个）

| 包 | 提供方 |
|---------|----------|
| `@langchain/openai` | OpenAI (GPT-4o, o3, …) |
| `@langchain/anthropic` | Anthropic (Claude) |
| `@langchain/google-genai` | Google (Gemini) |
| `@langchain/mistralai` | Mistral |
| `@langchain/groq` | Groq (fast inference) |
| `@langchain/cohere` | Cohere |
| `@langchain/aws` | AWS Bedrock |
| `@langchain/azure-openai` | Azure OpenAI |
| `@langchain/ollama` | Ollama (local models) |

### TypeScript——常用工具与检索包

| 包 | 增加什么 | 说明 |
|---------|------|-------|
| `@langchain/tavily` | Tavily 网页搜索（`TavilySearch`） | 专用集成包；优先用最新版 |
| `@langchain/community` | 覆盖面很广的社区集成 | 少用；优先专用包 |
| `@langchain/pinecone` | Pinecone 向量库 | 专用集成包；优先用最新版 |
| `@langchain/qdrant` | Qdrant 向量库 | 专用集成包；优先用最新版 |
| `@langchain/weaviate` | Weaviate 向量库 | 专用集成包；优先用最新版 |

> **在 yarn workspaces 和 monorepo 里，`@langchain/core` 必须显式安装**——它是对等依赖，不一定总会被自动提升。

</typescript-packages>

---

## 最小项目模板

<ex-langgraph-python>
<python>
LangGraph 项目的最小依赖集（不绑定模型提供方）。

```
# requirements.txt
langchain>=1.0,<2.0
langchain-core>=1.0,<2.0
langgraph>=1.0,<2.0
langsmith>=0.3.0

# Add your model provider, e.g.:
# langchain-openai
# langchain-anthropic
# langchain-google-genai
```
</python>
</ex-langgraph-python>

<ex-langgraph-typescript>
<typescript>
LangGraph 项目的最小 package.json 依赖（不绑定模型提供方）。

```json
{
  "dependencies": {
    "@langchain/core": "^1.0.0",
    "langchain": "^1.0.0",
    "@langchain/langgraph": "^1.0.0",
    "langsmith": "^0.3.0"
  }
}
```
</typescript>
</ex-langgraph-typescript>

<ex-deepagents-python>
<python>
Deep Agents 项目的最小依赖集（不绑定模型提供方）。

```
# requirements.txt
deepagents            # bundles langgraph internally
langchain>=1.0,<2.0
langchain-core>=1.0,<2.0
langsmith>=0.3.0

# Add your model provider, e.g.:
# langchain-anthropic
# langchain-openai
```
</python>
</ex-deepagents-python>

<ex-deepagents-typescript>
<typescript>
Deep Agents 项目的最小 package.json 依赖（不绑定模型提供方）。

```json
{
  "dependencies": {
    "deepagents": "latest",
    "@langchain/core": "^1.0.0",
    "langchain": "^1.0.0",
    "langsmith": "^0.3.0"
  }
}
```
</typescript>
</ex-deepagents-typescript>

<ex-with-tools-python>
<python>
给 LangGraph 项目加上 Tavily 搜索和向量库。

```
# requirements.txt
langchain>=1.0,<2.0
langchain-core>=1.0,<2.0
langgraph>=1.0,<2.0
langsmith>=0.3.0

# Web search
langchain-tavily          # use latest; partner package, semver

# Vector store — pick one:
langchain-chroma          # use latest; partner package, semver
# langchain-pinecone      # use latest; partner package, semver
# langchain-qdrant        # use latest; partner package, semver

# Text processing
langchain-text-splitters  # use latest; semver

# Your model provider:
# langchain-openai / langchain-anthropic / etc.
```
</python>
</ex-with-tools-python>

<ex-with-tools-typescript>
<typescript>
给 LangGraph 项目加上 Tavily 搜索和向量库。

```json
{
  "dependencies": {
    "@langchain/core": "^1.0.0",
    "langchain": "^1.0.0",
    "@langchain/langgraph": "^1.0.0",
    "langsmith": "^0.3.0",
    "@langchain/tavily": "latest",
    "@langchain/pinecone": "latest"
  }
}
```
</typescript>
</ex-with-tools-typescript>

---

## 版本策略与升级策略

<versioning-policy>

| 包分组 | 版本方式 | 安全的升级策略 |
|---------------|------------|-----------------------|
| `langchain`、`langchain-core` | 严格 semver（1.0 LTS） | 放开次版本：`>=1.0,<2.0` |
| `langgraph` / `@langchain/langgraph` | 严格 semver（v1 LTS） | 放开次版本：`>=1.0,<2.0` |
| `langsmith` | 严格 semver | 放开次版本：`>=0.3.0` |
| 专用集成包（例如 `langchain-tavily`、`langchain-chroma`） | 独立定版本 | 允许次版本更新；用最新版 |
| `langchain-community` | **不是 semver** | 钉死次版本：`>=0.4.0,<0.5.0` |
| `deepagents` | 跟随项目发布节奏 | 生产环境钉到已测试的版本 |

**破坏性改动只发生在主版本里**（1.x → 2.x），所有遵循 semver 的包都是如此。已废弃的功能在整个 1.x 系列里仍然可用，只是会给出警告。

**优先用专用集成包，而不是 langchain-community。** 只要存在专用包（例如用 `langchain-chroma` 而不是 `langchain-community` 里的 Chroma 集成），就用它——专用包独立定版本，测试也更充分。

**社区工具包（Tavily、各类向量库等）应保持在最新版**，除非你的项目需要一个锁死的环境。这些包经常跟着 LangChain/LangGraph 的更新一起发布兼容性修复。

</versioning-policy>

---

## 环境变量

<environment-variables>
所有 key 都在运行时从环境里读取。只设置你真正用到的那些服务的 key。

```bash
# LangSmith (always recommended for observability)
LANGSMITH_API_KEY=<your-key>
LANGSMITH_PROJECT=<project-name>   # optional, defaults to "default"

# Model provider — set the one(s) you use
OPENAI_API_KEY=<your-key>
ANTHROPIC_API_KEY=<your-key>
GOOGLE_API_KEY=<your-key>
MISTRAL_API_KEY=<your-key>
GROQ_API_KEY=<your-key>
COHERE_API_KEY=<your-key>
FIREWORKS_API_KEY=<your-key>
TOGETHER_API_KEY=<your-key>
HUGGINGFACEHUB_API_TOKEN=<your-key>

# Common tool/retrieval services
TAVILY_API_KEY=<your-key>          # for Tavily search
PINECONE_API_KEY=<your-key>        # for Pinecone
```
</environment-variables>

---

## 常见错误

<fix-legacy-version>
永远不要用 LangChain 0.3 起新项目。它只做维护，直到 2026 年 12 月。

```
# WRONG: legacy, no new features, security patches only
langchain>=0.3,<0.4

# CORRECT: LangChain 1.0 LTS
langchain>=1.0,<2.0
```
</fix-legacy-version>

<fix-community-unpinned>
`langchain-community` 在次版本升级时就可能坏掉——它不遵循 semver。

```
# WRONG: allows minor-version updates that may be breaking
langchain-community>=0.4

# CORRECT: pin to exact minor series
langchain-community>=0.4.0,<0.5.0
```
另外，如果存在等价的专用集成包，可以考虑切过去（例如用 `langchain-chroma` 而不是社区版的 Chroma 集成）。
</fix-community-unpinned>

<fix-community-tool-outdated>
`langchain-tavily` 这类社区工具包和向量库集成，会跟着 LangChain 的更新一起发布兼容性修复。用一个旧的钉死版本，可能导致导入报错或工具 schema 坏掉。

```
# RISKY: old pin may be incompatible with LangChain 1.0
langchain-tavily==0.0.1

# BETTER: allow latest within the current major
langchain-tavily>=0.1
```
</fix-community-tool-outdated>

<fix-community-import-deprecated>
许多原先住在 `langchain-community` 里的工具，现在有了专用包和更新过的导入路径。始终优先用专用包的导入。

```python
# WRONG — deprecated community import path
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_community.tools import WikipediaQueryRun
from langchain_community.vectorstores import Chroma
from langchain_community.vectorstores import Pinecone

# CORRECT — use dedicated package imports
from langchain_tavily import TavilySearch                  # pip: langchain-tavily (TavilySearchResults is deprecated)
from langchain_community.tools import WikipediaQueryRun  # no dedicated pkg yet
from langchain_chroma import Chroma                       # pip: langchain-chroma
from langchain_pinecone import PineconeVectorStore        # pip: langchain-pinecone
```

要查任何集成当前的标准导入，去搜集成目录：
https://python.langchain.com/docs/integrations/tools/

每个条目都写明正确的包和导入路径。只要有专用包就用它——社区路径也许还能用，但已算遗留写法。
</fix-community-import-deprecated>

<fix-core-not-installed>
<typescript>
`@langchain/core` 是对等依赖——它必须出现在你的 package.json 里，在 monorepo 里尤其如此。

```json
// WRONG: missing @langchain/core (breaks in yarn workspaces / strict hoisting)
{
  "dependencies": {
    "@langchain/langgraph": "^1.0.0"
  }
}

// CORRECT: always list @langchain/core explicitly
{
  "dependencies": {
    "@langchain/core": "^1.0.0",
    "@langchain/langgraph": "^1.0.0"
  }
}
```
</typescript>
</fix-core-not-installed>

<fix-python-version>
<python>
LangChain 1.0 不支持 Python 3.9 及更低版本。

```python
# Verify before installing
import sys
assert sys.version_info >= (3, 10), "Python 3.10+ required for LangChain 1.0"
```
</python>
</fix-python-version>

<fix-node-version>
<typescript>
Node.js 20 以下不在官方支持范围内。

```bash
# Verify before installing
node --version   # must be v20.x or higher
```
</typescript>
</fix-node-version>

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
