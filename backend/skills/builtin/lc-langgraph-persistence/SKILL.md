---
name: "Langgraph Persistence（LangGraph 持久化）"
description: >-
  LangGraph 需要持久化状态、记住对话、回溯历史，或配置子图检查点作用域时，调用本技能。涵盖检查点
  （checkpointer）、thread_id、时间旅行、Store 与子图持久化模式。
tags:
  - "langgraph"
  - "persistence"
  - "langchain-skills"
  - "skills"
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
author: "langchain-skills (MIT), adapted for LangConfig"
version: "1.0"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-langgraph-persistence/SKILL.md
---

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/langgraph-persistence`（MIT，原样收录于 `vendor/upstream-skills/langchain-skills/skills/langgraph-persistence/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。

## Instructions（指令）

<overview>
LangGraph 的持久化层给图状态做检查点，靠它实现可持久执行：

- **检查点（Checkpointer）**：在每个 super-step 保存、加载图状态
- **线程 ID（Thread ID）**：标识一条条互不相干的检查点序列，也就是一次次对话
- **Store**：跨线程记忆，存用户偏好与事实

**两类记忆：**
- **短期**（checkpointer）：线程范围内的对话历史
- **长期**（store）：跨线程的用户偏好、事实
</overview>

<checkpointer-selection>

| 检查点 | 适用场景 | 可用于生产 |
|--------------|----------|------------------|
| `InMemorySaver` | 测试、开发 | 否 |
| `SqliteSaver` | 本地开发 | 部分 |
| `PostgresSaver` | 生产 | 是 |

</checkpointer-selection>

---

## Checkpointer Setup（检查点配置）

<ex-basic-persistence>
<python>
搭一张最基础的图，用内存检查点，并按线程持久化状态。

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict, Annotated
import operator

class State(TypedDict):
    messages: Annotated[list, operator.add]

def add_message(state: State) -> dict:
    return {"messages": ["Bot response"]}

checkpointer = InMemorySaver()

graph = (
    StateGraph(State)
    .add_node("respond", add_message)
    .add_edge(START, "respond")
    .add_edge("respond", END)
    .compile(checkpointer=checkpointer)  # Pass at compile time
)

# ALWAYS provide thread_id
config = {"configurable": {"thread_id": "conversation-1"}}

result1 = graph.invoke({"messages": ["Hello"]}, config)
print(len(result1["messages"]))  # 2

result2 = graph.invoke({"messages": ["How are you?"]}, config)
print(len(result2["messages"]))  # 4 (previous + new)
```
</python>
<typescript>
搭一张最基础的图，用内存检查点，并按线程持久化状态。

```typescript
import { MemorySaver, StateGraph, StateSchema, MessagesValue, START, END } from "@langchain/langgraph";
import { HumanMessage } from "@langchain/core/messages";

const State = new StateSchema({ messages: MessagesValue });

const addMessage = async (state: typeof State.State) => {
  return { messages: [{ role: "assistant", content: "Bot response" }] };
};

const checkpointer = new MemorySaver();

const graph = new StateGraph(State)
  .addNode("respond", addMessage)
  .addEdge(START, "respond")
  .addEdge("respond", END)
  .compile({ checkpointer });

// ALWAYS provide thread_id
const config = { configurable: { thread_id: "conversation-1" } };

const result1 = await graph.invoke({ messages: [new HumanMessage("Hello")] }, config);
console.log(result1.messages.length);  // 2

const result2 = await graph.invoke({ messages: [new HumanMessage("How are you?")] }, config);
console.log(result2.messages.length);  // 4 (previous + new)
```
</typescript>
</ex-basic-persistence>

<ex-production-postgres>
<python>
为生产部署配置由 PostgreSQL 支撑的检查点。

```python
import os
from langgraph.checkpoint.postgres import PostgresSaver

# Run once during deployment (not at application startup):
#   PostgresSaver.from_conn_string(os.environ["DATABASE_URL"]).setup()

