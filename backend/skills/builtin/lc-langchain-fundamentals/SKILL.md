---
name: "Langchain Fundamentals（LangChain 基础）"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-langchain-fundamentals/SKILL.md
description: >-
  用 create_agent 创建 LangChain 智能体、定义工具，并用中间件实现人在回路与错误处理。
tags:
  - "langchain"
  - "fundamentals"
  - "langchain-skills"
triggers:
  - "当被要求 <oneliner> 时"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "bash"
author: "langchain-skills (MIT), adapted for LangConfig"
version: "1.0"
---

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/langchain-fundamentals`（MIT，原样收录于 `vendor/upstream-skills/langchain-skills/skills/langchain-fundamentals/SKILL.md`）。
> 为本仓库所做的改动：frontmatter（元数据）字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。

## Instructions（指令）

<oneliner>
用 `create_agent()`、中间件（middleware）模式，以及 `@tool` 装饰器 / `tool()` 函数来构建生产级智能体。凡是要创建 LangChain 智能体，你**必须**用 create_agent()，自定义流程一律通过中间件实现。除此之外的其他写法都已经过时。
</oneliner>

<create_agent>
## 用 create_agent 创建智能体

`create_agent()` 是构建智能体的推荐方式。智能体循环、工具执行与状态管理这三件事，都由它负责打理。

### 智能体配置项

| 参数 | 用途 | 示例 |
|-----------|---------|---------|
| `model` | 要使用的 LLM 模型 | `"anthropic:claude-sonnet-4-5"` 或模型实例 |
| `tools` | 智能体可以调用的工具列表 | `[search, calculator]` |
| `system_prompt` / `systemPrompt` | 发给智能体的系统指令 | `"You are a helpful assistant"` |
| `checkpointer` | 负责状态持久化保存的检查点 | `MemorySaver()` |
| `middleware` | 拦截智能体循环各处节点的处理钩子 | `[HumanInTheLoopMiddleware]`（Python）/ `[humanInTheLoopMiddleware({...})]`（TypeScript） |
</create_agent>

<ex-basic-agent>
<python>

```python
from langchain.agents import create_agent
from langchain_core.tools import tool

@tool
def get_weather(location: str) -> str:
    """Get current weather for a location.

    Args:
        location: City name
    """
    return f"Weather in {location}: Sunny, 72F"

agent = create_agent(
    model="anthropic:claude-sonnet-4-5",
    tools=[get_weather],
    system_prompt="You are a helpful assistant."
)

result = agent.invoke({
    "messages": [{"role": "user", "content": "What's the weather in Paris?"}]
})
print(result["messages"][-1].content)
```
</python>
<typescript>

```typescript
import { createAgent } from "langchain";
import { tool } from "@langchain/core/tools";
import { z } from "zod";

const getWeather = tool(
  async ({ location }) => `Weather in ${location}: Sunny, 72F`,
  {
    name: "get_weather",
    description: "Get current weather for a location.",
    schema: z.object({ location: z.string().describe("City name") }),
  }
);

const agent = createAgent({
  model: "anthropic:claude-sonnet-4-5",
  tools: [getWeather],
  systemPrompt: "You are a helpful assistant.",
});

const result = await agent.invoke({
  messages: [{ role: "user", content: "What's the weather in Paris?" }],
});
console.log(result.messages[result.messages.length - 1].content);
```
</typescript>
</ex-basic-agent>

<ex-agent-with-persistence>
<python>
给它配上 MemorySaver 检查点（checkpointer），让整个会话的状态在多次调用之间留存下来、不丢失。

```python
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver

checkpointer = MemorySaver()

agent = create_agent(
    model="anthropic:claude-sonnet-4-5",
    tools=[search],
    checkpointer=checkpointer,
)

config = {"configurable": {"thread_id": "user-123"}}
agent.invoke({"messages": [{"role": "user", "content": "My name is Alice"}]}, config=config)
result = agent.invoke({"messages": [{"role": "user", "content": "What's my name?"}]}, config=config)
# Agent remembers: "Your name is Alice"
```
</python>
<typescript>
给它配上 MemorySaver 检查点（checkpointer），让整个会话的状态在多次调用之间留存下来、不丢失。

```typescript
import { createAgent } from "langchain";
import { MemorySaver } from "@langchain/langgraph";

const checkpointer = new MemorySaver();

const agent = createAgent({
  model: "anthropic:claude-sonnet-4-5",
  tools: [search],
  checkpointer,
});

