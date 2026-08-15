# Tools Refactor — DSH-shaped definitions on the compile model

Status: **design + Phase A in progress (2026-08-15)** — see docs/settings-refactor.md
for the sibling settings refactor; REFACTORING.md for the broader cleanup.

## 1. Goal

Refactor the tool system toward the DeepSeek Harness tool model
(`packages/core/tools`: `defineTool`, registry + `toolOrder`, execution pipeline,
Code Mode) **while keeping LangConfig's compile-agent model** — DB rows are the
declarative source, `ToolFactory` compiles them to runnable tools at runtime.

Confirmed decisions:
- Code Mode (`run_code` + generated Python SDK) lands **after** the foundation.
- Output schemas are **declared now, enforced gradually** (string-returning
  built-ins keep working).
- Definition storage: a **JSONB `ToolDefinition`** on `custom_tools` (DSH
  `DefineToolOptions` analog — no column sprawl).

## 2. The current compile pipeline (baseline)

```
deep_agent_templates (config JSON) · custom_tools (code + input_schema) · skills (SKILL.md)
        │  AgentFactory.create_agent()  — the compile step
        │  1 validate → 2 extract → 3 LLM (fallbacks/streaming)
        │  4 ToolLoader (5 categories): native (DB-first via ToolFactory codegen,
        │     legacy fallback for 9 harness tools) · cli · custom (project-scoped)
        │     · memory · rag; + execution-constraint wrap + subagent/save_document
        │  5 prompt build: guardrails → tool-enforcement → role → context
        │     + web-research hints + skill injection (explicit + matcher)
        │  6 middleware/hooks → callbacks → 7 create_agent(...) → CompiledStateGraph
```

Deep-agent path: deepagents SDK + skills staged to sandbox with progressive
disclosure (metadata in prompt, SKILL.md on demand via read_file).

## 3. DSH model vs LangConfig today

| DSH | LangConfig today | Refactor target |
|---|---|---|
| `defineTool` (name/desc/parameters/output/execute/hooks) | row: tool_id/name/desc + input_schema + code | **`ToolDefinition` JSONB** on the row: category, order, section, timeout_ms, is_concurrency_safe, output_schema, guard, presentation |
| Registry + `toolOrder` + scoped layers | ToolLoader ad-hoc lists | **`ToolRegistry`** (Phase B): DB-backed, ordering, per-agent scope |
| Pipeline: validate → guards → execute → normalize → present | validation + exec sandbox; string returns | **Pipeline** (Phase B): guards (approval), timeout, normalization, presentation metadata |
| Code Mode: `run_code` + generated SDK | direct tool calls | **`run_code` + Python SDK generator** (Phase C, opt-in) |
| Ordered per-tool prompt guidance + `tools:sdk` | blunt "MANDATORY tool usage" block | **Ordered guidance + SDK section** (Phase D) |
| Tool packages with Config | tool_type/template_type enums | **Package/category organization** (Phase D) |
| Output schema + render | output_format (string/json/url) | **Output schema declared now, enforced gradually** |

## 4. Phases

### Phase A — ToolDefinition model ✅

- `core/tools/definition.py` — pydantic `ToolDefinition` (category, order,
  section, timeout_ms, is_concurrency_safe, output_schema, guard, presentation).
- Alembic `029_add_tool_definition` — `definition JSON` column (+ backfill
  category from tool_type).
- `ToolFactory.create_tool` — parse the definition, attach it as
  `tool.metadata` (category/order/presentation/output_schema) so the registry
  and future prompt assembly read it uniformly. Timeout/guards declared now,
  enforced in Phase B.
- Seed — `seed_builtin_tools.py` writes a generated definition per built-in
  (category map + order); the 9 legacy tools' `TOOL_REGISTRY` entries gain the
  same fields.
- `api/tools/registry.py` — surface definition fields.

### Phase B — ToolRegistry + execution pipeline ✅

- `core/tools/registry.py` — `ToolRegistry.list_definitions()` (DB + 9 legacy
  merged, ordered by `definition.order`), `resolve_for_agent()` (canonical
  names, aliases, dedupe, ordering), project-scoped rows, `run_code` reserved.
- `core/tools/pipeline.py` — `apply_tool_pipeline(tools)` wraps every compiled
  tool whose definition requests enforcement: **guard.approval** (blocked until
  `ApprovalGate.grant()`), **timeout_ms** (`asyncio.wait_for`), **output_schema**
  (light validation, enforced gradually). Wired into `AgentFactory.create_agent`
  after tool assembly; additive — tools without enforcement pass through.

### Phase C — Code Mode (opt-in)

- `run_code` tool: executes a Python program body; dispatches registry tools
  via a **generated Python SDK** (`await tools.web_search(...)`) from the
  definitions (schemas + docstrings → typed callable stubs). Sub-dispatches
  logged (SSE) but only the curated output enters history. Agent flag
  `code_mode: bool`, off by default; reuses the `python_execute` sandbox.

### Phase D — Prompt assembly + packages

- Ordered per-tool guidance (`toolOrder`, DSH 100–199 band) + optional
  `tools:sdk` section when code-mode.
- Unify skill disclosure (metadata in prompt + on-demand body) across both
  agent paths; organize tools into packages with config (possibly a `tools`
  settings namespace).

### Phase E — UI/API

- Schema-driven tool-definition editor + registry view; split
  `api/tools/routes.py` (1554 L) into a router package.

## 5. Verification

- Phase A: full suite stays green (396+), new definition/compile tests,
  registry surfaces categories, built-ins seeded with definitions.
- Phase B–C: incremental with opt-in flags; the direct-call flow never breaks.
