---
name: Agent Builder
description: 建 agent 的规程与六种结构模板。当用户要"做一个 agent""把这个活做成 agent""agent 建得对不对"时读我：先选 T1–T6 模板，写 rubric，填空建出来，跑探针逐条判，最后给证据。
version: 1.0.0
author: langconfig
tags:
- agent-building
- templates
- rubric
- verification
triggers:
- 用户要新建一个 agent
- 用户问某个 agent 的结构对不对
- 需要把需求变成 agent 配置
allowed_tools:
- create_agent
- update_agent
- test_agent
- pg_list_custom_tools
- pg_get_agent
- skill
---

# Agent Builder — how to build an agent that actually works

Read this before you `create_agent`. It is the long version; the short version is in
your system prompt.

## Pick a template before you think

Six structures cover everything we have built so far. Read the one that matches,
then fill in its JSON skeleton — do not invent a structure from scratch.

| template | structure | pick when |
|---|---|---|
| `templates/T1-single-agent.md` | one agent, 2–4 tools, no middleware | one job, one tool set, answer or file out |
| `templates/T2-supervisor-experts.md` | `task` only + N experts | work spans distinct domains, each expert answers in ~3 lines |
| `templates/T3-handoff-machine.md` | one agent + `handoff` middleware, per-step prompt/tools | one conversation, several stages, role changes mid-flow |
| `templates/T4-skills-driven.md` | agent + `skills` list + `skill` tool | long, rarely used, must stay editable knowledge |
| `templates/T5-research-pipeline.md` | deep agent + `todo_list` + research subagent | open question, deliverable is a cited file |
| `templates/T6-data-qa.md` | upload → sqlite → SQL | a table goes in, questions come after |

Every template has the same seven sections: when to use it, the JSON skeleton
(with `{{placeholders}}`), the prompt skeleton, tools/middleware, a rubric
template, a measured baseline, and the failure table. Copy the skeleton, replace
the placeholders, then verify every tool id against `pg_list_custom_tools`.

`facts/case-facts.md` holds the ground truth for the twelve training agents —
what they actually are, and where they disagree with the run book. Read it when
a template and a real agent disagree; quote the conflict instead of hiding it.

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

## Skill format (the spec the LangChain docs follow)

```
<skills-root>/<skill-id>/
├── SKILL.md            # YAML frontmatter (name, description) + instructions
├── references/         # docs the instructions point at
├── scripts/            # runnable helpers
└── assets/             # files used in output (templates, images)
```

- `name` **equals the directory name** (kebab-case id). The human label belongs in
  the body heading and the DB row, not in frontmatter.
- Only `references/`, `scripts/`, `assets/` are spec directories. A file under
  `templates/` or `facts/` is invisible to a spec-following reader — `create_skill`
  refuses those paths and says why.
- The instructions must **name every support file** and say when to read it. Files
  nobody mentions are files nobody loads (progressive disclosure level 3).
- Load order is fixed: metadata (name + description) at startup → full `SKILL.md`
  on invocation → support files only when the instructions ask for them.

## Creating a skill

A skill on this platform is two things: a row in `skills` and a git-tracked
`SKILL.md` under `backend/skills/personal/<owner>/<skill_id>/`. `create_skill`
writes both and returns the path; `update_skill` writes the file back. Never write
only the row — a skill without its folder has no support files and no way to reach
a teammate.

`create_skill(files={...})` writes the supporting files in the same call —
`references/`, `templates/`, `scripts/`, whatever the instructions point at.
Paths are checked: anything that escapes the skill folder is refused and
reported. They are read on demand with `skill("<id>", file="<relative path>")`
and never loaded together with the instructions.

The tool answers with a **disk listing and byte sizes** (`SKILL.md (4.0 KB)`,
`references/checklist.md (… B)`), because you cannot `ls` that folder yourself —
it lives under `backend/skills/`, outside your workspace. Quote that listing when
you report what you built; do not claim a file exists without it.

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
| a rubric names a specific read tool | the tool may legitimately be absent from that agent's catalogue — `read_file` showed up in one deep agent and not another | select `read_any_file` explicitly, or write the criterion as "read back with any read tool and quote it" |

## Are the templates on disk for you?

They live next to this file (`templates/`, `facts/`). If a deep agent's workspace
shows only `SKILL.md` under `skills/agent-builder/`, the staging step did not copy
the supporting files — say so and ask for them instead of inventing the structure
from the index table alone. (Seen on 2026-11-01: `skills/` staged empty for the
builder itself, so it rebuilt T2 from a library agent rather than the template.)

## When template and reality disagree

`facts/case-facts.md` records known bad examples on purpose (agent 319 is the
skills case with zero skills; agent 328 lists skill names as zero-tool
subagents; agent 159 carries 27 tools). Do not copy them. Say which template
rule the real agent breaks, and build the corrected version.
