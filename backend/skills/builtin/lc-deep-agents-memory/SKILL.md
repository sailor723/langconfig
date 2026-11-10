---
name: "Deep Agents Memory（Deep Agents 记忆）"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-deep-agents-memory/SKILL.md
description: >-
  当你的 Deep Agent 需要记忆、持久化或文件系统访问时调用本技能。涵盖 StateBackend（临时）、StoreBackend
  （持久）、FilesystemMiddleware，以及用于路由的 CompositeBackend。
tags:
  - "deep"
  - "agents"
  - "memory"
  - "langchain-skills"
  - "skills"
triggers:
  - "Deep Agent 需要记忆、持久化或文件系统访问时"
  - "要在 StateBackend、StoreBackend 或 CompositeBackend 之间选后端时"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
author: "langchain-skills (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/deep-agents-memory`（MIT，原样收录于
> `vendor/upstream-skills/langchain-skills/skills/deep-agents-memory/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


<overview>
Deep Agents 用可插拔的后端来做文件操作与记忆：

**短期（StateBackend）**：只在单个线程内存活，线程一结束就丢
**长期（StoreBackend）**：跨线程、跨会话持久
**混合（CompositeBackend）**：把不同路径路由到不同后端

FilesystemMiddleware 提供以下工具：`ls`、`read_file`、`write_file`、`edit_file`、`glob`、`grep`
</overview>

<backend-selection>

| 用途 | 后端 | 为什么 |
|----------|---------|-----|
| 临时工作文件 | StateBackend | 默认选择，无需任何配置 |
| 本地开发 CLI | FilesystemBackend | 直接读写磁盘上的文件 |
| 跨会话记忆 | StoreBackend | 跨线程持久保存 |
| 混合存储 | CompositeBackend | 临时存储与持久存储混用 |

</backend-selection>

<ex-default-state-backend>
<python>
默认的 `StateBackend` 把文件临时存放在单个线程内，线程结束就丢。

```python
from deepagents import create_deep_agent

agent = create_deep_agent()  # Default: StateBackend
result = agent.invoke({
    "messages": [{"role": "user", "content": "Write notes to /draft.txt"}]
}, config={"configurable": {"thread_id": "thread-1"}})
# /draft.txt is lost when thread ends
```
</python>
<typescript>
默认的 `StateBackend` 把文件临时存放在单个线程内，线程结束就丢。

```typescript
import { createDeepAgent } from "deepagents";

const agent = await createDeepAgent();  // Default: StateBackend
const result = await agent.invoke({
  messages: [{ role: "user", content: "Write notes to /draft.txt" }]
}, { configurable: { thread_id: "thread-1" } });
// /draft.txt is lost when thread ends
```
</typescript>
</ex-default-state-backend>

<ex-composite-backend-for-hybrid>
<python>
配置 `CompositeBackend`，把不同路径路由到不同的存储后端。

```python
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langgraph.store.memory import InMemoryStore

store = InMemoryStore()

composite_backend = lambda rt: CompositeBackend(
    default=StateBackend(rt),
    routes={"/memories/": StoreBackend(rt)}
)

agent = create_deep_agent(backend=composite_backend, store=store)

# /draft.txt -> ephemeral (StateBackend)
# /memories/user-prefs.txt -> persistent (StoreBackend)
```
</python>
<typescript>
配置 `CompositeBackend`，把不同路径路由到不同的存储后端。

```typescript
import { createDeepAgent, CompositeBackend, StateBackend, StoreBackend } from "deepagents";
import { InMemoryStore } from "@langchain/langgraph";

const store = new InMemoryStore();

const agent = await createDeepAgent({
  backend: (config) => new CompositeBackend(
    new StateBackend(config),
    { "/memories/": new StoreBackend(config) }
  ),
  store
});

// /draft.txt -> ephemeral (StateBackend)
// /memories/user-prefs.txt -> persistent (StoreBackend)
```
</typescript>
</ex-composite-backend-for-hybrid>

<ex-cross-session-memory>
<python>
`/memories/` 下的文件经 `StoreBackend` 路由，因此跨线程之后依然持久。

```python
# Using CompositeBackend from previous example
config1 = {"configurable": {"thread_id": "thread-1"}}
agent.invoke({"messages": [{"role": "user", "content": "Save to /memories/style.txt"}]}, config=config1)

config2 = {"configurable": {"thread_id": "thread-2"}}
agent.invoke({"messages": [{"role": "user", "content": "Read /memories/style.txt"}]}, config=config2)
# Thread 2 can read file saved by Thread 1
```
</python>
<typescript>
`/memories/` 下的文件经 `StoreBackend` 路由，因此跨线程之后依然持久。

```typescript
// Using CompositeBackend from previous example
const config1 = { configurable: { thread_id: "thread-1" } };
await agent.invoke({ messages: [{ role: "user", content: "Save to /memories/style.txt" }] }, config1);

const config2 = { configurable: { thread_id: "thread-2" } };
await agent.invoke({ messages: [{ role: "user", content: "Read /memories/style.txt" }] }, config2);
// Thread 2 can read file saved by Thread 1
```
</typescript>
</ex-cross-session-memory>

<ex-filesystem-backend-local-dev>
<python>
本地开发时用 `FilesystemBackend`，直接读写真实磁盘上的文件，并配上人在回路审批。

```python
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver

agent = create_deep_agent(
    backend=FilesystemBackend(root_dir=".", virtual_mode=True),  # Restrict access
    interrupt_on={"write_file": True, "edit_file": True},
    checkpointer=MemorySaver()
)

