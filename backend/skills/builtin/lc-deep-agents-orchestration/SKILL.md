---
name: "Deep Agents Orchestration（Deep Agents 编排）"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-deep-agents-orchestration/SKILL.md
description: >-
  在 Deep Agents 中使用子智能体、任务规划或人工审批时调用本技能。涵盖 SubAgentMiddleware、用于规划的
  TodoList，以及 HITL 中断。
tags:
  - "deep"
  - "agents"
  - "orchestration"
  - "langchain-skills"
  - "skills"
  - "deepagents"
triggers:
  - "被要求处理 <overview> 时"
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

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/deep-agents-orchestration`（MIT，原样收录于 `vendor/upstream-skills/langchain-skills/skills/deep-agents-orchestration/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。

## Instructions（指令）

<overview>
Deep Agents 内置三项编排能力：

1. **SubAgentMiddleware**：通过 `task` 工具把工作委派给专用智能体
2. **TodoListMiddleware**：通过 `write_todos` 工具规划并跟踪任务
3. **HumanInTheLoopMiddleware**：敏感操作执行前要求审批

这三项都自动包含在 `create_deep_agent()` 里。
</overview>

---

## 子智能体（任务委派）

<when-to-use-subagents>

| 什么时候用子智能体 | 什么时候用主智能体 |
|-------------------|-------------------|
| 任务需要专用工具 | 通用工具就够 |
| 想把复杂工作隔离出去 | 单步操作 |
| 需要给主智能体干净的上下文 | 上下文膨胀可以接受 |

</when-to-use-subagents>

<how-subagents-work>
主智能体持有 `task` 工具 -> 派生一个全新的子智能体 -> 子智能体自主执行 -> 返回最终报告。

**默认子智能体**：“general-purpose”——自动可用，工具与配置和主智能体相同。
</how-subagents-work>

<ex-custom-subagents>
<python>
创建一个自定义的“researcher”子智能体，配一个用于学术论文检索的专用工具。

```python
from deepagents import create_deep_agent
from langchain.tools import tool

@tool
def search_papers(query: str) -> str:
    """Search academic papers."""
    return f"Found 10 papers about {query}"

agent = create_deep_agent(
    subagents=[
        {
            "name": "researcher",
            "description": "Conduct web research and compile findings",
            "system_prompt": "Search thoroughly, return concise summary",
            "tools": [search_papers],
        }
    ]
)

# Main agent delegates: task(agent="researcher", instruction="Research AI trends")
```
</python>
<typescript>
创建一个自定义的“researcher”子智能体，配一个用于学术论文检索的专用工具。

```typescript
import { createDeepAgent } from "deepagents";
import { tool } from "@langchain/core/tools";
import { z } from "zod";

const searchPapers = tool(
  async ({ query }) => `Found 10 papers about ${query}`,
  { name: "search_papers", description: "Search papers", schema: z.object({ query: z.string() }) }
);

const agent = await createDeepAgent({
  subagents: [
    {
      name: "researcher",
      description: "Conduct web research and compile findings",
      systemPrompt: "Search thoroughly, return concise summary",
      tools: [searchPapers],
    }
  ]
});

// Main agent delegates: task(agent="researcher", instruction="Research AI trends")
```
</typescript>
</ex-custom-subagents>

<ex-subagent-with-hitl>
<python>
给子智能体配上 HITL 审批，用于敏感操作。

```python
from deepagents import create_deep_agent
from langgraph.checkpoint.memory import MemorySaver

agent = create_deep_agent(
    subagents=[
        {
            "name": "code-deployer",
            "description": "Deploy code to production",
            "system_prompt": "You deploy code after tests pass.",
            "tools": [run_tests, deploy_to_prod],
            "interrupt_on": {"deploy_to_prod": True},  # Require approval
        }
    ],
    checkpointer=MemorySaver()  # Required for interrupts
)
```
</python>
</ex-subagent-with-hitl>

<fix-subagents-are-stateless>
<python>
子智能体是无状态的——一次调用里把指令给全。

```python
# WRONG: Subagents don't remember previous calls
# task(agent='research', instruction='Find data')
# task(agent='research', instruction='What did you find?')  # Starts fresh!

# CORRECT: Complete instructions upfront
# task(agent='research', instruction='Find data on AI, save to /research/, return summary')
```
</python>
<typescript>
子智能体是无状态的——一次调用里把指令给全。

```typescript
// WRONG: Subagents don't remember previous calls
// task research: Find data
// task research: What did you find?  // Starts fresh!

// CORRECT: Complete instructions upfront
// task research: Find data on AI, save to /research/, return summary
```
</typescript>
</fix-subagents-are-stateless>