const config = { configurable: { thread_id: "user-123" } };
await agent.invoke({ messages: [{ role: "user", content: "My name is Alice" }] }, config);
const result = await agent.invoke({ messages: [{ role: "user", content: "What's my name?" }] }, config);
// Agent remembers: "Your name is Alice"
```
</typescript>
</ex-agent-with-persistence>

<tools>
## 定义工具

工具（tool）就是交给智能体去调用的那些函数。定义时 Python 里用 `@tool` 装饰器，TypeScript 里用 `tool()` 函数。
</tools>

<ex-basic-tool>
<python>

```python
from langchain_core.tools import tool

@tool
def add(a: float, b: float) -> float:
    """Add two numbers.

    Args:
        a: First number
        b: Second number
    """
    return a + b
```
</python>
<typescript>

```typescript
import { tool } from "@langchain/core/tools";
import { z } from "zod";

const add = tool(
  async ({ a, b }) => a + b,
  {
    name: "add",
    description: "Add two numbers.",
    schema: z.object({
      a: z.number().describe("First number"),
      b: z.number().describe("Second number"),
    }),
  }
);
```
</typescript>
</ex-basic-tool>

<middleware>
## 用中间件控制智能体

中间件（middleware）会拦截智能体循环，用来加上人工审批、错误处理、日志记录等等能力。做生产级智能体，必须把中间件的机制吃透——审批工作流用 `HumanInTheLoopMiddleware`（Python）/ `humanInTheLoopMiddleware`（TypeScript），自定义钩子用 `@wrap_tool_call`（Python）/ `createMiddleware`（TypeScript）。

下面这些是关键的 import 语句：

```python
from langchain.agents.middleware import HumanInTheLoopMiddleware, wrap_tool_call
```

```typescript
import { humanInTheLoopMiddleware, createMiddleware } from "langchain";
```

这几种关键模式值得记住：
- **人在回路（HITL）**：`middleware=[HumanInTheLoopMiddleware(interrupt_on={"dangerous_tool": True})]` —— 需要同时配好 `checkpointer` 与 `thread_id`
- **中断之后恢复执行**：`agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=config)`
- **自定义中间件**：用 `@wrap_tool_call` 装饰器（Python）或 `createMiddleware({ wrapToolCall: ... })`（TypeScript）挂自定义钩子
</middleware>

<structured_output>
## 结构化输出

用 `response_format` 或 `with_structured_output()`，从智能体那里拿到带类型、并且经过校验的响应结构。

<python>

```python
from langchain.agents import create_agent
from pydantic import BaseModel, Field

class ContactInfo(BaseModel):
    name: str
    email: str
    phone: str = Field(description="Phone number with area code")

# Option 1: Agent with structured output
agent = create_agent(model="gpt-4.1", tools=[search], response_format=ContactInfo)
result = agent.invoke({"messages": [{"role": "user", "content": "Find contact for John"}]})
print(result["structured_response"])  # ContactInfo(name='John', ...)

# Option 2: Model-level structured output (no agent needed)
from langchain_openai import ChatOpenAI
model = ChatOpenAI(model="gpt-4.1")
structured_model = model.with_structured_output(ContactInfo)
response = structured_model.invoke("Extract: John, john@example.com, 555-1234")
# ContactInfo(name='John', email='john@example.com', phone='555-1234')
```
</python>
<typescript>

```typescript
import { ChatOpenAI } from "@langchain/openai";
import { z } from "zod";

const ContactInfo = z.object({
  name: z.string(),
  email: z.string().email(),
  phone: z.string().describe("Phone number with area code"),
});

// Model-level structured output
const model = new ChatOpenAI({ model: "gpt-4.1" });
const structuredModel = model.withStructuredOutput(ContactInfo);
const response = await structuredModel.invoke("Extract: John, john@example.com, 555-1234");
// { name: 'John', email: 'john@example.com', phone: '555-1234' }
```
</typescript>
</structured_output>

<model_config>
## 模型配置

`create_agent` 既接受模型字符串（`"anthropic:claude-sonnet-4-5"`、`"openai:gpt-4.1"`），也接受模型实例，后者用来做自定义设置：

```python
from langchain_anthropic import ChatAnthropic
agent = create_agent(model=ChatAnthropic(model="claude-sonnet-4-5", temperature=0), tools=[...])
```
</model_config>


<fix-missing-tool-description>
<python>
把工具的描述写清楚，智能体才能判断在什么情况下该调用哪一个工具。

```python
# WRONG: Vague or missing description
@tool
def bad_tool(input: str) -> str:
    """Does stuff."""
    return "result"

# CORRECT: Clear, specific description with Args
@tool
def search(query: str) -> str:
    """Search the web for current information about a topic.

    Use this when you need recent data or facts.

    Args:
        query: The search query (2-10 words recommended)
    """
    return web_search(query)
```
</python>
<typescript>
把工具的描述写清楚，智能体才能判断在什么情况下该调用哪一个工具。

```typescript
// WRONG: Vague description
const badTool = tool(async ({ input }) => "result", {
  name: "bad_tool",
  description: "Does stuff.", // Too vague!
  schema: z.object({ input: z.string() }),
});

