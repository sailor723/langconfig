# Skill authoring — how to turn a working agent into a reusable skill

**Status:** working method, validated on `research-execution` (agent 212 → skill). Date: 2026-10-03.

The purpose of this doc: stop the most common mistake — *"I have a prompt that works, so I'll paste it into a
skill."* That produces a skill that only fits the agent it came from. A skill is not a prompt; it is the part
of a prompt that is **true for every agent that could load it**.

---

## 1. The mental model

| | Agent prompt | Skill |
|---|---|---|
| Audience | one agent | any agent that loads it |
| Contains | role, task, tools, language, workspace, install rules | portable know-how only |
| Enables tools? | yes (it selects them) | **no — it enables nothing** |
| Fails when | it is too generic | it is too specific |

So the conversion is a **classification**, not a copy.

## 2. Sort the prompt into four buckets

Every sentence goes into exactly one bucket. Only **C** becomes the skill.

| Bucket | What belongs there | Where it goes | Example from agent 212 |
|---|---|---|---|
| **A. Identity & task** | who the agent is, what it is for, workspace, language, tone | agent prompt | `<Task>` block; "please answer in Chinese"; identity block |
| **B. Tool inventory** | which tools exist and which to prefer *by name* | agent prompt — the skill may only state **requirements** | "You have access to research tools…" |
| **C. Portable know-how** | how to do the work well: budgets, anti-loop, reflection, source ranking, verification, output contract, stopping rule | **the skill** | Hard Limits; ANTI-LOOP RULE; Show Your Thinking; `### Sources` contract |
| **D. Install-specific rules** | this platform's file tools, panel names, quirks | agent prompt | "use `write_file` only, never `save_document`, files appear in the Files panel" |

**Rule of thumb:** if the sentence would still be correct on a *different* agent, on a *different* platform,
it can be bucket C. If it names a tool, a path, a model or a language — it is A/B/D.

## 3. Guardrails are copied verbatim

Behavioural guardrails are enforcement text, not prose. Copy them **word for word**; rewrite the framing
around them freely.

Measured evidence from agent 212:

| Wording | Observed behaviour |
|---|---|
| Cap split across "simple 2-3 / complex up to 5 / always stop after 5 *if you cannot find*", no counting rule | agent invented a ceiling of **8**, self-reported "4/8", and used **6** searches |
| `HARD CAP: 5 search calls per task … never state a budget other than 5 … At the cap: stop and list the gaps` + `searches used: n/5` in every reflection | two consecutive runs reported **"4/5"** and used **5** and **4** searches |

The only change was wording. Treat the anti-loop rule, stop conditions and hard caps this way.

## 4. The recipe

1. **Make the agent work first.** You need a measured baseline to test the skill against. Record it
   (searches used, budget statement, tool order, output path).
2. **Annotate the prompt with the four buckets.** Physically mark A/B/C/D — everything in C is skill candidate.
3. **Write the skill in "do X" voice.** Tool references should be *classes* of capability
   (`web_search` / `tavily_search` / `web_fetch` are generic; `save_document` is not). Paste bucket-C
   guardrails verbatim.
4. **Add the sections an agent prompt doesn't need but a skill does:**
   - what + when, in the `description` (this is the entire discovery surface);
   - verification rules;
   - ranked source tiers;
   - a stopping rule;
   - `## Not this skill's job` — explicit hand-offs to sibling skills;
   - `## Requirements (provided by the agent, not by this skill)` — a table naming the tools the host agent
     must carry.
5. **Frontmatter** — what is enforced and what is decoration:

   | Key | Reality |
   |---|---|
   | `name` | must equal the directory name, lowercase kebab-case. A violation only **warns** — the skill still loads |
   | `description` | *what + when*, ≤1024 chars; longer is **silently truncated**. This single line is how the model discovers the skill |
   | `tags`, `triggers` | UI/metadata only — the deepagents SDK **ignores** them |
   | `allowed-tools` | parsed and rendered into the prompt, but **never enforced** — metadata, not a permission system |
   | `author`, `license`, `compatibility` | metadata (`compatibility` truncates at 500) |

6. **Sync and verify.** The DB row is the runtime source of truth (see §5). After editing `SKILL.md`:
   `POST /api/skills/reload-all` with body `[]`, then confirm the DB `instructions` length, the `description`,
   and the **level-1 catalog line** the model actually reads.
7. **Test the skill as a behaviour spec.** Minimum checks:
   - **Discovery** — does an agent that was never told the skill name load it from the catalog?
   - **Compliance** — does it obey the cap, the anti-loop rule and the output contract?
   - **A/B** the wording when you change a guardrail: ≥3 samples per arm, compare medians.

## 5. How skills are served in LangConfig (db mode)