<fix-custom-subagents-dont-inherit-skills>
<python>
自定义子智能体不会继承主智能体的技能。

```python
# WRONG: Custom subagent won't have main agent's skills
agent = create_deep_agent(
    skills=["/main-skills/"],
    subagents=[{"name": "helper", ...}]  # No skills inherited
)

# CORRECT: Provide skills explicitly (general-purpose subagent DOES inherit)
agent = create_deep_agent(
    skills=["/main-skills/"],
    subagents=[{"name": "helper", "skills": ["/helper-skills/"], ...}]
)
```
</python>
</fix-custom-subagents-dont-inherit-skills>

---

## TodoList（任务规划）

<when-to-use-todolist>

| 什么时候用 TodoList | 什么时候不用 TodoList |
|------------------|-------------------|
| 复杂的多步任务 | 简单的单动作任务 |
| 长时间运行的操作 | 快速操作（< 3 步） |

</when-to-use-todolist>

<todolist-tool>

```
write_todos(todos: list[dict]) -> None
```

每个待办项包含：
- `content`：任务描述
- `status`：取 `"pending"`、`"in_progress"`、`"completed"` 之一
</todolist-tool>

<ex-todolist-usage>
<python>
调用一个智能体，它会为多步任务自动创建待办列表。

```python
from deepagents import create_deep_agent

agent = create_deep_agent()  # TodoListMiddleware included by default

result = agent.invoke({
    "messages": [{"role": "user", "content": "Create a REST API: design models, implement CRUD, add auth, write tests"}]
}, config={"configurable": {"thread_id": "session-1"}})

# Agent's planning via write_todos:
# [
#   {"content": "Design data models", "status": "in_progress"},
#   {"content": "Implement CRUD endpoints", "status": "pending"},
#   {"content": "Add authentication", "status": "pending"},
#   {"content": "Write tests", "status": "pending"}
# ]
```
</python>
<typescript>
调用一个智能体，它会为多步任务自动创建待办列表。

```typescript
import { createDeepAgent } from "deepagents";

const agent = await createDeepAgent();  // TodoListMiddleware included

const result = await agent.invoke({
  messages: [{ role: "user", content: "Create a REST API: design models, implement CRUD, add auth, write tests" }]
}, { configurable: { thread_id: "session-1" } });
```
</typescript>
</ex-todolist-usage>

<ex-access-todo-state>
<python>
调用结束后，从智能体的最终状态里取出待办列表。

```python
result = agent.invoke({...}, config={"configurable": {"thread_id": "session-1"}})

# Access todo list from final state
todos = result.get("todos", [])
for todo in todos:
    print(f"[{todo['status']}] {todo['content']}")
```
</python>
</ex-access-todo-state>

<fix-todolist-requires-thread-id>
<python>
待办列表状态需要 thread_id，才能在多次调用之间持久保留。

```python
# WRONG: Fresh state each time without thread_id
agent.invoke({"messages": [...]})

# CORRECT: Use thread_id
config = {"configurable": {"thread_id": "user-session"}}
agent.invoke({"messages": [...]}, config=config)  # Todos preserved
```
</python>
</fix-todolist-requires-thread-id>

---

## 人在回路（审批工作流）

<when-to-use-hitl>

| 什么时候用 HITL | 什么时候不用 HITL |
|--------------|---------------|
| 高风险操作（写数据库、部署） | 只读操作 |
| 合规要求人工把关 | 全自动的工作流 |

</when-to-use-hitl>

<ex-hitl-setup>
<python>
配置哪些工具在执行前需要人工审批。

```python
from deepagents import create_deep_agent
from langgraph.checkpoint.memory import MemorySaver

agent = create_deep_agent(
    interrupt_on={
        "write_file": True,  # All decisions allowed
        "execute_sql": {"allowed_decisions": ["approve", "reject"]},
        "read_file": False,  # No interrupts
    },
    checkpointer=MemorySaver()  # REQUIRED for interrupts
)
```
</python>
<typescript>
配置哪些工具在执行前需要人工审批。

```typescript
import { createDeepAgent } from "deepagents";
import { MemorySaver } from "@langchain/langgraph";

const agent = await createDeepAgent({
  interruptOn: {
    write_file: true,
    execute_sql: { allowedDecisions: ["approve", "reject"] },
    read_file: false,
  },
  checkpointer: new MemorySaver()  // REQUIRED
});
```
</typescript>
</ex-hitl-setup>

<ex-approval-workflow>
<python>
完整流程：触发中断、检查状态、审批动作，再恢复执行。