with PostgresSaver.from_conn_string(os.environ["DATABASE_URL"]) as checkpointer:
    graph = builder.compile(checkpointer=checkpointer)
```
</python>
<typescript>
为生产部署配置由 PostgreSQL 支撑的检查点。

```typescript
import { PostgresSaver } from "@langchain/langgraph-checkpoint-postgres";

// Run once during deployment (not at application startup):
//   await PostgresSaver.fromConnString(process.env.DATABASE_URL!).setup();

const checkpointer = PostgresSaver.fromConnString(process.env.DATABASE_URL!);
const graph = builder.compile({ checkpointer });
```
</typescript>
</ex-production-postgres>

---

## Thread Management（线程管理）

<ex-separate-threads>
<python>
演示不同 thread ID 之间彼此隔离的状态。

```python
# Different threads maintain separate state
alice_config = {"configurable": {"thread_id": "user-alice"}}
bob_config = {"configurable": {"thread_id": "user-bob"}}

graph.invoke({"messages": ["Hi from Alice"]}, alice_config)
graph.invoke({"messages": ["Hi from Bob"]}, bob_config)

# Alice's state is isolated from Bob's
```
</python>
<typescript>
演示不同 thread ID 之间彼此隔离的状态。

```typescript
// Different threads maintain separate state
const aliceConfig = { configurable: { thread_id: "user-alice" } };
const bobConfig = { configurable: { thread_id: "user-bob" } };

await graph.invoke({ messages: [new HumanMessage("Hi from Alice")] }, aliceConfig);
await graph.invoke({ messages: [new HumanMessage("Hi from Bob")] }, bobConfig);

// Alice's state is isolated from Bob's
```
</typescript>
</ex-separate-threads>

---

## State History & Time Travel（状态历史与时间旅行）

<ex-resume-from-checkpoint>
<python>
时间旅行：浏览检查点历史，并从过去某个状态重放或分叉。

```python
config = {"configurable": {"thread_id": "session-1"}}

result = graph.invoke({"messages": ["start"]}, config)

# Browse checkpoint history
states = list(graph.get_state_history(config))

# Replay from a past checkpoint
past = states[-2]
result = graph.invoke(None, past.config)  # None = resume from checkpoint

# Or fork: update state at a past checkpoint, then resume
fork_config = graph.update_state(past.config, {"messages": ["edited"]})
result = graph.invoke(None, fork_config)
```
</python>
<typescript>
时间旅行：浏览检查点历史，并从过去某个状态重放或分叉。

```typescript
const config = { configurable: { thread_id: "session-1" } };

const result = await graph.invoke({ messages: ["start"] }, config);

// Browse checkpoint history (async iterable, collect to array)
const states: Awaited<ReturnType<typeof graph.getState>>[] = [];
for await (const state of graph.getStateHistory(config)) {
  states.push(state);
}

// Replay from a past checkpoint
const past = states[states.length - 2];
const replayed = await graph.invoke(null, past.config);  // null = resume from checkpoint

// Or fork: update state at a past checkpoint, then resume
const forkConfig = await graph.updateState(past.config, { messages: ["edited"] });
const forked = await graph.invoke(null, forkConfig);
```
</typescript>
</ex-resume-from-checkpoint>

<ex-update-state>
<python>
在恢复执行之前，手动更新图状态。

```python
config = {"configurable": {"thread_id": "session-1"}}

# Modify state before resuming
graph.update_state(config, {"data": "manually_updated"})

# Resume with updated state
result = graph.invoke(None, config)
```
</python>
<typescript>
在恢复执行之前，手动更新图状态。

```typescript
const config = { configurable: { thread_id: "session-1" } };

// Modify state before resuming
await graph.updateState(config, { data: "manually_updated" });

