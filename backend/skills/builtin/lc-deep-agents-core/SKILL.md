---
name: "Deep Agents Core（Deep Agents 核心）"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-deep-agents-core/SKILL.md
description: >-
  构建任何 Deep Agents 应用时都要调用本技能。涵盖 create_deep_agent()、脚手架（harness）架构、
  SKILL.md 格式，以及各项配置选项。
tags:
  - "deep"
  - "agents"
  - "core"
  - "langchain-skills"
  - "skills"
  - "deepagents"
triggers:
  - "要用 create_deep_agent() 构建 Deep Agents 应用时"
  - "需要配置 Deep Agents 脚手架（harness）、SKILL.md 格式或选项时"
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

## Instructions（指令）

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/deep-agents-core`（MIT，原样收录于 `vendor/upstream-skills/langchain-skills/skills/deep-agents-core/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


<overview>
Deep Agents 是一个构建在 LangChain/LangGraph 之上、带内置中间件的、有主见的智能体框架：

- **任务规划**：TodoListMiddleware，用于拆解复杂任务
- **上下文管理**：带可插拔后端的文件系统工具
- **任务委派**：SubAgent 中间件，用于派生专用智能体
- **长期记忆**：通过 Store 跨线程持久化存储
- **人在回路**：敏感操作的审批工作流
- **技能**：按需加载的专用能力

智能体脚手架自动提供这些能力——你只做配置，不做实现。
</overview>

<when-to-use>

| 什么时候用 Deep Agents | 什么时候用 LangChain 的 create_agent |
|---------------------|-----------------------------------|
| 需要规划的多步任务 | 简单的单一用途任务 |
| 上下文很大、需要文件管理 | 上下文能塞进单个提示词 |
| 需要专用的子智能体 | 单个智能体就够 |
| 需要跨会话的持久记忆 | 短暂的单次会话工作 |

</when-to-use>

<middleware-selection>

| 如果你需要…… | 中间件 | 说明 |
|------------------|------------|-------|
| 跟踪复杂任务 | TodoListMiddleware | 默认启用 |
| 管理文件上下文 | FilesystemMiddleware | 配置后端 |
| 委派工作 | SubAgentMiddleware | 添加自定义子智能体 |
| 加入人工审批 | HumanInTheLoopMiddleware | 需要检查点 |
| 加载技能 | SkillsMiddleware | 提供技能目录 |
| 访问记忆 | MemoryMiddleware | 需要 Store 实例 |

</middleware-selection>

<ex-basic-agent>
<python>
创建一个带自定义工具的基础 deep agent，并用一条用户消息调用它。

```python
from deepagents import create_deep_agent
from langchain.tools import tool

@tool
def get_weather(city: str) -> str:
    """Get the weather for a given city."""
    return f"It is always sunny in {city}"

agent = create_deep_agent(
    model="claude-sonnet-4-5-20250929",
    tools=[get_weather],
    system_prompt="You are a helpful assistant"
)

config = {"configurable": {"thread_id": "user-123"}}
result = agent.invoke({
    "messages": [{"role": "user", "content": "What's the weather in Tokyo?"}]
}, config=config)
```
</python>
<typescript>
创建一个带自定义工具的基础 deep agent，并用一条用户消息调用它。

```typescript
import { createDeepAgent } from "deepagents";
import { tool } from "@langchain/core/tools";
import { z } from "zod";

const getWeather = tool(
  async ({ city }) => `It is always sunny in ${city}`,
  { name: "get_weather", description: "Get weather for a city", schema: z.object({ city: z.string() }) }
);

const agent = await createDeepAgent({
  model: "claude-sonnet-4-5-20250929",
  tools: [getWeather],
  systemPrompt: "You are a helpful assistant"
});

const config = { configurable: { thread_id: "user-123" } };
const result = await agent.invoke({
  messages: [{ role: "user", content: "What's the weather in Tokyo?" }]
}, config);
```
</typescript>
</ex-basic-agent>

<ex-full-configuration>
<python>
配置一个把所有可用选项都用上的 deep agent，包括子智能体、技能与持久化。

```python
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

agent = create_deep_agent(
    name="my-assistant",
    model="claude-sonnet-4-5-20250929",
    tools=[custom_tool1, custom_tool2],
    system_prompt="Custom instructions",
    subagents=[research_agent, code_agent],
    backend=FilesystemBackend(root_dir=".", virtual_mode=True),
    interrupt_on={"write_file": True},
    skills=["./skills/"],
    checkpointer=MemorySaver(),
    store=InMemoryStore()
)
```
</python>
<typescript>
配置一个把所有可用选项都用上的 deep agent，包括子智能体、技能与持久化。

