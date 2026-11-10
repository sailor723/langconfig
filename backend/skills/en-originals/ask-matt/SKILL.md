---
name: "Ask Matt"
description: "Ask which skill or flow fits your situation. A router over the skills in this repo."
tags:
  - "ask"
  - "matt"
  - "mattpocock"
  - "skills"
triggers:
  - "When asked to you don't remember every skill, so ask"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
  - "task"
  - "skill"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions

> **Provenance.** Adapted from `mattpocock/skills → skills/engineering/ask-matt` (MIT, vendored at `vendor/upstream-skills/mattpocock/skills/engineering/ask-matt/SKILL.md`).
> Changed for this repository: frontmatter fields (`tags` / `triggers` / `allowed_tools` / `author` /
> `version`), path conventions (`docs/specs`, `docs/tickets`, `work/<scope>`), tool names
> (`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`), and a verification floor
> section. Upstream's `disable-model-invocation` has no equivalent here — every skill is discoverable
> through the `skill` tool, so it is dropped rather than emulated.


# Ask Matt

You don't remember every skill, so ask.

Before stating what a skill does or recommending a step be skipped, read that skill's SKILL.md: the summaries here are for orientation only.

A **flow** is a path through the skills. Most paths run along one **main flow**, and two **on-ramps** merge onto it. Everything else is standalone, or a vocabulary layer that runs underneath.

## The main flow: idea → ship

The route most work travels. You have an idea and want it built.

1. **the `grill-with-docs` skill** sharpens the idea by interview. Start here whenever you are **working in a working directory**: it's stateful, retaining what it learns in `GLOSSARY.md` and ADRs. (No working directory? Use the `grill-me` skill instead, covered under Standalone. Both run the same the `grilling` skill primitive; `grill-with-docs` is the one that leaves a paper trail, which makes it the better of the two whenever a repo is there to leave it in.)
2. **Branch: can you settle every question in conversation?** If a question needs a runnable answer (state, business logic, a UI you have to see), detour through a prototype, bridged by **the `handoff` skill** in both directions (a prototype lives in its own directory, which is exactly what the `handoff` skill is for; see Phase boundaries):
   - **the `handoff` skill** out, then open a fresh session against that file,
   - **the `prototype` skill** to answer the question with throwaway code,
   - **the `handoff` skill** back what you learned, and reference it from the original idea thread.
3. **Branch: is this a multi-session build?**
   - **Yes** → **the `to-spec` skill** (turn the thread into a spec), then **the `to-tickets` skill** to split it into tracer-bullet tickets, each declaring its **blocking edges**. Then work the tickets one of two ways:
     - **the `implement` skill** per ticket, **the `clear` skilling context between each one**. On a local tracker that's one file per ticket under `.scratch/<feature>/issues/`, worked blockers-first by hand; on a real tracker the edges become native blocking links, so any ticket whose blockers are done can be grabbed. Each ticket is self-contained, so the last one's context is disposable.
     - **the `implement-spec` skill** for the whole spec in one run. It reads the tickets as a **task graph**, runs implementer subagents across the ready **frontier** in parallel, and lands everything on one **integration branch**. Reach for it when you'd rather orchestrate the build than drive each ticket yourself.
   - **No** → **the `implement` skill** right here, in the same context window.

   Either way, the code gets built by driving **the `tdd` skill** (one red-green slice at a time) and closes out with **the `code-review` skill**, a two-axis review (Standards + Spec) of the diff. the `implement` skill runs both per ticket; the `implement-spec` skill's implementers each drive the `tdd` skill, and it runs one the `code-review` skill over the integration branch. Reach for **the `tdd` skill** on its own when you just want to build a concrete behaviour test-first without a full spec, and **the `code-review` skill** on its own whenever you want to review a branch or PR against a fixed point.

   When the work goes up as a pull request, **the `pr` skill** shapes the body: the smallest visual that shows the change, before/after evidence that it works, and a one-way or two-way door call. It's model-invoked, so the agent reaches for it whenever it writes a PR.

4. **the `retro` skill** closes the loop. After a build, and especially one that went sideways, it looks back over the session and suggests changes to the agent's **environment**, not the code: navigation pointers, automated checks, the coding standards the `code-review` skill enforces, steering files, tooling. Mechanical mistakes become deterministic checks; judgement calls become coding standards. The next build then starts from a better environment.

### Context hygiene

