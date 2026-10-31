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

| 页面参数 | 平台上 | 这一轮填的 |
|---|---|---|
| `model=` | Overview → Model | `deepseek-flash`（Temperature `0`） |
| `system_prompt=` | Prompt → System Prompt | 一段中文工具说明（"搜索用 web_search / web_fetch，出文档用 write_file，不要编造数据"） |
| `tools=` | Tools 页签 | 28 个（`web_search`、`web_fetch`、`tavily_search`、`python_execute`、`pg_query`、`pg_describe_table`、`write_file`、`save_document`、`bash`、`ls` …） |

## 四个例子

同一个聊天里依次问这四句（第一条先发 `hi`）。

| 问 | 它用了 | 结果 |
|---|---|---|
| 上海的天气如何 | `web_search` ×2 + `web_fetch`（wttr.in） | 晴、约 23℃，今天 16–24℃ |
| 1,234,567 乘以 891,011 等于多少？ | `python_execute` | 1,100,012,777,237 |
| 用 pg_query 查一下 deep_agent_templates 有多少个 agent | `pg_query`（+ `pg_describe_table`） | 63 个，19 个分类 |
| 总结现在的 agent，输出一个文档 → 输出为 PDF | `write_file` ×5 + `save_document` + `python_execute` | `Agent_模板清单总览.md`、7 页 PDF、文档库归档 |

这 7 轮对话一共 **39 次工具调用、10 个工具**（还用到了 `ls`、`bash`、`delete`）。
天气那一句它同时用了 `web_fetch` 和 `web_search` 两个工具交叉核对 —— 页面那句 *a model calling tools
in a loop*，现场就是这样。

