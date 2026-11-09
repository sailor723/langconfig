---
name: To Tickets
description: >-
  Cut a spec into tracer-bullet tickets: vertical slices that each deliver something demoable, sized to
  one fresh context window, each declaring what blocks it and what will be checked. Use after a spec,
  so several agents (or several turns) can work the same plan without guessing the order. It refuses a
  ticket whose acceptance cannot be checked.
tags: [tickets, breakdown, planning, tracer-bullet, dependencies, work-graph]
triggers:
  - After a spec is agreed and the work needs an order
  - When several agents or turns will touch one plan
  - When a plan is a list of layers ("add the column, then the API, then the UI") that can never be demoed
  - When the work keeps stalling because nobody knows what is unblocked
allowed_tools: [read_file, write_file, grep, glob, ls, skill]
author: weiping
version: 1.0
params:
  ticket_dir: "where tickets live (default: docs/tickets)"
  spec_path: "the spec these tickets implement (default: docs/specs/<slug>.md)"
---

## Instructions

The unit is a **tracer bullet**: a narrow but *complete* path through every layer, demoable on its own,
small enough to finish in one fresh context window. The tickets are not a list of steps — they are a
**task graph**, and the useful output is the *frontier*: which tickets are ready now.

### Step 0 — Refuse to cut without a parent

Read `spec_path`. No agreed spec → stop: *"there is no agreed spec; run to-spec first"*. A ticket whose
acceptance criteria were invented during the cutting is a ticket nobody can validate.

### Step 1 — Explore before slicing

Read the code the spec touches. Look for **prefactoring** that makes every later ticket smaller ("make
the change easy, then make the easy change"): a seam, an extracted function, a missing test harness.
Prefactoring gets its own ticket, first, and everything else is blocked by it.

### Step 2 — Slice vertically, and name the blockers

For each slice:

- it cuts through schema → service → API → UI → test where those exist, rather than filling one layer;
- it is **demoable or verifiable on its own** — 4 of 4 criteria from the spec, not "half of each";
- it fits a fresh context window; if it does not, split it, do not stretch it.

Give each ticket its **blocking edges** — the tickets that must land first. A ticket with no blockers is
on the frontier and can start immediately.

**Wide refactors are the exception.** One mechanical change (a rename, a type change) whose blast radius
covers the codebase cannot be a tracer bullet — nothing lands green mid-way. Sequence it
**expand → migrate in batches → contract**:

1. *expand*: add the new form beside the old, so nothing breaks;
2. *migrate*: one ticket per batch (per package, per directory), each blocked by the expand;
3. *contract*: delete the old form, blocked by every migrate batch.

If even the batches cannot stay green alone, keep the sequence but let them share an integration branch
that all block a final integrate-and-verify ticket — green is promised only there.

### Step 3 — Write one file per ticket

`params.ticket_dir/NNN-<slug>.md`, three digits, numbered in dependency order (not necessarily execution
order):

```
# 003 — <title>

Spec: docs/specs/<slug>.md#AC2, AC3      Blocked by: 001, 002      Size: S | M | L (one context window)

## Delivers
The end-to-end behaviour this ticket makes true, in one paragraph, in the user's terms. If you cannot
write this paragraph without listing layers, the slice is horizontal — cut again.

## Acceptance (what a validator will check)
- [ ] <checkable criterion, copied or narrowed from the spec's AC table>
- [ ] <and the test/command that will prove it>

## Not in this ticket
What it deliberately leaves to a later ticket, so two agents do not both do it.

## Notes
Seams found while exploring, and anything that would change the split.
```

Rules:

- **Every ticket has at least one checkable acceptance line.** If the best you can write is "works
  properly", the ticket is not ready — that is the same failure `to-validation` exists to catch.
- **Acceptance lines trace to spec AC ids.** A ticket that satisfies none of the spec's criteria is scope
  creep; either it is in the spec or it is a new spec.
- **Blockers are stated as ticket numbers**, not as prose. "After the API" is not an edge.
- **One ticket, one why-to-be-alive.** Two reasons → two tickets.
- Do not put estimates of hours on them. "Fits one context window" is the only size that matters here.

### Step 4 — Quiz, then stop

Present the graph as a list — `NNN title · blocked by … · delivers …` — plus the current **frontier**
(the unblocked ones), and ask: *"Does this cut the work the way you want, and is the frontier what you
expected?"* Fix what they object to before anyone starts. Do not begin implementing in this skill.

### When NOT to use this

- One ticket's worth of work: write it and go.
- No agreed spec: run `to-spec` (and `Grilling` behind it) first.
- The "plan" is really an investigation: use `research` or `diagnosing-bugs`, which produce findings, not
  tickets.