Keep steps 1–3 in **one unbroken context window** (don't compact or clear until after the `to-tickets` skill) so the grilling, spec, and tickets all build on the same thinking. Each the `implement` skill then starts fresh, working from the ticket. Run the `retro` skill in the session it's looking back on, before you clear; after clearing, point it at that session's log instead.

The limit on this is the **[smart zone](https://www.aihero.dev/ai-coding-dictionary/smart-zone)**: the window (~150k tokens on state-of-the-art models) within which the model still reasons sharply. If a session approaches it before the `to-tickets` skill, don't push on degraded; the `compact` skill at the nearest phase boundary and carry on (see Phase boundaries).

## On-ramps

A starting situation that generates work, then merges onto the main flow.

- **Bugs and requests piling up** → **the `triage` skill**. It moves issues through triage roles and produces agent-ready issues, which **the `implement` skill** later picks up.

  Triage is only for issues **you didn't create**: bug reports, incoming feature requests, anything that arrives raw. Tickets that the `to-tickets` skill produced are already agent-ready, so **don't triage them**.

- **Something's broken** → **the `diagnosing-bugs` skill**. For the hard ones: the bug that resists a first glance, the intermittent flake, the regression that crept in between two known-good states. It refuses to theorise until it has a **tight feedback loop** (one command that already goes red on *this* bug), then fixes with a regression test. Once the fix is in, run **the `retro` skill** in the same session to ask what would have prevented the bug; where the real finding is that there's no good seam to lock it down, that's a job for **the `improve-codebase-architecture` skill**.

- **A huge, foggy effort: a greenfield project or a huge feature build, too big for one session** → **the `wayfinder` skill**, the most cognitively demanding flow here. When the way from here to the destination isn't visible yet, it charts a **shared map** of **decision tickets** on `docs/tickets/` and resolves them one at a time, producing **decisions, not deliverables**, until the fog is pushed back and the way is clear. Where **the `grill-with-docs` skill** sharpens an idea you can hold in one session, wayfinder is for the idea you can't, and it's slower and denser, so save it for exactly that, never a well-scoped feature.

  When the map clears, **it hands off, it doesn't build**: merge onto the main flow at **the `to-spec` skill**, which collapses the map's linked decisions into a buildable plan, then the `to-tickets` skill and the `implement` skill as usual. Looping the map straight into the `implement` skill skips that collapse and throws the linked detail away, so go straight to the `implement` skill only when the effort turned out genuinely small.

## Codebase health

Not feature work, just upkeep.

- **the `improve-codebase-architecture` skill** runs whenever you have a spare moment to keep the codebase good for agents to operate in. It surfaces **deepening opportunities**; picking one _generates an idea_ you can take into the main flow at the `grill-with-docs` skill. It's the survey that finds the candidates; **the `codebase-design` skill** (below) is the bench you design the chosen one on.

## Vocabulary underneath

Two model-invoked references that run *beneath* the other skills, each the single source of truth for its vocabulary. Reach for them directly when the **words**, not the process, are the problem; or let the skills above pull them in.

- **the `domain-modeling` skill**: sharpen the project's *domain* language: challenge a fuzzy term, resolve an overloaded word ("account" doing three jobs), record a hard-to-reverse decision as an ADR. It's the active discipline the `grill-with-docs` skill drives to keep `GLOSSARY.md` a clean glossary.
- **the `codebase-design` skill** is the deep-module vocabulary (module, interface, depth, seam, adapter, leverage, locality) for designing a module's *shape*: a lot of behaviour behind a small interface at a clean seam. the `tdd` skill and the `improve-codebase-architecture` skill both speak it.

## Phase boundaries

A **phase** is a chunk of work inside a session: the grilling, the implementation, the QA. At the **boundary** between two of them you have five options, and picking between them is the fuzziest decision in this whole map:

- **Continue**: stay put. Costs nothing, loses nothing.
- **the `clear` skill**: empty the window, when nothing here matters to what's next.
- **the `handoff` skill** writes a portable markdown file. Narrow: only for a **new harness**, a **new directory**, a **colleague**, or forking a side task **mid-phase**. What it buys is portability.
- **Subagent**: send a tightly-scoped task to its own window and get a report back.
- **the `compact` skill** compresses this context and seeds a fresh session with it. The **default**, at the bottom of the tree rather than the first reach.

Read [PHASE-BOUNDARIES.md](PHASE-BOUNDARIES.md) for the ordered tree: the five questions, the reasoning behind each branch, and why the primary-source cost makes **Continue** the one to rule out first. Make the decision **at** a boundary; mid-phase, continue or split the rest into subagents.

## Standalone

Off the main flow entirely.

- **the `grill-me` skill**: the same relentless interview as the `grill-with-docs` skill, but **stateless**: it saves nothing locally and builds no `GLOSSARY.md`. Reach for it when you are **not working in a working directory** (sharpening a plan, a design, a piece of writing, anything with no repo under it). If you are in a working directory, use the `grill-with-docs` skill instead: it runs the same interview and leaves a paper trail, so it is strictly the better one.
- **the `grilling` skill** is the interview primitive itself: rounds, the frontier, facts are the agent's job and decisions are yours. the `grill-me` skill and the `grill-with-docs` skill are the two named ways in, and the `triage` skill, the `wayfinder` skill and the `improve-codebase-architecture` skill all run it internally. Reach for it directly only when you want the interview with no wrapper around it.
- **the `prototype` skill** is a small, throwaway program that answers one design question: does this state model feel right, or what should this UI look like. Throwaway is a constraint on how the code is written, not a promise to destroy it: the answer folds into the real code, and the prototype itself is kept as a **primary source** on a `prototype/<name>` branch out of main, pointed at from the implementation issue. It's the detour in step 2 of the main flow, but reach for it any time a design question is hard to settle on paper.
- **the `research` skill**: delegate reading legwork to a **background agent**: it investigates a question against **primary sources**, then leaves a cited Markdown file in the repo. Keep working while it reads. The file it produces is something to take *into* the main flow at the `grill-with-docs` skill, since research feeds the thinking rather than replacing it.
- **the `to-questionnaire` skill** comes in when the thing blocking you isn't in your head or the codebase but in **someone else's**, and it writes them a questionnaire to fill in. It's the inverse of the `grill-me` skill: instead of interviewing you about the subject, it interviews you about the **send** (who it's going to, what you need back) and aims the questions at the gap. What comes back is material for the `grill-with-docs` skill or the `to-spec` skill.
- **the `wizard` skill** is for the steps only a **human** can take: provisioning infrastructure, setting up credentials or CI secrets, clicking through an unfamiliar third-party dashboard, running a one-off migration or cutover. It generates an interactive bash script that opens each URL, captures each value, and writes it into `.env` and GitHub secrets, so the procedure stops being something you re-explain to an agent every time. Model-invoked, so the agent reaches for it the moment it hits a wall only you can pass. If the agent could just do it itself, it should; this is for where a human is genuinely in the loop.
- **the `wait-what` skill** is the corrective for a message that didn't land. Use it mid-conversation, inside any other skill, and the agent re-pitches what it just said with the context you were missing, in plain English, using the `GLOSSARY.md` vocabulary. It works after the fact; the `grill-with-docs` skill is the upfront cure, because a shared language agreed early is what stops the jargon arriving at all.
- **the `teach` skill**: learn a concept over multiple sessions, using the current directory as a stateful workspace.
- **the `writing-for-agents` skill** is the reference for writing documents agents consume: skills, AGENTS.md, pointed-at docs.

## Precondition

**Skills activity → setup notes**: run before your first engineering flow to configure `docs/tickets/`, triage labels, and doc layout the other skills assume. Custom `docs/tickets/` directories also work.

## This repository's floor

- **Verify with the real commands**, not by eye: `./scripts/housekeeping_verify.sh` (guards + `tsc` +
  `vite build` + a document-store report). Add `--full-suite` for the backend suite.
- **The backend suite has 20 pre-existing failures.** "Not worse than that baseline" is the honest
  criterion; "the tests are green" is not a claim you can make here. Compare with
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  and diff the `FAILED` lines against the recorded baseline.
- **Specs, tickets and notes live in files**: `docs/specs/<slug>.md`, `docs/tickets/NNN-<slug>.md`,
  `work/<scope>/`. A verdict in a chat message is lost by the next turn.
- **Ecosystem layer**: agent code is LangChain (`create_agent`) inside a LangGraph runtime, usually wrapped
  by a Deep Agents harness (`deepagents`). Decide which layer the change belongs to before writing it — the
  `ecosystem-primer` rule — and prefer the highest layer that does the job.
