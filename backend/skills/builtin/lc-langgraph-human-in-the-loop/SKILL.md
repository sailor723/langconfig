---
name: "Langgraph Human in the Loop（LangGraph 人在回路）"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-langgraph-human-in-the-loop/SKILL.md
description: >-
  实现人在回路模式、为审批而暂停、或处理 LangGraph 里的错误时，调用本技能。
  涵盖 interrupt()、Command(resume=...)、审批/校验工作流，以及四层错误处理策略。
tags:
  - "langgraph"
  - "human"
  - "in"
  - "the"
  - "loop"
  - "langchain-skills"
triggers:
  - "被要求处理 <overview> 时"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
  - "skill"
author: "langchain-skills (MIT), adapted for LangConfig"
version: "1.0"
---

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/langgraph-human-in-the-loop`（MIT，原样收录于 `vendor/upstream-skills/langchain-skills/skills/langgraph-human-in-the-loop/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。

## Instructions（指令）

<overview>
LangGraph 的人在回路模式让你暂停图的执行、把数据呈现给用户，再带着用户的输入恢复：

- **`interrupt(value)`** —— 暂停执行，把一个值呈现给调用方
- **`Command(resume=value)`** —— 恢复执行，把这个值交回给 `interrupt()`
- **检查点（checkpointer）** —— 暂停期间保存状态所必需
- **线程 ID** —— 标识要恢复哪一次暂停执行所必需
</overview>

---

## 前置条件

要让人在回路生效，需要三件东西：

1. **检查点** —— 编译时传 `checkpointer=InMemorySaver()`（开发）或 `PostgresSaver`（生产）
2. **线程 ID** —— 每次 `invoke`/`stream` 调用都传 `{"configurable": {"thread_id": "..."}}`
3. **可 JSON 序列化的载荷** —— 传给 `interrupt()` 的值必须能被 JSON 序列化

---

## 基础用法：interrupt 与恢复

`interrupt(value)` 暂停图。这个值会以 `__interrupt__` 为键出现在结果里。`Command(resume=value)` 恢复执行——恢复值成为 `interrupt()` 的返回值。

**关键**：图恢复时，节点从**开头**重新开始——`interrupt()` 之前的所有代码都会重跑一遍。

<ex-basic-interrupt-resume>
<python>
暂停执行，交给人工评审，再用 Command 恢复。

```python
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

class State(TypedDict):
    approved: bool

def approval_node(state: State):
    # Pause and ask for approval
    approved = interrupt("Do you approve this action?")
    # When resumed, Command(resume=...) returns that value here
    return {"approved": approved}

checkpointer = InMemorySaver()
graph = (
    StateGraph(State)
    .add_node("approval", approval_node)
    .add_edge(START, "approval")
    .add_edge("approval", END)
    .compile(checkpointer=checkpointer)
)

config = {"configurable": {"thread_id": "thread-1"}}

# Initial run — hits interrupt and pauses
result = graph.invoke({"approved": False}, config)
print(result["__interrupt__"])
# [Interrupt(value='Do you approve this action?')]

# Resume with the human's response
result = graph.invoke(Command(resume=True), config)
print(result["approved"])  # True
```
</python>
<typescript>
暂停执行，交给人工评审，再用 Command 恢复。

```typescript
import { interrupt, Command, MemorySaver, StateGraph, StateSchema, START, END } from "@langchain/langgraph";
import { z } from "zod";

const State = new StateSchema({
  approved: z.boolean().default(false),
});

const approvalNode = async (state: typeof State.State) => {
  // Pause and ask for approval
  const approved = interrupt("Do you approve this action?");
  // When resumed, Command({ resume }) returns that value here
  return { approved };
};

const checkpointer = new MemorySaver();
const graph = new StateGraph(State)
  .addNode("approval", approvalNode)
  .addEdge(START, "approval")
  .addEdge("approval", END)
  .compile({ checkpointer });

const config = { configurable: { thread_id: "thread-1" } };

// Initial run — hits interrupt and pauses
let result = await graph.invoke({ approved: false }, config);
console.log(result.__interrupt__);
// [{ value: 'Do you approve this action?', ... }]

// Resume with the human's response
result = await graph.invoke(new Command({ resume: true }), config);
console.log(result.approved);  // true
```
</typescript>
</ex-basic-interrupt-resume>

