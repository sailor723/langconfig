# Agent Builder

Status: designed 2026-11-01 · agent 1 (`Agent Builder`) · implements create → test → judge in one chat.

## What it is for

Turn "I want an agent that does X" into a **working, verified agent in the database**:
a rubric the user approved, an agent built from the real tool/skill catalog, a probe run,
and a per-criterion verdict with evidence. The chat reply is a receipt, not the work.

Modelled on two reference behaviours rather than invented:

- **Rubrics before work** — Deep Agents Code's `/goal` and `/rubric`
  ([goals-and-rubrics](https://docs.langchain.com/oss/deepagents/code/goals-and-rubrics)):
  the agent drafts acceptance criteria, a human approves them, then the agent iterates
  against them. "Done" is defined before the work starts.
- **Gated actions** — [approval-modes](https://docs.langchain.com/oss/deepagents/code/approval-modes)
  enumerates what needs review (`write_file`/`edit_file`/`delete`, `execute`,
  `web_search`/`fetch_url`, `task`) and what never does (`ls`, `read_file`, `glob`, `grep`).
  We copy that split; `task` is gated because delegating is the action that matters, and
  because a subagent's own tool calls are invisible to the parent's middleware
  (measured: a calendar event was created without an approval card on 2026-11-01).

## Flow

```
1 DRAFT RUBRIC   builder writes 3–5 checkable criteria  →  HITL approval
2 BUILD          create_agent(kind=deep|normal, tools, skills, subagents, mcp, middleware)
3 TEST           test_agent(agent_id, probe) → tool sequence / elapsed / answer
4 JUDGE          per-criterion pass|fail + evidence
5 FIX (≤2 rounds) fail → update_agent → back to 3
6 DELIVER        id, fields that took effect, rubric path, last test result
```

Stuck is a defined state: the same criterion failing twice stops the loop and reports
"blocked on #N, evidence is X" instead of retrying forever.

## Tools the builder gets

New (this design):

```python
create_agent(name, system_prompt, native_tools, kind="deep", skills=None, description=None,
             category=None, model=None, temperature=0.3, subagents=None, middleware=None,
             mcp_servers=None, tool_params=None, agent_docs=None) -> str

update_agent(agent_id, system_prompt=None, native_tools=None, skills=None, subagents=None,
             middleware=None, mcp_servers=None, model=None, temperature=None,
             agent_docs=None) -> str          # patches only the fields passed

test_agent(agent_id, probe, max_seconds=120) -> str
             # own session, own probe, returns tool sequence + elapsed + answer
```

Reused: `write_todos`/`read_todos`, `pg_list_agents`, `pg_get_agent`,
`pg_list_custom_tools`, `pg_list_skills`, `search_skills`, `skill`, `create_skill`,
`update_skill`, `ls`, `read_file`, `write_file`, `glob`, `grep`.

Deliberately not given: `bash`, `execute`, `pg_query`, `delete_agent`, `delete_skill`,
`web_search`. The first three are raw authority (raw SQL bypasses every check), deletes
stay with a human in the UI, and search is not needed to build an agent.

## Approval

Writes gate themselves **inside the tool** (`_approval_gate` in `tools/native_impl.py`,
fail-closed like `core/mcp/client.py`), so a subagent cannot route around them:

| action | gated |
|---|---|
| `create_agent`, `update_agent`, `create_skill`, `update_skill` | yes — every call |
| `task` (delegation), `write_file` (deliverables) | yes — via the agent's HITL policy |
| `ls`, `read_file`, `glob`, `grep`, `pg_list_*`, `search_skills`, `skill`, `test_agent` | no |

The builder runs **without subagents**: it is the orchestrator, and a second layer only
lengthens the approval chain that today's bug showed to be unreliable.

## Deliverables

```
generated/<slug>.rubric.md    approval criteria, as approved
generated/<slug>.config.json  the exact create_agent input (reproducible)
generated/<slug>.test.md      per round: probe, tools, elapsed, per-criterion verdict
```

Chat reply ≤15 lines: id, kind, tool/skill counts, rubric pass count, three paths.

## test_agent mechanics

Loopback HTTP to the platform's own chat API (`LANGCONFIG_API_BASE`, default
`http://127.0.0.1:8765`): start a session, stream a probe, collect `tool_start` events,
elapsed time and the answer. Chosen over building the graph in-process because the probe
then exercises exactly the path a user exercises; a test that takes a different path
proves nothing.

Known limit: there is no remote sandbox here (Deep Agents Code has
[remote-sandboxes](https://docs.langchain.com/oss/deepagents/code/remote-sandboxes)), so
`test_agent` runs on this machine. Hence the hard rule: never build an agent with
`bash`/`execute`/`pg_query` — testing it would be executing code locally.

## Normal vs deep

| kind | what the harness gives | when |
|---|---|---|
| `deep` | built-in `ls/read_file/write_file/edit_file/glob/grep/execute`, subagents, skills, MCP | multi-step work, files, expert split |
| `normal` | platform-assembled prompt (guardrails + tool enforcement); no built-in file tools | single job, rules the platform should enforce |

`normal` agents must select `write_file` explicitly; `deep` agents already have it.
