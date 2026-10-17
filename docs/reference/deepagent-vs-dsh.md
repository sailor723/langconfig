# DeepAgent vs DeepSeek Harness — study & comparison (2026-08-15)

Companion research reports (full line-cited detail):
- `DEEPAGENTS_RESEARCH.md` (repo root) — LangConfig DeepAgent definition/configuration/runtime build.
- `DSH_AGENT_MODEL_REPORT.md` (repo root) — DeepSeek Harness agent/settings/tools/UI model.

This doc is the distilled comparison and the decision record for building a new DeepAgent.

---

## 1. The two mental models

| | LangConfig DeepAgent | DeepSeek Harness (DSH) |
|---|---|---|
| What an agent IS | A **database row** (`deep_agent_templates.config` JSON) validated by `DeepAgentConfig` Pydantic, compiled at chat time into a LangGraph graph by the `deepagents` SDK | A **live runtime object**: `ReactLoopAgent` + `Session` (append-only event log) sharing one `SessionId`; no persisted agent record |
| Where definitions live | PostgreSQL row + REST CRUD + GUI builder form (`DeepAgentCreator`/`Editor`) | `cordis.yml` boot rows, runtime `ctx.agents.create/resume` with a `setup` window, per-session **agent presets** (dirs mounted into the agent's scoped context) |
| Per-agent config surface | Rich: ~30 fields (`DeepAgentConfig`) — model/prompt/tools/skills/subagents/middleware/guardrails/backend/export | Tiny: `AgentOptions = { provider?, model?, maxTokens? }`; everything else composed by plugins scoped per agent |
| Tools | `custom_tools` DB rows compiled by `ToolFactory` (codegen); declarative `definition` JSONB mirrors DSH's `DefineToolOptions` | `defineTool` typed DSL → `ToolDefinition` in a `ToolRuntime` registry; per-agent scope registration + restrictions |
| Settings | DSH-style engine already ported: namespaces + JSON schemas, `settings_documents` table, revisions, secret redaction, generic describe/mutate | Native: namespaces + schemastery schemas, one document with per-namespace sections, base/user layering, `role('secret')` redaction, revision-conflict writes |
| Execution | LangGraph `astream_events` over a compiled graph; tools run via LangChain's built-in dispatch | Turn/step machine over the session log; tool calls run a **guarded pipeline** (pre-execute → guards → approval → execute → post-execute → finalize → result) |
| History | Dual: `ChatSession.messages` JSON **and** LangGraph checkpointer (drift risk, see gaps) | Single source of truth: the session event log; model history is *derived* (`deriveMessages`) |

---

## 2. What DSH has that LangConfig DeepAgent lacks (candidates to adopt)

Ranked by value-for-effort for a new DeepAgent:

1. **Guarded tool-execution pipeline (approval/timeout/output-schema).** DSH runs every tool
   through pre-execute waterfall → monotonic guards → one-shot approval → execute → post-execute →
   `finalizeContent` → `tools/result`, with `timeoutMs`, `isConcurrencySafe`, and **output JSON
   Schema enforced**. LangConfig's `ToolDefinition` (core/tools/definition.py) already *declares*
   `timeout_ms`, `is_concurrency_safe`, `output_schema`, `guard` — but enforcement is gradual
   (Phase A declared the surface; Phases B–D are incomplete). The tool pipeline
   (`core/tools/pipeline.py`, `ApprovalGate`) exists for the regular-agent path.

2. **Code Mode (`run_code` + generated SDK).** DSH collapses the tool surface to one
   `run_code` transport; the model writes a program calling `tools.name(args)` bindings that
   re-enter the guarded pipeline. LangConfig ported `core/tools/code_mode.py` with a generated
   Python SDK — but it is **regular-agent-only** (`DeepAgentConfig` has no `code_mode` field;
   the key is silently dropped by Pydantic). A new DeepAgent with `code_mode: true` would be
   the first to exercise it on the deep path.

3. **Session-log-as-truth.** DSH's agent memory is one append-only log; replay is
   reconstructable, cold resume works, compaction is pressure-triggered. LangConfig's dual
   storage (`ChatSession.messages` JSON + LangGraph checkpointer) is the acknowledged weak
   spot — worth noting for the new agent, not necessarily fixing now.

4. **Dynamic tool/skill injection** — *see §6 for the corrected finding*. DSH reads its
   tool registry every step; LangChain supports the same via `wrap_model_call` +
   `wrap_tool_call` middleware (per-step `request.tools` re-binding), but LangConfig does
   not wire it. §7 is the concrete plan to close this.

5. **Per-agent scope composition.** DSH mounts preset plugin subtrees into `agent.ctx`;
   everything registers agent-locally and unwinds on disposal. LangConfig's nearest analog is
   per-session agent caching (`session_id:agent_id:updated_at`) — no scoped tool registry.

5. **Waterfall events** (`agent/pre-step`, `agent/request`, `llm/stream`, `tools/*`) as the
   extension mechanism vs LangConfig's middleware instances + LangGraph interrupts.

6. **Credentials seam** — secrets referenced by env-var name, resolved per request, rotated
   keys reach the next request. LangConfig stores wizard-only keys encrypted in settings
   documents; fine for now.

7. **Compaction / spill** — pressure-triggered summarization + tool-result pruning; LangConfig
   has SummarizationMiddleware (the only actually-enforced guardrail) but no tool-result
   spill/prune on the deep path.

## 3. What LangConfig DeepAgent has that DSH lacks (keep)

- **Persisted, user-facing agent record + REST CRUD + builder UI** — the whole product surface.
- **Graph-based workflow authoring** (LangGraph canvas; compiled subagents = workflow graphs).
- **RAG / knowledge** — pgvector document upload/retrieval, graphindex (Neo4j), session docs.
- **Multi-tenant SaaS posture** (projects/vaults/users) vs DSH's local-first harness.
- **Familiar Python/LangChain ecosystem** — `@tool`, LangSmith, third-party integrations.
- **Skills** with progressive disclosure (SkillsMiddleware + DbBackend in db mode) — DSH has
  skills too, but LangConfig's DB-managed skill catalog is product-grade.

## 4. Known DeepAgent gaps surfaced by the study (from `DEEPAGENTS_RESEARCH.md` §E)

| # | Gap | Impact |
|---|---|---|
| 1 | `code_mode` not on `DeepAgentConfig` — deep agents can't enable it | Code Mode is deep-path-unavailable |
| 2 | `use_phase9_graphindex` orphaned (no consumer) | Dead flag |
| 3 | `reasoning_effort` / `modalities` dead (no runtime consumer) | Gemini knobs inert |
| 4 | `skill_router_model` implemented but never invoked | Configured-but-inert |
| 5 | `custom_prompt`/`custom_suffix` dropped by Pydantic (`extra='ignore'`) | Prompt assembly collapses to `system_prompt` |
| 6 | Auto-eviction half-wired (`maybe_evict_result` never called; SDK 0.7.x has no `guardrails=`) | token_limits not enforced |
| 7 | `long_term_memory` no consumer (no `store=` passed) | Inert |
| 8 | `BackendConfig` stored but never consulted at build | User backend settings inert |
| 9 | Middleware enum exceeds implementation (HITL/SUMMARIZATION/TOOL_RETRY raise) | Config entries log errors |
| 10 | Legacy `SubAgentMiddleware`/`TodoListMiddleware` scaffolding; duplicate todo tools possible | Schema pollution |
| 11 | `enable_default_tools` not on `DeepAgentConfig` (hardcoded True on deep path) | Can't opt out of the 35-tool base |
| 12 | `config.tools` vestigial (only native/cli/custom loaded) | Confusing |
| 13 | `context` (RAG) and `user_message` args ignored by deep path | RAG retrieval + skill routing never reach the agent |
| 14 | Harness-profile exclusion registered only when interrupts configured | Duplicate todo/fs tools in schema otherwise |
| 15 | Chat dual-storage drift (`ChatSession.messages` vs checkpointer) | Recovery complexity |
| 16 | `context_operations` never populated | Metrics gap |
| 17 | Fallback quirk: build-None silently swaps in phase9 graphindex agent | Surprising behavior |
| 18 | Export flags ignored by actual export endpoints | Dead config |
| 19 | `use_deepagents=False` legacy normalization shape drift | Model/config drift |

## 5. Decision record — what the new DeepAgent should use

For the next DeepAgent built in LangConfig, adopt DSH-informed choices that are already
available in-tree, and fix the minimal set of gaps that block them:

1. **Model**: use a configured provider from the `models` settings document (deepseek /
   minimax / claude / gemini — whatever key is set); prefer `deepseek` for reliability.
2. **Tools**: start from the **35-tool default set** (already materialized into every agent)
   and curate down; declare a per-tool `definition` (`category`, `order`, `timeout_ms`,
   `is_concurrency_safe`, `output_schema`, `guard`) so the registry/prompt assembly can
   consume them — the DSH-aligned declarative surface.
3. **Code Mode (new)**: add `code_mode` to `DeepAgentConfig` and wire it in
   `DeepAgentFactory.create_deep_agent` (mirror the regular-agent path in
   `core/agents/factory/assembly.py` → `create_run_code_tool`), so the new agent can be the
   first deep agent with `run_code` + the generated Python SDK.
4. **Prompt**: author a focused `system_prompt`; avoid relying on `custom_prompt`/`custom_suffix`
   until gap #5 is fixed (or fix #5 in the same pass: declare the fields on `DeepAgentConfig`
   so the USER→BASE→SUFFIX assembly actually works).