# Agent can read/write actual files on disk
```
</python>
<typescript>
本地开发时用 `FilesystemBackend`，直接读写真实磁盘上的文件，并配上人在回路审批。

```typescript
import { createDeepAgent, FilesystemBackend } from "deepagents";
import { MemorySaver } from "@langchain/langgraph";

const agent = await createDeepAgent({
  backend: new FilesystemBackend({ rootDir: ".", virtualMode: true }),
  interruptOn: { write_file: true, edit_file: true },
  checkpointer: new MemorySaver()
});
```
</typescript>

**安全：绝不要在 Web 服务里用 FilesystemBackend——改用 StateBackend 或沙箱。**
</ex-filesystem-backend-local-dev>

<ex-store-in-custom-tools>
<python>
在自定义工具里直接访问 store，完成长期记忆的读写操作。

```python
from langchain.tools import tool, ToolRuntime
from langchain.agents import create_agent
from langgraph.store.memory import InMemoryStore

@tool
def get_user_preference(key: str, runtime: ToolRuntime) -> str:
    """Get a user preference from long-term storage."""
    store = runtime.store
    result = store.get(("user_prefs",), key)
    return str(result.value) if result else "Not found"

@tool
def save_user_preference(key: str, value: str, runtime: ToolRuntime) -> str:
    """Save a user preference to long-term storage."""
    store = runtime.store
    store.put(("user_prefs",), key, {"value": value})
    return f"Saved {key}={value}"

store = InMemoryStore()

agent = create_agent(
    model="gpt-4.1",
    tools=[get_user_preference, save_user_preference],
    store=store
)
```
</python>
</ex-store-in-custom-tools>

<boundaries>
### 智能体可以配置什么

- 后端的类型与配置
- CompositeBackend 的路由规则
- FilesystemBackend 的根目录
- 文件操作上的人在回路

### 智能体不能配置什么

- 工具名（ls、read_file、write_file、edit_file、glob、grep）
- 访问 virtual_mode 限制之外的文件
- 不配好后端就跨线程访问文件
</boundaries>

<fix-storebackend-requires-store>
<python>
使用 `StoreBackend` 时必须提供一个 store 实例。

```python
# WRONG
agent = create_deep_agent(backend=lambda rt: StoreBackend(rt))

# CORRECT
agent = create_deep_agent(backend=lambda rt: StoreBackend(rt), store=InMemoryStore())
```
</python>
<typescript>
使用 `StoreBackend` 时必须提供一个 store 实例。

```typescript
// WRONG
const agent = await createDeepAgent({ backend: (c) => new StoreBackend(c) });

// CORRECT
const agent = await createDeepAgent({ backend: (c) => new StoreBackend(c), store: new InMemoryStore() });
```
</typescript>
</fix-storebackend-requires-store>

<fix-statebackend-files-dont-persist>
<python>
`StateBackend` 里的文件是按线程隔离的——想跨线程访问，就复用同一个 `thread_id`，或改由 `StoreBackend` 存储。

```python
# WRONG: thread-2 can't read file from thread-1
agent.invoke({"messages": [...]}, config={"configurable": {"thread_id": "thread-1"}})  # Write
agent.invoke({"messages": [...]}, config={"configurable": {"thread_id": "thread-2"}})  # File not found!
```
</python>
<typescript>
`StateBackend` 里的文件是按线程隔离的——想跨线程访问，就复用同一个 `thread_id`，或改由 `StoreBackend` 存储。

```typescript
// WRONG: thread-2 can't read file from thread-1
await agent.invoke({ messages: [...] }, { configurable: { thread_id: "thread-1" } });  // Write
await agent.invoke({ messages: [...] }, { configurable: { thread_id: "thread-2" } });  // File not found!
```
</typescript>
</fix-statebackend-files-dont-persist>

<fix-path-prefix-for-persistence>
<python>
路径必须匹配 `CompositeBackend` 的路由前缀，文件才会持久保存。

```python
# With routes={"/memories/": StoreBackend(rt)}:
agent.invoke(...)  # /prefs.txt -> ephemeral (no match)
agent.invoke(...)  # /memories/prefs.txt -> persistent (matches route)
```
</python>
<typescript>
路径必须匹配 `CompositeBackend` 的路由前缀，文件才会持久保存。

```typescript
// With routes: { "/memories/": StoreBackend }:
await agent.invoke(...);  // /prefs.txt -> ephemeral (no match)
await agent.invoke(...);  // /memories/prefs.txt -> persistent (matches route)
```
</typescript>
</fix-path-prefix-for-persistence>

<fix-production-store>
<python>
生产环境请使用 `PostgresStore`（`InMemoryStore` 重启即丢失）。

```python
# WRONG                              # CORRECT
store = InMemoryStore()              store = PostgresStore(connection_string="postgresql://...")
```
</python>
<typescript>
生产环境请使用 `PostgresStore`（`InMemoryStore` 重启即丢失）。

```typescript
// WRONG                                    // CORRECT
const store = new InMemoryStore();          const store = new PostgresStore({ connectionString: "..." });
```
</typescript>
</fix-production-store>

<fix-filesystem-backend-needs-virtual-mode>
<python>
开启 `virtual_mode=True` 来限制路径访问范围（挡住 `../` 与 `~/` 逃逸）。

```python
backend = FilesystemBackend(root_dir="/project", virtual_mode=True)  # Secure
```
</python>
</fix-filesystem-backend-needs-virtual-mode>

<fix-longest-prefix-match>
<python>
`CompositeBackend` 匹配路由时按最长前缀优先。

```python
routes = {"/mem/": StoreBackend(rt), "/mem/temp/": StateBackend(rt)}
# /mem/file.txt -> StoreBackend, /mem/temp/file.txt -> StateBackend (longer match)
```
</python>
</fix-longest-prefix-match>

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
