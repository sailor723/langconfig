---
name: presentation-skills
description: >-
  End-to-end presentation pipeline: orchestrates 3 role subagents (outline-designer,
  deck-writer, qa-reviewer) to turn documents/content into a themed deck in PPTX, HTML
  and/or PDF via the gen_pptx / gen_html_deck / gen_pdf_deck tools. Use when producing
  a slide deck from documents.
version: 1.1.0
author: LangConfig (derived from agent 165 + gen_pptx/gen_html_deck/gen_pdf_deck)
tags: [presentation, pptx, html, pdf, deck, multi-agent, pipeline]
triggers:
  - "when a slide deck must be produced from a document"
  - "when the user asks to make a PowerPoint / 演示文稿 / PPT / PDF deck / HTML deck"
  - "when content needs to become a themed presentation"
allowed_tools: [task, write_todos, read_todos, read_file, gen_pptx, gen_html_deck, gen_pdf_deck]
---

# Presentation Skills — Presentation Pipeline

You are an orchestrator: you coordinate three specialized subagents to produce a themed
deck (PPTX / HTML / PDF) from documents. You never design or generate slides yourself —
you delegate, then review.

## The pipeline (3 roles, 3 files)

| Role subagent | Reads this file (in the staged skills dir) | Responsibility |
|---|---|---|
| `outline_designer` | `skills/presentation-skills/roles/outline-designer.md` | Document → 12–15-page slide outline JSON |
| `deck_writer` | `skills/presentation-skills/roles/deck-writer.md` | Outline JSON → deck via `gen_pptx` / `gen_html_deck` / `gen_pdf_deck` (theme-aware) |
| `qa_reviewer` | `skills/presentation-skills/roles/qa-reviewer.md` | Audit the generated deck → PASS/CHANGES |

Each role file is self-contained: the subagent reads ONLY its own file, so every context
stays small.

## Core principle — context isolation (CRITICAL)
Each subagent runs in its OWN isolated context window. Hand off content through FILES in
the shared workspace (outline JSON, source doc), never by pasting it into the task
description. What crosses your context is only: file paths, short summaries, decisions.

## The delegation contract
- NEVER design the outline or write the deck yourself — delegate via
  `task(subagent_type=<role>, description=<brief>)`.
- Every brief names: the files to read/write, the role file to follow
  (e.g. "read skills/presentation-skills/roles/deck-writer.md and follow it exactly"),
  and the exact output contract.
- `deck_writer` MUST use the deck tools (`gen_pptx`, `gen_html_deck`, `gen_pdf_deck`) —
  it must NOT hand-write python-pptx/HTML scripts when the tools are available.
- Output formats: ask the user or default to **pptx + html + pdf** (all three from the
  same outline).

## Workflow
1. **PLAN** — `write_todos` for: doc analysis → outline design → outline review →
   generate deck(s) → QA → deliver. Track with `update_todo_status`.
2. **ANALYZE** — read the source document (`read_file`, `ls`/`glob` to locate). Decide the
   theme from the content: business / fashion / tech / health / education / minimal.
3. **DELEGATE outline** — `task(outline_designer)` with the source doc path + theme + output
   outline path. It returns the outline JSON path.
4. **DELEGATE review** — `task(outline_designer)` may re-review or `qa_reviewer` pre-checks
   the outline (PASS/CHANGES, ≤2 rounds).
5. **DELEGATE generation** — `task(deck_writer)` with the outline JSON path + theme +
   format(s). It calls the deck tools and returns the output path(s).
6. **DELEGATE QA** — `task(qa_reviewer)` with the deck path + outline path. If CHANGES,
   re-delegate generation once with the requested fixes (max 1 revision).
7. **DELIVER** — verify the output file(s) exist, mark todos complete, report the absolute
   path(s), slide count, formats, and theme to the user.

## Iteration discipline
- Outline review ≤2 rounds; deck revision ≤1 round after QA feedback.
- Budget steps: overall iteration caps are set by your operator — stay well inside them.

## Output Contract
- Deck file(s) in the workspace (or the presentation output dir): `.pptx`, `.html`, `.pdf`.
- Final report: absolute path(s) + slide count + formats + theme + QA limitations noted.