5. **Skills**: use the full-catalog progressive disclosure (no `skill_router_model` until #4
   is wired; no pinning needed).
6. **Guardrails**: keep `interrupts` (HITL) as the enforceable knob; set
   `enable_summarization=True` so SummarizationMiddleware actually compresses; do not rely on
   token_limits/auto_eviction (#6).
7. **Subagents**: only if the task needs delegation; prefer dictionary subagents (compiled
   subagents require workflows).
8. **Backend**: leave `BackendConfig` at defaults (stored but inert, #8); runtime picks
   DbBackend/FilesystemBackend from storage mode + skills automatically.

### Minimal gap fixes to land with the new agent (in priority order)

- **P1**: add `code_mode: bool = False` to `DeepAgentConfig` + wire `run_code` into the deep
  build (gaps #1). This is the DSH-signature capability.
- **P1**: declare `custom_prompt` / `custom_suffix` on `DeepAgentConfig` (or read from the raw
  dict) so prompt assembly honors them (gap #5).
- **P2**: pass `context` (RAG) and `user_message` (skill router) through in the deep path, or
  explicitly log them as unused (gap #13, #4).
- **P2**: register the harness-profile exclusion unconditionally (gap #14) to avoid duplicate
  todo/fs tools in the model schema.
- **P3**: `enable_default_tools` on `DeepAgentConfig` (gap #11).

---

## 6. Dynamic tool/skill injection — corrected finding (verified in code)

**Correction to the earlier claim that dynamic injection is a platform boundary.**
The deepagents/LangChain stack **does** support dynamic tool injection natively;
LangConfig just doesn't wire it. The "kick off" problem is a *wiring* gap, not a
*platform* gap.

### 6.1 Evidence — LangChain `create_agent` middleware contract

`langchain.agents.create_agent` (backend/.venv/.../langchain/agents/factory.py) builds
`request.model.bind_tools(final_tools)` **per model call** (factory.py:1346-1404). The
`ModelRequest.tools` list is mutable, so any middleware can add/remove tools every step:

1. **`wrap_model_call` can add/remove tools per request** — `ModelRequest.tools` is
   re-bound on every step; a middleware mutating it changes what the model sees *this
   turn*. deepagents itself uses this: `_tool_exclusion.py:45-63` filters
   `request.tools`; `filesystem.py:2790+` drops unsupported tools per call.
2. **`wrap_tool_call` executes tools that were never registered in the graph** —
   the `DYNAMIC_TOOL_ERROR_TEMPLATE` (factory.py:115-139) documents it explicitly:
   *"Option 2: Handle dynamic tools in middleware (for tools created at runtime)"*
   (factory.py:130-138). The unknown-tool validation (factory.py:1291-1319) is
   **skipped when `wrap_tool_call` is defined**, so a middleware can receive a tool
   call by name and run it itself (via `handler(request.override(tool=...))`).
3. **`AgentMiddleware.tools`** (middleware/types.py:398) — static middleware-owned
   tools are collected into the ToolNode at build (factory.py:1005, 1056-1067);
   `wrap_tool_call` is the escape hatch for the dynamic ones.

**LangConfig already ships one such middleware — unwired.** `core/middleware/tool_selection.py`
`PermissionBasedToolMiddleware` filters `request.tools` by user role via `@wrap_model_call`
(lines 94-140). No code outside its own module imports it; the deep path never passes it.

### 6.2 Skills — half-supported

- `SkillsMiddleware.before_agent` loads `skills_metadata` into LangGraph state **once per
  session**; later turns skip reload (`if "skills_metadata" in state: return None`,
  deepagents/middleware/skills.py:919-980). The prompt catalog is therefore frozen per
  session **unless the state key is popped**, which makes the next `before_agent` re-list
  from the backend.
- The native `skill` tool reads the in-memory `SkillRegistry` cache
  (native_impl.py:1914-1945 → core/skills/registry.py:190-196). The API route
  `POST /api/skills` updates that cache via `registry.create_skill`; the native
  `create_skill` tool (native_impl.py:2103-2148) writes only the DB row and does **not**
  refresh the in-memory cache — so even the `skill` tool can't see a new skill in the same
  process until `initialize()`/`reload_all()` re-runs.

### 6.3 What this unlocks vs DSH

| Capability | DSH (native) | LangConfig after plan |
|---|---|---|
| Create a skill, use it this turn | live catalog read per step | write-through registry + state pop → same-turn |
| New skill appears in prompt without restart | live catalog read per step | `LiveSkillsMiddleware` pops state on fingerprint change → next turn |
| New *tool* usable without rebuild | registry read per step | `DynamicToolsMiddleware` re-reads DB + appends to `request.tools` → **same step**, matching DSH |

The earlier "LangGraph cannot gain a new tool mid-session" boundary was wrong: the
per-step `bind_tools` + `wrap_tool_call` contract is the LangChain-native equivalent of
DSH's live registry. The remaining difference is only that DSH reads the registry
implicitly every step while LangChain needs an explicit middleware to re-materialize.

---

## 7. Change plan — dynamic tool/skill injection (P0, design only)

Land this before or with the new DeepAgent. It makes DSH-grade dynamic injection work on
the existing middleware contract — no platform fork, no deepagents fork.

### 7.1 `DynamicToolsMiddleware` (new: `core/middleware/dynamic_tools.py`)

Goal: the model can call a **custom tool created/edited mid-session**, same turn.

```python
class DynamicToolsMiddleware(AgentMiddleware):
    # before each model call:
    #   1. fingerprint = max(custom_tools.updated_at)  (cheap DB query, cached ~2s)
    #   2. if fingerprint changed since last build: re-load custom_tool rows via
    #      ToolLoader.load_custom / ToolFactory.create_tool for the agent's ids
    #   3. append newly-added / replace edited tools in request.tools
    def wrap_model_call(self, request, handler):
        fresh = self._refresh_if_changed()
        if fresh is not None:
            merged = {t.name: t for t in request.tools}
            merged.update({t.name: t for t in fresh})
            request.tools = list(merged.values())
        return handler(request)

    # execute tool calls whose name is not in the ToolNode (dynamic tools):
    def wrap_tool_call(self, request, handler):
        if request.tool_call["name"] in self._dynamic_tools:
            tool = self._dynamic_tools[request.tool_call["name"]]
            return handler(request.override(tool=tool))
        return handler(request)
```

- Reads the same `custom_tools` rows `ToolLoader.load_custom` already uses; reuse the
  scope filter (`_custom_tool_scope_filter`, core/agents/tool_loader.py:49-64).
- Wire into `DeepAgentFactory.create_deep_agent` middleware list (factory/assembly.py)
  and the regular-agent path (`core/agents/factory/assembly.py`).
- **Fingerprint cache**: a module-level `(fingerprint, tools)` with a short TTL (e.g.
  2 s) avoids a DB hit per turn; `create_tool`/`update_tool`/`delete_tool` endpoints can
  bump it eagerly via a helper (same pattern as the agent-cache `updated_at` key).

### 7.2 `LiveSkillsMiddleware` (new: `core/middleware/live_skills.py`)

Goal: skills created/edited mid-session appear in the agent's prompt catalog next turn.

```python
class LiveSkillsMiddleware(AgentMiddleware):
    # fingerprint = max(skills.updated_at); when changed:
    #   - pop "skills_metadata" (and "skills_load_errors") from LangGraph state via
    #     the before_model/after_model hook + Command(update=...) so the SDK's
    #     SkillsMiddleware.before_agent re-lists from the backend next turn
    def after_model(self, state, runtime):
        if self._skills_changed():
            return {"skills_metadata": [], "skills_load_errors": []}  # forces reload
```

- Sits **after** the SDK's `SkillsMiddleware` in the stack so it runs per turn and can
  clear the cached catalog. On the next turn `before_agent` sees no `skills_metadata`
  and re-lists from the backend (db mode: DbBackend → storage; ensure storage re-staged
  or made read-through so new DB rows are visible — see 7.3).

### 7.3 Skill write-through (small fixes)

1. Native `create_skill`/`update_skill`/`delete_skill` (native_impl.py:2103+) should call
   `SkillRegistry` (like `POST /api/skills` does) instead of raw `db.add` — so the
   in-memory `_skills` cache is refreshed and the `skill` tool returns the new skill
   **same turn**.
2. db-mode skill staging (`_stage_skill_catalog`, factory/assembly.py:88-111) should
   re-persist changed rows to storage when the fingerprint changes (or serve `/skills/`
   read-through from the `skills` table), so `LiveSkillsMiddleware`'s reload actually
   sees new rows.

### 7.4 Wiring checklist

| File | Change |
|---|---|
| `core/middleware/dynamic_tools.py` | new middleware (7.1) |
| `core/middleware/live_skills.py` | new middleware (7.2) |
| `services/deepagent_factory/assembly.py` | append both to `middleware_instances` before `create_deep_agent` |
| `core/agents/factory/assembly.py` | append both to regular-agent middleware list |
| `tools/native_impl.py` | `create_skill`/`update_skill`/`delete_skill` → registry write-through (7.3.1) |
| `core/tools/defaults.py` / `api/tools/routes.py` | optional: expose fingerprint helper + eager bump on tool CRUD |
| `api/chat/messages.py` | no change required (per-step middleware is inside the cached graph) |

### 7.5 Verification (manual + test)

- Create a custom tool via UI mid-session → next turn the agent's schema includes it and
  it can call it (`wrap_tool_call` path proves ToolNode-less execution).
- `create_skill` via agent → same turn `skill()` returns it; next turn the prompt catalog
  lists it (state-pop path).
- Existing chat audit (start→stream→end) stays green for all 34 agents.

---

*Research sources: `DEEPAGENTS_RESEARCH.md` (LangConfig), `DSH_AGENT_MODEL_REPORT.md` (DSH),
plus `docs/tools-refactor.md` and `docs/settings-refactor.md` for the already-ported DSH seams.*