---

## 审批工作流

一个常见模式：用 interrupt 展示一份草稿，再按人的决定做路由。

<ex-approval-workflow>
<python>
插入人工评审，再按决定路由到发送或结束。

```python
from langgraph.types import interrupt, Command
from langgraph.graph import StateGraph, START, END
from typing import Literal
from typing_extensions import TypedDict

class EmailAgentState(TypedDict):
    email_content: str
    draft_response: str
    classification: dict

def human_review(state: EmailAgentState) -> Command[Literal["send_reply", "__end__"]]:
    """Pause for human review using interrupt and route based on decision."""
    classification = state.get("classification", {})

    # interrupt() must come first — any code before it will re-run on resume
    human_decision = interrupt({
        "email_id": state.get("email_content", ""),
        "draft_response": state.get("draft_response", ""),
        "urgency": classification.get("urgency"),
        "action": "Please review and approve/edit this response"
    })

    # Process the human's decision
    if human_decision.get("approved"):
        return Command(
            update={"draft_response": human_decision.get("edited_response", state.get("draft_response", ""))},
            goto="send_reply"
        )
    else:
        # Rejection — human will handle directly
        return Command(update={}, goto=END)
```
</python>
<typescript>
插入人工评审，再按决定路由到发送或结束。

```typescript
import { interrupt, Command, END, GraphNode } from "@langchain/langgraph";

const humanReview: GraphNode<typeof EmailAgentState> = async (state) => {
  const classification = state.classification!;

  // interrupt() must come first — any code before it will re-run on resume
  const humanDecision = interrupt({
    emailId: state.emailContent,
    draftResponse: state.responseText,
    urgency: classification.urgency,
    action: "Please review and approve/edit this response",
  });

  // Process the human's decision
  if (humanDecision.approved) {
    return new Command({
      update: { responseText: humanDecision.editedResponse || state.responseText },
      goto: "sendReply",
    });
  } else {
    return new Command({ update: {}, goto: END });
  }
};
```
</typescript>
</ex-approval-workflow>

---

## 校验循环

在循环里用 `interrupt()` 校验人工输入，无效就重新提示。

<ex-validation-loop>
<python>
在循环里校验人工输入，无效则一直重新提示，直到有效为止。

```python
from langgraph.types import interrupt

def get_age_node(state):
    prompt = "What is your age?"

    while True:
        answer = interrupt(prompt)

        # Validate the input
        if isinstance(answer, int) and answer > 0:
            break
        else:
            # Invalid input — ask again with a more specific prompt
            prompt = f"'{answer}' is not a valid age. Please enter a positive number."

    return {"age": answer}
```

每次 `Command(resume=...)` 调用都会提供下一个答案。如果无效，循环会带着更清楚的提示信息再次 interrupt。

```python
config = {"configurable": {"thread_id": "form-1"}}
first = graph.invoke({"age": None}, config)
# __interrupt__: "What is your age?"

retry = graph.invoke(Command(resume="thirty"), config)
# __interrupt__: "'thirty' is not a valid age..."

final = graph.invoke(Command(resume=30), config)
print(final["age"])  # 30
```
</python>
<typescript>
在循环里校验人工输入，无效则一直重新提示，直到有效为止。

```typescript
import { interrupt } from "@langchain/langgraph";

const getAgeNode = (state: typeof State.State) => {
  let prompt = "What is your age?";

  while (true) {
    const answer = interrupt(prompt);

    // Validate the input
    if (typeof answer === "number" && answer > 0) {
      return { age: answer };
    } else {
      // Invalid input — ask again with a more specific prompt
      prompt = `'${answer}' is not a valid age. Please enter a positive number.`;
    }
  }
};
```
</typescript>
</ex-validation-loop>

---

## 多个 interrupt

当并行分支各自调用 `interrupt()` 时，把每个 interrupt 的 ID 映射到它的恢复值，在一次调用里把它们全部恢复。

<ex-multiple-interrupts>
<python>
把 interrupt ID 映射到对应的值，恢复多个并行的 interrupt。

