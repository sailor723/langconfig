# Agent 训练 · 跟随 LangChain Agents 页

> 依据：**<https://docs.langchain.com/oss/python/langchain/agents>**
>
> 一句话：*a model calling tools in a loop until a task is complete, shaped by a harness
> of prompt, tools, and middleware.*

## 开场（页面原文）

> Agent 是一个**在循环里调用工具的模型**，直到给定任务完成为止。
> （*An agent is a model calling tools in a loop until a given task is complete.*）

![核心 agent 循环：request → model → action → tools → observation → model，直到模型给 result](assets/agent-loop.svg)

> Harness 是围绕这个循环的一切：**提示词、工具，以及任何塑造模型行为的中间件。**
> （*A harness is everything around that loop: the prompt, the tools, and any middleware
> that shapes the model's behavior.*）

> **Agent = Model + Harness**
> Harness 的职责：**在正确的时刻，把正确的上下文交给模型。**

## create_agent 就是一个可配置的 harness

> `create_agent` 高度可配置。最简单的用法是这样：

```python
from langchain.agents import create_agent

agent = create_agent(model="deepseek-flash", tools=tools)
```

> 在此基础上，**基础配置就是 `model=`、`tools=`、`system_prompt=` 三个参数**；
> 再往上要加能力，用中间件扩展 harness。

## 核心组件（Core components）

![agent = model + harness：model 在中心，周围是 system prompt、skills、memory、context、tools、subagents](assets/agent-harness.svg)

| 组件 | 页面原话 |
|---|---|
| **Model** | 传一个模型标识字符串（`"provider:model"`），或一个已初始化的模型实例。 |
| **Tools** | 传任何 Python 可调用对象、LangChain 工具或工具字典。 |
| **System prompt** | 塑造 agent 处理任务的方式。接受字符串或 `SystemMessage`。运行时要动态改，用中间件。 |
| **Structured output** | 用 `response_format=` 让 agent 返回**校验过的结构**。 |
| **Agent state** | 每个 agent 都用 `AgentState`（typed dictionary）管理执行上下文。内置字段是 `messages`（只追加）。要加自定义字段，继承它并用 `state_schema=` 传进去。 |

## 在平台上：模型 + 系统提示词 + 工具

三个位置填一次（Temperature 填 `0`）：

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