// Resume with updated state
const result = await graph.invoke(null, config);
```
</typescript>
</ex-update-state>
---

## Subgraph Checkpointer Scoping（子图检查点作用域）

编译子图时，`checkpointer` 参数决定持久化行为。对于要用到中断、需要多轮记忆，或者会并行运行的子图，这一点至关重要。

<subgraph-checkpointer-scoping-table>

| 特性 | `checkpointer=False` | `None`（默认） | `True` |
|---|---|---|---|
| 中断（HITL） | 否 | 是 | 是 |
| 多轮记忆 | 否 | 否 | 是 |
| 多次调用（不同子图） | 是 | 是 | 警告（可能出现命名空间冲突） |
| 多次调用（同一子图） | 是 | 是 | 否 |
| 状态查看 | 否 | 警告（只看得到当前这次调用） | 是 |

</subgraph-checkpointer-scoping-table>

<subgraph-checkpointer-when-to-use>

### When to use each mode（各模式何时使用）

- **`checkpointer=False`** — 子图不需要中断，也不需要持久化。这是最省事的选择，没有检查点开销。
- **`None`（默认 / 不传 `checkpointer`）** — 子图需要 `interrupt()`，但不需要多轮记忆。每次调用都从头开始，不过可以暂停、恢复。并行执行照常可行，因为每次调用都会拿到自己的命名空间。
- **`checkpointer=True`** — 子图需要跨调用记住状态（多轮对话）。每次调用都从上次停下的地方接着走。

</subgraph-checkpointer-when-to-use>

<warning-stateful-subgraphs-parallel>

**警告**：有状态的子图（`checkpointer=True`）不支持在单个节点内多次调用同一个子图实例——这些调用会写进同一份检查点命名空间，从而互相冲突。

</warning-stateful-subgraphs-parallel>

<ex-subgraph-checkpointer-modes>
<python>
为子图挑对检查点模式。

```python
# No interrupts needed — opt out of checkpointing
subgraph = subgraph_builder.compile(checkpointer=False)

# Need interrupts but not cross-invocation persistence (default)
subgraph = subgraph_builder.compile()

# Need cross-invocation persistence (stateful)
subgraph = subgraph_builder.compile(checkpointer=True)
```
</python>
<typescript>
为子图挑对检查点模式。

```typescript
// No interrupts needed — opt out of checkpointing
const subgraph = subgraphBuilder.compile({ checkpointer: false });

// Need interrupts but not cross-invocation persistence (default)
const subgraph = subgraphBuilder.compile();

// Need cross-invocation persistence (stateful)
const subgraph = subgraphBuilder.compile({ checkpointer: true });
```
</typescript>
</ex-subgraph-checkpointer-modes>

<parallel-subgraph-namespacing>

### Parallel subgraph namespacing（并行子图的命名空间）

多个**不同**的有状态子图并行运行时，把每个子图都包进各自的 `StateGraph`，再配一个唯一的节点名，命名空间隔离才能稳定：

<python>

```python
from langgraph.graph import MessagesState, StateGraph

def create_sub_agent(model, *, name, **kwargs):
    """Wrap an agent with a unique node name for namespace isolation."""
    agent = create_agent(model=model, name=name, **kwargs)
    return (
        StateGraph(MessagesState)
        .add_node(name, agent)  # unique name -> stable namespace
        .add_edge("__start__", name)
        .compile()
    )

fruit_agent = create_sub_agent(
    "gpt-4.1-mini", name="fruit_agent",
    tools=[fruit_info], prompt="...", checkpointer=True,
)
veggie_agent = create_sub_agent(
    "gpt-4.1-mini", name="veggie_agent",
    tools=[veggie_info], prompt="...", checkpointer=True,
)
```
</python>
<typescript>

```typescript
import { StateGraph, StateSchema, MessagesValue, START } from "@langchain/langgraph";

function createSubAgent(model: string, { name, ...kwargs }: { name: string; [key: string]: any }) {
  const agent = createAgent({ model, name, ...kwargs });
  return new StateGraph(new StateSchema({ messages: MessagesValue }))
    .addNode(name, agent)  // unique name -> stable namespace
    .addEdge(START, name)
    .compile();
}

