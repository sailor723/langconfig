# Deep Agents — a three-layer study (library / our code / the LangConfig product)

**Date:** 2026-10-03 · **SDK:** `deepagents` 0.7.1 (installed at `backend/.venv/lib/python3.13/site-packages/deepagents`) · **Backend:** LangConfig @ `main`

This is a working study, not a client deck. It answers three questions in order:

1. **What is a Deep Agent in the library?** — what `create_deep_agent` actually builds, with the exact
   middleware stack, tools, prompt and subagent wiring.
2. **What does LangConfig do with it?** — the 8-argument call our factory makes, the backends we inject,
   the skills plumbing, and the two "harness profile" registrations we add.
3. **What is a Deep Agent as a product here?** — the config model, the API, the editor, the session.

Method note: every runtime claim below was reproduced in-process by intercepting
`deepagents.create_deep_agent` and `deepagents.graph.create_agent` with spies and inspecting the real
`agent_kwargs`, the middleware list handed to LangChain, and the compiled graph's `tools` node, rather than
inferred from source alone. Where a claim is source-only it says so. The probe is kept in-tree so anyone can
re-run it:

```bash
cd backend && .venv/bin/python scripts/inspect_agent_build.py 213 --prompt
```

Companion prior art already in the repo (still worth reading, partly superseded):
`DEEPAGENTS_RESEARCH.md` (2026-08-15), `docs/deepagent-vs-dsh.md` (§4 lists 19 gaps — Part IV.1 below re-checks them).

---

## Part I — the library: what `create_deep_agent` really builds

### I.1 The one-sentence model

> A Deep Agent is **a LangChain `create_agent` graph plus an opinionated middleware stack that supplies
> planning, a virtual filesystem, skills and sub-agents — and nothing else.** The library is a *harness
> assembler*: you hand it a model, tools, a backend and a prompt, and it hands back a compiled graph.

The important consequence: **there is no "DeepAgent" class.** `deepagents` has no agent object of its own.
Everything you think of as "the deep agent" is a middleware instance in a list, plus a system prompt. This
is also the cleanest evidence for the taxonomy in our client briefing — *LangGraph is the runtime,
LangChain the framework, Deep Agents the harness*: the harness is literally a list of middleware plus a
prompt-assembly policy, and the library now ships **per-model harness profiles** as first-class data
(`deepagents/profiles/harness/`).

### I.2 The public entry point

```python
def create_deep_agent(
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict] | None = None,
    *,
    system_prompt: str | SystemMessage | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    subagents: Sequence[SubAgent | CompiledSubAgent | AsyncSubAgent] | None = None,
    skills: list[str] | None = None,
    memory: list[str] | None = None,
    permissions: list[FilesystemPermission] | None = None,
    backend: BackendProtocol | None = None,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    response_format: ... = None, state_schema: ... = None, context_schema: ... = None,
    checkpointer=None, store=None, debug=False, name=None, cache=None,
) -> CompiledStateGraph
```

(`deepagents/graph.py:268-288`.) Package exports are 19 names (`__init__.py:28-48`); note
**`SkillsMiddleware` is not exported at package level** — you must import it from
`deepagents.middleware.skills`.

Also note what is *absent*: there is **no `guardrails=`** (our code logs this at `assembly.py:841`) and no
`history_path_prefix` any more. And the returned graph is force-configured with
`recursion_limit=9999` plus LangSmith metadata (`graph.py:935-943`) — a deep agent effectively cannot run
out of recursion, unlike a regular `create_agent` graph.

### I.3 Assembly order

1. remember the caller's *string* model spec (the only thing that preserves `provider:model` for profile lookup);
2. resolve the model (`BaseChatModel` passes through untouched);
3. resolve + validate the **harness profile** for that model;
4. copy `tools`, rewriting descriptions from the profile;
5. default the backend to `StateBackend()`;
6. process caller `subagents` (dispatch by key: `graph_id` → async, `runnable` → compiled, else declarative);
7. **auto-add a `general-purpose` subagent** unless one exists or the profile disables it;
8. build the main middleware stack (below);
9. append profile `extra_middleware`, prompt caching, `MemoryMiddleware`, `HumanInTheLoopMiddleware`;
10. apply profile `excluded_middleware`, splice caller middleware, apply exclusions again;
11. append `_ToolExclusionMiddleware` if the profile excludes tools;
12. aggregate state schemas, push private-state keys into the `task` tool;
13. assemble the system prompt;
14. call LangChain's `create_agent(...)`;
15. return with forced config.

### I.4 The middleware stack (the whole harness, in order)

| # | Middleware | Condition | What it contributes |
|---|---|---|---|
| 1 | `SkillsMiddleware` | `skills is not None` (**not** truthiness — `skills=[]` still installs it) | the skill catalog in the prompt; **no tools** |
| 2 | `FilesystemMiddleware` | always | 8 tools: `ls read_file write_file edit_file delete glob grep execute` |
| 3 | `SubAgentMiddleware` | any inline subagent (incl. the auto-added one) | the `task` tool |
| 4 | summarization | always | message compression |
| 5 | `PatchToolCallsMiddleware` | always | repairs dangling tool calls |
| — | *caller `middleware=` splices in here* | | |
| 6 | profile `extra_middleware` | profile-driven | e.g. Codex adds `TodoListMiddleware` |
| 7 | prompt-caching middleware | Anthropic always; Bedrock/Fireworks if installed | cache breakpoints |
| 8 | `MemoryMiddleware` | `memory is not None` | AGENTS.md-style long-term instructions |
| 9 | `HumanInTheLoopMiddleware` | merged `interrupt_on` non-empty | approvals |
| 10 | `_ToolExclusionMiddleware` | profile has `excluded_tools` | strips tools from the *model request* |

Measured on a stock build (`model="anthropic:claude-sonnet-4-6"`): exactly
`FilesystemMiddleware, SubAgentMiddleware, SummarizationMiddleware, PatchToolCallsMiddleware,
AnthropicPromptCachingMiddleware`. Our own agents get the same shape **plus `SkillsMiddleware` in front**
(see the stack dump in II.1) — the only hook-bearing graph nodes are
`SkillsMiddleware.before_agent`, `PatchToolCallsMiddleware.before_agent`, `model`, `tools`, because we pass
`middleware=[]` and no `memory=`/`permissions=`, and the other entries work through `wrap_model_call`.

Three traps worth remembering:

- **Caller middleware is not appended last.** It is inserted after the last *core* entry, i.e. *before*
  profile/prompt-caching/memory/HITL.
- **A caller middleware whose `.name` matches a built-in replaces it in place** — silently.
- **`excluded_tools` does not remove a tool from the graph**, only from what the model sees per request.
  A tool-node dump therefore cannot tell you what the model was actually offered.

### I.5 Tools: constructed ≠ visible

`FilesystemMiddleware` builds all eight fs tools unconditionally (`filesystem.py:1474-1487`), then filters
**per request**: without a `SandboxBackendProtocol` backend it strips `execute` from the request
(`filesystem.py:2477-2480`). So on a plain workspace agent the model sees seven fs tools, while the graph's
tool node holds eight. `delete` *is* visible. A stock deep agent therefore offers
`ls read_file write_file edit_file delete glob grep` + `task`.

**`write_todos` is not part of the default stack in 0.7.1.** The only place `TodoListMiddleware` is added is
the OpenAI Codex harness profile (`profiles/harness/_openai_codex.py:77`). Every `write_todos` our agents
have comes from **our own** native tool set — which is why the deep path's planning ability is a LangConfig
feature, not a deepagents one.

### I.6 Sub-agents

A declarative subagent is a dict with required `name`, `description`, `system_prompt` (missing the last one
raises `KeyError` — the TypedDict is not validated) and optional `tools`, `model`, `middleware`, `skills`,
`permissions`, `interrupt_on`, `response_format`. Defaults are inherited from the parent: model, tools
(unless a `tools` key is present at all — `tools=[]` means *no* tools), permissions and `interrupt_on`.

The `task` tool is the dispatcher. It passes the parent state down **minus** `messages`, `todos`,
`structured_response` and middleware-private keys, and starts the child from a single `HumanMessage`.

The auto-added **general-purpose** subagent is the reason a deep agent with zero configured subagents still
has a `task` tool (confirmed in our graph dump for 213). It is *not* a clone of the parent: no
`SubAgentMiddleware` (so no nested delegation), and it inherits caller middleware only when the `.name`
matches one of its own slots.

### I.7 Skills

`skills=[...]` is a list of **source paths relative to the backend root**; later sources win. The middleware:

- loads `SKILL.md` frontmatter once per session in `before_agent` (skipped when `skills_metadata` is already
  in state — the catalog is frozen for the session unless that key is cleared);
- injects `name: description` + `-> Read \`path\` for full instructions` into the system message **per model
  request**;
- registers **no tool at all** — level 2/3 disclosure is ordinary `read_file` on the listed paths, which
  means the filesystem tools must be present or the catalog is advice the model cannot follow.

That last point is the cleanest way to explain progressive disclosure to a client: *level 1 is a line in the
prompt, levels 2 and 3 are just file reads.* LangConfig additionally has a second, DB-driven path
(`skill(skill_id)` native tool) — see finding 11 in Part IV.

