# Phase 4: Human-in-the-Loop (HITL)

> How LangConfig pauses agent execution, waits for human approval, and resumes via LangGraph's interrupt/checkpointing system.

---

## Architecture Overview

The HITL flow spans four components working together:

```
Agent executes → hits interrupt node → pauses (checkpoints state)
                                        ↓
                              Frontend shows HITL panel
                                        ↓
                      User clicks Approve/Reject → POST /api/hitl/{id}/approve
                                        ↓
                              Event Bus publishes hitl_approved
                                        ↓
                      Workflow resumes from checkpoint → handle_hitl_node()
                                        ↓
                      Decision: approve → continue | retry → retry | reject → terminate
```

---

## 1. Interrupt Configuration (AgentFactory)

**File**: [`backend/core/agents/factory.py`](../../backend/core/agents/factory.py#L661-L673)

When creating an agent, the config can specify *when* to pause execution:

```python
# HITL configuration from agent config
interrupt_before = agent_config.get("interrupt_before", False)
interrupt_after = agent_config.get("interrupt_after", False)

# Applied during agent creation
if interrupt_before:
    nodes = interrupt_before if isinstance(interrupt_before, list) else ["agent"]
    create_agent_kwargs["interrupt_before"] = nodes
if interrupt_after:
    nodes = interrupt_after if isinstance(interrupt_after, list) else ["agent"]
    create_agent_kwargs["interrupt_after"] = nodes
```

| Config Field | Type | Default | Effect |
|---|---|---|---|
| `interrupt_before` | `bool` or `list[str]` | `False` | Pause before executing specified nodes |
| `interrupt_after` | `bool` or `list[str]` | `False` | Pause after executing specified nodes |

Valid node names: `"agent"`, `"tools"`

### Validation

```python
# factory.py #L193-199
for interrupt_field in ["interrupt_before", "interrupt_after"]:
    interrupt_val = agent_config.get(interrupt_field)
    if interrupt_val and isinstance(interrupt_val, list):
        valid_nodes = {REASONING_NODE, TOOLS_NODE}
        for node in interrupt_val:
            if node not in valid_nodes:
                logger.warning(f"Unknown node '{node}'")
```

---

## 2. Workflow Nodes (Status Transitions)

**File**: [`backend/core/workflows/nodes.py`](../../backend/core/workflows/nodes.py)

### Setting AWAITING_HITL Status

Two paths lead to `AWAITING_HITL`:

**Path A — Config-based HITL (mandatory approval after execution):**

```python
# nodes.py #L419-423 — in execute_code_node()
if node_agent_config.get("requires_human_approval", False):
    next_status = WorkflowStatus.AWAITING_HITL
```

**Path B — Critique-based HITL (agent decides it needs human review):**

```python
# nodes.py #L560-578 — in critique_validate_node()
if "[DECISION: HITL_REQUIRED]" in critique_text:
    decision = "HITL_REQUIRED"
    # ...
    elif decision == "HITL_REQUIRED":
        return {
            **_update_status(WorkflowStatus.AWAITING_HITL, "critique_validate"),
            "needs_hitl": True,
        }
```

### handle_hitl_node — Resume Processing

**File**: [`backend/core/workflows/nodes.py#L608-L686`](../../backend/core/workflows/nodes.py#L608-L686)

This node executes **after** the human responds and the workflow resumes. It reads `state["hitl_response"]` and routes accordingly:

```python
async def handle_hitl_node(state, config):
    hitl_response = state.get("hitl_response")
    decision = hitl_response.get("decision", "reject").lower()

    if decision == "approve":
        return {**_update_status(WorkflowStatus.PASSED, ...)}
    elif decision == "retry":
        return {"hitl_decision": "retry", "hitl_feedback": feedback}
    else:  # reject
        return {**_update_status(WorkflowStatus.TERMINATED, ...)}
```

### WorkflowStatus Values

**File**: [`backend/core/workflows/state.py`](../../backend/core/workflows/state.py)

```python
class WorkflowStatus(str, Enum):
    AWAITING_HITL = "AWAITING_HITL"   # Waiting for human decision
    HITL_APPROVED = "HITL_APPROVED"   # Human approved (resume)
    HITL_REJECTED = "HITL_REJECTED"   # Human rejected (terminate)
    PASSED = "PASSED"                  # Continue execution
    TERMINATED = "TERMINATED"          # Stopped
```

---

## 3. HITL API Endpoints

**File**: [`backend/api/hitl/routes.py`](../../backend/api/hitl/routes.py)

Prefix: `/api/hitl`

| Endpoint | Method | Description |
|---|---|---|
| `/api/hitl/{workflow_id}/approve` | POST | Approve and resume workflow |
| `/api/hitl/{workflow_id}/reject` | POST | Reject and terminate workflow |

### Approve Flow

```python
@router.post("/{workflow_id}/approve")
async def approve_hitl(workflow_id, approval: HITLApprovalRequest, db):
    # 1. Verify workflow exists
    # 2. Find in-progress task
    # 3. Publish event to event bus
    event_bus.publish(f"workflow:{workflow_id}", {
        "type": "hitl_approved",
        "data": {
            "approved": True,
            "comment": approval.comment,
            "approved_at": datetime.utcnow().isoformat()
        }
    })
```

### Reject Flow

```python
@router.post("/{workflow_id}/reject")
async def reject_hitl(workflow_id, approval, db):
    # 1. Verify workflow exists
    # 2. Require comment for rejection
    if not approval.comment:
        raise HTTPException(400, "Comment required for rejection")
    # 3. Mark task as FAILED
    task.status = TaskStatus.FAILED
    # 4. Publish rejection event
    event_bus.publish(f"workflow:{workflow_id}", {
        "type": "hitl_rejected",
        "data": {"rejected_at": datetime.utcnow().isoformat()}
    })
```

> **Note**: The comments mention "TODO: Integrate with LangGraph interrupt_after/interrupt_before resume" — the event bus publishing is implemented, but the workflow executor needs to listen for `hitl_approved` events to trigger actual graph resumption. Currently the workflow resumes via the checkpointer when the LangGraph node is re-invoked with the same `thread_id`.

---

## 4. Checkpointing (Persistence for Resumption)

**File**: [`backend/core/workflows/checkpointing/manager.py`](../../backend/core/workflows/checkpointing/manager.py)

HITL depends entirely on checkpointing. When an interrupt fires, LangGraph:

1. **Saves the full graph state** (all channel values) to the `checkpoints` PostgreSQL table
2. **Returns control** to the caller with the checkpoint information
3. **Resumes** when the same workflow is invoked with the same `thread_id`

```python
# Checkpointer initialization during app startup
_checkpointer = PostgresSaver(_connection_pool)
await _checkpointer.setup()  # Creates checkpoints + checkpoint_blobs tables

# Used in executor.py
config = {
    "configurable": {
        "thread_id": f"workflow_{workflow.id}_task_{task_id}"
    }
}
```

### Finding HITL-interrupted Workflows

**File**: [`backend/core/workflows/checkpointing/utils.py#L177-L191`](../../backend/core/workflows/checkpointing/utils.py#L177-L191)

```python
# Query checkpoints where workflow_status is AWAITING_HITL
SELECT checkpoint, metadata, created_at
FROM checkpoints
WHERE checkpoint->'channel_values'->>'workflow_status' IN ('AWAITING_HITL', 'HITL_REVIEWING')
ORDER BY created_at DESC;
```

### State Recovery

**File**: [`backend/core/workflows/runner.py#L280-L329`](../../backend/core/workflows/runner.py#L280-L329)

On failure, the runner attempts to recover state from the last checkpoint:

```python
async def _attempt_state_recovery(workflow, config, initial_state):
    if not workflow.checkpointer:
        return initial_state
    last_checkpoint = await workflow.checkpointer.aget(config)
    if last_checkpoint and "channel_values" in last_checkpoint:
        return last_checkpoint["channel_values"]
```

---

## 5. Event Bus & SSE Streaming

**File**: [`services/event_bus.py`](../../services/event_bus.py), [`api/workflows/execution.py#L570-L625`](../../backend/api/workflows/execution.py#L570-L625)

HITL decisions are communicated in real-time via the event bus + SSE.

### Event Bus (In-Memory)

```python
class EventBus:
    _subscribers: Dict[str, List[asyncio.Queue]]

    async def publish(channel, event):
        for queue in self._subscribers[channel]:
            await queue.put(event)

    async def subscribe(channel) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=500)
        self._subscribers[channel].append(queue)
        return queue
```

### SSE Endpoint

```
GET /api/workflows/{workflow_id}/events
  → Subscribes to "workflow:{workflow_id}" channel
  → Streams events as text/event-stream
  → 30s keepalive pings
  → Cleanup on disconnect
```

```python
def event_generator():
    queue = await event_bus.subscribe(f"workflow:{workflow_id}")
    while True:
        event = await asyncio.wait_for(queue.get(), timeout=30.0)
        yield f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"
```

### HITL Events Published to Event Bus

| Event Type | Trigger | Published By |
|---|---|---|
| `hitl_approved` | User clicks Approve | `POST /api/hitl/{id}/approve` |
| `hitl_rejected` | User clicks Reject | `POST /api/hitl/{id}/reject` |
| `status` (AWAITING_HITL) | Agent reaches HITL state | Workflow executor |

---

## Complete HITL Flow (End-to-End)

```
1. Agent execution begins
   ├── config: {"configurable": {"thread_id": "workflow_42_task_7"}}
   ├── graph is compiled with interrupt_after=["agent"]
   └── workflow.ainvoke(state, config)

2. Agent node completes → LangGraph saves checkpoint → returns control
   ├── Checkpoint stored in PostgreSQL (full graph state)
   └── Status set to AWAITING_HITL

3. Frontend polls SSE: GET /api/workflows/42/events
   ├── Receives event: status=AWAITING_HITL
   └── Shows HITLApprovalPanel with agent output

4. User clicks "Approve" with optional comment
   └── POST /api/hitl/42/approve  {approved: true, comment: "Looks good"}

5. Event published: workflow:42 → hitl_approved
   ├── Workflow resume handler detects the event
   └── Re-invokes workflow with same thread_id

6. LangGraph resumes from checkpoint
   ├── Loads saved state from checkpoints table
   ├── Executes handle_hitl_node()
   │   └─ Reads hitl_response → decision=approve → status=PASSED
   └── Continues to next node (e.g., retry_workflow or complete)
```

---

## Key Takeaways

1. **Two triggers** for HITL — Config-based (`requires_human_approval`) and critique-based (`[DECISION: HITL_REQUIRED]`)
2. **Checkpointing is essential** — Without the checkpointer, HITL cannot work (no state to resume from)
3. **`thread_id` is the resume key** — Re-invoking with the same `thread_id` is how LangGraph knows to load the checkpoint
4. **Event bus bridges API → workflow** — The approval endpoint publishes to event bus, which the workflow executor listens to
5. **Three outcomes** — Approve (continue), Retry (loop back with feedback), Reject (terminate)
6. **SSE provides real-time UX** — Frontend subscribes to workflow events via Server-Sent Events