const fruitAgent = createSubAgent("gpt-4.1-mini", {
  name: "fruit_agent", tools: [fruitInfo], prompt: "...", checkpointer: true,
});
const veggieAgent = createSubAgent("gpt-4.1-mini", {
  name: "veggie_agent", tools: [veggieInfo], prompt: "...", checkpointer: true,
});
```
</typescript>

注：以节点形式（通过 `add_node`）加进去的子图，本来就会按名字自动获得命名空间，不需要再套这一层包装。

</parallel-subgraph-namespacing>

---

## Long-Term Memory (Store)（长期记忆：Store）

<ex-long-term-memory-store>
<python>
用 Store 做跨线程记忆，让用户偏好在多个对话之间共享。

```python
from langgraph.store.memory import InMemoryStore

store = InMemoryStore()

# Save user preference (available across ALL threads)
store.put(("alice", "preferences"), "language", {"preference": "short responses"})

# Node with store — access via runtime
from langgraph.runtime import Runtime

def respond(state, runtime: Runtime):
    prefs = runtime.store.get((state["user_id"], "preferences"), "language")
    return {"response": f"Using preference: {prefs.value}"}

# Compile with BOTH checkpointer and store
graph = builder.compile(checkpointer=checkpointer, store=store)

# Both threads access same long-term memory
graph.invoke({"user_id": "alice"}, {"configurable": {"thread_id": "thread-1"}})
graph.invoke({"user_id": "alice"}, {"configurable": {"thread_id": "thread-2"}})  # Same preferences!
```
</python>
<typescript>
用 Store 做跨线程记忆，让用户偏好在多个对话之间共享。

```typescript
import { MemoryStore } from "@langchain/langgraph";

const store = new MemoryStore();

// Save user preference (available across ALL threads)
await store.put(["alice", "preferences"], "language", { preference: "short responses" });

// Node with store — access via runtime
const respond = async (state: typeof State.State, runtime: any) => {
  const item = await runtime.store?.get(["alice", "preferences"], "language");
  return { response: `Using preference: ${item?.value?.preference}` };
};

// Compile with BOTH checkpointer and store
const graph = builder.compile({ checkpointer, store });

// Both threads access same long-term memory
await graph.invoke({ userId: "alice" }, { configurable: { thread_id: "thread-1" } });
await graph.invoke({ userId: "alice" }, { configurable: { thread_id: "thread-2" } });  // Same preferences!
```
</typescript>
</ex-long-term-memory-store>

<ex-store-operations>
<python>
Store 的基本操作：put、get、search、delete。

```python
from langgraph.store.memory import InMemoryStore

store = InMemoryStore()

store.put(("user-123", "facts"), "location", {"city": "San Francisco"})  # Put
item = store.get(("user-123", "facts"), "location")  # Get
results = store.search(("user-123", "facts"), filter={"city": "San Francisco"})  # Search
store.delete(("user-123", "facts"), "location")  # Delete
```
</python>
</ex-store-operations>

---

## Fixes（常见修法）

<fix-thread-id-required>
<python>
一定要在 config 里始终提供 thread_id，状态持久化才会生效。

```python
# WRONG: No thread_id - state NOT persisted!
graph.invoke({"messages": ["Hello"]})
graph.invoke({"messages": ["What did I say?"]})  # Doesn't remember!

# CORRECT: Always provide thread_id
config = {"configurable": {"thread_id": "session-1"}}
graph.invoke({"messages": ["Hello"]}, config)
graph.invoke({"messages": ["What did I say?"]}, config)  # Remembers!
```
</python>
<typescript>
一定要在 config 里始终提供 thread_id，状态持久化才会生效。

```typescript
// WRONG: No thread_id - state NOT persisted!
await graph.invoke({ messages: [new HumanMessage("Hello")] });
await graph.invoke({ messages: [new HumanMessage("What did I say?")] });  // Doesn't remember!

