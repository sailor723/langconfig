# Plan — 100% Mirror of 2.3_subagents.ipynb in LangConfig UI

## Goal
Reproduce the observable behavior of `2.3_subagents.ipynb` cells 9-12 in
the LangConfig UI: a **research supervisor agent** that delegates work to a
**sub-agent** with isolated context, using the `task(description, subagent_type)`
tool and the `SUBAGENT_USAGE_INSTRUCTIONS` system prompt.

## What 2.3 actually does (cell by cell)

### Cell 5 (task_tool.py — vendored module):
```python
class SubAgent(TypedDict):
    name: str
    description: str
    prompt: str
    tools: NotRequired[list[str]]


def _create_task_tool(tools, subagents, model, state_schema):
    agents = {}
    tools_by_name = {t.name: t for t in tools}

    for _agent in subagents:
        _tools = [tools_by_name[t] for t in _agent["tools"]] if "tools" in _agent else tools
        agents[_agent["name"]] = create_agent(
            model, system_prompt=_agent["prompt"], tools=_tools, state_schema=state_schema
        )

    other_agents_string = [f"- {a['name']}: {a['description']}" for a in subagents]

    @tool(description=TASK_DESCRIPTION_PREFIX.format(other_agents=other_agents_string))
    def task(description, subagent_type, state, tool_call_id):
        if subagent_type not in agents:
            return f"Error: invoked agent of type {subagent_type}, the only allowed types are ..."
        sub_agent = agents[subagent_type]
        state["messages"] = [{"role": "user", "content": description}]  # context isolation
        result = sub_agent.invoke(state)
        return Command(update={
            "files": result.get("files", {}),
            "messages": [ToolMessage(result["messages"][-1].content, tool_call_id=tool_call_id)],
        })

    return task
```

### Cell 9 (build supervisor agent):
- Mock `web_search` returns fixed Chinese MCP paragraph
- Model: `agnes-2.0-flash` (will be `minimax-m3` in our env)
- One sub-agent:
  ```python
  research_sub_agent = {
      "name": "research-agent",
      "description": "Delegate research to the sub-agent researcher. Only give this researcher one topic at a time.",
      "prompt": "你是一个研究员。研究提供给你的主题。重要提示：只需对web_search工具进行一次调用...",
      "tools": ["web_search"],
  }
  ```
- System prompt: `SUBAGENT_USAGE_INSTRUCTIONS.format(max_concurrent_research_units=3, max_researcher_iterations=3, date=...)`
- Agent: `create_agent(model, [task_tool], system_prompt=..., state_schema=DeepAgentState)`

### Cell 10/12 (invoke):
- Query: "请给我一个关于MCP的概述。"
- Supervisor calls `task("请给我一个关于MCP的概述。", "research-agent")`
- Sub-agent invokes `web_search("MCP")` and returns the mock result
- Supervisor receives ToolMessage and replies to user

## Cross-check with LangConfig

### What LangConfig already has

| Aspect | Notebook | LangConfig | Match? |
|---|---|---|---|
| `task` tool | `description, subagent_type` | `description, subagent_type, context, expected_output` | partial — extra args are optional defaults |
| `task` semantics | real sub-agent invocation | placeholder (logs only) | ❌ no real execution |
| Sub-agent config | `name, description, prompt, tools` | stored in `config.subagents` (need to check) | similar |
| System prompt | `SUBAGENT_USAGE_INSTRUCTIONS` | configurable | OK |
| `state_schema=DeepAgentState` | passed | not passed via UI | same as 2.1/2.2 |
| `enable_default_middleware` | none | adds 6 default middleware | needs `False` |

### Sub-agent storage in LangConfig

Need to check `config.subagents` field — does it have the same shape?

### Sub-agent execution

LangConfig's `task` tool is a **placeholder**. The actual sub-agent execution is
done by the `DeepAgents` framework. So:
- For **Regular Agents**: there's no real sub-agent execution path (only Deep Agents have it)
- For **Deep Agents**: the framework intercepts `task` calls and routes to sub-agents

### Two implementation paths

#### Path A — Use existing Deep Agent framework
1. Create agent with `use_deepagents: true`
2. Configure sub-agents in `config.subagents`
3. Add `task` to `native_tools`
4. Use `SUBAGENT_USAGE_INSTRUCTIONS` as system prompt
5. The Deep Agent framework handles sub-agent execution

**Pros**: Uses existing infrastructure
**Cons**: We just spent the last session making the agent be a **Regular Agent**. Switching back to Deep Agent is a step back.