```typescript
import { createDeepAgent, FilesystemBackend } from "deepagents";
import { MemorySaver, InMemoryStore } from "@langchain/langgraph";

const agent = await createDeepAgent({
  name: "my-assistant",
  model: "claude-sonnet-4-5-20250929",
  tools: [customTool1, customTool2],
  systemPrompt: "Custom instructions",
  subagents: [researchAgent, codeAgent],
  backend: new FilesystemBackend({ rootDir: ".", virtualMode: true }),
  interruptOn: { write_file: true },
  skills: ["./skills/"],
  checkpointer: new MemorySaver(),
  store: new InMemoryStore()
});
```
</typescript>
</ex-full-configuration>

<built-in-tools>
每个 deep agent 都能访问：

1. **规划**：`write_todos` —— 跟踪多步任务
2. **文件系统**：`ls`、`read_file`、`write_file`、`edit_file`、`glob`、`grep`
3. **委派**：`task` —— 派生专用的子智能体
</built-in-tools>

---

## SKILL.md 格式

<skill-md-format>
技能使用**渐进式披露**——智能体只在相关时加载内容。

### 目录结构

```
skills/
└── my-skill/
    ├── SKILL.md        # Required: main skill file
    ├── examples.py     # Optional: supporting files
    └── templates/      # Optional: templates
```

### SKILL.md 格式

```markdown
---
name: my-skill
description: Clear, specific description of what this skill does
---

# Skill Name

## Overview
Brief explanation of the skill's purpose.

## When to Use
Conditions when this skill applies.

## Instructions
Step-by-step guidance for the agent.
```
</skill-md-format>

<skills-vs-memory>

| 技能 | 记忆（AGENTS.md） |
|--------|-------------------|
| 按需加载 | 启动时总是加载 |
| 任务专用的说明 | 通用偏好 |
| 大篇幅文档 | 紧凑的上下文 |
| 目录里的 SKILL.md | 单个 AGENTS.md 文件 |

</skills-vs-memory>

<ex-skills-with-filesystem-backend>
<python>
为一个智能体配好技能目录与文件系统后端，实现技能的按需加载。

```python
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver

agent = create_deep_agent(
    backend=FilesystemBackend(root_dir=".", virtual_mode=True),
    skills=["./skills/"],
    checkpointer=MemorySaver()
)

result = agent.invoke({
    "messages": [{"role": "user", "content": "Use the python-testing skill"}]
}, config={"configurable": {"thread_id": "session-1"}})
```
</python>
<typescript>
为一个智能体配好技能目录与文件系统后端，实现技能的按需加载。

```typescript
import { createDeepAgent, FilesystemBackend } from "deepagents";
import { MemorySaver } from "@langchain/langgraph";

const agent = await createDeepAgent({
  backend: new FilesystemBackend({ rootDir: ".", virtualMode: true }),
  skills: ["./skills/"],
  checkpointer: new MemorySaver()
});

const result = await agent.invoke({
  messages: [{ role: "user", content: "Use the python-testing skill" }]
}, { configurable: { thread_id: "session-1" } });
```
</typescript>
</ex-skills-with-filesystem-backend>

<ex-skills-with-store-backend>
<python>
在没有文件系统访问的环境里，把技能内容加载进 Store 后端。

```python
from deepagents import create_deep_agent
from deepagents.backends import StoreBackend
from deepagents.backends.utils import create_file_data
from langgraph.store.memory import InMemoryStore

store = InMemoryStore()

# Load skill content into store
skill_content = """---
name: python-testing
description: Best practices for Python testing with pytest
---
# Python Testing Skill
..."""

store.put(
    namespace=("filesystem",),
    key="/skills/python-testing/SKILL.md",
    value=create_file_data(skill_content)
)

agent = create_deep_agent(
    backend=lambda rt: StoreBackend(rt),
    store=store,
    skills=["/skills/"]
)
```
</python>
</ex-skills-with-store-backend>

<boundaries>

### 智能体可以配置什么

- 模型选择与参数
- 额外的自定义工具
- 系统提示词定制
- 后端存储策略
- 哪些工具需要审批
- 带专用工具的自定义子智能体