```python
from typing import Annotated, TypedDict
import operator
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, END, StateGraph
from langgraph.types import Command, interrupt

class State(TypedDict):
    vals: Annotated[list[str], operator.add]

def node_a(state):
    answer = interrupt("question_a")
    return {"vals": [f"a:{answer}"]}

def node_b(state):
    answer = interrupt("question_b")
    return {"vals": [f"b:{answer}"]}

graph = (
    StateGraph(State)
    .add_node("a", node_a)
    .add_node("b", node_b)
    .add_edge(START, "a")
    .add_edge(START, "b")
    .add_edge("a", END)
    .add_edge("b", END)
    .compile(checkpointer=InMemorySaver())
)

config = {"configurable": {"thread_id": "1"}}

# Both parallel nodes hit interrupt() and pause
result = graph.invoke({"vals": []}, config)
# result["__interrupt__"] contains both Interrupt objects with IDs

# Resume all pending interrupts at once using a map of id -> value
resume_map = {
    i.id: f"answer for {i.value}"
    for i in result["__interrupt__"]
}
result = graph.invoke(Command(resume=resume_map), config)
# result["vals"] = ["a:answer for question_a", "b:answer for question_b"]
```
</python>
<typescript>
把 interrupt ID 映射到对应的值，恢复多个并行的 interrupt。

```typescript
import { Command, END, MemorySaver, START, StateGraph, interrupt, isInterrupted, INTERRUPT, Annotation } from "@langchain/langgraph";

const State = Annotation.Root({
  vals: Annotation<string[]>({
    reducer: (left, right) => left.concat(Array.isArray(right) ? right : [right]),
    default: () => [],
  }),
});

function nodeA(_state: typeof State.State) {
  const answer = interrupt("question_a") as string;
  return { vals: [`a:${answer}`] };
}

function nodeB(_state: typeof State.State) {
  const answer = interrupt("question_b") as string;
  return { vals: [`b:${answer}`] };
}

const graph = new StateGraph(State)
  .addNode("a", nodeA)
  .addNode("b", nodeB)
  .addEdge(START, "a")
  .addEdge(START, "b")
  .addEdge("a", END)
  .addEdge("b", END)
  .compile({ checkpointer: new MemorySaver() });

const config = { configurable: { thread_id: "1" } };

const interruptedResult = await graph.invoke({ vals: [] }, config);

// Resume all pending interrupts at once
const resumeMap: Record<string, string> = {};
if (isInterrupted(interruptedResult)) {
  for (const i of interruptedResult[INTERRUPT]) {
    if (i.id != null) {
      resumeMap[i.id] = `answer for ${i.value}`;
    }
  }
}
const result = await graph.invoke(new Command({ resume: resumeMap }), config);
// result.vals = ["a:answer for question_a", "b:answer for question_b"]
```
</typescript>
</ex-multiple-interrupts>

用户能修的错误用 `interrupt()` 暂停并收集缺失的数据——这就是本技能覆盖的模式。完整的四层错误处理策略（RetryPolicy、Command 错误循环等），见 **fundamentals** 技能。

---

## interrupt 之前的副作用必须是幂等的

图恢复时，节点从**开头**重新开始——`interrupt()` 之前的**所有**代码都会重跑。在子图里，父节点和子图节点**两者**都会重新执行。

<idempotency-rules>

**要做：**
- 在 `interrupt()` 之前用 **upsert**（而非 insert）操作
- 用**先查后建**（check-before-create）的模式
- 尽可能把副作用放在 `interrupt()` **之后**
- 把副作用拆到它们自己的节点里

**不要做：**
- 在 `interrupt()` 之前创建新记录——每次恢复都会多出一条
- 在 `interrupt()` 之前往列表里追加——每次恢复都会多出条目

</idempotency-rules>

<ex-idempotent-patterns>
<python>
interrupt 之前的幂等操作，与非幂等的错误做法。

