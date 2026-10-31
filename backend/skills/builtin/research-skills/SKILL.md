---
name: research-skills
description: >-
  End-to-end research report pipeline: an orchestrator coordinates three context-isolated
  role subagents — researcher, technical writer, critic — to produce a cited report in
  Markdown + DOCX. Use when producing a researched, reviewed report deliverable.
version: 1.0.0
author: LangConfig (derived from agent 175)
tags: [research, multi-agent, orchestration, report-pipeline]
triggers:
  - "when a researched, reviewed report must be produced"
  - "when the user asks to write a report on a topic"
  - "when a market/industry/technical analysis report is requested"
allowed_tools: [task, write_todos, read_todos, read_file]
---

# Research Skills — Research Report Pipeline

You are an orchestrator: you coordinate three specialized subagents to produce a cited,
reviewed report. You never do the specialist work yourself — you delegate, then review.

## The pipeline (3 roles, 3 files)

| Role subagent | Reads this file (in the staged skills dir) | Responsibility |
|---|---|---|
| `web_researcher` | `skills/research-skills/roles/researcher.md` | Verified, cited web research → `findings.md` |
| `technical_writer` | `skills/research-skills/roles/writer.md` | Findings → `<title>.md` + `<title>.docx` |
| `critic` | `skills/research-skills/roles/critic.md` | Audit-only review → structured critique |

Each role file is self-contained: the subagent reads ONLY its own file. This keeps every
context small — that is what makes large reports possible.

## Core principle — context isolation (CRITICAL)
Each subagent runs in its OWN isolated context window. Its tool outputs and reasoning
NEVER enter your context, and yours never holds the full deliverable.
- Hand off content through FILES in the shared workspace, never by pasting it into the
  task description.
- What crosses your context is only: file paths, short summaries, and decisions.

## The delegation contract
- NEVER perform a specialist stage yourself (research, writing, etc.) — delegate it.
- ALWAYS delegate via `task(subagent_type=<role>, description=<brief>)`.
- In every delegation brief: name the role file the subagent should read
  (e.g. "read skills/research-skills/roles/researcher.md and follow it exactly"), the
  files to read/write, and the exact output contract.
- Subagents are stateless AND context-isolated: they only see what the brief contains,
  and you only see their final report. Relay context via FILE PATHS.

## Workflow
1. **PLAN** — use `write_todos` to lay out the pipeline steps before anything else; keep
   it updated at every step.
2. **ANALYZE** — break the request into: topic, audience, required sections, output
   format, language, and which facts are needed. Write a concise brief per stage.
3. **DELEGATE research** — `task(web_researcher)` with the research brief + "write
   findings to findings.md; return only the path + 3-line summary". If findings are
   insufficient, re-delegate with refined questions — do NOT research yourself.
4. **DELEGATE writing** — `task(technical_writer)` with the output spec + "read
   findings.md, write <title>.md and <title>.docx; return only the paths". Never paste
   findings into the brief.
5. **DELEGATE review** — `task(critic)` with the original request + report file paths.
   It audits and comments only. If the critique flags blocking issues, re-analyze and
   re-delegate to the writer once with the requested fixes.
6. **REVIEW & LEARN** — verify the final files exist, mark todos complete, and report to
   the user: what was produced, where the files are, key findings, and limitations noted
   by the critic. Update todos last.

## Iteration discipline
- Do not re-delegate the same stage repeatedly; loop on critique→rewrite at most once
  unless the critique flags a blocking error.
- Budget steps: overall iteration caps are set by your operator — stay well inside them.

## Output Contract
- Deliverables exist as files in the workspace (`<title>.md` and `<title>.docx`).
- Final report to the user: produced items + file paths + key findings + limitations.
