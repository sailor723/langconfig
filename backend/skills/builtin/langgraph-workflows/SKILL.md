---
name: "langgraph-workflows（LangGraph 工作流）"
lang: zh
translated: machine
source: backend/skills/en-originals/langgraph-workflows/SKILL.md
description: >-
  设计与搭建 LangGraph 状态机、多智能体工作流的专家指南。在 LangConfig 里搭建工作流、连接智能体，
  或实现复杂控制流时使用。
tags: [langgraph, workflows, state-machine, multi-agent, orchestration]
triggers:
  - "用户提到 LangGraph 时"
  - "用户提到工作流时"
  - "用户提到状态机时"
  - "用户提到多智能体时"
  - "连接智能体时"
allowed-tools: [filesystem, shell, python]
author: LangConfig
---

你是 LangGraph 架构专家，帮助用户在 LangConfig 里设计和搭建工作流。LangGraph 支持有状态、可循环的多智能体工作流，并自带状态管理。

### LangGraph 核心概念

依据 LangGraph 官方文档：

#### StateGraph
一种专门的图，在整个执行过程中维护并更新共享状态：
- 每个节点接收当前状态，并返回更新后的状态
- 状态在节点之间自动传递
- 支持上下文感知的决策与持久记忆

#### 节点
表示工作流中的处理步骤：
```python
# Each node is a function that takes state and returns updates
def research_node(state: WorkflowState) -> dict:
    # Process state
    result = do_research(state["query"])
    # Return state updates
    return {"research_results": result}
```

#### 边
定义节点之间的跳转：
- **静态边**：固定的跳转（A → B）
- **条件边**：依据状态做动态路由

### LangConfig 节点类型

#### AGENT_NODE
标准的 LLM 智能体，处理输入并能使用工具：
```json
{
  "id": "researcher",
  "type": "AGENT_NODE",
  "data": {
    "agentType": "AGENT_NODE",
    "name": "Research Agent",
    "model": "claude-sonnet-4-5-20250929",
    "system_prompt": "Research the given topic thoroughly.",
    "native_tools": ["web_search", "web_fetch"],
    "temperature": 0.5
  }
}
```

#### CONDITIONAL_NODE
按求值后的条件对工作流做路由：
```json
{
  "id": "router",
  "type": "CONDITIONAL_NODE",
  "data": {
    "agentType": "CONDITIONAL_NODE",
    "condition": "'error' in messages[-1].content.lower()",
    "true_route": "error_handler",
    "false_route": "continue_processing"
  }
}
```

#### LOOP_NODE
实现带退出条件的迭代：
```json
{
  "id": "refinement_loop",
  "type": "LOOP_NODE",
  "data": {
    "agentType": "LOOP_NODE",
    "max_iterations": 5,
    "exit_condition": "'APPROVED' in messages[-1].content"
  }
}
```

#### OUTPUT_NODE
终止工作流并格式化最终输出：
```json
{
  "id": "output",
  "type": "OUTPUT_NODE",
  "data": {
    "agentType": "OUTPUT_NODE",
    "output_format": "markdown"
  }
}
```

#### CHECKPOINT_NODE
保存工作流状态，供之后恢复：
```json
{
  "id": "checkpoint",
  "type": "CHECKPOINT_NODE",
  "data": {
    "agentType": "CHECKPOINT_NODE",
    "checkpoint_name": "after_research"
  }
}
```

#### APPROVAL_NODE
人在回路中的检查点：
```json
{
  "id": "human_review",
  "type": "APPROVAL_NODE",
  "data": {
    "agentType": "APPROVAL_NODE",
    "approval_prompt": "Please review the generated content."
  }
}
```

### 工作流模式

#### 1. 顺序流水线
智能体的简单线性流程：
```
START → Agent A → Agent B → Agent C → END

Use case: Content generation pipeline
- Research → Outline → Write → Edit
```

#### 2. 条件分支
按输出做路由：
```
START → Classifier → [Condition]
                        ├── Route A → Handler A → END
                        └── Route B → Handler B → END

Use case: Intent classification
- Classify query → Route to appropriate specialist
```

#### 3. 反思 / 评审循环
自我改进的闭环：
```
START → Generator → Critic → [Condition]
                               ├── PASS → END
                               └── REVISE → Generator (loop)

Use case: Code review, content quality
- Generate → Critique → Revise until approved
```

#### 4. 主管模式
中心协调者管理各专家：
```
START → Supervisor → [Delegate]
                        ├── Specialist A → Supervisor
                        ├── Specialist B → Supervisor
                        └── Complete → END

Use case: Complex research tasks
- Supervisor assigns subtasks to specialists
```

#### 5. Map-Reduce
并行处理并聚合结果：
```
START → Splitter → [Parallel]
                      ├── Worker A ─┐
                      ├── Worker B ─┼→ Aggregator → END
                      └── Worker C ─┘

Use case: Document analysis
- Split document → Analyze sections → Combine insights
```

### 状态管理

#### 工作流状态结构
```python
class WorkflowState(TypedDict):
    # Core identifiers
    workflow_id: int
    task_id: Optional[int]

    # Message history (accumulates via reducer)
    messages: Annotated[List[BaseMessage], operator.add]

    # User input
    query: str

    # RAG context
    context_documents: Optional[List[int]]

    # Execution tracking
    current_node: Optional[str]
    step_history: Annotated[List[Dict], operator.add]

    # Control flow
    conditional_route: Optional[str]
    loop_iterations: Optional[Dict[str, int]]

    # Results
    result: Optional[Dict[str, Any]]
    error_message: Optional[str]
```

#### 归约器（reducer）
自动合并状态的增量更新：
```python
# Messages accumulate (don't overwrite)
messages: Annotated[List[BaseMessage], operator.add]

# Step history accumulates
step_history: Annotated[List[Dict], operator.add]
```

### 边配置

#### 静态边
始终路由到指定节点：
```json
{
  "source": "researcher",
  "target": "writer",
  "type": "default"
}
```

#### 条件边
按状态做路由：
```json
{
  "source": "classifier",
  "target": "router",
  "type": "conditional",
  "data": {
    "condition": "state['intent']",
    "routes": {
      "question": "qa_agent",
      "task": "task_agent",
      "default": "general_agent"
    }
  }
}
```

### 最佳实践

#### 1. 让节点职责单一
每个节点只应把一件事做好：
- ❌ “研究、编写并编辑”
- ✅ “研究” → “编写” → “编辑”

#### 2. 有的放矢地打检查点
在高开销操作处保存状态：
- 长时间 LLM 调用之后
- 人工审批之前
- 在自然的断点处

#### 3. 优雅地处理错误
补上错误处理路径：
```
Agent → [Error?]
          ├── No → Continue
          └── Yes → Error Handler → Retry/Exit
```

#### 4. 限制循环次数
始终设置 `max_iterations` 以防死循环：
```json
{
  "max_iterations": 5,
  "exit_condition": "'DONE' in result"
}
```

#### 5. 为可观测性而设计
带上能说明问题的命名与步骤历史：
- 节点命名要描述用途
- 记录状态转移
- 跟踪耗时指标

### 调试工作流

#### 常见问题

1. **工作流挂起**
   - 检查是否缺少边
   - 验证条件逻辑
   - 排查无限循环

2. **路由错误**
   - 调试条件表达式
   - 检查状态的取值
   - 确认边标签是否匹配

3. **状态没有更新**
   - 确认节点返回 dict 形式的更新
   - 检查 reducer 配置
   - 确认键名一致

4. **内存问题**
   - 限制消息历史长度
   - 打检查点并清理旧状态
   - 大输出改用流式
