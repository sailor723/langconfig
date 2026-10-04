---
name: agent-to-skill
description: >-
  Convert an existing agent into a reusable skill: read the agent's prompt, derive name / description / tags / triggers, move the authored body into instructions verbatim, and leave every tool decision to the host agent. Use when the user asks to turn an agent into a skill, extract a skill from an agent, reuse a working agent's prompt as a skill, or migrate an agent's know-how into the skill library.
tags: [skill-creation, meta, conversion, agent-design]
triggers:
  - "when the user asks to convert an agent into a skill"
  - "when the user asks to extract a skill from an agent"
  - "when the user asks to reuse an agent prompt as a skill"
  - "when the user says 'make a skill from agent X'"
author: LangConfig
---

You convert **agents into skills**. One conversion = one agent in, one skill out.

A skill is **portable know-how, not a capability**: it enables no tools and selects no model. The
host agent keeps its own identity, tools, model, language and workspace; the skill only carries what
is true for every agent that could load it. That distinction is the whole job — the conversion is a
**transcription with a header**, not a rewrite and not an optimisation.

## The four steps

### Step 1 — Read the source agent's prompt

Read the agent's stored system prompt. In this platform the stored prompt is **three concatenated
parts**, and only the first is portable:

| Part | Where it starts | Verdict |
|---|---|---|
| The authored instruction body | the top of the prompt, before the identity block | **this is the conversion source** |
| The baked `## Identity` block | at the `## Identity` heading (agent id, workspace path, "you are agent N…") | drop |
| The embedded instruction docs | at `## AGENTS.md (embedded)` (`AGENTS.md` + `CLAUDE.md` mirrors, path map, working conventions) | drop |

**Cut at `## Identity` and ignore the embedded docs.** They are regenerated per install and per
project, so copying them produces a skill that is wrong on every other agent, and stale on the next
rebake. Also ignore the separate `agent_docs` field for the same reason.

Expect the authored body to be a small fraction of what you read — that is normal, not a signal that
the agent is thin.

### Step 2 — Derive the header fields

An agent prompt carries no frontmatter, so these fields are **derived**, not extracted. Four of them:

| Field | Rule | Why it matters |
|---|---|---|
| `name` / id | Short and descriptive. The id is the name lowercased with spaces and underscores turned into dashes — so **choose the name to get the id you want**, you cannot set the id directly | The id must match the skill's directory name; it is also how the skill is invoked by name |
| `description` | **what + when**, one or two sentences, within 1024 characters | This single line is the *entire* discovery surface — it is all the model sees when deciding whether to load the skill. Write it for the agent that will *find* it, not for the human who wrote the source prompt |
| `tags` | 3-8, first is the primary category | Library metadata and filtering only; nothing at runtime reads them |
| `triggers` | 2-6 phrases shaped "when the user …" | Library metadata only, same as tags |

Derive the description from the source agent's task and from the body's own first lines — but write
the *when*, which an agent description usually lacks (an agent is invoked deliberately; a skill is
discovered by description). Never exceed 1024 characters: overlong descriptions are truncated
silently, and the tail is where the "when" usually lives.

### Step 3 — Body → `instructions`

Take the authored body from step 1 and move it into `instructions` **verbatim**:

- No frontmatter block — the writer supplies the header; a pasted `---` block becomes literal text.
- No `## Instructions` heading — the stored body is served wrapped in that heading already.
- No condensing, no re-ordering, no "cleaning up" the voice. Enforcement wording (caps, stop
  conditions, anti-loop rules, output contracts) is exact text: rewording it changes behaviour. If
  you must touch anything, leave the guardrails alone.

The body is loaded on demand, in full, into the host agent's context. Before you paste it, confirm
that everything in it is genuinely portable; anything you would not want a different agent to obey
belongs in the host's prompt, not in the skill.

### Step 4 — Tools: leave them alone

Do **not** rewrite tool references, strip them out, or emit a tool list, a permission list or a
requirements table. The skill states the work; the host agent decides what it carries.

Tool mentions inside the body travel with the body, unchanged, exactly like any other sentence. This
is deliberate: the tool text is part of the know-how, and the field that would otherwise hold a tool
list is metadata that nothing enforces.

The accepted consequence: a converted skill can name a tool the host does not carry. That is a host
configuration matter — fix it on the agent, not in the skill. A skill is loaded by many agents; it
must never assume one agent's toolbox.

## What never travels into a skill

Everything here stays on the host agent:

- identity, agent id, workspace path, project or vault names;
- the model, temperature, iteration or token limits;
- the user's language preference and tone instructions;
- install-specific file, folder and panel rules;
- the tool selection itself;
- anything already covered by the skill library's global discovery.

If the conversion leaves you holding text that fits one of those buckets, it belongs to the agent.
If it fits none of them and still cannot be obeyed by a different agent, it is not know-how — say so
and hand it back to the user instead of writing it into the skill.

## Verify before reporting

1. **Read the skill back** the way an agent would, as a file, and confirm the body arrived intact —
   no lost headings, no duplicated title, no leftover frontmatter.
2. **Confirm the derived fields** survived: the description within 1024 characters, the name equal
   to the id, tags and triggers present.
3. **Check the discovery line** the model will actually see, and ask whether a different agent, given
   only that line and its own task, would know to load this skill.
4. Remember the catalogue is read **once per conversation**: a skill created mid-session is not
   visible in that session. Verification in a fresh conversation is the only honest test.

## Worked example — why the strip rule is the whole conversion

| Source agent prompt | Authored body | Converted skill body |
|---|---|---|
| 4,000 characters, 59 lines | **4 numbered lines** of approach | 45 lines (the 4 lines plus an output contract) |
| 5,265 characters, 79 lines | tool ladder, reflection rule, hard cap, anti-loop rule, output contract | 140 lines, ~30% of the source's lines carried verbatim |
| 3,340 characters | **one sentence** | 21 lines |

Most of what a stored prompt contains is identity and embedded docs generated by the platform. The
conversion quality shows up in what you *left out*, and the guardrails are the part that must survive
character-for-character.

## Report the result as

1. The skill id and its description (the discovery line).
2. The authored body's size in, versus the skill body's size out — the strip ratio.
3. Anything you deliberately did **not** carry, and where it stayed.
4. Confirmation that the body was pasted verbatim and that the guardrails are unchanged.

## Not this skill's job

- **Authoring a skill with no source agent** (a new capability, or one learned from a run rather
  than from a prompt) — that is skill authoring, not conversion.
- **Choosing or changing the host agent's tools.**
- **Fixing an agent that does not follow its own prompt.** Conversion preserves behaviour; it does
  not repair it. Diagnose the agent first, then convert.

---

*Origin: the LangConfig agent → skill conversions (agents 161, 212, 210 → `research-planner`,
`research-execution`, `document-deliverables`). Ported from that work: the four-step procedure, the
cut-at-identity strip rule, the derived-header rules, the verbatim-body rule and the verification
catalogue. The tool rule is deliberately narrower than the earlier conversions, which rewrote tool
ladders and emitted requirements tables — per the agreed policy, tools are now left exactly where the
source body put them. This skill enables nothing: it is procedure only.*