```python
from deepagents import create_deep_agent
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

agent = create_deep_agent(
    interrupt_on={"write_file": True},
    checkpointer=MemorySaver()
)

config = {"configurable": {"thread_id": "session-1"}}

# Step 1: Agent proposes write_file - execution pauses
result = agent.invoke({
    "messages": [{"role": "user", "content": "Write config to /prod.yaml"}]
}, config=config)

# Step 2: Check for interrupts
state = agent.get_state(config)
if state.next:
    print(f"Pending action")

# Step 3: Approve and resume
result = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=config)
```
</python>
<typescript>
完整流程：触发中断、检查状态、审批动作，再恢复执行。

```typescript
import { createDeepAgent } from "deepagents";
import { MemorySaver, Command } from "@langchain/langgraph";

const agent = await createDeepAgent({
  interruptOn: { write_file: true },
  checkpointer: new MemorySaver()
});

const config = { configurable: { thread_id: "session-1" } };

// Step 1: Agent proposes write_file - execution pauses
let result = await agent.invoke({
  messages: [{ role: "user", content: "Write config to /prod.yaml" }]
}, config);

// Step 2: Check for interrupts
const state = await agent.getState(config);
if (state.next) {
  console.log("Pending action");
}

// Step 3: Approve and resume
result = await agent.invoke(
  new Command({ resume: { decisions: [{ type: "approve" }] } }), config
);
```
</typescript>
</ex-approval-workflow>

<ex-reject-with-feedback>
<python>
带反馈驳回一个待批动作，促使智能体换一种做法。

```python
result = agent.invoke(
    Command(resume={"decisions": [{"type": "reject", "message": "Run tests first"}]}),
    config=config,
)
```
</python>
<typescript>
带反馈驳回一个待批动作，促使智能体换一种做法。

```typescript
const result = await agent.invoke(
  new Command({ resume: { decisions: [{ type: "reject", message: "Run tests first" }] } }),
  config,
);
```
</typescript>
</ex-reject-with-feedback>

<ex-edit-before-execution>
<python>
在放行之前，先修改拟执行动作的参数。

```python
result = agent.invoke(
    Command(resume={"decisions": [{
        "type": "edit",
        "edited_action": {
            "name": "execute_sql",
            "args": {"query": "DELETE FROM users WHERE last_login < '2020-01-01' LIMIT 100"},
        },
    }]}),
    config=config,
)
```
</python>
</ex-edit-before-execution>

<boundaries>
### 智能体可以配置什么

- 子智能体的名称、工具、模型、系统提示词
- 哪些工具需要审批
- 每个工具允许的决策类型
- TodoList 的内容与结构

### 智能体不能配置什么

- 工具名（`task`、`write_todos`）
- HITL 协议（approve/edit/reject 的结构）
- 中断时跳过检查点的要求
- 把子智能体变成有状态的（它们都是瞬时的）
</boundaries>

<fix-checkpointer-required>
<python>
在 HITL 工作流里用 interrupt_on 时，必须提供检查点。

```python
# WRONG
agent = create_deep_agent(interrupt_on={"write_file": True})

# CORRECT
agent = create_deep_agent(interrupt_on={"write_file": True}, checkpointer=MemorySaver())
```
</python>
<typescript>
在 HITL 工作流里用 interruptOn 时，必须提供检查点。

```typescript
// WRONG
const agent = await createDeepAgent({ interruptOn: { write_file: true } });

// CORRECT
const agent = await createDeepAgent({ interruptOn: { write_file: true }, checkpointer: new MemorySaver() });
```
</typescript>
</fix-checkpointer-required>

<fix-thread-id-required-for-resumption>
<python>
要恢复被中断的工作流，必须用一致的 thread_id。

```python
# WRONG: Can't resume without thread_id
agent.invoke({"messages": [...]})

# CORRECT
config = {"configurable": {"thread_id": "session-1"}}
agent.invoke({...}, config=config)
# Resume with Command using same config
agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=config)
```
</python>
<typescript>
要恢复被中断的工作流，必须用一致的 thread_id。

```typescript
// WRONG: Can't resume without thread_id
await agent.invoke({ messages: [...] });

// CORRECT
const config = { configurable: { thread_id: "session-1" } };
await agent.invoke({ messages: [...] }, config);
// Resume with Command using same config
await agent.invoke(new Command({ resume: { decisions: [{ type: "approve" }] } }), config);
```
</typescript>
</fix-thread-id-required-for-resumption>

<fix-interrupt-checks-between-invocations>
<python>
中断发生在两次 invoke() 调用之间，而不是执行中途。

```python
result = agent.invoke({...}, config=config)       # Step 1: triggers interrupt
if "__interrupt__" in result:                      # Step 2: check for interrupt
    result = agent.invoke(                         # Step 3: resume
        Command(resume={"decisions": [{"type": "approve"}]}),
        config=config,
    )
```
</python>
</fix-interrupt-checks-between-invocations>

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
