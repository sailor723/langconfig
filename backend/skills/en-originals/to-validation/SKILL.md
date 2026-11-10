---
name: Validate Acceptance
description: >-
  Prove that finished work actually met its acceptance criteria, one criterion at a time, with evidence
  from this repository. Use when someone says "done", "finished", "is it working", "validate this",
  "to-validation", or when a build/refactor/fix claims completion and nobody has run the checks. It
  produces PASS / FAIL / PARTIAL / UNVERIFIABLE per criterion, each backed by a command, a file:line or
  a query result — never by the implementer's own summary.
tags: [validation, acceptance-criteria, verification, evidence, gates, review, quality]
triggers:
  - When work is claimed complete and acceptance criteria exist somewhere (a grill.md, a plan, a request)
  - When the user says validate / to-validation / "prove it" / "is it really done"
  - Before an ontology publish, a merge, or a hand-off to another person
  - When a build or agent reports success and you cannot see the evidence in its answer
  - When a criterion was "deferred because the environment does not allow it"
allowed_tools: [read_file, write_file, grep, glob, ls, bash, python_execute, pg_query, sqlite_execute]
author: weiping
version: 1.0
params:
  report_path: "where the report goes (default: work/<scope>/validation.md)"
  baseline: "a command whose output is the PRE-CHANGE state, when 'not worse' is the criterion"
---

## Instructions

You are the check, not the author. Report what the evidence shows; **do not fix anything** in this
skill — a fixer and a validator in one pass is how "looks right" gets written down as "verified".

### Step 0 — Refuse to validate nothing

Validation needs criteria. If the conversation holds no request, plan, spec or `grill.md`, say so and
stop: *"I need the request, the plan file, or the criteria to validate against."* Deriving criteria from
a vague memory of what was asked is guessing with a table around it.

### Step 1 — Find the criteria, in this order

1. **`work/<scope>/grill.md`** — the settled decisions from a grill round. These are the strongest
   kind: somebody already agreed they are the definition of done.
2. **A plan/spec/ticket file** — look for `## Acceptance Criteria`, `## Success Criteria`,
   `## Done when`, `## Validation gate`, and any checklist whose items are phrased as outcomes.
3. **The request itself** — explicit "it should…", "done when…", numbered requirements.
4. **Nowhere** → propose 5–8 criteria across the dimensions (correctness, error paths, integration,
   data, non-functional, explicitly out of scope) and ask the user to accept or edit them. **Do not
   proceed until they answer** — an unaccepted criterion is not a criterion.

Write the criteria down before evaluating anything. A criterion you invent *after* seeing the code is
shaped by the code.

### Step 2 — Evidence that counts, in this repository

Prefer the strongest available, and say which one you used:

| Kind | How, here |
|---|---|
| **A failing-first test** | `backend/tests/test_<name>.py` — the test must *name* the behaviour, not merely pass |
| **A gate** | `scripts/ontology_gates.py` / `features/ontology/gates.json` output: `N checks, 0 failed` |
| **The housekeeping verify bundle** | `./scripts/housekeeping_verify.sh` (guards + tsc + build + store report) |
| **A live HTTP check** | `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/api/...` against the **running** app |
| **A query** | `pg_query` / `.venv/bin/python -c "…"` returning the row count or the value the criterion names |
| **Type/build** | `npx tsc --noEmit`, `npm run build` — exit status, not "no errors seen" |
| **The artefact** | the file exists, contains the declaration, and its `git log` line says when |
| **A baseline diff** | run the suite now and `comm` it against the recorded pre-change failures |

Rules that keep this honest:

- **A command or a citation per criterion.** `file.py:123`, an exit code, a row count, a gate line.
  "Reviewed the code" is not evidence; "read `x.py:40-70`, the branch returns 409 when `busy is not
  None`" is.
- **"Tests pass" is only evidence for the criterion the test names.** A green suite says nothing about
  a behaviour no test exercises — check the test's name and assertion, or mark PARTIAL.
- **Not worse than baseline** is a legitimate verdict — but only with the baseline captured *before*
  the change and the two lists diffed. This repo has 20 pre-existing backend failures; "the suite fails"
  and "the change broke something" are different claims.
- **404 is a FAIL, not UNVERIFIABLE.** A newly introduced endpoint URL that does not resolve is the
  single most expensive "looks fine" there is: the tool call fails silently at runtime.
- **Deferring an executable surface needs a structural probe.** If a criterion is deferred because it
  needs a live service or a human step, still (a) import/compile it, (b) run it up to its first external
  dependency, (c) check the wiring (route registered? env var read? path exists?). Skipping those makes
  the verdict PARTIAL, never UNVERIFIABLE — and "covered at unit level" never excuses a CLI or endpoint
  that has never been executed once.
- **Never accept the implementer's own summary as the evidence.** Its "done" is a claim about its own
  work; that is exactly what you were asked to check.

### Step 3 — One verdict per criterion

- **PASS** — evidence shows it is met; cite it.
- **FAIL** — evidence shows it is not met, or was skipped; say what is missing.
- **PARTIAL** — some of it is there; say precisely which part.
- **UNVERIFIABLE** — the artefacts cannot answer it; say what *would* answer it. A criterion that can
  never be verified is a criterion that does not exist: surface it instead of hiding it here.

### Step 4 — The report

Write to `params.report_path` (default `work/<scope>/validation.md`) and show the same table in the
answer:

```
## Validation report
Feature: <one line>   Criteria source: <grill.md | plan | request | user-confirmed>   Date: <date>

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | <verbatim criterion> | PASS | `pytest tests/test_x.py::test_y` → 1 passed; asserts 409 on busy build |
| 2 | <verbatim criterion> | FAIL | `api/chat/documents.py:337` declares /upload twice; second handler unreachable |

PASS n · FAIL n · PARTIAL n · UNVERIFIABLE n
Open questions: <criteria that cannot be verified, and what would settle them>
Not checked (on purpose): <anything out of scope, named so nobody assumes it was covered>
```

Then one sentence a human can act on: **ship / do not ship / ship and file N follow-ups** — with the
FAILs named. If any criterion is FAIL, the work is not done; do not soften it into "mostly complete".

### Refuse to do these

- Validate against criteria you invented after reading the code.
- Write PASS for anything you only read rather than ran, when running it was possible.
- Treat a green suite as coverage of a specific behaviour.
- Fold several criteria into one row so the FAIL disappears in an average.
- Fix the code and then validate it in the same breath.
- Say "verified" without the command, file:line, or query that produced the verdict.

### When NOT to use this

- Nobody has claimed completion yet — validate at the end, not continuously.
- The work has no criteria and the user explicitly says "just make it work" — then criteria are the
  first thing to produce (use `Grilling`), not the last.
- You are the implementer being asked to check your own work in the same turn: say that the independent
  pass is missing rather than blessing yourself.