// CORRECT: Clear, specific description
const search = tool(async ({ query }) => webSearch(query), {
  name: "search",
  description: "Search the web for current information about a topic. Use this when you need recent data or facts.",
  schema: z.object({
    query: z.string().describe("The search query (2-10 words recommended)"),
  }),
});
```
</typescript>
</fix-missing-tool-description>

<fix-no-checkpointer>
<python>
加上检查点（checkpointer）与 thread_id，让对话记忆在多轮调用之间留存下来不丢。

```python
# WRONG: No persistence - agent forgets between calls
agent = create_agent(model="anthropic:claude-sonnet-4-5", tools=[search])
agent.invoke({"messages": [{"role": "user", "content": "I'm Bob"}]})
agent.invoke({"messages": [{"role": "user", "content": "What's my name?"}]})
# Agent doesn't remember!

# CORRECT: Add checkpointer and thread_id
from langgraph.checkpoint.memory import MemorySaver

agent = create_agent(
    model="anthropic:claude-sonnet-4-5",
    tools=[search],
    checkpointer=MemorySaver(),
)
config = {"configurable": {"thread_id": "session-1"}}
agent.invoke({"messages": [{"role": "user", "content": "I'm Bob"}]}, config=config)
agent.invoke({"messages": [{"role": "user", "content": "What's my name?"}]}, config=config)
# Agent remembers: "Your name is Bob"
```
</python>
<typescript>
加上检查点（checkpointer）与 thread_id，让对话记忆在多轮调用之间留存下来不丢。

```typescript
// WRONG: No persistence
const agent = createAgent({ model: "anthropic:claude-sonnet-4-5", tools: [search] });
await agent.invoke({ messages: [{ role: "user", content: "I'm Bob" }] });
await agent.invoke({ messages: [{ role: "user", content: "What's my name?" }] });
// Agent doesn't remember!

// CORRECT: Add checkpointer and thread_id
import { MemorySaver } from "@langchain/langgraph";

const agent = createAgent({
  model: "anthropic:claude-sonnet-4-5",
  tools: [search],
  checkpointer: new MemorySaver(),
});
const config = { configurable: { thread_id: "session-1" } };
await agent.invoke({ messages: [{ role: "user", content: "I'm Bob" }] }, config);
await agent.invoke({ messages: [{ role: "user", content: "What's my name?" }] }, config);
// Agent remembers: "Your name is Bob"
```
</typescript>
</fix-no-checkpointer>

<fix-infinite-loop>
<python>
在 invoke 的配置里设置 `recursion_limit`，防止智能体循环失控、一直停不下来。

```python
# WRONG: No iteration limit - could loop forever
result = agent.invoke({"messages": [("user", "Do research")]})

# CORRECT: Set recursion_limit in config
result = agent.invoke(
    {"messages": [("user", "Do research")]},
    config={"recursion_limit": 10},  # Stop after 10 steps
)
```
</python>
<typescript>
在 invoke 的配置里设置 `recursionLimit`，防止智能体循环失控、一直停不下来。

```typescript
// WRONG: No iteration limit
const result = await agent.invoke({ messages: [["user", "Do research"]] });

// CORRECT: Set recursionLimit in config
const result = await agent.invoke(
  { messages: [["user", "Do research"]] },
  { recursionLimit: 10 }, // Stop after 10 steps
);
```
</typescript>
</fix-infinite-loop>

<fix-accessing-result-wrong>
<python>
从结果里的 messages 数组里取内容，不要直接去访问 result.content 属性。

```python
# WRONG: Trying to access result.content directly
result = agent.invoke({"messages": [{"role": "user", "content": "Hello"}]})
print(result.content)  # AttributeError!

# CORRECT: Access messages from result dict
result = agent.invoke({"messages": [{"role": "user", "content": "Hello"}]})
print(result["messages"][-1].content)  # Last message content
```
</python>
<typescript>
从结果里的 messages 数组里取内容，不要直接去访问 result.content 属性。

```typescript
// WRONG: Trying to access result.content directly
const result = await agent.invoke({ messages: [{ role: "user", content: "Hello" }] });
console.log(result.content); // undefined!

// CORRECT: Access messages from result object
const result = await agent.invoke({ messages: [{ role: "user", content: "Hello" }] });
console.log(result.messages[result.messages.length - 1].content); // Last message content
```
</typescript>
</fix-accessing-result-wrong>

## This repository's floor（本仓库的底线）

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  一份文档库报告）。后端测试套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能做出的宣称。
  用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句判词，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 脚手架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `ecosystem-primer` 规则——并优先选
  能胜任的最高层。
