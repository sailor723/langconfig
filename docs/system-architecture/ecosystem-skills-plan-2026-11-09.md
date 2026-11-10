# Ecosystem skills — the study behind the port

Two upstream skill sets are now in this library, generated rather than pasted: **mattpocock/skills** (the
engineering process half) and **langchain-ai/langchain-skills** (the ecosystem half, which is the part this
repository was missing). This file is the study: what was read, what our workspace already did, what the
official docs say the rules are, what the port changed, and what is still open.

Measured 2026-11-09. Regenerate with `./scripts/import_upstream_skills.py`; verify with
`backend/tests/test_imported_skills.py` (277 checks).

## 1. What was read

| Source | Read | Licence | Why this one |
|---|---|---|---|
| [`mattpocock/skills`](https://github.com/mattpocock/skills) | all **39** `SKILL.md` + **28** support `.md` + 3 non-markdown templates; `plugin.json`, `README`, `skills/deprecated/README`, `SKILL-MECHANICS.md` | MIT | the honest-skill counter-position: small, composable, no process ownership (§1 of the earlier review) |
| [`langchain-ai/langchain-skills`](https://github.com/langchain-ai/langchain-skills) | **22** skills | MIT | the ecosystem layer we were missing: LangChain / LangGraph / Deep Agents rules, written by the vendor |
| [docs.langchain.com](https://docs.langchain.com/oss/python/langchain/agents) | `langchain/agents`, `tools`, `structured-output`, `middleware`, `human-in-the-loop`; `langgraph/persistence`, `interrupts`, `graph-api`, `thinking-in-langgraph`; `deepagents/overview`, `skills`, `backends`, `subagents`, `customization` | — | primary source for the rules quoted below |
| **this repository** | 44 hand-written skills, the loader (`core/skills/loader.py`), the sync (`core/skills/sync.py`), the deep-agent assembly (`services/deepagent_factory/assembly.py`), middleware (`core/middleware/`), the ontology gates, the verification floor | — | what a port must not break |

Upstream's own naming churn is worth noting: **`writing-great-skills` no longer exists** — it was added
2026-06-17 and later replaced by **`writing-for-agents` + `SKILL-MECHANICS.md`**. A skill name is not a
stable API, which is exactly why the port is generated from vendored files with a provenance block: when
upstream renames something, the diff says so.

## 2. What our workspace already had (and what it was missing)

**Had.** 44 hand-written skills; a loader that requires `description` and reads the body as instructions
(`## Instructions` optional); extra frontmatter our UI and agent assembly read (`tags`, `triggers`,
`allowed_tools`, `required_context`, `params`, `version`, `author`); skills staged to a
`FilesystemBackend` (local) or served from `DbBackend` (db mode) by `deepagent_factory/assembly.py`; a
`skill` tool for on-demand reading and `search_skills` for lookup; a real verification floor
(`./scripts/housekeeping_verify.sh`, `tsc`/`vite build`, a backend suite with **20 known failures**); and
gate suites for the ontology work.

**Missing.** Three things, all of which the ecosystem half supplies:

1. **A layer rule.** Nothing in our 44 skills told an agent to decide *which* layer a change belongs to
   before writing agent code — LangChain (`create_agent`), LangGraph (graph/state/checkpointer) or a Deep
   Agents harness (`create_deep_agent`). `lc-ecosystem-primer` does, and it is now the first thing loaded.
2. **A method for state.** LangGraph builds a node's input from its first parameter's annotation; a node
   that reads a field its `State` cannot carry receives an empty state, silently. We had `check_states.py`
   (run by `start.sh`) but no skill explaining the rule — the failure mode is a skill-shaped failure.
3. **Context discipline.** Upstream's own words: skills exist so the agent "gets a summary of the contents
   on startup and discovers and reads the contained files only when relevant". Our skills were written as
   one-shot instructions; several of them (e.g. `sql-analyst` at 334 lines) are read whole every time.

## 3. The ecosystem rules, as the docs state them

Quoted or closely paraphrased from the pages in §1; each is followed by where this repository stands.

| Rule | Source | Our position |
|---|---|---|
| **The stack is layered**: Deep Agents (harness) → LangGraph (runtime) → LangChain (framework) → LangSmith (observability). Higher layers depend on lower ones; you do not need to use lower layers directly. | `deepagents/overview`, `ecosystem-primer` | we use all three: `create_deep_agent` for builder agents, LangGraph for the Studio's generated code, `create_agent` for simple agents |
| **An agent is a loop; a harness is prompt + tools + middleware. "Get the model the right context at the right time."** | `langchain/agents` | `core/middleware/{core,deep,advanced,predicates}.py` is our harness; the skill now says to reach for middleware rather than a bigger prompt |
| **Skills are progressive disclosure**: a summary at startup, the body only when relevant; knowledge lives in files, not in the prompt. | `deepagents/skills` | our loader does this; the port keeps bodies small and moves reference material into support files (e.g. `tdd/tests.md`, `domain-modeling/ADR-FORMAT.md`) |
| **Subagents isolate context.** Long exploration belongs in a fresh-context subagent whose result is a pointer, not a transcript. | `deepagents/subagents`, Matt's `research` / `implement-spec` | our `task` tool exists; the ported skills now say *when* to use it |
| **Durability is a runtime property**: checkpointer + thread id give resumable execution; `interrupt` is how a human approves inside a run. | `langgraph/persistence`, `interrupts` | `langgraph-checkpoint-postgres` is a dependency and chat sessions are thread-scoped; our HITL panel is the UI for it |
| **Structured output is a tool call**, not a parsing trick (`response_format` / provider-native). | `langchain/structured-output` | our agents mostly parse prose; `lc-*` skills now where it matters |
| **Evaluation is a separate discipline** (dataset + grader + trace), not "it looked right". | `eval-engineering` | our closest equivalent is the ontology gate suite — deterministic checks, which is the stronger form |

## 4. What the port did, per upstream set

**mattpocock (36 generated, 3 skipped).** All engineering/productivity/misc skills came across; the three
process skills this repository had already adapted by hand — `grilling`, `to-spec`, `to-tickets` — were
**skipped on purpose**: they are repo-specific (they write to `docs/specs/`, `docs/tickets/`, `work/<scope>/`)
and are covered by tests. `code-review` was **replaced**: Matt's two-axis version (Standards vs Spec,
parallel sub-agents, a fixed-point diff) is materially better than our 63-line checklist, so our text was
kept beside it as `code-review/STANDARDS-CHECKLIST.md`, which the generated skill now names as the Standards
reference. `grill-me` arrives as a two-line router next to `grilling` — upstream's own split, kept.

**langchain-skills (22 generated, `lc-` prefix).** Imported under a prefix so their provenance is visible in
the Skills list and they cannot collide with ours: `lc-ecosystem-primer`, `lc-langchain-fundamentals`,
`lc-langchain-middleware`, `lc-langchain-rag`, `lc-langgraph-fundamentals`, `lc-langgraph-persistence`,
`lc-langgraph-human-in-the-loop`, `lc-langgraph-decision-models`, `lc-langgraph-cli`,
`lc-deep-agents-core`, `lc-deep-agents-memory`, `lc-deep-agents-orchestration`, `lc-eval-engineering`,
`lc-swarm`, `lc-managed-deep-agents`, `lc-langchain-dependencies`, and the four quickstarts.

**What every generated file gained** (`scripts/import_upstream_skills.py`):

- our frontmatter (`tags`, `triggers`, `allowed_tools`, `author`, `version`) — YAML scalars are always
  quoted, because five skills disappeared the first time a description contained `: `;
- our paths (`docs/specs`, `docs/tickets`, `work/<scope>`) instead of `.agents/plans` and an issue tracker;
- our tool names (`read_file`, `write_file`, `edit_file`, `bash`, `grep`, `glob`, `task`, `skill`), and
  upstream's `mcp__server__tool` namespacing translated to the `server_tool` prefix our MCP seam produces;
- a **provenance** block naming the upstream repo + path, and stating what was changed — including that
  `disable-model-invocation` has no equivalent here, rather than emulating it silently;
- a **verification-floor** section naming `./scripts/housekeeping_verify.sh` and the 20-failure baseline, so
  a ported skill cannot invent its own definition of "done".

## 5. What is still open

- **Body quality, not just plumbing.** The transform fixes paths and tool names; it cannot rewrite prose.
  A read-through pass of the highest-value ports is owed: `implement`, `code-review`, `tdd`,
  `domain-modeling`, `diagnosing-bugs`, `triage`, and `lc-ecosystem-primer`.
- **Our own gaps the ecosystem half exposes** (candidates for hand-written skills): LangGraph
  **state-annotation discipline** (we have the checker, not the teaching), **middleware-first** guidance for
  our `core/middleware/`, and **`create_agent` vs `create_deep_agent`** as a decision the Studio should
  make explicitly rather than by template.
- **Upstream's `agents/*.yaml` stubs** are skipped: they are Claude-client configuration, not skill content.
  Recorded here so the omission is a decision, not an accident.
- **Licences**: both upstreams are MIT; `vendor/upstream-skills/README.md` and the licences beside them are
  the record. Each generated file repeats the provenance so a copy that travels alone is still attributed.

## 6. Commands

```bash
./scripts/import_upstream_skills.py --dry-run      # what would be written
./scripts/import_upstream_skills.py                # regenerate all (deterministic)
cd backend && .venv/bin/python -m pytest tests/test_imported_skills.py -q   # 277 checks
cd backend && .venv/bin/python -c "from core.skills.sync import scan_builtin_skills; print(len(list(scan_builtin_skills())))"
```