Frontmatter is parsed strictly and forgivingly at the same time (SDK `skills.py:395-498`): **only** `name`,
`description`, `license`, `compatibility`, `metadata` and `allowed-tools` are read — everything else
(`tags`, `triggers`, `author`, `version`, …) is **silently dropped**. `name` must equal the directory name
and be lowercase-kebab, but a violation only *warns and loads anyway*; a `description` over 1024 chars is
silently truncated; and `allowed-tools` is rendered into the prompt but **never enforced** — it is metadata,
not a permission system. Skills are de-duplicated by name with **last source winning**, and loaded **once
per session** (the presence check is `if "skills_metadata" in state`, and the comment stresses "even if
empty"), so a skill created mid-conversation does not appear in that thread.

### I.8 Profiles — the "harness" made explicit

Two registries, both process-global, keyed by `provider` or `provider:model`, both **additive (merge, never
replace)**:

- **Provider profiles** act at *model construction* (`init_chat_model` kwargs, e.g. OpenAI's
  `use_responses_api=True`) and are keyed on the **string** spec only — a pre-built model never gets them.
- **Harness profiles** act at *runtime*: `base_system_prompt`, `system_prompt_suffix`,
  `tool_description_overrides`, `excluded_tools`, `excluded_middleware`, `extra_middleware`,
  `general_purpose_subagent`. For a pre-built model the key is derived as
  `f"{provider}:{identifier}"`.

Shipped harness profiles: Anthropic Sonnet 4.6 / Opus 4.7 / Haiku 4.5 (prompt suffixes steering parallel
tool use and reflection), three OpenAI Codex models (suffix **plus** `TodoListMiddleware`), and a large
NVIDIA Nemotron 3 Ultra profile that installs twelve extra middleware (progress budget, tool-call shim,
retry/rate-limit handling, textual tool-call parsing, final-answer guards…).

This is the single best illustration of the "harness" idea: **the same frozen model behaves differently
because the harness around it differs — and here the harness is versioned data, not code you write.**

Two consequences we should internalise:

- `deepseek-chat` has **no** built-in harness profile, so our deep agents get an *empty* base prompt and no
  suffix — 100% of their behaviour comes from our `system_prompt` and our tool list.
- Because the registry is global and additive, *any* `register_harness_profile` call in our process leaks to
  every later agent on the same model. We do this twice per build (finding 5).

### I.9 Backends — where the filesystem actually lives

Every file tool is a thin wrapper over a pluggable backend, and the backend is
**the argument that most changes what an agent can do**. The protocol has no `execute`; that is added by a
separate `SandboxBackendProtocol`, which is exactly the capability the SDK checks per request before
offering the `execute` tool.

| Backend | Where files live | Durability | Pick it when |
|---|---|---|---|
| `StateBackend` | LangGraph state (default) | per-thread, dies with the checkpoint | quick agent, no real files needed |
| `StoreBackend` | LangGraph `BaseStore` | cross-thread, survives sessions | shared long-term file space |
| `FilesystemBackend` | real disk under `root_dir`, virtual-mode confinement, ripgrep-backed `grep` | real files | deliverables must be readable by the host |
| `CompositeBackend` | routes by **path prefix** to sub-backends, everything else to `default` | mixed | skills in one place, output in another (our db mode) |
| `LocalShellBackend` | disk + a shell | real files | the agent must run code (`execute`) |
| `BaseSandbox` / `LangSmithSandbox` | remote sandbox | remote | isolation, remote execution |
| `ContextHubBackend` | a LangSmith Hub repo | remote, versioned | knowledge bundles under version control |

`CompositeBackend` is the one worth understanding precisely, because LangConfig depends on it: a request for
`/skills/builtin/x/SKILL.md` matches the `"/skills/"` route and is served from storage, while
`generated/report.md` falls through to `default` and lands on disk. Only the `default` branch can provide
`execute` — a sandbox capability has to be the default, which is why our ladder puts `LocalShellBackend`
there and never inside `routes`.

Two backend-level traps that matter for us:

- **`execute` on a non-sandbox backend is impossible**, not merely broken: the tool is constructed but
  filtered out of the model request (I.5). There is no "silently errors" path to debug.
- **`LocalShellBackend.max_output_bytes` counts characters but reports bytes** while announcing bytes to
  the model, and its timeout returns `exit_code=124` instead of raising — a caller cannot tell "command
  failed" from "backend refused" without parsing the output string.

Two other backend-level behaviours surface directly in our product:

- **Summarization writes files through the backend.** Each compaction appends the evicted messages to
  `{artifacts_root}/conversation_history/{thread_id}.md` (SDK `summarization.py:1195-1224`), and oversized
  tool results can be offloaded under `/large_tool_results/…`. With our disk-backed workspace those land in
  the agent's folder — so `conversation_history/` appearing in a workspace is expected, not a bug.
- **The summarizer's threshold is model-profile dependent** — and `deepseek-chat` **does** have a profile.
  Measured: `model.profile` = `{max_input_tokens: 1000000, max_output_tokens: 384000, tool_calling: true, …}`,
  so `compute_summarization_defaults(model)` returns `trigger=("fraction", 0.85)`,
  `keep=("fraction", 0.10)` — compaction at ~850k input tokens keeping the last ~100k. The documented
  no-profile fallback (`("tokens", 170000)` / `keep=("messages", 6)`) applies only to models whose `profile`
  lacks an integer `max_input_tokens`; it is **not** what our agents get. Either way our configured 60k
  never applies (finding 2).

LangConfig ships three backends of its own on top of these: `WorkspaceFilesystemBackend` (path re-basing),
`FormatAwareBackend` (multi-format render/extract, Part II.2), and `DbBackend`
(`services/storage/db_backend.py`) — a full `BackendProtocol` implementation over the storage seam, with a
`storage_prefix` so one instance can be mounted under `/skills/`.

---

## Part II — the LangConfig port

### II.1 What LangConfig actually calls (verified, not inferred)

`DeepAgentFactory.create_deep_agent` (`backend/services/deepagent_factory/assembly.py:276`) ultimately makes
exactly one call with **eight** keyword arguments. Captured live for agent 213 (`skill_research_writer`):

```
parameters: ['backend', 'checkpointer', 'middleware', 'model', 'skills', 'subagents', 'system_prompt', 'tools']
model:      ChatDeepSeek("deepseek-chat")  temperature=0.3 max_tokens=4096
tools:      6   web_fetch, skill, web_search, think_tool, write_todos, read_todos
middleware: 0
backend:    FormatAwareBackend → CompositeBackend{default: WorkspaceFilesystemBackend,
                                                  routes: {"/skills/": DbBackend(prefix="skills")}}
skills:     ['/skills/builtin', '/skills/personal']
subagents:  0
checkpointer: None (in the standalone probe; the server passes the Postgres checkpointer)
```

For the richer agent 209 (`skill_research_planner`) the same call carries **28 tools** and **1 dict subagent**:

```
tools:     28 (reasoning_chain … memory_recall)
subagents: [{name: 'research-planner', description: …, system_prompt: …, 'tools': inherit}]
```

Two things follow immediately.

**The stack our build actually produces is 100% SDK-supplied.** Intercepting
`deepagents.graph.create_agent` for agent 213 shows the list handed to LangChain — our `middleware=[]`
contributed nothing:

```
0. SkillsMiddleware                     tools=-
1. FilesystemMiddleware                 tools=['ls','read_file','write_file','edit_file','delete','glob','grep','execute']
2. SubAgentMiddleware                   tools=['task']
3. _DeepAgentsSummarizationMiddleware   name='SummarizationMiddleware'
4. PatchToolCallsMiddleware             tools=-
5. AnthropicPromptCachingMiddleware      (no-ops for non-Anthropic models)
   state_schema = DeepAgentState      tools= kwarg = the 6 configured tools
```

**The editor's tool list is not the runtime tool list.** 209 shows 28 tools in the builder; the compiled
graph's tool node holds **37**: those 28 + the SDK's eight filesystem tools
(`ls read_file write_file edit_file delete glob grep execute`) + `task`. 213 shows 6 and runs **15**.
The gap is entirely SDK-injected middleware, and it is not visible anywhere in the product.

**Prompt assembly is a five-part sandwich**, captured verbatim for 213 (3,821 chars):

| # | Layer | Source |
|---|---|---|
| 1 | Skill declaration (`生成文档…必须先调用 skill 工具加载 skill_id="document-deliverables"…`) | authored in the agent's `system_prompt` |
| 2 | `## Identity` + `## AGENTS.md (embedded)` + `## CLAUDE.md (embedded)` | `build_identity_system_prompt` re-baked per chat (`api/chat/messages.py:405-428`) |
| 3 | First-turn greeting | `first_chat_greeting` (`api/chat/messages.py:454-468`), first message only |
| 4 | `# Web research efficiency` hints | appended by our factory when a search tool is present (`assembly.py:530-546`) |
| 5 | Harness-profile suffix | SDK `_apply_profile_prompt` — **empty for `deepseek-chat`**, since no built-in profile matches |

`## Identity` appears **twice** in the captured prompt (once standalone, once inside the default AGENTS.md
template that `_materialize_agent_docs` seeded into the workspace). That duplication is real prompt budget.

---

### II.2 The backend ladder (the most bespoke part of the port)

The SDK accepts one `backend=` and every file tool routes through it. Our factory picks it in a fixed
ladder (`assembly.py:665-727`), then wraps the winner:

| Condition (in order) | Backend passed | Why |
|---|---|---|
| `storage_mode == "db"` + skills, sandbox on | `CompositeBackend(default=LocalShellBackend, routes={"/skills/": DbBackend})` | shell `execute` stays in the sandbox, skills come from Postgres |
| `storage_mode == "db"` + skills, no sandbox | `CompositeBackend(default=WorkspaceFilesystemBackend, routes={"/skills/": DbBackend})` | agent files must land on **disk** so the Files panel can show them; only `/skills/` lives in storage |
| sandbox only | `LocalShellBackend(root_dir=workspace, timeout=120, max_output_bytes=100000, inherit_env=True)` | gives the `execute` tool |
| skills staged, local mode | `WorkspaceFilesystemBackend(root_dir=staging_root)` | `SkillsMiddleware` needs a listable backend |
| none of the above | SDK default (`StateBackend`, in-memory) | plain chat |

…then, **always**, the result is wrapped in `FormatAwareBackend` (`services/format_backend.py:46`) — our
own `BackendProtocol` adapter that turns the SDK's text-only file tools into document tools:
`write_file("x.docx", markdown)` renders real OOXML via the native renderers, and
`read_file("x.pdf")` extracts text instead of returning bytes. This is the single highest-value extension
in the port: it needs no SDK change and adds no duplicate tool names.

`WorkspaceFilesystemBackend` (`services/workspace_filesystem_backend.py:26`) exists for a second reason:
the SDK's backend is *virtual-mode*, so an agent that writes to the absolute workspace path it learned from
its identity block would otherwise create a nested `<workspace>/Users/…` tree. Our subclass re-bases any
absolute path that falls inside the workspace root.

#### II.2.1 Skills are staged, not enumerated

`_stage_skill_catalog` (`assembly.py:46`) implements the "every agent sees the whole library" Anthropic
pattern. `config.skills` does **not** limit discovery — it only *pins* skills living outside the two global
roots. In db mode the full `skills` table is serialized to storage under canonical keys and served through
`DbBackend`; in local mode both roots are `copytree`d into `<staging>/skills` (`builtin` first so personal
skills win name collisions) and the sources handed to the SDK are `["skills/builtin", "skills"]`.

**On this install (`storage_mode=db`) `config.skills` has no runtime effect at all.** The db branch returns
early (`assembly.py:126`) *before* the pinned-skills block at `:198`, so the "stage out-of-root pins" logic
never runs; the full catalog is served from storage either way. Measured: 42 skills are persisted under
`/skills/builtin/<id>/SKILL.md` and `/skills/personal/<id>/SKILL.md`, both sources handed to
`SkillsMiddleware`, so an agent can read — and `skill(skill_id=…)` can load — any skill in the library
regardless of its pinned list. The remaining consumers of `config.skills` are display-only (the GET merge),
a reverse lookup in `/api/skills`, and the export bundle.

That is why the trace above shows `skills=['/skills/builtin', '/skills/personal']` for *every* agent,
including ones whose `config.skills` is a single entry.

#### II.2.2 Two harness profiles registered on every build

`register_harness_profile` is a **process-global, additive** registry keyed by `provider:model`
(`profiles/harness/harness_profiles.py:937`, merge semantics at `:1194`). Our factory writes to it during
each build:

1. **Always** — `tool_description_overrides=filesystem_tool_descriptions()` (`assembly.py:817-834`), which
   teaches the model that `write_file`/`read_file` handle `.docx/.pdf/.html`. The SDK's own descriptions
   say only "Writes content to a file", so without this the model never learns about the format support.
2. **Only when `guardrails.interrupts` is non-empty** — a profile with
   `excluded_tools = {write_todos, update_todo_status, get_todos, ls, glob, grep, execute, task}`
   (`assembly.py:777-809`). Verified live: after building one such agent the registry for
   `deepseek:deepseek-chat` holds exactly that frozenset.

Finding 5 in Part IV explains why (2) is both latent and mis-scoped.

---

### II.3 What the deep path does **not** get

This is the most counter-intuitive result of the study, and it is worth stating plainly for the deck.

LangConfig has **two unrelated middleware systems**:

- `core/middleware/core.py` — our own `AgentMiddleware` ABC with `before_model` / `after_model` /
  `wrap_model_call` / `wrap_tool_call`, plus `get_default_middleware()` (Timestamp, ProjectContext,
  Logging, QuestionDetection, PermissionBasedTool, ContextBasedTool). Consumed **only** by the regular
  agent path (`core/agents/factory/llm.py:79-103`, passed at `assembly.py:492`).
- `core/middleware/deep.py` — `DeepAgentsMiddlewareFactory`, whose "middleware" classes are **tool
  factories**, not middleware. `TodoListMiddleware.create_tools()` returns three in-memory
  `StructuredTool`s; `FilesystemMiddleware.create_tools()` returns native fs tools + `get_evicted_result`;
  `SubAgentMiddleware.spawn_subagent()` is a stub that literally returns
  `"[Subagent execution would happen here]"` and is skipped by `create_all_tools` anyway
  (`deep.py:523-528`).

So a Deep Agent gets **none** of the six default middleware behaviours — no timestamp stamping, no project
context injection, no permission-based tool filtering, no `QuestionDetection`. Its "middleware" list in the
editor (`todo_list`, `filesystem`, `subagent`) only decides which *tools* get loaded. Both agents traced
here have `middleware: []`, so it contributed nothing at all.

---

## Part III — the product surface: what an agent is to a user

### III.1 The record

An agent is a **row**: `deep_agent_templates` (`backend/models/deep_agent.py:380`), with the model config in
a `config` JSON column validated by `DeepAgentConfig` (~30 fields: `model`, `temperature`, `max_tokens`,
`reasoning_effort`, `modalities`, `system_prompt`, `tools`, `native_tools`, `cli_tools`, `custom_tools`,
`tool_params`, `use_deepagents`, `enable_compiled_subagents`, `use_local_sandbox`, `middleware`,
`subagents`, `backend`, `guardrails`, `skills`, `plugins`, `skill_router_model`,
`disable_memory_middleware`, `interrupt_before/after`, `export_format`, `include_chat_ui`,
`include_docker`), plus DB-level `name`, `category`, `workspace_path`, `agent_docs`, and four **legacy JSON
columns** (`middleware_config`, `subagents_config`, `backend_config`, `guardrails_config`) that duplicate
parts of `config` — the GET response derives them, the editor writes through `config`, so they drift.

`DeepAgentConfig` accepts `custom_prompt` / `custom_suffix`? **No** — they are not declared, so Pydantic
drops them and the two `getattr` branches in `assembly.py:524-527` are dead (gap #5 in Part IV.1).

### III.2 The API (`backend/api/agents/deep_agents.py`, 15 routes)

Router prefix **`/api/deepagents`** (registered `main.py:604`). **No route declares an auth dependency** —
only `Depends(get_db)`.

| Method + path | Purpose |
|---|---|
| `GET /templates` | built-in template list (`core/templates/deep_agent.py`); hardcodes `use_deepagents: True` |
| `POST /` | create; **then** bakes the identity block into `system_prompt` and commits again |
| `GET /` | list (`public_only=True` by default → filters `is_public`); runs `_ensure_deep_agent_config`, which **injects skill subagents** on read (finding 6) |
| `GET /{id}` | fetch one |
| `PUT /{id}` | update (merge); **no identity re-bake** |
| `GET`/`PUT /{id}/agents-md` | read/write `agent_docs`; the PUT does not re-bake the prompt |
| `DELETE /{id}` | `db.delete` — see finding 12 |
| `POST /from-creator` | creates from `/tmp/agent_creator_output.json`; **no frontend caller** |
| `POST /quick-create` | one-shot creation; **no frontend caller** |
| `POST /prompt-preview` | renders USER→BASE/SUFFIX segments (the closest thing to a debugger we have) |
| `PATCH /{id}/prompt` | persists `custom_prompt`/`custom_suffix` into `config` |
| `POST /import` | import a `.langconfig` bundle |
| `GET /{id}/export` | `.langconfig` bundle download |
| `GET /{id}/code` | generates `agent.py`, **writes it to `outputs/exports/<slug>/` with a 0600 `.env`**, returns it |

**`GET /` and `GET /{id}` do not return `workspace_path` or `agent_docs`.** `DeepAgentResponse` declares
`workspace_path` but neither endpoint passes it (`deep_agents.py:596-614`, `:648-663`), and `agent_docs`
is not a field of the response model at all — even though create and update pass `agent_docs=…` and Pydantic
silently drops it. This is the direct cause of mismatch 1 in III.4.

### III.3 The editor (`src/components/layout2/`)

`DeepAgentEditor.tsx` (1,284 lines) + `DeepAgentCreator.tsx` (851) share nine sections defined in
`editorConstants.tsx`:

**Overview · Prompt · Tools · Skills · Subagents · Middleware · Guardrails · Docs · JSON**

with helpers `editorToolsPicker.tsx`, `editorSkillsPicker.tsx`, `editorChatToolbar.tsx` (a live test chat),
`editorJsonSection.tsx` (raw config editing — and the Save payload *is* `jsonEdit`, so it is the only route
to any field the form does not expose). Tools come from `GET /api/tools/registry`; skills from
`GET /api/skills` and are written as `skill_id`s.

| | Fields |
|---|---|
| **Editable** | `model`, `temperature`, `max_tokens`, `system_prompt`, `native_tools`, `custom_tools`, `tool_params`, `skills`, `subagents` (name/description/type/model/prompt/tools/graph_id/database/workflow_id), `guardrails.enable_auto_eviction`/`enable_summarization`/`long_term_memory`/`token_limits.*`, plus ORM `name`, `description`, `category`, `workspace_path`, `agent_docs` |
| **Read-only** | `middleware` (ON/OFF badges), `backend`, `usage_count`, `version`, `is_public` |
| **No UI at all** | `plugins`, `skill_router_model`, `disable_memory_middleware`, `use_local_sandbox`, `enable_compiled_subagents`, `modalities`, `reasoning_effort`, `cli_tools` (consumed but uneditable; the creator zeroes it), `guardrails.interrupts`, `interrupt_before/after`, `export_format`, `include_chat_ui`, `include_docker`, `base_template_id`, `tools` |

Several of the no-UI fields **do** have runtime consumers, so their only set path today is raw JSON or a
script — `use_local_sandbox` (the `execute` tool) and `interrupts` (HITL) are the two that matter most.

**The creator and the model disagree on defaults.** `DeepAgentCreator` sends
`enable_auto_eviction=false`, `enable_summarization=false`, `long_term_memory=true` and
`token_limits={max: 8000, summarization: 4800, eviction: 6400}` (`DeepAgentCreator.tsx:116-119`, `:223-229`),
while `GuardrailsConfig` defaults to `true`/`true`/`false` with `100000/60000/80000`. An agent made in the
Creator therefore gets a **12× smaller** budget than one created through the API, and the three flags it
flips are precisely the three that do nothing (finding 2, 3).

### III.4 Product-level mismatches (the ones a user would actually hit)

1. **Opening an agent and pressing Save silently clears its custom workspace path.** The editor seeds its
   input from `agent.workspace_path` (`DeepAgentEditor.tsx:70`) — which the GET never returns — then sends
   `payload.workspace_path = workspacePath.trim() || null` on every save (`:396`), and `PUT` writes it
   whenever the key is present (`deep_agents.py:733-734`). So the value is destroyed by a no-op save.
2. **The Docs tab always starts blank, and saving it can erase the agent's instructions.** `agent_docs` is
   never returned (III.2), so the Docs editor initialises empty and PUT persists whatever is in the form.
   The regular-agent editor is worse: `AgentEditor.handleSave` always sends `agent_docs: {}`, which `PUT`
   stores as `None` — every save of a regular agent wipes its AGENTS.md / CLAUDE.md.
3. **The Guardrails panel exposes exactly the three knobs that do nothing** (`enable_auto_eviction`,
   `enable_summarization`, `long_term_memory`) plus `token_limits.*` that the SDK ignores in favour of its
   own 170k default (findings 2 and 3).
4. **HITL is unreachable from the UI.** No component writes `guardrails.interrupts`, which is why **0 of 54
   agents** have it set — and therefore why the harness-profile exclusion path (finding 5) has never run.
5. **The Middleware section is not middleware.** Its options (`todo_list`, `filesystem`, `subagent`) map to
   `DeepAgentsMiddlewareFactory.create_all_tools`, i.e. they add or remove *tools*; `subagent` is skipped
   entirely. The six real LangConfig middleware never reach a deep agent (II.3). In the editor the section is
   read-only anyway; only the Creator can toggle it.
6. **Skills are visible but the *declaration* is not.** The picker writes `config.skills`, which only pins
   skills for availability; discovery is catalog-wide. Nothing in the UI writes the sentence that tells the
   model to call `skill(...)` — that sentence had to be hand-authored into the system prompt, which is the
   opposite of the "declare the skill clearly" design goal.
7. **Tool lists lie in both directions.** The editor shows the configured list (6 for 213, 28 for 209); the
   runtime graph carries 15 and 37 with no UI for the injected ones, and `execute` is in the graph but hidden
   from the model on a non-sandbox backend.
8. **An empty tool list means "everything".** An agent deliberately configured with zero tools silently gets
   the ~35-tool default base (`create`/`update` treat falsy as unset, `deep_agents.py:480-482`, `:713-715`;
   `load_agent_tools` hardcodes `enable_default_tools=True`), and there is no field to opt out.
9. **`category` is editable but not updatable.** It is absent from `UpdateDeepAgentRequest`, so PUT drops it
   and only create persists it.
10. **A second consecutive Save in one tab returns 409.** The editor echoes `lock_version` but never
    refreshes it after a PUT, and the global `before_flush` listener bumps it on every update.
11. **`custom_prompt`/`custom_suffix` are stored, re-planted by PUT, previewed — and unusable.** They are not
    `DeepAgentConfig` fields, so the chat path drops them and `assembly.py:524-527` always reads `None`
    (gap #5). The same applies to `mcp_tools`.

### III.5 Sessions, workspace and identity

- A chat is a row in `chat_sessions` (`agent_id`, `project_id`, `session_id`); `session_id` is the LangGraph
  `thread_id` (`messages.py:512/534/1122`), so conversation history is the checkpointer — with
  `ChatSession.messages` kept alongside as a second copy (gap #15). `checkpoint_id` is never written.
- The agent is **project-agnostic**; the binding lives on the session, and every chat re-resolves the
  workspace and **re-bakes the identity block** (`api/chat/messages.py:405-428`). So the same agent in two
  projects writes to two workspaces. `PUT /{id}` does **not** re-bake, so a rename or prompt edit keeps a
  stale `## Identity` until the next message.
- Workspace layout: root + `upload/ generated/ skills/ other/`. Resolution order
  (`services/workspace_manager.py:284-304`): user `workspace_path` → `<base>/{vault_key}/agents/{agent_key}`
  → legacy `<base>/agents/agent_{id}`. Every branch **creates** the directory, and `workspace_path` itself is
  unvalidated even though it becomes the filesystem/sandbox root.
- **The same agent in the same project can resolve to two different folders**: create, import and backfill
  pass `agent_key=None` → `agents/agent_{id}`, while chat passes the name slug → `agents/{name-slug}`
  (`deep_agents.py:515-519` vs `messages.py:418-422`). The folder created at creation time is abandoned, and
  the rename left-behind behaviour noted earlier is the same mechanism.
- Slug rules: `_slugify` keeps CJK (so `agent_vault_key` can be non-ASCII), while the export folder slug is
  ASCII-only — two different alphabets for the same agent.
- `_materialize_agent_docs` writes `agent_docs` into the workspace on every chat and seeds defaults back to
  the DB when empty — this is the mechanism that makes the Docs section work, since MemoryMiddleware does not
  (finding 1).
- Agents are cached per `{session_id}:{agent_id}:{agent_version}`, so a config change takes effect on the
  next message without a restart.
- **Memory is per project, not per agent** (finding 17): the PG-backed `memory_store`/`memory_recall` tools
  are scoped `agent_id=f"task_{task_id}"` with `task_id=0`, so two deep agents in one project share one
  memory namespace. `agent_memories` is empty today, so this is latent.
- Checkpoint cleanup happens only in `POST /api/chat/{session_id}/end` (`session.py:132-139`), which deletes
  the thread's checkpoints; nothing else (not even agent deletion) touches them.

---

## Part IV — verified findings

Severity: **A** = wrong behaviour shipping today, **B** = inert feature / dead code, **C** = cosmetic or
naming. Each was reproduced; evidence is the command or file:line cited.

| # | Sev | Finding | Evidence |
|---|---|---|---|
| 1 | **A** | **MemoryMiddleware never initializes.** `assembly.py:391/400` use `FilesystemBackend`, but the only import of that name is inside the *later* filesystem block (`assembly.py:431`) in the same function → Python makes it a function-local → `UnboundLocalError` on every deep build. Consequence: the project/agent `AGENTS.md` never reaches the model *through this middleware*, and `disable_memory_middleware` is a no-op switch. AGENTS.md content still arrives because the chat path embeds `agent_docs` into the system prompt (layer 2 in II.1). | live stderr on every build: `MemoryMiddleware not available: cannot access local variable 'FilesystemBackend' where it is not associated with a value` |
| 2 | **A** | **Our summarization settings are ignored, and a second, dead summarizer is configured.** We build a `SummarizationMiddleware(model=config.model, trigger=("tokens", 60000), keep=("messages", 20))` (`assembly.py:471-492`) — but pass the model as a **string**, so the SDK/lc resolves it from env and dies on a missing `DEEPSEEK_API_KEY` while our keys live in `settings_documents`. Every build logs the failure and drops it. The SDK's own summarization (installed unconditionally, SDK `graph.py:843`) is configured from the **resolved model instance**, so it uses that model's profile: for `deepseek-chat` (profile `max_input_tokens=1000000`) that is `trigger=("fraction", 0.85)` / `keep=("fraction", 0.10)` — measured, not inferred. Net effect: compaction happens at ~850k tokens keeping the last ~100k, and the 60k/20 shown in the Guardrails panel never applies. | live stderr `1 validation error for ChatDeepSeek …`; `compute_summarization_defaults(ChatDeepSeek("deepseek-chat"))` → `{'trigger': ('fraction', 0.85), 'keep': ('fraction', 0.10)}` |
| 3 | **B** | **Auto-eviction is inert.** `maybe_evict_result` (`core/middleware/deep.py:257`) has no caller anywhere in the repo, so `get_evicted_result` can never return anything and `eviction_threshold` (80,000) does nothing. Same for the whole `guardrails=` surface: deepagents 0.7.x has no such parameter, which our own log now admits (`assembly.py:841-851`). | repo-wide grep; runtime warning |
| 4 | **B** | **`skill_router_model` is configured-but-never-invoked.** `_run_skill_router` (`preflight.py:52`) is referenced only by `scripts/test_skill_router.py`; `create_deep_agent` accepts `user_message` "for skill routing" and never reads it. | grep + `assembly.py:286` docstring vs body |
| 5 | **B** | **The tool-exclusion profile is (a) mis-scoped and (b) currently unreachable.** It is registered only inside `if raw_interrupts:` — and **0 of 54 agents** have non-empty `guardrails.interrupts`, so it has never run in production. When it *does* run it leaks: the registry is global and keyed by model, so from then on **every** deep agent on `deepseek:deepseek-chat` in that process has those 8 tool names stripped from its model-visible schema — including agents with no HITL at all. | live registry dump after building one HITL agent; DB query for interrupts |
| 6 | **B** | **`config.skills` subagents are a read-path illusion.** `_merge_skill_subagents` (`api/agents/deep_agents.py:278`) synthesizes one subagent per pinned skill for the GET response; nothing in the factory ever does this. So agent 209 has a `research-planner` subagent that exists only because a GET injected it and a later save persisted it — permanently, and indistinguishable from a user-authored one. The docstring points at "deepagent_factory.py lines 447-456", which no longer exist. | grep for callers; 209's stored config; editor PUTs the array back |
| 7 | **C** | **The deepagent "instrumentation" middleware emits nothing.** `InstrumentedFilesystemMiddleware` overrides plain `ls/read_file/write_file/edit_file` methods (`deepagents_instrumentation.py:64-102`), but the SDK's tools call `backend.write(...)` directly (verified in `middleware/filesystem.py:1755-1800`), never `self.write_file`. `InstrumentedSubAgentMiddleware` and `TodoListTracker` are never instantiated at all (`create_todo_tracker` is imported at `assembly.py:373` and unused). The path-sanitisation "SECURITY" block inside `write_file` is therefore dead too — harmless today, but it would rewrite any path containing `Users` to `outputs/<filename>` if it ever went live. | greps + SDK tool-factory source |
| 8 | **C** | **Our stale SDK assumptions are now wrong.** `assembly.py:496-498` asserts "the deepagents library does NOT auto-create SubAgentMiddleware"; in 0.7.1 it does — every deep agent gets an auto-added **general-purpose** subagent and a `task` tool even with `subagents=None` (SDK `graph.py:750-814`). Same file at `:609-611` claims we must drop duplicate fs tools "because the SDK always injects its own" — true, but then it also drops tools that the SDK *filters per request* rather than removes. | SDK source + graph node dump showing `task` with 0 configured subagents |
| 9 | **C** | **`execute` is always constructed, never usable without a sandbox.** It appears in the compiled tool node for a plain workspace agent; the SDK strips it from the *model's* schema per request when the backend lacks `SandboxBackendProtocol` (SDK `filesystem.py:2477-2480`), so the tool-node dump overstates what the model sees by exactly one. Our HITL profile excludes it explicitly, which is redundant. | node dump + SDK source |
| 10 | **B** | **`DynamicToolMiddleware` exists, unwired.** Implemented from `docs/deepagent-vs-dsh.md` §7.1 and covered by its own test, but imported by nothing outside `tests/`. `live_skills.py` from the same plan was never written. | grep for importers |
| 11 | **C** | **Two parallel skill mechanisms run at once.** Every agent with `skill` in `native_tools` gets our native `skill(skill_id)` tool, which reads the DB-backed `SkillRegistry` (`tools/native_impl.py:2133`); simultaneously the SDK's `SkillsMiddleware` injects a catalog and tells the model to `read_file` the SKILL.md (the SDK registers **no** skill tool at all). Two routes to the same knowledge, two id spaces (DB `skill_id` vs staged path), and only ours works for a skill created mid-session. | agent 213 runs both; SDK `skills.py` has no `tools` |
| 12 | **C** | **Deleting an agent is half a delete.** `DELETE /api/deepagents/{id}` is a bare `db.delete` (`deep_agents.py:805-821`). Verified non-destructively: it cascade-deletes the agent's `chat_sessions` rows (ORM `cascade="delete,delete-orphan"`), but leaves the LangGraph checkpoints for those threads (`checkpoints`/`checkpoint_blobs`/`checkpoint_writes`; 27 thread ids currently have no session row, an upper bound since workflow runs use the same checkpointer) and leaves the workspace folder and export folder on disk. It can also 500 on the `agent_documents` FK (no `ON DELETE` action) for an agent that produced documents via `save_document`. | delete+flush rollback probe; `checkpoints` vs `chat_sessions` counts |
| 13 | **A** | **`workspace_path` is destroyed by a no-op Save.** `GET /`/`GET /{id}` never return it (`deep_agents.py:596-614`, `:648-663`) although the response model declares it; the editor seeds from `agent.workspace_path` (`DeepAgentEditor.tsx:70`) and PUTs `workspace_path: null` on every save (`:396`), which `PUT` applies whenever the key is present (`:733-734`). Opening an agent with a custom workspace and saving resets it to the default. | verified: response block omits the field; editor sends it unconditionally |
| 14 | **A** | **`agent_docs` is never returned, so the Docs tab is blank and saving it overwrites the real instructions.** `DeepAgentResponse` has no `agent_docs` field while create/update pass it (dropped by `extra="ignore"`). The regular-agent editor always sends `agent_docs: {}` → stored as `None` → **every save of a regular agent erases its AGENTS.md/CLAUDE.md.** | response model vs `:554`/`:761`; `AgentEditor.handleSave` |
| 15 | **B** | **Most of an agent is invisible to the export.** `GET /{id}/code` reads only `model` (default `gpt-4o`), `temperature`, `max_tokens` (4000), `system_prompt`, `native_tools`, `custom_tools`, `skills`, `use_deepagents` — ignoring `subagents`, `middleware`, `backend`, `guardrails`, `tool_params`, `plugins` and all three export flags; `export_format`/`include_chat_ui`/`include_docker` are used nowhere. Both export routes **write files to disk as a GET side effect** (`outputs/exports/<slug>/` + a 0600 `.env`), with no auth. The bundle export likewise carries neither `workspace_path` nor `agent_docs`. | `deep_agents.py:1291-1297`, `:1535`; `_write_export_folder:163-183` |
| 16 | **C** | **No HTTP-level test covers any `/api/deepagents` route.** There is no `TestClient` usage for this router anywhere: create/update merge semantics, the response shape (`agent_docs` dropped, `workspace_path` missing), `category` immutability, `lock_version` behaviour, delete cascade, and the ~500 lines of export codegen are all unpinned. `test_deepagent_fallback.py`, `test_deep_agent_validation.py`, `test_vault_workspace.py`, `test_fs_middleware_dedup.py`, `test_tool_defaults.py`, `test_summarization.py`, `test_middleware*.py` cover the model, the workspace resolver and the factory, not the API. | grep for `TestClient` in `backend/tests/` |
| 22 | **B** | **Skill storage is written but never pruned, so a moved skill leaves a stale shadow that wins.** `_stage_skill_catalog` saves every DB row to storage on every build and deletes nothing. Live instance: `document-deliverables` was moved from the personal root to builtin, but `skills/personal/document-deliverables/SKILL.md` (2,946 B, the pre-move revision with the malformed `triggers:` block and no examples) is still in storage. Because sources are ordered `['/skills/builtin', '/skills/personal']` and `SkillsMiddleware` merges by name with **last source winning** (SDK `skills.py:951-963`, "later sources override earlier ones"), the catalog line the model sees points at the **personal** path and level‑2 loads the **old body** instead of the current builtin one (3,468 B). Full inventory: storage holds 18 builtin + 25 personal dirs vs 18 + 24 DB rows — exactly one stale object and exactly one name duplicated across sources. | catalog dump for 115 (43 entries, `document-deliverables` twice); `DbBackend.ls` vs DB rows; body hashes `20584cf0188d` vs `34604d9845d9` |
| 17 | **A** (latent) | **Memory is scoped per project, not per agent.** The PG-backed memory tools are built as `get_or_create_memory(project_id=…, agent_id=f"task_{task_id}")` (`services/agent_utils.py:625-637`; same construction in `core/agents/tool_loader.py:585`) and the chat path always passes `task_id=0` (`api/chat/messages.py:474/486/1046/1059/1089`). So **every deep agent in a project shares the memory namespace `task_0`** — agent 209's `memory_store` writes would be visible to any other agent in project 1 that has the tools. Not yet observable: `agent_memories` currently holds **0 rows**, which is also why nobody has noticed. Compounding it, `guardrails.long_term_memory` (which the Creator defaults to **true**) has no consumer and the graph is compiled without `store=`. | code path read; `SELECT count(*) FROM agent_memories` = 0 |
| 18 | **B** | **Six writers into `deep_agent_templates`, with different behaviour.** `POST /`, `POST /from-creator`, `POST /quick-create`, `import_agent_bundle`, the `create_deepagent` agent tool, and startup seeding (`core/templates/deep_agent.py:568`). Only `POST /` bakes the identity block with the request's `project_id`; from-creator/quick-create pass `project_id=None`; the meta tool and the seeder never bake identity or `agent_docs` at all, and the meta tool hardcodes `use_deepagents=True` + `minimax-m3` + the default-helper middleware/backend/guardrails that `POST /` never uses. `/from-creator` reads a hardcoded `/tmp/agent_creator_output.json` and deletes it; neither it nor `/quick-create` has a frontend caller. | `deep_agents.py:828/857-859/906`; `tools/native_impl.py:2494-2509` |
| 19 | **C** | **Frontend defects that make working features look broken.** Built-in template tabs pass a **string** id, so `localAgentId` is `null` (`DeepAgentEditor.tsx:78-80`, comment: "template ids are strings until saved"), the toolbar is rendered `saveDisabled={!localAgentId}` (`:1201`) → `disabled={saving \|\| saveDisabled}` (`editorChatToolbar.tsx:269`), and **the create-on-save branch at `:399-417` can never run** — a built-in template can be edited and not saved (and Run is blocked too, `canRun={!!localAgentId}`). `useSidebarData.ts:43/89` calls `listDeepAgents()` with no args → backend default `public_only=true` (`deep_agents.py:567`), so the sidebar hides non-public agents while other callers pass `false`; `ModernStudioPage` hardcodes agent ids 112/69; `useAgentStructure.ts:29-78` fetches `/api/skills/{name}` while the pickers store `skill_id`s, so the Studio visualisation enriches nothing. | cited lines verified directly; `PromptAssemblyPage`/`PromptCanvas`/`SkillBuilderModal` are unreferenced dead code |
| 20 | **A** | **The todo list does not work on any deep agent, and fails with a success message.** The compiled graphs expose 13 state channels and **no `todos`** (verified on 115 and 213), so the native `write_todos` (`tools/native_tools.py:263`, `Command(update={"todos": …})`) has its update **accepted and silently discarded** — proven with a real `ToolNode` on this LangGraph version: the tool reports *"updated to ['a','b']"* while the resulting state holds only `messages`. `read_todos` (`:287`, reads `state["todos"]`) therefore always answers *"No todos currently in the list."* On agent 115 the `todo_list` middleware also registers a **second** `write_todos` (`core/middleware/deep.py:58`, in-memory `self.todos`) and **wins dispatch**, so writes land in a per-instance Python list that `read_todos` cannot see and that dies on every rebuild. Planning — the headline Deep Agents selling point — is inert. | channel dump on 115/213; ToolNode probe; `tools_by_name` description check on 115; full write-up in VI.3 |
| 21 | **C** | **The default AGENTS.md boilerplate misdescribes skills.** `default_agent_docs()` writes "the skill catalog is staged into `skills/`; read SKILL.md files from there" plus a Path map entry `Skills: skills/…` into every agent workspace, but in db mode nothing is staged there — skills are served virtually from `/skills/…` via `DbBackend`, and the workspace `skills/` folder is empty by design. Agent 115 believed the boilerplate, `ls`-ed the empty folder, and then explained its own skill system incorrectly (VI.4/VI.5). | 115's workspace listing (empty `skills/`); the boilerplate text; its session transcript |

### IV.1 Re-check of the 19 gaps recorded on 2026-08-15 (`docs/deepagent-vs-dsh.md` §4)

Still true: **#4** skill_router inert, **#6** auto-eviction half-wired + no `guardrails=`, **#7** no
`store=` passed, **#8** `BackendConfig` stored and never consulted, **#10** legacy middleware scaffolding —
now **proven live on agent 115**, which ships two `write_todos` tools and loses every plan (finding 20),
**#11** `enable_default_tools` hardcoded `True` in `load_agent_tools` (`services/agent_utils.py:595`),
**#12** `config.tools` vestigial (only native/cli/custom load), **#13** `context` and `user_message` ignored
by the deep path, **#14** exclusion registered only under interrupts (plus the new scoping problem),
**#15** dual chat storage, **#18** export flags unused by the export endpoints, **#19** `use_deepagents=False`
normalization drift.

Still true, newly confirmed: **#1** no `code_mode` on `DeepAgentConfig`, **#2** `use_phase9_graphindex`
orphaned, **#3** `reasoning_effort`/`modalities` have no deep-path consumer, **#5**
`custom_prompt`/`custom_suffix` are **not fields** on `DeepAgentConfig`, so Pydantic drops them and
`assembly.py:524-527`'s `getattr` always returns `None` (the code reads as if it worked), **#9** the
middleware enum exceeds its implementation, **#16** `context_operations` unpopulated, **#17** the
build-failure fallback quirk.

Fixed or obsolete since: **#6** is now *partly* documented in-code (the factory logs that guardrails are not
enforced, and the build no longer falls back silently — `assembly.py:870-883` raises instead). Nothing else
in the list appears closed.

### IV.2 What is genuinely good about the port (worth defending in the deck)

- **Format-aware file tools.** No other deepagents consumer in this repo, and not the SDK, renders
  `.docx/.pdf` from Markdown; verified end-to-end earlier with a real 39,284-byte OOXML file.
- **DB-managed skill catalog with progressive disclosure**, served through a custom `BackendProtocol`
  implementation (`services/storage/db_backend.py`) — product-grade, and the reason skills are editable in
  the UI at all.
- **Composite routing that keeps deliverables on disk**, so the Files panel works instead of files vanishing
  into the DB seam (`assembly.py:685-699` — an explicit fix for that bug).
- **Workspace path re-basing** so absolute paths from the identity block do not create nested trees.
- **Compiled subagents from workflow graphs** (`langgraph/tool_adapters.py` + `support.py:190-251`), with
  per-subagent database pinning injected into the state key the graph's tools read via `InjectedState`.
- **Honest failure**: a deep-build failure now raises `RuntimeError` instead of silently degrading to a plain
  agent (`assembly.py:870-883`).

---

## Part V — what pins this, what to fix first, and what it means for the deck

### V.1 What is already pinned by tests (and what is not)

Covered: the config model and its validators (`tests/test_deep_agent_validation.py`), the workspace resolver
and identity re-bake helpers (`test_vault_workspace.py`, `test_agent_workspace.py`), the no-silent-fallback
rule (`test_deepagent_fallback.py`), the default-tool base (`test_tool_defaults.py`), summarization wiring
(`test_summarization.py`), middleware construction (`test_middleware*.py`), the duplicate-filesystem-rule
(`test_fs_middleware_dedup.py`).

Not covered: **any `/api/deepagents` route over HTTP** — no `TestClient` anywhere for this router. That is
why the create/update merge semantics, the response shape (`agent_docs` dropped, `workspace_path` missing
from GET), `category` immutability, `lock_version` behaviour, delete cascade, `_merge_skill_subagents`, and
the ~500 lines of export codegen are all unpinned. Findings 13 and 14 are exactly the class of bug an API
test would have caught on day one.

### V.2 Suggested fix order (cheap → expensive, all independent)

1. **Data-loss pair (findings 13, 14).** Add `agent_docs` and `workspace_path` to `DeepAgentResponse` and
   pass them from both GETs; make the editor only send fields the user actually touched (or have PUT keep
   `workspace_path` when the payload is `None` and the row has a value). Two small diffs remove both
   silent-erasure paths.
2. **MemoryMiddleware (finding 1).** Move the `FilesystemBackend` import to module scope in `assembly.py`
   (or import it inside the memory block). One line; the middleware has presumably never run.
3. **Summarization (finding 2).** Pass the already-resolved `main_chat_model` instead of `config.model`, or
   drop our middleware entirely and accept the SDK's defaults — but then stop showing `token_limits` in the
   UI as if they applied.
4. **Harness-profile hygiene (finding 5).** Stop registering per-agent policy in a global, model-keyed
   registry: either register the exclusion union once at startup and document it, or move the intent to the
   SDK's `permissions=` / `tools=` arguments where it is per-agent.
5. **Instrumentation (finding 7).** Either delete `deepagents_instrumentation.py` or re-implement it as a
   `wrap_tool_call` middleware, which is the only place FS/subagent events can actually be observed.
6. **Delete completeness (finding 12).** Clean checkpoints, workspace and export folders, and guard the
   `agent_documents` FK.
7. **Memory scope (finding 17).** Pass the agent id instead of `task_{task_id}` for chat builds (or accept
   per-project memory deliberately and say so in the UI). Cheap now — the table is empty.
8. **Todo state (finding 20).** Declare a `todos` channel via a `state_schema` (what langchain's
   `TodoListMiddleware` does), and stop shipping two tools with the same name: either use the native
   stateful pair and drop the `todo_list` middleware tool factory, or drop the native pair. Until then the
   model is told a plan was saved when nothing was.

### V.3 The three sentences for the client deck

1. **An agent is a tool list plus a prompt.** In LangConfig, a "DeepAgent" is a database row that becomes a
   `create_agent` graph at chat time. Nothing about the agent exists before that build.
2. **The harness is the product.** `deepagents` ships per-model *harness profiles* — Sonnet gets prompt
   suffixes steering parallel tool use, Codex gets a TODO middleware, Nemotron gets twelve extra middleware.
   Same frozen model, different behaviour, because the harness is versioned data. That is precisely what
   LangConfig is doing for its customers, one level up: choosing tools, skills, subagents and storage per
   agent instead of per model.
3. **The honest caveat: our numbers and the runtime's numbers are not the same numbers.** The editor shows 6
   tools where the graph carries 15; the Guardrails panel shows a 60k token threshold where the SDK applies
   170k; the Docs tab shows an empty file where a real AGENTS.md exists. Deep Agents is a young harness
   (0.7.1, beta profile APIs) and our port has drifted from it in twelve places — all of them listed in
   Part IV, all of them fixable without touching the platform architecture.

### V.4 Open questions / not verified

- Whether the two harness-profile registrations can be scoped per agent (they cannot, as written — the only
  fix is to register the union once, or to stop using the profile registry for per-agent policy).
- Whether `SkillsMiddleware`'s catalog is re-listed after a skill is created mid-session (it caches
  `skills_metadata` in state; `docs/deepagent-vs-dsh.md` §6.2 says no, and `live_skills.py` was the planned
  fix).
- Real token cost of the 36-tool model schema on agent 209 (not measured).
- Whether `AgentEditor`'s `agent_docs: {}` was ever intentional (finding 14) — it looks like a missing
  field, not a decision.

---

## Part VI — case study: agent 115 (`全球股市研究分析师`)

Studied 2026-10-03 because it is the agent that has been *interrogated about the skill system in chat* — it
is a real, long-lived, heavily-configured agent, and it exercises code paths 209/213 do not (non-empty
`middleware`, persisted skill subagents, a non-OpenAI-compatible model, embedded instruction docs).

### VI.1 The record

| | |
|---|---|
| id / name | `115` · `全球股市研究分析师` (Global Equity Research Analyst), category `金融研究`, created 2026-07-01 |
| model | `minimax-m3` — a **DB-registered cloud model** (provider `minimax`, active) → resolves to `ChatOpenAI(model_name="minimax-m3")` against `settings.MINIMAX_API_BASE` = `https://api.minimax.chat/v1` with `minimax_api_key` from settings. Resolution works; the noisy "Supported providers: …" warning during a build comes from the broken summarizer (finding 2), because langchain cannot infer a provider for the *bare string* `minimax-m3` |
| prompt | 13,423 chars / 617 lines: 547 authored (role, workflow, compliance scripts, an 8-section industry methodology, two full report templates) + the auto-appended identity block |
| tools | 28 `native_tools` (incl. `bash`, `python_execute`, `pg_*`, `graphindex_*`, `write_todos`/`read_todos`, `skill`, `save_document`), no CLI/custom tools, no `tool_params` |
| middleware | **non-empty** (rare): `todo_list` + `filesystem` + `subagent`, all enabled |
| skills | `['web-search', 'text-summarizer', 'data-analysis']` pinned; 3 corresponding subagents persisted |
| docs | `agent_docs` = AGENTS.md (2,051 chars) + CLAUDE.md (570 chars) |
| usage | 5 chat sessions, all `is_active=True`, none ever ended; `usage_count` **0**, `last_used_at` NULL |
| workspace | **two of them**, a live instance of finding 27: the creation-time path `outputs/agents/agent_115/` (the folder I first inventoried) is empty and abandoned, while the chat path `outputs/langconfig-test/agents/全球股市研究分析师/` holds the real working tree — `AGENTS.md`, `CLAUDE.md`, `.gitkeep`s and the delivered report. Any inventory that reads only the creation path will wrongly conclude the agent has never produced anything |

Its `system_prompt` still contains the identity block **three times** (once standalone, once inside the
embedded AGENTS.md, once inside CLAUDE.md), and the authored part contains **no skill declaration** at all —
the only skill mentions are generic workspace boilerplate. So 115 is a "pure catalog" agent: it finds skills
through `SkillsMiddleware` metadata, not through a prompt instruction.

### VI.2 What the runtime builds

| Stage | Result |
|---|---|
| `create_deep_agent` kwargs | `backend` = `FormatAwareBackend → CompositeBackend{"/skills/": DbBackend, default: WorkspaceFilesystemBackend}`, `skills=['/skills/builtin','/skills/personal']`, `subagents` = the 3 persisted skill subagents, `middleware=[]` (ours — the instrumented FS copy is dropped for a disk backend) |
| middleware stack | exactly the SDK's six: `SkillsMiddleware, FilesystemMiddleware, SubAgentMiddleware, SummarizationMiddleware, PatchToolCallsMiddleware, AnthropicPromptCachingMiddleware` |
| tools we pass | **32 objects** (28 native + 3 from `todo_list` + `get_evicted_result`; six fs tools from the `filesystem` middleware config are dropped as duplicates) |
| tool entries at `create_agent` | **41** (32 + the SDK's 8 fs tools + `task`) with **40 unique names — `write_todos` is duplicated** |
| model-visible schema | 41 entries, `write_todos` twice (verified by binding the tools and reading the payload) |
| state channels | 13: `messages, files, structured_response, jump_to, skills_metadata, skills_load_errors, _summarization_event` + pregel internals — **note the absence of `todos`** and of `memory_contents` |
| subagent tool surface | each of the 3 skill subagents has no `tools` key → inherits all 32, and runs a copy of the parent's whole prompt |

Two live symptoms visible only on this agent:

- **`get_evicted_result` is offered to the model** (from the `filesystem` middleware config) even though
  `maybe_evict_result` is never called anywhere (finding 3), so it can never return anything.
- **`execute` is in the schema but stripped per request** (no `SandboxBackendProtocol` backend), and
  `write_todos` appears twice — see findings 9 and 20.

### VI.3 The duplicate `write_todos` — and why the todo list does not work anywhere

The dispatch table resolves the duplicated name to the **LangConfig middleware** copy
(`core/middleware/deep.py:58` — description *"Create or update the task list with multiple todo items…"*),
**not** the stateful native one (`tools/native_tools.py:263`, which returns
`Command(update={"todos": …})`). Verified from the compiled graph's `tools_by_name`.

That matters because the two implementations store nothing in the same place:

| Tool | Implementation | Storage | Readable by `read_todos`? |
|---|---|---|---|
| `write_todos` (native, `native_tools.py:263`) | returns `Command(update={"todos": todos})` | **agent state** | yes — *if* the channel existed |
| `write_todos` (middleware, `core/middleware/deep.py:58`) | appends to `self.todos` | **a Python list on the middleware instance** | no |
| `get_todos` / `update_todo_status` (middleware) | read/write `self.todos` | same instance list | n/a |
| `read_todos` (native, `native_tools.py:287`) | `state.get("todos", [])` | agent **state** | — |

And the state channel does not exist: the compiled graphs for 115 **and** 213 (and by the same build path,
every deep agent) expose 13 channels with **no `todos`**. Probe result with a real `ToolNode` on this
LangGraph version: a tool returning `Command(update={"todos": ["a","b"], …})` returns
`ToolMessage: "updated to ['a','b']"` — a success message — while the resulting state contains only
`messages`; the `todos` key is **accepted and silently discarded**.

So:

- **On 115** (and any agent with `todo_list` enabled): the model writes a plan into an in-memory list that
  `read_todos` cannot see, and the plan dies whenever the agent instance is rebuilt (new session, config
  change, cache eviction).
- **On 209/213** (default middleware, native tools): `write_todos` reports success, stores nothing, and
  `read_todos` always answers *"No todos currently in the list."*

Either way, **the "planning" capability that Deep Agents is sold on is inert in this port** — and it fails
silently, with a success message, which is why it has gone unnoticed. The fix is to declare the `todos`
channel (a `state_schema` extension, as langchain's own `TodoListMiddleware` does) and to stop shipping two
tools with the same name.

### VI.4 What 115 told you about skills — and where it was wrong

Asked (in session `c82998cb`) where its skill configuration was and how skills are discovered, 115 answered
at length. **Right:** the two-source layout (`/skills/builtin`, `/skills/personal`), that `ls /skills/` fails
in the shell because the mount is virtual (true — `bash` runs on the host, while `/skills/...` exists only in
the backend), the `read_file("/skills/…/SKILL.md")` route, the `skill(skill_id=…)` route, that the catalog
lives in its system prompt, that `deepagents/middleware/skills.py` is the source of the "Available Skills"
text, and the catalogue inventory itself (it counted 42 skills; the DB holds 42 — 18 builtin, 24 personal).

**Wrong, and instructively so:**

0. **Its own pinned list is decorative.** 115's config does pin three skills
   (`web-search`, `text-summarizer`, `data-analysis`) and the editor renders them as "3/42 selected" — but
   in db mode that list has no runtime effect (II.2.1), and none of the three is what it used. The skill it
   actually loaded, `global-equity-research`, is a **personal** skill reached purely through the
   `SkillsMiddleware` catalog. This is the single clearest demonstration in the repo that **pinning ≠
   enabling**: `config.skills` is a UI/export field for deep agents, while discovery is catalog-wide.

1. It presented **`core/agents/factory/prompting.py::_inject_skills()`** + **`SkillMatcher`** (DeepSeek
   scoring, `min_score=0.6`) as *the* mechanism behind its own disclosure, gated on `enable_skills`. That is
   the **regular-agent** path, and `enable_skills` is not a `DeepAgentConfig` field — for deep agents the
   catalog comes from the SDK's `SkillsMiddleware`. `SkillMatcher` is additionally dead code (its model is
   built from env while keys live in the DB), so the described "real progressive disclosure" scores nothing.
2. It claimed staging "**copies ALL skills into `<workspace>/skills/builtin/`**". In this install
   `storage_mode=db`, so `_stage_skill_catalog` persists skills to **storage** and serves them through
   `DbBackend` at `/skills/…`; nothing is copied into the workspace — 115's own workspace `skills/` folder is
   empty, which is exactly what it had just discovered with `bash` and then explained away.
3. It gave inconsistent counts between answers (18/24 then "20 personal") and listed `sql-analyst` as builtin
   (the DB says `personal`).

The pattern worth remembering: 115 has no schema access, so it reconstructed its own harness by grepping the
repository — correctly for the parts it could read directly, and wrongly where two code paths share a name.
Agent self-description is not evidence; this study's probes are.

### VI.5 A platform bug 115 exposed

The default AGENTS.md/CLAUDE.md boilerplate that `default_agent_docs()` writes into every agent workspace
says:

> **Skills** — the skill catalog is staged into `skills/`; read SKILL.md files from there when a task
> requires a skill.

In db mode that is false — nothing is staged into the workspace, and the correct path is the virtual
`/skills/…`. The boilerplate also appears in the prompt's *Path map* ("Skills: `skills/…`"). This is the
most likely reason 115 believed skills were "copied into the workspace", and it pushes every agent to `ls`
a folder that is empty by design.

### VI.6 Conversation-log review (2026-10-03)

115 has five sessions, all still `is_active=True` (none ever ended, so every thread's checkpoints are still
retained; `usage_count` remains 0). DB timestamps are **UTC while the workspace filenames are local (UTC+8)**,
which is worth remembering before drawing timeline conclusions:

| Session | Local time | Content |
|---|---|---|
| `6a7b57a4` (#54) | Aug 26, 14:44 | intro + workspace status (1 bash) |
| `f9074fa3` (#57) | Oct 3, 11:34 | intro + workspace status (1 bash) |
| `17b84e22` (#58) | Oct 3, 11:35 | empty |
| `dc9c6113` (#59) | Oct 3, 11:35–11:53 | **the US/China market research run** |
| `c82998cb` (#103) | Oct 3, 19:47–20:15 | 12 turns of skills Q&A (55 tool calls) |

**The research run (#59) — the only session that produced a deliverable.** Two user messages ("study last
week US and APAC stock market…", then "…with report for China stock market after national holiday"), and
13 tool calls: **4 `web_search`, 5 `write_file`, 4 `bash`**. The recorded calls show the agent trying the
absolute workspace path with a CJK filename twice, then an ASCII filename three times — **none of those
five produced any file** (no artifact on disk, no nested `Users/…` tree, nothing in DB storage) — before it
fell back to a shell heredoc (`cat > … <<'REPORT_EOF'`), which wrote the 13,527-byte, 229-line report that
is on disk today. So the deliverable exists *in spite of* `write_file`, not because of it. I reproduced the
backend layer afterwards (absolute path, absolute CJK filename, relative path → all three write fine), so
the failure is not in `WorkspaceFilesystemBackend`; the tool-level error text is not in the archived log
(the recorder captures arguments at *tool start*, where `content` is absent, and a checkpointer read of that
thread timed out), so the root cause is still open.

**The skills Q&A (#103) — 55 tool calls, of which exactly 3 touched the skill system:** one
`skill(skill_id="global-equity-research")` and two `read_file` calls of `SKILL.md`
(`/skills/personal/global-equity-research/…`, `/skills/builtin/code-review/…`). The other 52 were `bash`
(42) and `grep` (3) against the repository — it was doing source archaeology, not practising progressive
disclosure. Its own summary of that ("only 3 reads via the progressive disclosure tools", plus a separate
list of skills it "peeked at via shell `sed`") is **accurate**, and its claim that
`SkillsMiddleware` is a deepagents-only feature with no vanilla-LangChain equivalent is **correct**.

**What the log settles about the research run's skills:** _none were used._ There is no `skill` call and no
`SKILL.md` read anywhere in session #59, so the US-market report was produced entirely from the agent's
authored prompt (its AGENTS.md templates, four-dimension weighting, compliance script) plus `web_search`
and a file write. 115's own inference in #103 — "this report was driven by `AGENTS.md`, not by the 3-stage
pipeline" — matches the recorded evidence.

---

## Part VII — the step-by-step build: `skill_research_search` (agent 214)

A deliberately tiny reference agent for the three-skill pipeline, built one capability at a time so each
step can be verified on its own. Not a legacy agent; created 2026-10-03.

### VII.1 Step 1 — one skill, progressive disclosure, chat-only answer

| | |
|---|---|
| id / name | `214` · `skill_research_search`, category `research`, project 1 |
| model | `deepseek-chat`, temp 0.3, max_tokens 4096 |
| configured tools | **3**: `skill`, `web_search`, `web_fetch` (12 dispatchable after SDK injection) |
| pinned skills | **none** — discovery must come from the catalog |
| middleware / subagents | none in step 1 |

Prompt shape (~1.1 KB authored, not 13 KB like 115): role → *"check the catalog; if a skill matches, load it
with `skill` and follow it"* → tools → *"answer in chat only; no files"*.

Verified run (session `#104`, 8 tool calls, 3,626 tokens): **`skill(skill_id="research-execution")` was the
first call**, then 4 `web_search` + 3 `web_fetch`, and a 3,447-char inline answer with 5 sourced bullets and
a `Gaps:` line. No file was written (`generated/` stayed empty). That is requirement 1 and 2 confirmed
end to end — the skill was never named in the prompt.

### VII.2 Step 2 — add the planner phase

Two changes only: a `research-planner` **dictionary subagent** (whose own prompt calls
`skill(skill_id="research-planner")`) and a two-phase main prompt (delegate the plan, then execute it with
whichever skill the catalog says covers execution).

Note there are now **two independent catalogs** at work, both metadata-driven rather than hard-coded:

- the planner is discovered through the **`task` tool's description**, which the SDK renders as
  `- research-planner: Decomposes a broad topic into 4-8 independent, parallelisable sub-queries…`
  (verified in the compiled graph);
- the execution skill is discovered through the **`SkillsMiddleware` catalog** as before.

Verified run (session `#106`, 11 tool calls, 7,315 tokens):

```
[01] task        research-planner     ← delegated planning
[02] skill       research-execution   ← progressive disclosure
[03-10] web_search × 8                ← exactly one per planned sub-query
[11] web_fetch   <a Fraunhofer PDF>
```

Reply: 7,171 chars with `## Plan`, `## Findings`, `## Gaps` and 20 inline URLs; `generated/` still empty.
The plan is not decoration — the eight searches map one-to-one onto the eight sub-queries the planner
returned, so decomposition actually drove execution.

**This arrangement was then rejected** (see VII.2b): it delegates the step that needs the most context —
planning — to the one component that receives only a single description string.

### VII.2b Step 2, revised — plan **inline**, execute **delegated**

The correct division: planning stays in the main workflow (it needs the user's wording, constraints and any
earlier turns), execution is fanned out (it is mechanical and pulls in a lot of raw page text, so isolating
it is the point).

Two enforcement details beyond the prompt wording:

- the executor subagent declares its own `tools` (`skill`, `web_search`, `web_fetch`), so it does **not**
  inherit them;
- the main agent's `native_tools` is reduced to **`["skill"]`** — it has no search tools at all, so
  "you plan, the subagent researches" is structural rather than a request the model may ignore.

Verified at build time: `main tools=: ['skill']` (10 dispatchable after SDK injection) and
`subagent 'research-execution': tools=['web_fetch','skill','web_search']`.

Verified run (session `#108`, 6 logged calls, 7,933 parent tokens):

```
[01] skill       research-planner        ← planning, in the main workflow, via the skill catalog
[02-06] task     research-execution × 5  ← one delegation per sub-query
```

Reply: 7,795 chars, 24 inline URLs, 5 sub-queries planned, `generated/` untouched (the executors have
filesystem tools injected but wrote nothing).

Two costs of the delegation worth knowing before step 3:

- **Subagent internals are invisible in the session log.** The log holds only the six parent calls — the
  executor's own `skill(research-execution)` load and all of its searches never reach
  `chat_sessions.tool_calls`, and `metrics.subagent_spawns` stays `0`. Demo-wise the UI shows *that* work was
  delegated but not *what* it did; that needs `astream_events(..., subgraphs=True)` or per-subagent tracing.
- **The token metric under-counts.** `metrics.total_tokens` = 7,933 reflects the parent only; five executor
  runs (each loading a skill and searching) are not included. Real cost is materially higher than the number
  shown in the UI.

Minor drift: the requested `Gaps:` label was dropped — the model wrote the uncertainty paragraph without the
prefix (content present, label missing). A stricter instruction or a post-check would fix it.

### VII.3 Step 3 options (not yet built)

- **Writer**: add `document-deliverables` so the result becomes a real `.docx/.pdf` — this reintroduces the
  file-writing path, and note that on agent 115 five `write_file` calls produced nothing before a shell
  heredoc succeeded (VI.6), so that path deserves a test of its own.
- **Fan-out width**: 5 `task` calls is 5 executor runs; batching 2-3 sub-queries per call trades context
  isolation for fewer round-trips (and a bigger blob in the parent's history).
- **Known noise to live with**: the SDK still injects 8 filesystem tools + `task` into every deep agent, and
  the workspace AGENTS.md boilerplate still claims skills are staged into `skills/` (finding 21). The
  instruction not to write files is what keeps `generated/` empty.

### VII.4 What actually bounds a deep-research run (measured 2026-10-03)

Asked "is there a limit / max calls for the executor?", the honest answer is that several ceilings exist,
only two of ours are real, and one advertised limit does not exist at all.

| Limit | Value | Where it comes from | Applies to |
|---|---|---|---|
| **Graph recursion limit** | **1000** supersteps | `ANALYSIS_RECURSION_LIMIT=1000` (`.env:103`, `config.py:89`), passed at invoke time (`messages.py:535`, `:1124`) | the whole run, parent and each subagent |
| SDK's own recursion limit | 9999 | SDK `graph.py:935-943` (`.with_config`) | **overridden** by the value above |
| **Number of `task` calls** | **no cap** | — | a plan of 5 → 5 calls; 20 → 20 |
| `web_search` results per call | `max_results=8` (tool default; model may lower it) | `tools/native_impl.py:170` | each search |
| `web_search` retries per query | **3**, then a "HARD STOP" message | `WEB_SEARCH_MAX_RETRIES=3`, `native_impl.py:144-166` | counter is **process-global and keyed by query**, so it survives across sessions in the same server process |
| Web call timeouts | search 15 s, DDG fallback 15 s, Yahoo 10 s, `web_fetch` 10 s (param) | `native_impl.py:235/362/490/616` | each tool call |
| Per-subagent output | `max_tokens=4096` | agent config | caps each executor's report |
| Context ceiling | profile `max_input_tokens=1000000`; compaction at **85 %** keeping the last **10 %** | model profile + SDK summarization defaults | parent and subagent contexts |
| HTTP rate limit | 1000 req/min | `RATE_LIMIT_REQUESTS_PER_MINUTE=1000`, `middleware/rate_limit.py` | API requests, not tool calls |
| ~~Chat wall-clock cap~~ | ~~120 s~~ | `analysis_chat_timeout` is defined, defaulted, i18n'd and exposed in Settings → Runtime… | **no consumer anywhere — the knob is inert** |
| Per-tool `timeout_ms` / guard / output schema | not enforced on the deep path | `apply_tool_pipeline` is called only in `core/agents/factory/assembly.py:337` (regular agents) | deep agents get none of it |

Verified rather than assumed: the graph's own config reads `recursion_limit: 9999`, but invoking it with
`recursion_limit=2` and `=6` produced `GraphRecursionError: Recursion limit of 2/6 reached` — so the
call-time value wins and **1000 is the real ceiling**. Practically, one 5-sub-query run consumed ~7 parent
supersteps and each executor a handful of its own, so 1000 is far above what a research run uses: the
binding constraints in practice are **wall-clock/spend** (nothing stops a run) and the **3-retry search
block per query**, not the recursion limit.

Two consequences for pipeline design:

1. Since nothing bounds wall-clock, the practical guard has to come from the caller (frontend abort) or a
   limit we add ourselves; the Settings knob that looks like it does this is inert.
2. The process-global search-failure counter is shared across every agent and session in a server process,
   so one agent's rate-limit failures can hard-stop the *same query string* for a later run.






