---
name: "Deepagents Python Quickstart（Deep Agents Python 快速入门）"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-deepagents-python-quickstart/SKILL.md
description: >-
  沿官方快速入门，在本地搭建一个最小的 Deep Agents Python 智能体，用 provider 原生的 web search 代替 Tavily。
  当用户想在本地快速构建或试用 Deep Agent 时使用。
tags:
  - "deepagents"
  - "python"
  - "quickstart"
  - "langchain-skills"
triggers:
  - "用户想在本地快速构建或试用 Deep Agent"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "bash"
author: "langchain-skills (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/deepagents-python-quickstart`（MIT，原样收录于
> `vendor/upstream-skills/langchain-skills/skills/deepagents-python-quickstart/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


# Deep Agents Python 快速入门

跟着官方在线文档走——不要凭记忆另造一套 API：

**https://docs.langchain.com/oss/python/deepagents/quickstart**

抓取那个页面（Docs MCP 或 HTTP），照着它演示的研究型智能体形态实现（`create_deep_agent`、研究用 system prompt、用“What is LangGraph?”这类研究问题去 invoke）。

## 本地环境约束

在快速入门之上再叠加这几条（它们让搭建保持最小，且与模型无关）：

1. **先问**用户用哪个 provider/model。顺带展示 Deep Agents 与模型无关。建议的提示词：

   > 这个智能体该用哪个模型？传一个 `provider:model` 字符串——例如 `openai:gpt-5.5`、`anthropic:claude-sonnet-5`、`google_genai:gemini-3.5-flash`。拿不准就用默认值：**`anthropic:claude-sonnet-5`**。  
   > 我们会用该 provider 内置的 web search（不需要单独的搜索 API key）。

2. 建一个**新**目录（例如 `deep-agent/`），所有工作都在那里做——不要弄脏当前打开的项目。

3. **不要用 Tavily**（也不要引入第二个搜索厂商）。把快速入门里的 `internet_search` / Tavily 工具换成所选 provider 内置的 web search。到那个 provider 的 LangChain chat 文档里查当前的工具形态（以下是写作时的示例——有需要就重新核对）：

   | Provider | 内置搜索工具 |
   |----------|----------------------|
   | Anthropic | `{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}` |
   | OpenAI | `{"type": "web_search"}` |
   | Google | `{"google_search": {}}` |

   优先用 Anthropic / OpenAI / Google，这样才有 provider 搜索可用。唯一的机密：该 provider 的 API key，放在 `.env` 里（已被 gitignore）。除非用户开口，跳过 LangSmith tracing。

4. 安装 `deepagents`（外加 `python-dotenv`）以及他们所用模型对应的 provider 包——不要装 `tavily-python`。

5. 跑通研究示例，展示输出，然后停下。下一步指向 `lc-deep-agents-core` / customization / Managed Deep Agents。

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
