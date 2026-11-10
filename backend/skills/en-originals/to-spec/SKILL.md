---
name: To Spec
description: >-
  Turn settled decisions into one written specification: the problem, the decisions that were made and
  by whom, what is in and out of scope, and the acceptance criteria a validator will later check. Use
  after a grill round, or when a request is clear enough to write down but nobody has. It refuses to
  write a spec while a decision is still open — that is what Grilling is for.
tags: [spec, requirements, design, decisions, plan, acceptance-criteria]
triggers:
  - After a grill round, when the frontier is empty and the decisions should be recorded in one place
  - When a request is clear but nobody has written down what "done" means
  - Before cutting tickets, so the tickets have one parent they can cite
  - When two people remember the same requirement differently
allowed_tools: [read_file, write_file, grep, glob, ls, skill]
author: weiping
version: 1.0
params:
  spec_dir: "where specs live (default: docs/specs)"
  grill_path: "the grill.md this spec came from, if any (default: work/<scope>/grill.md)"
---

## Instructions

A spec is the one document a ticket, an implementer and a validator can all cite. It records decisions,
not intentions: if a sentence could be true after any implementation, it does not belong here.

### Step 0 — Is it specifiable yet?

List the decisions the work depends on. For each, is it **settled** (a grill answer, a prior doc, the
user said so) or **open**? If anything material is open, stop and say: *"N decisions are still open:
…; run Grilling first."* Writing a spec on top of open decisions produces a document that reads
confidently and is wrong.

### Step 1 — Gather what is already decided

- `grill_path` (default `work/<scope>/grill.md`) — the decisions, verbatim, with their reasons.
- `GLOSSARY.md`, `docs/adr/` — terminology and architecture decisions this work must not contradict.
- The code and declarations the work touches — a spec that proposes something the repository already
  does is worse than no spec.
- The request/ticket that started this — the words the person actually used.

### Step 2 — Write the spec

Path: `params.spec_dir/<slug>.md`. Sections, in this order (the order is the argument):

```
# <title>

Status: draft | agreed (<date>)   ·   Decisions from: <grill.md / conversation / ADR n>   ·   Author: <agent|person>

## Problem
What is wrong today, in one paragraph, with the evidence that it is wrong (a file:line, a number, a
user's sentence). Not "we want a better X".

## Decisions
| # | Decision | Why | Source |
|---|---|---|---|
| D1 | <decision> | <one line of reasoning> | grill Q3 / ADR 0002 |

## Scope
In: <the smallest thing that delivers the decisions>.
Out: <what this deliberately does not do, named so nobody assumes it was covered>.

## Acceptance criteria
Numbered, each checkable by a command, a query, or a file:line. Each one is what `to-validation` will
later judge PASS/FAIL. If you cannot say how it will be checked, it is not a criterion.

| # | Criterion | How it will be checked |
|---|---|---|
| AC1 | … | `pytest tests/test_x.py::test_y` exits 0 |
| AC2 | … | `curl -s -o /dev/null -w '%{http_code}' …/api/x` prints 200 |

## Risks and reversibility
What breaks if this is wrong, and how it is undone. If undo is expensive, say so here, not in review.

## What would change this spec
The evidence that would move a decision. This is what turns a spec into something a reader can argue
with rather than obey.
```

Rules:

- **Every decision cites its source.** A decision with no source is your invention, and should be an
  open question instead.
- **Acceptance criteria are outcome-shaped and few.** Five that a machine can check beat fifteen that
  sound thorough. "Better UX" is not a criterion; "the panel shows 0 rows and a reason when the endpoint
  returns 412" is.
- **Scope out is a list, not a vibe.** Name the tempting adjacent thing you are not doing.
- **No implementation.** No file paths to create beyond what the criteria need, no function names unless
  a decision fixed them. The implementer owns the how; the spec owns the what and the why.

### Step 3 — Read it back before confirming

Present the Decisions table and the Acceptance criteria to the user, and ask two questions only:
*"Are these the decisions you agreed?"* and *"Would you check any of these criteria differently?"*
Then set `Status: agreed` when they answer. One round, not an interview — if it turns into an interview,
the grill was incomplete and you should say so.

### When NOT to use this

- The work is a one-line fix with an obvious check: write the criterion in the ticket and move on.
- The decisions are open: grill first.
- The user wants a plan of steps: that is `to-tickets`, and it needs this spec as its parent.
