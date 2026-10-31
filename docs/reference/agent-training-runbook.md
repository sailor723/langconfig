# Agent 训练 · 对齐 LangChain Agents 页

> 依据：**<https://docs.langchain.com/oss/python/langchain/agents>**

## 页面上怎么说的

> **An agent is a model calling tools in a loop** until a given task is complete.

> A harness is everything around that loop: **the prompt, the tools, and any middleware**
> that shapes the model's behavior.

> **The job of a harness: get the model the right context at the right time for the given task.**

> **Agent = Model + Harness.**

> **Middleware is the primitive for customization**: each piece handles one concern, hooks into
> the agent loop at the right moment, and composes freely with any other.

## 图 1 · 核心循环

![核心 agent 循环：request → model → action → tools → observation → model，直到模型给 result](assets/agent-loop.svg)

循环的终点由模型决定；`action` 是它要调工具，`observation` 是工具回来的结果。
**没有 tools 这条边，就只是一次模型调用。**

## 图 2 · agent = model + harness

![agent = model + harness：model 在中心，周围是 system prompt、skills、memory、context、tools、subagents](assets/agent-harness.svg)

中间只有 model 是"智能"；其余六块（system prompt、tools、skills、memory、context、subagents）
都是围着它摆的上下文。

## 页面上那段代码

```python
agent = create_agent(
    "deepseek-flash",                               # 模型
    tools=[get_weather],                            # 工具
    system_prompt="You are a helpful assistant",    # 系统提示词
)
agent.invoke({"messages": [{"role": "user", "content": "上海的天气如何？"}]})
```

平台上：**Model** = `deepseek-flash`（Temperature `0`）｜**System Prompt** =
`You are a helpful assistant`｜**Tools** = `web_search`、`python_execute`、`pg_query`、`save_document`。

## 四个例子

每个例子各开新聊天，先发一句 `hi`。

| 问 | 它用了 | 结果 |
|---|---|---|
| 上海的天气如何？ | `web_search` | 晴转多云，18–25℃ |
| 1,234,567 乘以 891,011 等于多少？ | `python_execute` | 1,100,012,777,237 |
| 用 pg_query 查一下 deep_agent_templates 有多少个 agent | `pg_query` | 63 |
| 把这句话存成一份文档：标题《工具路由测试》，正文「四个工具各自命中了一次」 | `write_file` → `save_document` | 文件 + 文档库 |

提示词里没有一个字提工具，四个例子它都自己挑对了 —— **挑哪个由工具自己的描述决定**。
