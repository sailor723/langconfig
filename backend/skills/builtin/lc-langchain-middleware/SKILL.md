---
name: "Langchain Middleware（LangChain 中间件）"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-langchain-middleware/SKILL.md
description: >-
  当需要人在回路审批、自定义中间件或结构化输出时调用本技能。涵盖：用 HumanInTheLoopMiddleware 为危险的工具
  调用请求人工审批；用钩子编写自定义中间件；Command 恢复模式；以及用 Pydantic/Zod 做结构化输出。
tags:
  - "langchain"
  - "middleware"
  - "langchain-skills"
  - "skills"
triggers:
  - "需要人在回路审批、自定义中间件或结构化输出时"
  - "要用 HumanInTheLoopMiddleware 或 Command 恢复流程时"
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

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/langchain-middleware`（MIT，原样收录于
> `vendor/upstream-skills/langchain-skills/skills/langchain-middleware/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


<overview>
生产级 LangChain 智能体的中间件模式：

- **HumanInTheLoopMiddleware** / **humanInTheLoopMiddleware**：在危险工具调用之前暂停，等待人工审批
- **自定义中间件**：拦截工具调用，做错误处理、日志、重试
- **Command 恢复**：在人工做出决定（批准、编辑、拒绝）之后继续执行

**要求：** 所有 HITL 工作流都需要检查点（checkpointer）与 thread_id 配置。
</overview>

---

## Human-in-the-Loop（人在回路）

<ex-basic-hitl-setup>
<python>
搭一个带 HITL 中间件的智能体，在发出邮件之前暂停等待审批。

```python
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import MemorySaver
from langchain.tools import tool

@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email."""
    return f"Email sent to {to}"

agent = create_agent(
    model="gpt-4.1",
    tools=[send_email],
    checkpointer=MemorySaver(),  # Required for HITL
    middleware=[
        HumanInTheLoopMiddleware(
            interrupt_on={
                "send_email": {"allowed_decisions": ["approve", "edit", "reject"]},
            }
        )
    ],
)
```
</python>
<typescript>
搭一个带 HITL 的智能体，在发出邮件之前暂停等待人工审批。

```typescript
import { createAgent, humanInTheLoopMiddleware } from "langchain";
import { MemorySaver } from "@langchain/langgraph";
import { tool } from "@langchain/core/tools";
import { z } from "zod";

const sendEmail = tool(
  async ({ to, subject, body }) => `Email sent to ${to}`,
  {
    name: "send_email",
    description: "Send an email",
    schema: z.object({ to: z.string(), subject: z.string(), body: z.string() }),
  }
);

const agent = createAgent({
  model: "anthropic:claude-sonnet-4-5",
  tools: [sendEmail],
  checkpointer: new MemorySaver(),
  middleware: [
    humanInTheLoopMiddleware({
      interruptOn: { send_email: { allowedDecisions: ["approve", "edit", "reject"] } },
    }),
  ],
});
```
</typescript>
</ex-basic-hitl-setup>

<ex-running-with-interrupts>
<python>
运行智能体，检测中断，然后在人工批准之后恢复执行。

```python
from langgraph.types import Command

config = {"configurable": {"thread_id": "session-1"}}

# Step 1: Agent runs until it needs to call tool
result1 = agent.invoke({
    "messages": [{"role": "user", "content": "Send email to john@example.com"}]
}, config=config)

# Check for interrupt
if "__interrupt__" in result1:
    print(f"Waiting for approval: {result1['__interrupt__']}")

# Step 2: Human approves
result2 = agent.invoke(
    Command(resume={"decisions": [{"type": "approve"}]}),
    config=config
)
```
</python>
<typescript>
运行智能体，检测中断，然后在人工批准之后恢复执行。

```typescript
import { Command } from "@langchain/langgraph";

const config = { configurable: { thread_id: "session-1" } };

// Step 1: Agent runs until it needs to call tool
const result1 = await agent.invoke({
  messages: [{ role: "user", content: "Send email to john@example.com" }]
}, config);

// Check for interrupt
if (result1.__interrupt__) {
  console.log(`Waiting for approval: ${result1.__interrupt__}`);
}

// Step 2: Human approves
const result2 = await agent.invoke(
  new Command({ resume: { decisions: [{ type: "approve" }] } }),
  config
);
```
</typescript>
</ex-running-with-interrupts>

<ex-editing-tool-arguments>
<python>
原始参数需要更正时，在批准之前编辑工具参数。

```python
# Human edits the arguments — edited_action must include name + args
result2 = agent.invoke(
    Command(resume={
        "decisions": [{
            "type": "edit",
            "edited_action": {
                "name": "send_email",
                "args": {
                    "to": "alice@company.com",  # Fixed email
                    "subject": "Project Meeting - Updated",
                    "body": "...",
                },
            },
        }]
    }),
    config=config
)
```
</python>
<typescript>
原始参数需要更正时，在批准之前编辑工具参数。

```typescript
// Human edits the arguments — editedAction must include name + args
const result2 = await agent.invoke(
  new Command({
    resume: {
      decisions: [{
        type: "edit",
        editedAction: {
          name: "send_email",
          args: {
            to: "alice@company.com",  // Fixed email
            subject: "Project Meeting - Updated",
            body: "...",
          },
        },
      }]
    }
  }),
  config
);
```
</typescript>
</ex-editing-tool-arguments>

<ex-rejecting-with-feedback>
<python>
拒绝一次工具调用，并给出说明拒绝原因的反馈。

```python
# Human rejects
result2 = agent.invoke(
    Command(resume={
        "decisions": [{
            "type": "reject",
            "feedback": "Cannot delete customer data without manager approval",
        }]
    }),
    config=config
)
```
</python>
</ex-rejecting-with-feedback>