### 智能体不能配置什么

- 移除核心中间件（TodoList、Filesystem、SubAgent 始终存在）
- `write_todos`、`task` 或文件系统工具的名字
- SKILL.md 的 frontmatter 格式
</boundaries>

<fix-checkpointer-for-interrupts>
<python>
interrupt 需要检查点。

```python
# WRONG
agent = create_deep_agent(interrupt_on={"write_file": True})

# CORRECT
agent = create_deep_agent(interrupt_on={"write_file": True}, checkpointer=MemorySaver())
```
</python>
<typescript>
interrupt 需要检查点。

```typescript
// WRONG
const agent = await createDeepAgent({ interruptOn: { write_file: true } });

// CORRECT
const agent = await createDeepAgent({ interruptOn: { write_file: true }, checkpointer: new MemorySaver() });
```
</typescript>
</fix-checkpointer-for-interrupts>

<fix-store-for-memory>
<python>
StoreBackend 需要 Store 实例，才能在跨线程时保持持久记忆。

```python
# WRONG
agent = create_deep_agent(backend=lambda rt: StoreBackend(rt))

# CORRECT
agent = create_deep_agent(backend=lambda rt: StoreBackend(rt), store=InMemoryStore())
```
</python>
<typescript>
StoreBackend 需要 Store 实例，才能在跨线程时保持持久记忆。

```typescript
// WRONG
const agent = await createDeepAgent({ backend: (config) => new StoreBackend(config) });

// CORRECT
const agent = await createDeepAgent({ backend: (config) => new StoreBackend(config), store: new InMemoryStore() });
```
</typescript>
</fix-store-for-memory>

<fix-thread-id-for-conversations>
<python>
用一致的 thread_id，让对话上下文在多次调用之间延续。

```python
# WRONG: Each invocation is isolated
agent.invoke({"messages": [{"role": "user", "content": "Hi"}]})
agent.invoke({"messages": [{"role": "user", "content": "What did I say?"}]})

# CORRECT
config = {"configurable": {"thread_id": "user-123"}}
agent.invoke({"messages": [...]}, config=config)
agent.invoke({"messages": [...]}, config=config)
```
</python>
<typescript>
用一致的 thread_id，让对话上下文在多次调用之间延续。

```typescript
// WRONG: Each invocation is isolated
await agent.invoke({ messages: [{ role: "user", content: "Hi" }] });
await agent.invoke({ messages: [{ role: "user", content: "What did I say?" }] });

// CORRECT
const config = { configurable: { thread_id: "user-123" } };
await agent.invoke({ messages: [...] }, config);
await agent.invoke({ messages: [...] }, config);
```
</typescript>
</fix-thread-id-for-conversations>

<fix-frontmatter-required>

```markdown
# WRONG: Missing frontmatter in SKILL.md
# My Skill
This is my skill...

# CORRECT: Include YAML frontmatter
---
name: my-skill
description: Python testing best practices with pytest fixtures and mocking
---
# My Skill
This is my skill...
```
</fix-frontmatter-required>

<fix-backend-for-skills>
<python>
技能需要一个合适的后端，才能从文件系统加载。

```python
# WRONG: Skills won't load without proper backend
agent = create_deep_agent(skills=["./skills/"])

# CORRECT: Use FilesystemBackend for local skills
agent = create_deep_agent(
    backend=FilesystemBackend(root_dir=".", virtual_mode=True),
    skills=["./skills/"]
)
```
</python>
</fix-backend-for-skills>

<fix-specific-skill-descriptions>
用具体的描述，帮助智能体判断什么时候该用某个技能。

```markdown
# WRONG: Vague description
---
name: helper
description: Helpful skill
---

# CORRECT: Specific description
---
name: python-testing
description: Python testing best practices with pytest fixtures, mocking, and async patterns
---
```
</fix-specific-skill-descriptions>

<fix-subagent-skills>
<python>
子智能体不会继承技能——要显式给它。

```python
# WRONG: Custom subagents don't inherit skills
agent = create_deep_agent(
    skills=["/main-skills/"],
    subagents=[{"name": "helper", ...}]  # No skills
)

# CORRECT: Provide skills explicitly
agent = create_deep_agent(
    skills=["/main-skills/"],
    subagents=[{"name": "helper", "skills": ["/helper-skills/"], ...}]
)
```
</python>
</fix-subagent-skills>

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
