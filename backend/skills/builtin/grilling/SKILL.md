---
name: Grilling
description: >-
  Interrogate a plan, design, metric definition or decision until nothing is silently assumed. Use when
  the user says "grill me", "stress-test this", "poke holes in it", or when a request is about to become
  expensive work (a build, a schema change, a metric everyone will quote) and the definitions are not
  settled yet. It asks numbered questions in rounds, each with a recommended answer, and does not start
  implementing until the frontier is empty.
tags: [grilling, requirements, design, decisions, review, clarification]
triggers:
  - When the user asks to be grilled, stress-tested, or to have a plan challenged
  - When a request would turn into hours of agent work and its definitions are still vague
  - When two people (or two documents) use one word for different things
  - Before a metric, threshold or policy is written into a declaration other people will quote
  - When a build/refactor/bug-fix request arrives with no acceptance criterion
allowed_tools: [read_file, write_file, ls, glob, grep, skill, task]
author: weiping
version: 1.0
params:
  output_path: "where to record settled decisions (default: work/<scope>/grill.md, or docs/adr/<n>-<slug>.md when the answer is an architecture decision)"
---

## Instructions

Interview the user until you reach a shared understanding. Do not implement, plan, or "get started
while they answer" — this skill produces **settled decisions**, and acting early is how a run burns
hours on a definition nobody agreed to.

### Map the decision as a tree, then work it in rounds

Everything you need to settle is a **design tree**: each decision branches into the decisions that
depend on it. The **frontier** is every decision whose prerequisites are already settled — the questions
you can ask *now* without guessing at answers you have not heard.

Ask the whole frontier in one round. Then stop and wait. Each answer reshapes the tree: settled
decisions push the frontier outward and unblock the questions behind them. Recompute and ask the next
round.

A question whose answer depends on another question still open in this round belongs to a **later**
round. Asking it now is how rounds turn into a questionnaire.

### The round format

```
❓ Q1 — <question title>: <question body. Multiple paragraphs are fine; state the options>
➡️ <your recommended answer, and the one-line reason>

❓ Q2 — …
➡️ …
```

Rules for the questions:

- **Word each one so "yes" accepts your recommendation.** Then a user who agrees can answer
  "1 yes, 2 yes, except Q3: use 5%" instead of writing essays.
- **One decision per question.** If it takes "and", it is two questions.
- **Every question carries a recommendation.** A question without a recommendation is you shifting your
  job onto the user.

### Finding facts is your job, never the user's

If a frontier question needs something from the environment — a schema, a column's null rate, whether
the file exists, what the previous build decided — go and find it (`read_file`, `grep`, the skill for
that domain, or a subagent for a long lookup). Never ask a person what you could look up.

A fact you dispatched someone to find is an unsettled prerequisite: only the questions *downstream* of
it wait for the answer. Ask the rest of the frontier now.

**The decisions are the user's.** Put each to them and wait.

### Before you ask, mine what is already written

Read in this order, and use what you find to *delete* questions rather than ask them:

1. `GLOSSARY.md` and `docs/adr/` (if they exist) — a term is usually already defined, or already
   decided the other way.
2. The declaration itself (TTL, `dashboard.json`, the skill, the doc) — many "questions" are answered by
   `answers:` entries or a `# refused:` note.
3. `work/<scope>/` — a previous round's `grill.md`, `questions.json`, `answers.json`.
4. The code path that would change — read it before proposing anything about it.

A question whose answer is in the repository is a research failure, not a question.

### Domains where grilling is mandatory

- **A metric or KPI**: what exactly is counted, over what grain, excluding what, unit and scale, and
  what number the business expects to see. Then: does the data support it at all?
- **A threshold or policy**: who acts on it, and what happens at the boundary.
- **A schema or storage change**: what already exists, what breaks when it moves, who reads it.
- **A build or refactor**: the acceptance criterion — the red test, the gate, or the number that must
  move. "It works" is not one.

### Close the round: write it down

When the frontier is empty, do **not** start the work. Instead:

1. Write the settled decisions to `params.output_path` (default `work/<scope>/grill.md`; use
   `docs/adr/<n>-<slug>.md` when the answer is an architecture decision):
   each decision, its answer, and the one line of reasoning that will let a future reader know **why**.
2. List what was **not** decided on purpose, and what would change your mind.
3. State plainly: *"Frontier empty. Nothing implemented yet. Confirm and I will proceed."*

If the user answers "go ahead", then — and only then — act, and follow the decisions you recorded. If
later work contradicts a recorded decision, stop and grill that delta rather than silently overriding it.

### Refuse to do these

- Ask a question you could have answered by reading the repository.
- Ask more than ~9 questions in one round (that is not a round, it is a form; split the frontier).
- Recommend something you would not defend if asked why.
- Treat a polite "sounds good" on one question as approval of the whole tree.
- Produce a "plan" instead of questions: a plan is what you write *after* the frontier is empty.

### When NOT to use this

- The decision is reversible and cheap: make it, state the assumption, move on.
- The user has already settled the frontier in this conversation: skip to recording it, do not re-ask.
- The task is mechanical and unambiguous ("rename this column in these 4 files").