// CORRECT: Always provide thread_id
const config = { configurable: { thread_id: "session-1" } };
await graph.invoke({ messages: [new HumanMessage("Hello")] }, config);
await graph.invoke({ messages: [new HumanMessage("What did I say?")] }, config);  // Remembers!
```
</typescript>
</fix-thread-id-required>


<fix-inmemory-not-for-production>
<python>
生产环境的持久化要用 PostgresSaver，而不是 InMemorySaver。

```python
# WRONG: Data lost on process restart
checkpointer = InMemorySaver()  # In-memory only!

# CORRECT: Use persistent storage for production
from langgraph.checkpoint.postgres import PostgresSaver
with PostgresSaver.from_conn_string("postgresql://...") as checkpointer:
    checkpointer.setup()  # only needed on first use to create tables
    graph = builder.compile(checkpointer=checkpointer)
```
</python>
<typescript>
生产环境的持久化要用 PostgresSaver，而不是 MemorySaver。

```typescript
// WRONG: Data lost on process restart
const checkpointer = new MemorySaver();  // In-memory only!

// CORRECT: Use persistent storage for production
import { PostgresSaver } from "@langchain/langgraph-checkpoint-postgres";
const checkpointer = PostgresSaver.fromConnString("postgresql://...");
await checkpointer.setup(); // only needed on first use to create tables
```
</typescript>
</fix-inmemory-not-for-production>


<fix-update-state-with-reducers>
<python>
要替换状态值，就用 Overwrite 直接盖掉，而不是让它从归约器里过一遍。

```python
from langgraph.types import Overwrite

# State with reducer: items: Annotated[list, operator.add]
# Current state: {"items": ["A", "B"]}

# update_state PASSES THROUGH reducers
graph.update_state(config, {"items": ["C"]})  # Result: ["A", "B", "C"] - Appended!

# To REPLACE instead, use Overwrite
graph.update_state(config, {"items": Overwrite(["C"])})  # Result: ["C"] - Replaced
```
</python>
<typescript>
要替换状态值，就用 Overwrite 直接盖掉，而不是让它从归约器里过一遍。

```typescript
import { Overwrite } from "@langchain/langgraph";

// State with reducer: items uses concat reducer
// Current state: { items: ["A", "B"] }

// updateState PASSES THROUGH reducers
await graph.updateState(config, { items: ["C"] });  // Result: ["A", "B", "C"] - Appended!

// To REPLACE instead, use Overwrite
await graph.updateState(config, { items: new Overwrite(["C"]) });  // Result: ["C"] - Replaced
```
</typescript>
</fix-update-state-with-reducers>

<fix-store-injection>
<python>
在图节点里通过 Runtime 对象访问 store。

```python
# WRONG: Store not available in node
def my_node(state):
    store.put(...)  # NameError! store not defined

# CORRECT: Access store via runtime
from langgraph.runtime import Runtime

def my_node(state, runtime: Runtime):
    runtime.store.put(...)  # Correct store instance
```
</python>
<typescript>
在图节点里通过 runtime 参数访问 store。

```typescript
// WRONG: Store not available in node
const myNode = async (state) => {
  store.put(...);  // ReferenceError!
};

// CORRECT: Access store via runtime
const myNode = async (state, runtime) => {
  await runtime.store?.put(...);  // Correct store instance
};
```
</typescript>
</fix-store-injection>

<boundaries>
### What You Should NOT Do（不该做的事）

- 生产环境别用 `InMemorySaver`——进程重启数据就没了；用 `PostgresSaver`
- 别忘 `thread_id`——没有它，状态不会持久化
- 别指望 `update_state` 绕过归约器——它就是会穿过归约器；要替换请用 `Overwrite`
- 别在一个节点里并行跑同一个有状态子图（`checkpointer=True`）——命名空间会冲突
- 别在节点里直接访问 store——通过 `Runtime` 参数拿 `runtime.store`
</boundaries>

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
