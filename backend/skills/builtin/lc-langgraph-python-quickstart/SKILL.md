---
name: "Langgraph Python Quickstart（LangGraph Python 快速入门）"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-langgraph-python-quickstart/SKILL.md
description: >-
  沿官方快速入门，在本地搭建一个最小的 LangGraph Python 智能体。
  当用户想在本地快速构建或试用 LangGraph 智能体时使用。
tags:
  - "langgraph"
  - "python"
  - "quickstart"
  - "langchain-skills"
triggers:
  - "用户想在本地快速构建或试用 LangGraph 智能体"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
author: "langchain-skills (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/langgraph-python-quickstart`（MIT，原样收录于
> `vendor/upstream-skills/langchain-skills/skills/langgraph-python-quickstart/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


# LangGraph Python 快速入门

跟着官方在线文档走——不要凭记忆另造一套 API：

**https://docs.langchain.com/oss/python/langgraph/quickstart**

抓取那个页面（Docs MCP 或 HTTP），照着它演示的内容实现（用 Graph API 的 calculator / 数学智能体）。除非用户另有要求，走 Graph API 这条路而不是 Functional API。跳过 IPython 的图可视化。

## 本地环境约束

在快速入门之上再叠加这几条（它们让搭建保持最小，且与模型无关）：

1. **先问**用户用哪个 provider/model。顺带展示 LangGraph 能搭配任意 LangChain chat model。建议的提示词：

   > 这个智能体该用哪个模型？传一个 `provider:model` 字符串——例如 `openai:gpt-5.5`、`anthropic:claude-sonnet-5`、`google_genai:gemini-2.5-flash-lite`。拿不准就用默认值：**`anthropic:claude-sonnet-5`**。

   文档里常把 Anthropic 写死——换成 `init_chat_model("<MODEL>")`（或等价写法），填入他们的选择。如果用 Claude Sonnet 5+，省略 `temperature` / `top_p` / `top_k`（不支持）。

2. 建一个**新**目录（例如 `langgraph-agent/`），所有工作都在那里做——不要弄脏当前打开的项目。

3. 唯一的机密：`.env` 里的 provider API key（已被 gitignore）。除非用户开口，否则不要 LangSmith / Tavily。尽量让用户自己改 `.env`——不要把密钥贴进对话。

4. 装快速入门里的包，再加上他们所用模型对应的 provider 包。

5. 跑通示例（例如“Add 3 and 4.”），展示输出，然后停下。下一步指向 `langgraph-fundamentals`。若要更高层的 agent API，改用 LangChain 的 `create_agent`。

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
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `ecosystem-primer` 规则——并优先选
  能胜任的最高层。