| Fact | Consequence for authors |
|---|---|
| The **DB row** is what `SkillsMiddleware` serves; `SKILL.md` on disk is the git-tracked source | editing the file alone changes nothing until you reload |
| `_stage_skill_catalog` re-serialises **every** skill row to storage on each agent build under `skills/<source_type>/<skill_id>/SKILL.md` | no per-skill staging step; but see the next row |
| Storage keys are **written, never pruned** | moving a skill between roots (personal → builtin) leaves the old object behind |
| Sources are handed to the middleware in order `[/skills/builtin, /skills/personal]` and the middleware merges by **name, last source wins** | a stale personal copy **shadows** the current builtin one. Live example: `document-deliverables` (personal 2,946 B beats builtin 3,468 B) |
| `config.skills` (the Skills picker) has **no runtime effect** in db mode | pinning ≠ enabling. Discovery is library-wide |
| `SkillsMiddleware.before_agent` loads `skills_metadata` **once per thread** | the catalog is frozen for that conversation; a new/edited skill needs a new chat |
| The catalog is metadata only; level 2 is `read_file` on the path, level 3 is whatever that body references | the skill must be readable **as a file**, and the agent must carry a file-reading tool |

## 6. Measuring — use the checkpointer, not the chat log

`chat_sessions.tool_calls` **double-counts batched tool calls** (observed: 16 recorded vs 12 real; 10
"searches" vs 6 real in one run). It made a correct run look like it violated the anti-loop rule.

Read the real history from the LangGraph checkpointer instead:

```python
url = engine.url.render_as_string(hide_password=False).replace("postgresql+psycopg2://", "postgresql://")
async with AsyncPostgresSaver.from_conn_string(url) as cp:
    t = await cp.aget_tuple({"configurable": {"thread_id": session_id}})
msgs = t.checkpoint["channel_values"]["messages"]        # one entry per real tool call
```

Also remember: `temperature=0.0` still varies run to run. Two runs with identical settings produced
"wrote a file" and "answered inline" on the same request — never conclude from n=1.

## 7. What a skill must never contain

Tools · model names · identity/workspace paths · language preference · absolute paths · this platform's file
or panel rules · secrets · "you are a…" framing. If it needs a capability, it **states the requirement**; the
agent supplies the tool.

## 8. Pitfalls

| Pitfall | Reality |
|---|---|
| "Pinning a skill makes it used" | `config.skills` is inert in db mode |
| "The catalog limits what the agent can find" | discovery is library-wide; agent 115 loaded `global-equity-research` with nothing pinned |
| "Editing SKILL.md is live" | reload required, and the catalog is frozen per existing thread |
| "Moving a skill is clean" | storage is never pruned → stale shadow wins the merge |
| "Bigger skill = better" | it is loaded into context on demand; 9 KB is fine, 50 KB taxes every call |
| "The agent's self-report is evidence" | 212 once reported a filename that existed only in a phantom tree |

## 9. Worked example — agent 212 → `research-execution`

The same prompt, sorted:

| Bucket | Content | Destination |
|---|---|---|
| A | `<Task>` block ("answer the user's question by gathering real information"), role framing | stayed on 212 |
| B | "You have access to research tools" | stayed on 212; the skill only declares a `Requirements` table |
| **C** | tool ladder, `think_tool` reflection, hard cap, self-count, Stop-Immediately-When, ANTI-LOOP, inline-URL + `### Sources` + unverified contract | **→ the skill** |
| D | "one write path: `write_file` only", filename reporting, Files-panel behaviour | stayed on 212 |

Resulting fidelity (measured with `difflib` on the extracted blocks):

| Block | Similarity | Note |
|---|---|---|
| `think_tool` requirement | 100% | verbatim |
| Stop Immediately When | 100% | verbatim |
| Self-count line | 99% | verbatim (backticks added around `think_tool`) |
| ANTI-LOOP RULE | 89% | verbatim + one added rate-limit line |
| Tool ladder | 48% | their STRATEGY / Use for / Why structure, our real tools (no `serper_*`, no `wikipedia_search`) |
| Reflection questions | 50% | their questions + a `Count` bullet |
| Hard cap block | 46% | the cap lines verbatim; the surrounding "simple/complex" lines rewritten |

Additions the skill has that no single agent prompt needs: ranked source tiers, a verification section,
`graphindex_*` as the internal-documents rung, a stopping rule, requirements table, and hand-off notes to
`research-planner` / `document-deliverables`.

## 10. Author checklist

```
[ ] baseline recorded for the source agent (searches, budget statement, output path)
[ ] prompt annotated A / B / C / D
[ ] only bucket C moved into the skill
[ ] all guardrails pasted verbatim (cap, anti-loop, stop conditions)
[ ] tool references are capability classes, not this install's tool names
[ ] description states what + when, ≤1024 chars
[ ] name == directory name, kebab-case
[ ] sections present: tool ladder · reflection · budget · query craft · ranked sources ·
    verification · output contract · stopping rule · not-this-job · requirements
[ ] reload-all run; DB instructions + description + level-1 catalog line verified
[ ] behaviour test: discovery by a skill-less agent, cap compliance, output contract
[ ] changes A/B tested with ≥3 samples, measured from the checkpointer
```

---

*Companion docs: `docs/deepagents-study.md` (how the deep-agent runtime and skills are actually wired, with
the verified findings this method is based on), `docs/deepagent-vs-dsh.md` (gap list).*