```python
# GOOD: Upsert is idempotent — safe before interrupt
def node_a(state: State):
    db.upsert_user(user_id=state["user_id"], status="pending_approval")
    approved = interrupt("Approve this change?")
    return {"approved": approved}

# GOOD: Side effect AFTER interrupt — only runs once
def node_a(state: State):
    approved = interrupt("Approve this change?")
    if approved:
        db.create_audit_log(user_id=state["user_id"], action="approved")
    return {"approved": approved}

# BAD: Insert creates duplicates on each resume!
def node_a(state: State):
    audit_id = db.create_audit_log({  # Runs again on resume!
        "user_id": state["user_id"],
        "action": "pending_approval",
    })
    approved = interrupt("Approve this change?")
    return {"approved": approved}
```
</python>
<typescript>
interrupt 之前的幂等操作，与非幂等的错误做法。

```typescript
// GOOD: Upsert is idempotent — safe before interrupt
const nodeA = async (state: typeof State.State) => {
  await db.upsertUser({ userId: state.userId, status: "pending_approval" });
  const approved = interrupt("Approve this change?");
  return { approved };
};

// GOOD: Side effect AFTER interrupt — only runs once
const nodeA = async (state: typeof State.State) => {
  const approved = interrupt("Approve this change?");
  if (approved) {
    await db.createAuditLog({ userId: state.userId, action: "approved" });
  }
  return { approved };
};

// BAD: Insert creates duplicates on each resume!
const nodeA = async (state: typeof State.State) => {
  await db.createAuditLog({  // Runs again on resume!
    userId: state.userId,
    action: "pending_approval",
  });
  const approved = interrupt("Approve this change?");
  return { approved };
};
```
</typescript>
</ex-idempotent-patterns>

<subgraph-interrupt-re-execution>

### 恢复时子图的重新执行

子图里含有 `interrupt()` 时，恢复会**同时**重新执行父节点（调用子图的那个）和子图节点（调用 `interrupt()` 的那个）：

<python>

```python
def node_in_parent_graph(state: State):
    some_code()  # <-- Re-executes on resume
    subgraph_result = subgraph.invoke(some_input)
    # ...

def node_in_subgraph(state: State):
    some_other_code()  # <-- Also re-executes on resume
    result = interrupt("What's your name?")
    # ...
```
</python>
<typescript>

```typescript
async function nodeInParentGraph(state: State) {
  someCode();  // <-- Re-executes on resume
  const subgraphResult = await subgraph.invoke(someInput);
  // ...
}

async function nodeInSubgraph(state: State) {
  someOtherCode();  // <-- Also re-executes on resume
  const result = interrupt("What's your name?");
  // ...
}
```
</typescript>
</subgraph-interrupt-re-execution>

---

## Command(resume) 的警告

`Command(resume=...)` 是**唯一**一种适合作为 `invoke()`/`stream()` 输入的 Command 用法。不要把 `Command(update=...)` 当输入传进去——它会从最新的检查点恢复，图看起来就像卡住了。完整的反模式解释见 fundamentals 技能。

---

## 修复

<fix-checkpointer-required-for-interrupts>
<python>
interrupt 功能需要检查点。

```python
# WRONG
graph = builder.compile()

# CORRECT
graph = builder.compile(checkpointer=InMemorySaver())
```
</python>
<typescript>
interrupt 功能需要检查点。

```typescript
// WRONG
const graph = builder.compile();

// CORRECT
const graph = builder.compile({ checkpointer: new MemorySaver() });
```
</typescript>
</fix-checkpointer-required-for-interrupts>

<fix-resume-with-command>
<python>
用 Command 从 interrupt 恢复（传普通 dict 会重启整个图）。

```python
# WRONG
graph.invoke({"resume_data": "approve"}, config)

# CORRECT
graph.invoke(Command(resume="approve"), config)
```
</python>
<typescript>
用 Command 从 interrupt 恢复（传普通对象会重启整个图）。

```typescript
// WRONG
await graph.invoke({ resumeData: "approve" }, config);

// CORRECT
await graph.invoke(new Command({ resume: "approve" }), config);
```
</typescript>
</fix-resume-with-command>

<boundaries>
### 不该做的事

- 没有检查点就用 interrupt —— 会失败
- 用不同的 thread_id 恢复 —— 会新建一个线程，而不是恢复
- 把 `Command(update=...)` 当 invoke 的输入 —— 图看起来卡住（要用普通 dict）
- 在 `interrupt()` 之前做非幂等的副作用 —— 恢复时会产生重复
- 以为 `interrupt()` 之前的代码只跑一次 —— 每次恢复它都会重跑
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