#### Path B — Implement real sub-agent execution for Regular Agents
1. Replace the placeholder `task` tool with a real implementation
2. Read `config.subagents` to find sub-agent configs
3. Invoke each sub-agent's `langchain.agents.create_agent` model in a sub-process
4. Return the result as a `Command` (matching the notebook's pattern)

**Pros**: Works with Regular Agent
**Cons**: Significant new code, more risk

#### Path C (RECOMMENDED) — Add a new tool `delegate_task` for Regular Agents
- Keep the existing `task` (placeholder, for Deep Agents)
- Add `delegate_task(description, subagent_type)` — actual execution
- The tool reads `config.subagents` and dispatches to the right sub-agent
- Sub-agents are themselves Regular Agents (already in DB)

**Pros**: Works with Regular Agent, no framework change
**Cons**: New tool, new code

## Recommended approach: Path C

1. Add `delegate_task(description, subagent_type)` to `tools/native_tools.py`:
   - Read `config.subagents` from agent state (via `InjectedState` or DB)
   - For each sub-agent, find the DB agent template by name
   - Invoke the sub-agent's `create_agent(model, tools, system_prompt)` in the same process
   - Return `Command(update={"messages": [ToolMessage(result, tool_call_id)]})`

2. Add the description constant `TASK_DESCRIPTION_PREFIX` (notebook's verbatim)

3. Add to `TOOL_REGISTRY` with `category: "delegation"`

4. In UI: configure agent with:
   - `native_tools: ["delegate_task"]` (and any other tools)
   - `system_prompt: SUBAGENT_USAGE_INSTRUCTIONS.format(...)`
   - `subagents: [{name: "research-agent", description: "...", prompt: "SIMPLE_RESEARCH_INSTRUCTIONS", tools: ["web_search"]}]`
   - `enable_default_middleware: false`

5. Test: send "请给我一个关于MCP的概述。" → expect `delegate_task` to be called with `subagent_type="research-agent"`, which triggers a sub-agent invocation that returns the MCP mock.

## Concrete steps

### Backend
1. `backend/tools/native_tools.py`:
   - Add `TASK_DESCRIPTION_PREFIX` constant
   - Add `delegate_task(description, subagent_type, state, tool_call_id) -> Command` tool
   - Add 1 entry to `available_tools` and `TOOL_REGISTRY`

2. (Optional) Add helper to invoke sub-agents by name

### Frontend
1. `src/hooks/useAvailableTools.ts`: add `delegation: 'Subagent Delegation'` (already done)
2. `src/features/agents/ui/DeepAgentBuilder.tsx`: add `delegate_task` to NATIVE_TOOLS (already done)

### UI configuration (no code)
1. Studio → + New Agent → Regular Agent
2. Native tools: `["delegate_task", "web_search"]`
3. Sub-agents:
   - name: `research-agent`
   - description: "Delegate research to the sub-agent researcher. Only give this researcher one topic at a time."
   - prompt: SIMPLE_RESEARCH_INSTRUCTIONS (the Chinese text)
   - tools: `["web_search"]`
4. System prompt: `SUBAGENT_USAGE_INSTRUCTIONS.format(max_concurrent_research_units=3, max_researcher_iterations=3, date=<today>)`
5. Save → Chat → query

## Known divergences

1. `state_schema=DeepAgentState` not exposed via UI (same as 2.1/2.2)
2. `enable_default_middleware=False` needed
3. Sub-agent execution is in-process (not a separate thread) — fine for this use case
4. Model is `minimax-m3` not `agnes-2.0-flash`
5. The `delegate_task` tool reuses the parent's model and tools (the notebook's task_tool also reuses the same model for all sub-agents)

## Files to add/modify

| File | Change |
|---|---|
| `backend/tools/native_tools.py` | +~80 lines: TASK_DESCRIPTION_PREFIX + delegate_task tool + dict/registry entry |
| `learning/phase13/README.md` | this file |

## What I need you to confirm

1. Use **Path C** (add `delegate_task` tool, keep existing `task` placeholder)?
2. Sub-agents will be **in-process** (same model, separate agent context)?
3. Use the existing `config.subagents` field for sub-agent configuration?

## Implementation plan

1. Add `TASK_DESCRIPTION_PREFIX` constant
2. Add `delegate_task` tool that:
   - Reads `subagents` from agent state (injected)
   - For the requested `subagent_type`, looks up the config
   - Creates a new `langchain.agents.create_agent` instance with the sub-agent's tools + prompt
   - Invokes it with isolated context (`state["messages"] = [{"role": "user", "content": description}]`)
   - Returns `Command(update={"messages": [ToolMessage(content, tool_call_id)]})`
3. Add to `available_tools` and `TOOL_REGISTRY`
4. Test via curl

### Tool implementation sketch

```python
DELEGATE_TASK_DESCRIPTION = """Delegate a task to a specialized sub-agent with isolated context.
Available agents for delegation are:
{other_agents}
"""

@tool(description=DELEGATE_TASK_DESCRIPTION)  # filled at binding time
def delegate_task(
    description: str,
    subagent_type: str,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    # Get subagents from state (or from a registry)
    subagents = state.get("subagents", {})
    if subagent_type not in subagents:
        return f"Error: invoked agent of type {subagent_type}, ..."
    
    sub_config = subagents[subagent_type]
    # Build sub-agent
    sub_model = ...  # use parent's model
    sub_prompt = sub_config.get("prompt", "")
    sub_tools = ...  # load from sub_config["tools"]
    sub_agent = create_agent(sub_model, sub_tools, system_prompt=sub_prompt)
    
    # Isolated context
    state["messages"] = [{"role": "user", "content": description}]
    result = sub_agent.invoke(state)
    
    return Command(update={
        "files": result.get("files", {}),
        "messages": [ToolMessage(result["messages"][-1].content, tool_call_id=tool_call_id)],
    })
```

The actual sub-agent execution requires plumbing (model + tools). I'll need to
read the existing `config.subagents` field and create a sub-agent on the fly.

## Risks

- **In-process sub-agent execution** can deadlock if the LLM API hangs — need timeout
- **State injection** of subagents is not yet supported in LangConfig (we use config dict, not state)
- **Tool name resolution** — sub-agents need their own tool list (like `["web_search"]`) which must be looked up at runtime

Tell me to proceed and I'll start implementing.