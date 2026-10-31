# Agent 训练 · 跟随 LangChain Agents 页

> 依据：**<https://docs.langchain.com/oss/python/langchain/agents>**
>
> 页面的一句话：*a model calling tools in a loop until a task is complete, shaped by a harness
> of prompt, tools, and middleware.*

## 开场（页面原文）

> An agent is a **model calling tools in a loop** until a given task is complete.

![核心 agent 循环：request → model → action → tools → observation → model，直到模型给 result](assets/agent-loop.svg)

> A harness is everything around that loop: **the prompt, the tools, and any middleware**
> that shapes the model's behavior.

> **Agent = Model + Harness**
> The job of a harness: get the model the right context at the right time for the given task.

## create_agent 就是一个可配置的 harness

> `create_agent` is a highly configurable harness. At its simplest, you can create one with:

```python
from langchain.agents import create_agent

agent = create_agent(model="deepseek-flash", tools=tools)
```

> Building on that, you can configure the basics directly with the `model=`, `tools=`, and
> `system_prompt=` parameters. For more advanced capabilities, extend the harness with middleware.

## Core components

![agent = model + harness：model 在中心，周围是 system prompt、skills、memory、context、tools、subagents](assets/agent-harness.svg)

| 组件 | 页面原话 |
|---|---|
| **Model** | Pass a model identifier string (`"provider:model"`) or an initialized model instance to select the model for your agent. |
| **Tools** | To provide the agent with tools, pass any Python callable, LangChain tool, or tool dict. |
| **System prompt** | Shape how the agent approaches tasks. Accepts a string or `SystemMessage`. For dynamic prompts at runtime, use middleware. |
| **Structured output** | Return a **validated schema** from the agent using `response_format=`. |
| **Agent state** | Every agent manages its execution context through `AgentState`, a typed dictionary. The built-in field is `messages` (append-only). To add custom fields, subclass it and pass via `state_schema=`. |

## 在平台上：模型 + 系统提示词 + 工具

三个位置填一次（Temperature `0`）：

| 页面参数 | 平台上 | 填什么 |
|---|---|---|
| `model=` | Overview → Model | `deepseek-flash` |
| `system_prompt=` | Prompt → System Prompt | `You are a helpful assistant` |
| `tools=` | Tools 页签 | `web_search`、`python_execute`、`pg_query`、`save_document` |

## 四个例子

每个例子各开新聊天，先发一句 `hi`。

| 问 | 它用了 | 结果 |
|---|---|---|
| 上海的天气如何？ | `web_search` | 晴转多云，18–25℃ |
| 1,234,567 乘以 891,011 等于多少？ | `python_execute` | 1,100,012,777,237 |
| 用 pg_query 查一下 deep_agent_templates 有多少个 agent | `pg_query` | 63 |
| 把这句话存成一份文档：标题《工具路由测试》，正文「四个工具各自命中了一次」 | `write_file` → `save_document` | 文件 + 文档库 |

提示词里没有一个字提工具，四个例子它都自己挑对了 —— **挑哪个由工具自己的描述决定**。
