# Agent Builder — how to build an agent that actually works

Read this before you `create_agent`. It is the long version; the short version is in
your system prompt.

## The order is not negotiable

```
rubric  →  build  →  test  →  judge  →  (fix ≤2)  →  deliver
```

A rubric written after the build is a rationalisation, not a standard. Write it first,
show it to the person, and only build once they approve.

### Rubric rules

- 3–5 criteria. Each one must be decidable by looking at a test run.
- Bad: 「回答质量好」 · Good: 「调用 web_search 取到当天天气，且温度数字来自工具返回」
- Bad: 「能处理 CSV」 · Good: 「上传 3 行 CSV 后，回答里的行数与文件一致」
- Each criterion gets one probe. A probe like `hi` tests nothing — write the message a
  real user would send for that criterion.
- Save it: `generated/<slug>.rubric.md`, one line per criterion, numbered (`R1`–`R5`).

## Choosing the kind

| kind | harness gives | you must add | pick when |
|---|---|---|---|
| `deep` | `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute`; subagents; skills; MCP | tools beyond files, middleware if you want HITL | multi-step work, files as output, expert split |
| `normal` | platform-assembled prompt (guardrails + tool enforcement); **no file tools** | `write_file` explicitly if it must save files | one job, rules the platform should enforce for you |

Default to `deep` unless the person asks for platform-enforced rules.

## Reading the catalog — never guess a tool id

```
pg_list_custom_tools()      # the real 66 ids with descriptions
search_skills("weather")    # skill search by intent
pg_list_skills()            # everything
skill("<skill-id>")         # full text of one skill
pg_list_agents()            # what already exists, so you do not duplicate
pg_get_agent(<id>)          # the full config of one agent, before you update it
```

Tool names in a prompt that do not exist in the catalog fail silently — the agent
simply never calls them. That is the single most common way a build looks fine and
does nothing.

## Subagents

Add one only when the split is real:

- the sub-problem needs **a different tool set** (security analyst reading code, not
  writing it), or
- the sub-problem's output is **a summary**, not a file.

If everything needs the same tools and the same context, one agent is better. Each
subagent costs a hand-off and its result comes back as text.

`interrupt_on` on a subagent gates its own tools; a parent's policy does **not** reach
into it (measured 2026-11-01: an event was created inside a `task` with the parent's
approval list set).

## MCP servers

`mcp_servers={"calendar": {"url": "http://127.0.0.1:3000"}}` — the tools arrive as
`calendar_list_events`, `calendar_create_event`, … at build time. A server that is down
is skipped with a warning; the agent still runs. Approval for those tools comes from the
agent's HITL policy and is enforced inside each tool.

## Testing

`test_agent(agent_id, probe)` returns: tool sequence, elapsed time, answer text, timeout
flag. Judge with evidence:

```
R1 PASS — 工具序列里有 web_search；回答「上海 24–25℃」与工具返回一致
R2 FAIL — 没有写文件；工具序列只有 web_search、ls
```

Fix one thing per round, then retest the same probes. Two rounds of the same failure =
report blocked with the evidence, do not keep looping.

## Naming and delivery

- Name: `case-N-<topic>` when it is course material, `<topic>-assistant` otherwise.
  Lowercase, hyphens, no spaces.
- Deliver three files: `generated/<slug>.rubric.md`, `<slug>.config.json` (the exact
  create_agent input), `<slug>.test.md` (probe, tools, elapsed, R# verdicts).
- Chat reply ≤15 lines: id, kind, tool/skill counts, rubric pass count, three paths.

## Failure patterns worth recognising

| symptom | likely cause | fix |
|---|---|---|
| answers without calling any tool | tool id typo, or the prompt never says what the output must contain | read the catalog again; state the deliverable in the prompt |
| calls the right tool but ignores the result | two tools with overlapping descriptions | remove the weaker one |
| normal agent cannot save files | `write_file` not in `native_tools` | add it, or use `deep` |
| works in test, breaks in use | probe was narrower than real input | widen the probe |
| approval card never appears | the call happened inside a subagent | gate at the tool, or drop the subagent |