<ex-multiple-tools-different-policies>
<python>
按风险等级为每个工具配置不同的 HITL 策略。

```python
agent = create_agent(
    model="gpt-4.1",
    tools=[send_email, read_email, delete_email],
    checkpointer=MemorySaver(),
    middleware=[
        HumanInTheLoopMiddleware(
            interrupt_on={
                "send_email": {"allowed_decisions": ["approve", "edit", "reject"]},
                "delete_email": {"allowed_decisions": ["approve", "reject"]},  # No edit
                "read_email": False,  # No HITL for reading
            }
        )
    ],
)
```
</python>
</ex-multiple-tools-different-policies>

<boundaries>
### 你可以配置什么

- 哪些工具需要审批（按工具的策略）
- 每个工具允许的决定（approve、edit、reject）
- 自定义中间件钩子：`before_model`、`after_model`、`wrap_tool_call`、`before_agent`、`after_agent`
- 只作用于个别工具的中间件（tool-specific middleware）
</boundaries>

---

## Custom Middleware Hooks（自定义中间件钩子）

可用的装饰器钩子有六个，分成两种模式：

- **包装钩子**（`wrap_tool_call`、`wrap_model_call`）：`(request, handler)`——调用 `handler(request)` 继续往下走，
  或者提前返回以短路。
- **前/后钩子**（`before_model`、`after_model`、`before_agent`、`after_agent`）：`(state, runtime)`——检查或修改
  状态。返回 `None`，或返回一个装着状态更新的 dict。

<ex-wrap-tool-call>
<python>
`@wrap_tool_call` 拦截工具执行。**不要用 `yield`**——它会造出一个生成器，导致 `NotImplementedError`。

```python
from langchain.agents.middleware import wrap_tool_call

@wrap_tool_call
def retry_middleware(request, handler):
    for attempt in range(3):
        try:
            return handler(request)
        except Exception:
            if attempt == 2:
                raise

@wrap_tool_call
def guard_middleware(request, handler):
    if request.tool_call["name"] == "dangerous_tool":
        return "This tool is disabled"  # short-circuit
    return handler(request)
```
</python>
<typescript>
`createMiddleware({ wrapToolCall })` 拦截工具执行。

```typescript
import { createMiddleware } from "langchain";

const retryMiddleware = createMiddleware({
  wrapToolCall: async (request, handler) => {
    for (let attempt = 0; attempt < 3; attempt++) {
      try { return await handler(request); }
      catch (e) { if (attempt === 2) throw e; }
    }
  },
});
```
</typescript>
</ex-wrap-tool-call>

<ex-before-after-hooks>
<python>
`before_model` / `after_model` / `before_agent` / `after_agent` 共用 `(state, runtime)` 签名。

```python
from langchain.agents.middleware import before_model, after_model

@before_model
def log_calls(state, runtime):
    print(f"Calling model with {len(state['messages'])} messages")

@after_model
def check_output(state, runtime):
    print(f"Model responded")
```
</python>
<typescript>
所有前/后钩子经 `createMiddleware` 共用同一个 `(state, runtime)` 签名。

```typescript
import { createMiddleware } from "langchain";

const loggingMiddleware = createMiddleware({
  beforeModel: (state, runtime) => {
    console.log(`Calling model with ${state.messages.length} messages`);
  },
  afterModel: (state, runtime) => {
    console.log("Model responded");
  },
});
```
</typescript>
</ex-before-after-hooks>

<boundaries>
### 你不能配置什么

- 在工具执行之后中断（中断只能发生在执行之前）
- 跳过 HITL 对检查点的要求
</boundaries>

<fix-missing-checkpointer>
<python>
HITL 中间件需要检查点（checkpointer）来持久化状态。

```python
# WRONG
agent = create_agent(model="gpt-4.1", tools=[send_email], middleware=[HumanInTheLoopMiddleware({...})])

# CORRECT
agent = create_agent(
    model="gpt-4.1", tools=[send_email],
    checkpointer=MemorySaver(),  # Required
    middleware=[HumanInTheLoopMiddleware({...})]
)
```
</python>
<typescript>
HITL 需要检查点来持久化状态。

```typescript
// WRONG: No checkpointer
const agent = createAgent({
  model: "anthropic:claude-sonnet-4-5", tools: [sendEmail],
  middleware: [humanInTheLoopMiddleware({ interruptOn: { send_email: true } })],
});

// CORRECT: Add checkpointer
const agent = createAgent({
  model: "anthropic:claude-sonnet-4-5", tools: [sendEmail],
  checkpointer: new MemorySaver(),
  middleware: [humanInTheLoopMiddleware({ interruptOn: { send_email: true } })],
});
```
</typescript>
</fix-missing-checkpointer>

<fix-no-thread-id>
<python>
用 HITL 时始终提供 thread_id，以便追踪会话状态。

```python
# WRONG
agent.invoke(input)  # No config!

# CORRECT
agent.invoke(input, config={"configurable": {"thread_id": "user-123"}})
```
</python>
</fix-no-thread-id>

<fix-wrong-resume-syntax>
<python>
用 `Command` 类在中断之后恢复执行。

```python
# WRONG
agent.invoke({"resume": {"decisions": [...]}})

# CORRECT
from langgraph.types import Command
agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=config)
```
</python>
<typescript>
用 `Command` 类在中断之后恢复执行。

```typescript
// WRONG
await agent.invoke({ resume: { decisions: [...] } });

// CORRECT
import { Command } from "@langchain/langgraph";
await agent.invoke(new Command({ resume: { decisions: [{ type: "approve" }] } }), config);
```
</typescript>
</fix-wrong-resume-syntax>

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
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `lc-ecosystem-primer` 规则——并优先选
  能胜任的最高层。
