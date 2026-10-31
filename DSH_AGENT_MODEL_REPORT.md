# DeepSeek Harness (DSH): How Agents Are Defined, Configured, and Built

**Scope.** This report documents how the DeepSeek Harness codebase (checked out at
`/Users/weiping/dev/Learn/deepseek-harness`) defines, configures, and builds agents. It is
intended to be compared against LangConfig's DeepAgent model, so every claim carries a
file path + line number. No DSH files were modified.

**Reading guide / primary sources.** The canonical docs are:
`docs/architecture.md`, `docs/agent-lifecycle.md`, `docs/tool-catalog.md`,
`docs/tool-execution-pipeline.md`, `docs/capability-seams.md`, `docs/config-catalog.md`,
and the per-subsystem pages under `docs/subsystems/` (`core.md`, `tools.md`, `session.md`,
`settings.md`). The implementation lives in `packages/`: the agent service is
`packages/core/agent`, the driver is `packages/core/agent-loop`, tools are
`packages/core/tools`, settings are `packages/settings/*`, the LLM seam is
`packages/llm/llm`, sessions are `packages/core/session`, and the web gateway is
`packages/host/apiproxy`. The web GUI itself is not in `apps/web` (that is a 10-line
bootstrap, `apps/web/src/main.ts`) but in the client plugin packages under `packages/client/`.

---

## 0. Executive summary

- DSH is **not** a platform where an "agent" is a database row with a name, system
  prompt, tool list, and model. An agent is a **live runtime object** — one `ReactLoopAgent`
  (the concrete driver) bound one-to-one to one `Session` (an append-only typed event log).
  The pair shares a single `SessionId` (`packages/core/agent/src/runtime-types.ts:64-77`).
- The minimal "agent config" is deliberately tiny: `AgentOptions = { provider?, model?,
  maxTokens? }` (`packages/core/agent/src/runtime-types.ts:24-31`). Everything else that
  shapes an agent — persona/system prompt sections, tools, guardrails, model catalog,
  subagent backends, sandbox policy — is composed by the **Cordis plugin tree**, and can be
  scoped **per agent** through the agent's scoped context (`agent.ctx`).
- "Where agents are defined" has three answers:
  1. **Declaratively in `cordis.yml`** — the `agent-loop` plugin's `agents:` array creates
     agents at boot (`packages/core/agent-loop/src/index.ts:255-272`, `355-381`); the shipped
     base bundle leaves it empty (`packages/bundle/base/cordis.patch.yml:436-439`).
  2. **At runtime on demand** — the web gateway's `session.create` RPC calls
     `ctx.agents.create(...)` with `AgentOptions` resolved from a default model selection and a
     `setup` callback that mounts an **agent preset** into the new agent's scope
     (`packages/host/apiproxy/src/api-proxy.ts:1618-1707`, `1227-1248`).
  3. **Per-session compositions ("agent presets")** — a preset is a directory containing a
     `cordis.yml` (+ code) that is mounted as a plugin subtree *inside* the agent's scoped
     context during the creation "setup window", so tools/prompt sections/restrictions
     register agent-locally and unwind with the agent (`packages/preset/agent-presets/src/mount.ts:332-381`).
- **There is no "compile a declarative agent definition into a runnable object" step.** The
  closest DSH concepts are (a) the `AgentFactory` interface (`createAgent`/`resume`) implemented
  by `AgentLoop` and registered on `ctx.agents` (`packages/core/agent/src/index.ts:183-214`,
  `372-388`), and (b) schema "compilation" in the *tool* DSL (`packages/core/tools/src/schema.ts`),
  which compiles author-facing value schemas to raw JSON Schema — not agent compilation.
- The model of **configuration** is a layered user-settings seam: plugins register a schema
  per **settings namespace**; the resolved value layers schema defaults → the plugin's own
  composition `base` → the user document's section; the wire serves **redacted** descriptors
  (secrets are `role('secret')` schema fields, stripped before crossing the wire) with
  revision-based optimistic concurrency (`packages/settings/settings/src/index.ts`).
- The **tool model** is a first-class `ToolRuntime` registry with `defineTool` (typed args +
  output schema + render), per-agent scoped registration/restriction, a guarded execution
  pipeline (`tools/pre-execute` waterfall → monotonic guards → approval `ask` → `tools/execute`
  around-dispatch → `tools/post-execute` → `finalizeContent` → `tools/result`), plus **Code
  Mode** (`run_code` + generated TypeScript/Python SDK) where the model writes programs that
  call tools through bindings.

---

## A. The DSH agent model: what an agent IS, how it is DEFINED, and where definitions live

### A.1 The `Agent` interface — a live handle over a session

`Agent` is a merge-free public interface (`packages/core/agent/src/runtime-types.ts:64-144`):

```ts
interface Agent {
  readonly id: SessionId            // shared with session
  readonly options: AgentOptions    // provider/model/maxTokens
  readonly session: Session         // append-only event log = source of truth
  readonly inbox: Inbox             // next-turn / next-step pending-message lists
  readonly status: AgentStatus      // 'idle' | 'running'
  readonly ctx: Context             // agent-scoped context (agent.ctx)
  cancel(cause, options?): void
  whenIdle(): Promise<void>
  runMaintenance<T>(task): Promise<T>
  send(message, target, wakeup): void
  followup(message): void
  steer(message): void
  inject(message): void
}
```

Key facts:
- **Agent identity == Session identity.** `Agent.id` is a `SessionId`; the registry entry
  asserts `id === agent.session.id` (`packages/core/agent/src/index.ts:476-478`). There is no
  separate "agent id" — the durable session log is the agent.
- `AgentOptions` is the entire per-agent config surface (`runtime-types.ts:24-31`):
  `provider`, `model`, `maxTokens`. The subsystem doc stresses: *"Dispatch requires `provider`
  and `model` after `agent/request`"* and "persona belongs to system-prompt sections"
  (`docs/subsystems/core.md:157-169`).
- `AgentStatus` is `'idle' | 'running'` (`runtime-types.ts:50`); disposal removes the agent
  from the registry and is not a third status.
- The inbox is an ordered pair of durable pending-message lists (`InboxTarget = 'next-turn' |
  'next-step'`, `runtime-types.ts:10`); `followup` = ordinary turn, `steer` = nearest step,
  `inject` = model-facing context without waking (`runtime-types.ts:117-143`).
- `agent.ctx` is the *agent-scoped context*: `createScope(loopCtx, this)` + `ctx.extend({ agent: this })`
  (`packages/core/agent-loop/src/agent.ts:94-95`). Anything registered through `agent.ctx`
  (scoped tools, prompt sections, variables, restrictions, guards, listeners) is agent-local
  and unwinds on disposal. This is the mechanism that makes one process run many differently
  composed agents.
- Event vocabulary: `agent/created`, `agent/disposed`, `agent/status`, `agent/inbox/*`,
  `agent/session-start`, and the machine extension points `agent/pre-step`,
  `agent/request`, `agent/request-error`, `agent/turn-stopping`, `agent/error`
  (`runtime-types.ts:146-291`). These are *live* events; durable transcript facts are session
  events (`docs/architecture.md:57-61`).

### A.2 `AgentRegistry` (`ctx.agents`) — the live registry

`packages/core/agent/src/index.ts:256-704` (`AgentRegistry extends Service`):
- Holds a `Map<SessionId, AgentEntry>` (line 257), where an entry records the agent, its
  runtime creator-owner (not the durable lineage), and a scope carrier (`index.ts:222-231`).
- **Creation is delegated to a factory**: `setFactory(factory)` registers the
  `AgentFactory` (the loop calls this in its constructor, `agent-loop/src/index.ts:350`);
  `create(options)` and `resume(options)` route through it (`index.ts:405-430`). Throws
  "no agent factory registered (load an agent-loop plugin)" otherwise (`index.ts:217`).
- `register(agent)` inserts an already-built agent and emits `agent/created`
  (`index.ts:450-457`); `enter`/`announce` are the ordered-lifecycle primitives used by the
  async factory (`index.ts:474-576`). Lookups: `get`, `list`, `roots`, `isOwnedBy`
  (`index.ts:583-617`).
- `CreateAgentOptions` (`index.ts:80-133`): caller supplies the single live `sessionId`,
  optional session `meta` (validated `cwd`, `parentSession` fork lineage, `seedLength`,
  `origin: 'subagent'`, `delegationDepth`, `agentPreset`), an optional `seed` replay prefix,
  `agentOptions`, a cancellation `signal`, and a `setup` callback. `ResumeAgentOptions`
  (`index.ts:139-156`) is the persisted-identity counterpart (`resumeSessionId` + setup).
- **The setup window**: `AgentSetup = (agentCtx) => commit? | Promise<...>` (`index.ts:69-71`).
  The factory awaits setup *before publishing either id*, so no observer ever sees a
  half-configured agent; a setup rejection rolls the transaction back (`index.ts:117-132`).
  "Setup composes, it never drives."
- `AgentHandle = { agent, dispose() }` — the disposer is a *capability*: only the creating
  consumer may tear the agent down (`index.ts:158-175`).
- The registry also carries a process-local **initiator** (`AsyncLocalStorage`) that
  attributes a driver chain to one Agent (`currentInitiator()`, `requireInitiator()`,
  `withInitiator()`, `index.ts:309-358`) — used e.g. by the loop so tool executions know
  which agent they belong to (`packages/core/agent-loop/src/tool-calls.ts:67`).

### A.3 The concrete driver: `ReactLoopAgent` (package-internal to `dsh-agent-loop`)

`packages/core/agent-loop/src/agent.ts:64-496`:
- Constructor mints the scope/context, inbox, and phase machine (`agent.ts:80-97`).
- `turn()` opens `turn/start`, claims input, runs `preStep` (`agent/pre-step` waterfall),
  appends entered messages as `user/message`, runs `step()` in a loop, and closes with
  `turn/end` + a `TurnEndReason` (`agent.ts:246-330`).
- `step()` assembles the prompt, streams the model (`llm/stream`), appends
  `assistant/chunk` per chunk and `assistant/message` on completion, then executes tool
  calls through the parallel scheduler (`agent.ts:332-401`).
- `buildRequest()` resolves the provider/model from `AgentOptions` (first request) or the
  logged `request/header` (later), runs the `agent/request` waterfall, snapshots the header,
  and freezes the `GenerateOptions` (`agent.ts:407-495`).
- `preStep()` claims the inbox batch and assembles the prompt through `ctx.systemPrompt`
  (`agent.ts:225-243`).

### A.4 `AgentLoop` — the factory + declarative `agents:` config

`packages/core/agent-loop/src/index.ts:296-711` (`AgentLoop extends Service implements AgentFactory`):
- Plugin `Config` (`index.ts:255-272`): `maxParallelToolCalls?: number` and
  `agents: (AgentOptions & { id, sessionId?, cwd?, resumeSessionId? })[]`.
- The runtime schema (`static Config`, `index.ts:300-311`) validates `id` (required),
  `sessionId`, `provider`, `model`, `maxTokens`, `cwd`, `resumeSessionId`.
- On construction it: registers itself as the factory (`index.ts:350`), installs prompt
  variables `{{provider}}`, `{{model}}`, `{{cwd}}` (`index.ts:351-353`), and creates/resumes
  each configured agent (`index.ts:355-381`): fresh combined id `session-<uuid>` when no
  identity is given, `restoreOrCreateConfigured` when persistence is present, `resumeWith`
  for `resumeSessionId`.
- Public entry points: `create(id, options, meta)` (`index.ts:589`),
  `createAgent(ownerCtx, options)` (`index.ts:606`), `resume(ownerCtx, options)`
  (`index.ts:653`). The lifecycle is rollback-covered: `prepare()` mints the driver, the
  abort fuses caller-cancel/owner-unload/factory-teardown, and `publish()` enters sessions +
  agents, announces, fires `agent/session-start`, then starts the machine
  (`index.ts:459-578`).
- It also registers a settings namespace `agent-loop` exposing `maxParallelToolCalls`
  (`index.ts:237-252`, `335-345`) — an example of the settings pattern (section B).

### A.5 Where "agent definitions" live — three layers

1. **Boot-time declarative rows (`cordis.yml`)** — the `agent-loop` `agents:` array. The
   shipped base bundle defines none (`packages/bundle/base/cordis.patch.yml:436-439`:
   `agents: []`), because Web creates sessions on client request; raw overlays may add rows.
   Each row is `{ id, provider, model, maxTokens?, cwd?, sessionId? | resumeSessionId? }`.

2. **Runtime-created agents (the web path)** — `session.create` → `ensureSession()`
   (`packages/host/apiproxy/src/api-proxy.ts:1618-1707`): resolves or creates the agent with
   `agentOptions()` = `defaults.defaultModelSelection()` (`api-proxy.ts:1112-1115`), and a
   `setup` built by `composeAgent()` (`api-proxy.ts:1227-1248`) that (a) installs the
   session-local model selection and (b) mounts the resolved **agent preset** into
   `agentCtx`. `meta.agentPreset` is recorded on the durable `SessionHeader`
   (`packages/core/session/src/types.ts:98`).

3. **Agent presets (`dsh-agent-presets`)** — the closest thing to "agent templates":
   - Config (`packages/preset/agent-presets/src/preset.ts:52-203`): `default` preset id,
     `roots: PresetRoot[]` (dirs scanned for preset subdirectories, each with `trust:
     'system' | 'user'`), `includeUserRoot` (adds `~/.dsh/presets`).
   - `ctx.agentPresets` (`docs/subsystems/core.md:382-459`): `list()`, `resolve()`,
     `mount(agentCtx, id)` — mounts one preset's `cordis.yml` as a plugin subtree *under the
     agent's scope* so every registration files into that agent's layer and unwinds with it;
     `composeFrom(agentCtx, parentCtx)` lets a child join the parent's exact standing
     composition; a preset that never activates, or that publishes a service into the root
     realm, fails the mount loudly (`packages/preset/agent-presets/src/mount.ts:332-381`).
   - A preset is essentially a **per-session capability set**: tools, prompt sections,
     persona, plan-mode policy, model routing rows. It is edited as files (the GUI copies
     presets or authors them in conversation — see section E).
   - The default preset is stored in the `agent-presets` settings namespace's `default`
     field (`packages/client/ui-agent-preset/src/client/settings-store.ts:14`, `37-50`).

4. **Subagent-created agents** — `subagent` tools delegate to providers
   (`subagent-spawn-in-process`, `subagent-fork-in-process`, `subagent-acp`, `subagent-codex`,
   `subagent-claude-code`, `subagent-dsh-sdk`); each child is itself a full agent+session
   created through the same factory (`docs/capability-seams.md` table row `ctx.subagents`,
   line 458). ACP-created agents use `AcpConfig { provider, model }`
   (`docs/config-catalog.md:18-28`).

**Bottom line for A:** an agent definition is *not* a stored document. It is: (a) an
`AgentOptions` triple, (b) the durable session (whose history is the agent's memory), and
(c) the set of plugins/preset rows mounted into its scoped context at creation. Definitions
live in `cordis.yml` files (boot rows + preset directories) and in the registry as live
objects; the only durable *record* of an agent's composition is `SessionHeader.agentPreset`
plus the `agent-preset/selected` log event (`packages/host/apiproxy/src/api-proxy.ts:3113`).

---

## B. The settings architecture: namespaces, schemas, layering, revisions, redaction

### B.1 The seam

`ctx.settings` is an abstract seam (`SettingsProvider`, `packages/settings/settings/src/index.ts:350`):
providers implement raw-document storage (`load`/`persist`), the base class owns namespace
registration, resolution, validation, change detection, and commit events. The shipped
provider is `dsh-settings-file` (`packages/settings/settings-file/src/index.ts`): one
`settings.yaml` under the harness home (`$DSH_HOME` or `~/.dsh`), hot-reloaded by default
(`watch: true`, `debounceMs: 100`; `docs/config-catalog.md:1816-1834`).

**One document, one section per namespace.** The raw document maps namespace → section
(`settings/src/index.ts:353`, `687-694`); the provider stores the whole document, and each
plugin registers the schema for its own namespace.

### B.2 Namespaces

- `SettingsNamespace` is a branded string validated as lowercase kebab-case
  (`settings/src/index.ts:19-31`; `types.ts:13`). Examples: `agent-loop`,
  `agent-default-model`, `llm-deepseek`, `llm-pi-ai`, `agent-presets`.
- Registration: `register<T>(ns, schema, { base?, applies?, validate? })`
  (`settings/src/index.ts:435-470`) returns a `SettingsScope<T>` with `get()`,
  `watch(cb)` (serialized, commit-ordered, contained failures), `update(patch)` (merge),
  `replace(section)` (wholesale). Registration is an effect on the registrant's fiber —
  unload removes the namespace.

### B.3 Resolution layering

`resolve(schema, base, section)` (`settings/src/index.ts:697-710`):
```
value = schema(mergeLayers(base, userSection))
```
- `mergeLayers` (`index.ts:297-305`): plain objects merge recursively; arrays and other
  values replace wholesale; `undefined` entries strip (sparse patch semantics).
- Order: **schema defaults → registrant's composition `base` → user section** (module doc,
  `index.ts:1-7`). A field present in the user section is "user-overridden" (the `user`
  layer in descriptors exists so forms can mark it).
- `validate` (`SettingsRegisterOptions.validate`, `index.ts:37-62`): a cross-field check the
  schema cannot express; throwing refuses the write that produced the value. An externally
  edited section that later fails keeps the namespace's last good value and warns.
- `installSettingsSection(ctx, ns, schema, entry, hooks)` (`index.ts:863-897`) is the
  canonical consumer wiring: while a settings service exists, register with the consumer's
  composition entry as `base` and point the source thunk at the resolved scope; when the
  service goes away, fall back to the entry. Used by `agent-loop` (`agent-loop/src/index.ts:335-345`),
  `agent-default-model`, and the LLM adapters (section B.6).

### B.4 The generic describe/mutate API (one API, any namespace)

- `describe(options?)` (`index.ts:479-512`) returns one `SettingsDescriptor` per registered
  namespace: `ns`, serialized schemastery schema (`schema.toJSON()`), resolved `value`,
  `revision`, `base`, `user`, `applies` ('live' | 'restart'), and — under `redactSecrets` —
  `secrets` (`index.ts:65-90`).
- Writes: `update(ns, patch, expectedRevision?)`, `replace(ns, section, expectedRevision?)`,
  `mutate(ns, ops, expectedRevision?)` (`index.ts:534-575`). All three funnel into `write()`
  (`index.ts:578-648`) which:
  - snapshots+validates the input as **lossless JSON only** (`cloneJsonShaped`,
    `index.ts:253-288` — rejects Dates, Maps, BigInts, cycles, non-finite numbers);
  - serializes per-namespace writes on a queue (`writeQueues`);
  - checks `expectedRevision` against the namespace's current `revision` and refuses with
    `SettingsConflictError` (`SETTINGS_CONFLICT`, `index.ts:164-183`) when stale;
  - persists through the provider, then commits (`commit()`, `index.ts:749-799`) and emits
    `settings/updated` (deep-equal-gated; `types.ts:35`) and `settings/document-updated`
    (raw-section change, for configuration surfaces; `types.ts:48`).
- `mutate` (`SettingsPathOp = { op: 'set'|'unset', path: string[] }`, `index.ts:200-228`) is
  the write path for a caller holding a **redacted** view: it names the field without
  restating the section, so a wholesale `replace` rebuilt from a redacted document can never
  silently delete secrets the wire never returned.

### B.5 Secret redaction at the wire

`packages/settings/settings/src/redact.ts`:
- Schemastery fields marked `role('secret')` are stripped structurally (`redactSecrets(schema,
  value)`, `redact.ts:105-109`). The walker follows `object`, `dict`, `array` containers and
  records each secret position as `{ path: string[], set: boolean }` (`redact.ts:26-43`) — the
  slot is enumerated even when unset, so a form can render a write-only input.
- `describe({ redactSecrets: true })` (mandatory on every wire surface) redacts `value`,
  `base`, and `user` and returns `secrets` (`settings/src/index.ts:501-511`).
- The web gateway **always** passes it: `settings.describe` → `settings.describe({ redactSecrets: true })`
  (`packages/host/apiproxy/src/api-proxy.ts:3268`), and `namespaceView` forwards the
  redacted layers + `secrets` (`api-proxy.ts:1929-1940`).
- Exposed namespaces are allowlisted: `exposedNamespaces()` = configurable-provider
  settings namespaces + explicit web/product allowlists (`api-proxy.ts:1942-1958`);
  anything else is refused with `settings-not-exposed` (`api-proxy.ts:1960-1967`).
- Wire writes: `settings.update/replace/mutate` map to `settingsWrite()` which maps
  `SettingsConflictError` → `settings-conflict` and everything else → `settings-rejected`,
  then acknowledges with the namespace's fresh redacted view (`api-proxy.ts:1976-2024`).

### B.6 Credentials — secret *values* live outside settings

Settings/composition files carry only **references** (env-var names); values live in the
credential seam (`ctx.credentials`, `packages/credentials/credentials/src/index.ts:60-143`):
`resolve(ref)` per operation (so a rotated key reaches the next request), `describe(ref)`
(value-free: `configured`, `source`, `writable`), `set(ref, value)`, `unset(ref)`. The local
provider layers inherited environment over the managed `$DSH_HOME/.credentials.yaml`, with
project/user `.env` fallbacks (`packages/bundle/base/cordis.patch.yml:81-86`). The web
gateway exposes only value-free `credentials.describe` and write-only `credentials.set/unset`
(`api-proxy.ts:3321-3368`).

**Example (the LLM provider config loop):** `dsh-llm-deepseek` registers its whole plugin
`Config` (including `apiKeyEnv` with `role('credential-ref')`) as the `llm-deepseek` settings
section, layers its cordis.yml entry under it via `installSettingsSection`, registers the
adapter for route `deepseek-official`, and resolves the API key **per request** through
`ctx.credentials.resolve(apiKeyEnv)` (`packages/llm/llm-deepseek/src/index.ts:44-101`, `200-276`).
`dsh-llm-pi-ai` mounts dormant with zero routes and registers provider profiles the moment a
`llm-pi-ai:` settings section supplies them (`base/cordis.patch.yml:88-96`); the web Models
page writes exactly that section (section E).

---

## C. The tool model

### C.1 `defineTool` — the typed authoring API

`packages/core/tools/src/schema.ts:545-617`:

```ts
defineTool<const S extends ParameterSchemaSpec, const O extends ValueSchemaSpec>({
  name, description,
  parameters: S,                       // implicit open object root; per-property required: true
  output: { schema: O, render(args, value): ContentBlock[], presentationMeta?(args, value) },
  timeoutMs?,                          // cooperative budget, never sent to the model
  isConcurrencySafe?(args): boolean,   // pure classifier for sibling overlap
  execute(args, exec): Promise<value>, // validated args; returns canonical output
  finalizeContent?(exec, result)?,     // last-mile content-only transform
  presentCall?(args)?, presentResult?(args, result)?,  // UI render intents
}): ToolDefinition
```

- The **value-schema DSL** (`ValueSchemaSpec`, `schema.ts:85-94`) supports
  string/number/integer/boolean/null/array/object (with *mandatory* `additionalProperties`)/
  `json` (unconstrained)/`oneOf`, plus `enum`/`const`/annotations; compile-time inference
  (`InferArgs<S>`, `InferValue<O>`) is bounded to 16 container levels (`schema.ts:128-175`).
  Compilation is stack-safe (`runSchemaCompiler`, `schema.ts:275-414`) and produces the
  **enforced raw JSON Schema subset** (`assertSupportedJsonSchema`, `json-schema.ts`).
- `defineTool` compiles `parameters` → `ParameterJsonSchema`, wraps `execute` so model args
  are validated with `ToolArgsError` (`schema.ts:461-470`, `585-589`), and soft-validates
  presenters/replay (they must never throw on obsolete logged args, `schema.ts:594-615`).
- Example consumer: every shipped tool (`tool-catalog.md`), e.g. the `bash` tool
  (`packages/shell/tool-bash/src/index.ts`), `tool-fs` read/write/edit, `tool-web`,
  `tool-todo`, `tool-jobs`, etc.

### C.2 `ToolDefinition` — what the registry holds

`packages/core/tools/src/index.ts:222-288`:
- extends `ToolSchema` (`name`/`description`/`parameters` — the only model-visible fields;
  `schemas()` whitelists exactly those, `index.ts:1234-1267`);
- `output: ToolOutputDefinition` (`index.ts:212-219`): `schema` (raw JSON Schema enforced
  against every successful value), `render(args, value)` (pure → content blocks), optional
  `presentationMeta(args, value)` (pure UI payload for top-level calls only);
- `execute(args, exec)` — must observe `exec.signal` and settle only after owned work reaches
  quiescence; returns the canonical lossless-JSON value;
- `finalizeContent?` — synchronous, total, content-only, invoked once per normalized outcome
  (including pipeline failures) immediately before materialization (`index.ts:240-247`);
- `timeoutMs?` — **metadata only**: enforced by `@deepseek-ai/dsh-tool-call-timeout-policy`
  (a `tools/execute` wrapper), never sent to the model (`index.ts:249-255`;
  `docs/config-catalog.md:3088`);
- `isConcurrencySafe?(args)` — only an exact `true` opts into parallel overlap; failure
  classes exclusive (`index.ts:258-269`);
- `presentCall?`/`presentResult?` — pure, side-effect-free UI render intents
  (`ToolCallView`/`ToolResultView`, `index.ts:272-287`), replayable from logged args.

### C.3 `ToolRuntime` (`ctx.tools`) — the registry

`packages/core/tools/src/index.ts:787-1863`:
- `register(definition)` (global or into the calling agent scope — scoped tools shadow
  globals; the reserved `run_code` name cannot be registered, `index.ts:1037-1062`);
- `restrict({ allow?, deny? })` — per-scope filter over *global* tools; empty/unknown names
  fail; restrictions intersect; scope-local registrations are exempt (`index.ts:1071-1098`);
- `guard(fn)` — register a **monotonic guard**: returning a reason denies; no guard can
  force-allow a call another guard denied (`index.ts:711`, `1110-1128`);
- `schemas(scope?)` — the model-facing schema projection (`index.ts:1234-1267`);
- `executionMode(exec)` — `parallel` | `exclusive` classification for the loop scheduler
  (`index.ts:1276-1285`);
- `presentAs(mode)` — per-scope presentation override (how a preset composes Code Mode
  agents beside native ones, `index.ts:946-974`);
- visibility resolution `view(scope)`: inherited layers (restriction-filtered) + own scope
  registrations + reserved transport, `index.ts:1152-1193`;
- Config (`index.ts:654-674`, `790-793`): `mode: 'native' | 'code' | 'both'` and
  `maxParallelSubCalls` (default 10).

### C.4 The execution pipeline (guards, timeout, output validation, approval)

From `docs/tool-execution-pipeline.md` and `index.ts`:

```
model tool-call block
  → tool/call session event (logged before execution)        tool-calls.ts:263
  → UI presentCall(args)
  → tools/pre-execute waterfall   (allow | deny | ask)       index.ts:1475-1478
      ask → ctx.approval one-shot (allowed-once|rejected|cancelled|unavailable)
            absent/unanswerable ⇒ deny                        index.ts:1689-1729
  → registered monotonic guards (deny or abstain)             index.ts:1119-1128, 1486-1499
  → tools/execute waterfall (around-dispatch: timeout,
      retry, metrics — only this view may replace exec.signal) index.ts:1573-1576
      → tool body execute()                                   index.ts:1532-1560
         (tool-fs mutations additionally gate on fs/write-intent|fs/edit-intent)
  → tools/post-execute waterfall (accept | replace value/content | block
      + attach additionalContexts)                            index.ts:1742-1781
  → registry outer normalization (snapshot throws → isError)  index.ts:1826-1844
  → ToolDefinition.finalizeContent (content-only invariant)   index.ts:1649-1654
  → tools/result synchronous notification (frozen outcome)    index.ts:1657-1676
  → tool/result session event (+ UI presentResult)
```

Details worth noting:
- **Approval** is a seam (`ctx.approval`, `docs/capability-seams.md:453`): one-shot
  permission decisions over the `approval/request` waterfall; the shipped policy plugin
  `dsh-user-approval` is `'ask'` (delegate to composed answerers; fail-closed when none) or
  `'never'` (deterministic reject — the headless stance)
  (`docs/config-catalog.md:2815-2844`). The base bundle binds approval policy to the
  permission preset: `danger-full-access → never`, otherwise `ask`
  (`packages/bundle/base/cordis.patch.yml:188-205`).
- **Permission presets** (`dsh-permission-presets`, `docs/config-catalog.md:1296-1333`):
  `read-only`/`workspace-write`/`danger-full-access` each bundle a `sandbox/mode` + an
  `approval/policy`; a switch writes one `permission/preset` event that fans into both knobs
  (`docs/capability-seams.md:454`). Sandbox modes are `read-only` | `workspace-write` |
  `danger-full-access` with default `read-only` (fail-safe) or the base bundle's
  `workspace-write` default (`base/cordis.patch.yml:172-176`; `config-catalog.md:1496-1521`).
- **Output-schema validation**: every successful body/policy value is snapshotted as
  lossless JSON (`snapshotToolValue`, `index.ts:544-553`), validated against
  `output.schema` (`validateJsonSchemaValue`, `index.ts:1795`), and failures become
  `ToolOutputError` (`INVALID_TOOL_OUTPUT`, `index.ts:513-522`). `render()` and
  `presentationMeta()` are likewise snapshot-checked (`index.ts:1799-1814`).
- **Cancellation semantics**: `ABORTED_BEFORE_DISPATCH` (body never invoked) vs `ABORTED`
  (body was invoked; the outcome is drained then replaced), `index.ts:469-472`, `1518-1525`,
  `1919-1944`.
- **Result enrichment**: `additionalContexts` (user-role messages for the *next* request,
  FIFO) and `concludesTurn` (a successful result that ends the turn) ride the result
  (`index.ts:556-577`, `1747-1781`).
- **Spill policy** (`dsh-spill-policy`, `config-catalog.md:1920-1938`) is a
  `tools/post-execute` consumer: results over `maxInlineBytes` are replaced by a preview +
  locator through the `ctx.spillStore` seam.
- The scheduler used by the loop keeps ordered pre/post stages while only the
  around-dispatch/body stage overlaps (`packages/core/agent-loop/src/tool-calls.ts:121-246`):
  exclusive calls form barriers, parallel calls use a rolling pool capped at
  `maxParallelToolCalls`, results commit in model order, and abort records synthetic
  `ABORTED_BEFORE_DISPATCH` results for skipped calls so replay stays valid.

### C.5 Code Mode: `run_code` + the generated SDK

`packages/core/tools/src/code-mode.ts`:
- `RUN_CODE_NAME = 'run_code'` (`code-mode.ts:20`) is a **reserved transport** outside the
  filterable capability layers (`index.ts:1189-1191`). Under `mode: 'code'` it is the only
  wire contribution; the other visible tools are declared in a **generated SDK section**
  (`tools:sdk`, order 150; renderers for TypeScript and Python, `index.ts:60-63`,
  `ts-types.ts`, `py-types.ts`).
- The model-facing schema is language-aware: the `description`/`code` parameter text is
  resolved at schema-emission time from the loaded `ctx.codeRuntime.language`
  (`code-mode.ts:33-130`).
- A program is the body of an async function (`code`, `description` args) run by
  `ctx.codeRuntime` (a seam; worker-thread backend `dsh-code-runtime-worker-thread`). Tools
  are exposed as `tools.name(args)` bindings over the calling agent's visible set
  (`code-mode.ts:601-609`).
- Each sub-call re-enters the **complete guarded pipeline** as a nested execution with a
  parent token, gets a deterministic sub-call id `<parent>:code:<n>`, is scheduled under the
  native concurrency contract (submission-ordered starts; exclusive barriers; overlap up to
  `maxParallelSubCalls`), and is logged as `tool/code-dispatch-start` + `tool/code-dispatch`
  (log-only events; `types.ts:10-57`). Denials return as binding rejections
  (`code-mode.ts:464-594`).
- Only the outer curated result (`{ logs, result }`) enters model history
  (`code-mode.ts:260`, `322-327`); failures surface as `CodeRunFailedError`
  (`CODE_RUN_FAILED`, `code-mode.ts:139-144`).
- The `code` collapse denies model-direct calls to native tools with an actionable
  `UNKNOWN_TOOL` message ("call X from inside a run_code program instead", `index.ts:1373-1444`);
  the prompt states the same rule (`CODE_ONLY_INSTRUCTION`, `index.ts:58`).

---

## D. How a chat / agent run works: session, message flow, tool execution, streaming

### D.1 The session — an append-only typed event log

`packages/core/session/src/types.ts`:
- `SessionEventMap` (`types.ts:236-333`) is the merge-extensible vocabulary: `turn/start`,
  `turn/end` (with `TurnEndReason`), `step/start`, `step/end`, `user/message`,
  `assistant/chunk`, `assistant/message` (+ usage), `tool/call` (raw args JSON string),
  `tool/result` (+ optional error identity and tool-private `meta`), `todo/write`,
  `request/header`, `request/context`, `session/end-seed`. Plugins extend it by declaration
  merging (e.g. `agent/inbox/spliced` in `packages/core/agent/src/types.ts:12-26`;
  `tool/code-dispatch*` in `packages/core/tools/src/types.ts:25-57`).
- Every event is lossless JSON with contiguous `seq` (`types.ts:404-436`); the model-visible
  surface is marked with `surfaceOp` (`'append'` | `{ op: 'replace', start, end }`) and
  `sourceEventSeqs` (`types.ts:343-389`). Only `user/message`, `assistant/message`,
  `tool/result` are surface events (`SurfaceEventType`, `types.ts:343-346`).
- **"Model-visible means logged"**: anything reaching a model request must be reconstructable
  from the log; a runtime invariant asserts it (`docs/architecture.md:96`).
- `Session.deriveMessages()` projects the surface into the `Message[]` the model sees —
  cached, frozen, O(new nodes) (`packages/core/session/src/index.ts:726-747`).
- `SessionStore` (`ctx.sessions`, `index.ts:792+`) is the in-memory store; persistence is a
  seam (`ctx.sessionPersistence`) with JSONL (`packChunks`, zstd) and SQLite backends that
  store the same event vocabulary (`docs/capability-seams.md:422`). Sessions fork via
  `ctx.sessions.fork(source, boundary?, childSessionId?)` (`docs/architecture.md:126`).

### D.2 Turn / step model

`docs/architecture.md:63-90`: a **step** is one model request plus the tools it calls; a
**turn** is zero or more steps, opened before its first input is claimed and closed once
nothing is owed. Input reaches the driver through one **inbox**; `agent/pre-step` decides
what the model sees (reject or enter messages); `agent/request` lets plugins replace the
frozen call config; `agent/turn-stopping` is the serial terminal checkpoint. The full
sequence is in `docs/agent-lifecycle.md` (claim → pre-step → step/start → user/message →
prompt assembly → `agent/request` → `llm/stream` → `assistant/chunk*` → `assistant/message`
→ `tool/call*` → pipeline → `tool/result*` → step/end → turn/end).

### D.3 Message flow and streaming

- `ReactLoopAgent.step()` (`packages/core/agent-loop/src/agent.ts:332-401`) renders the
  prompt from the assembly, streams `preparedCall?.stream(request) ?? ctx.llm.stream(request)`,
  appends one `assistant/chunk` event per chunk, accumulates via `BlockAssembler`
  (`packages/llm/llm/src/assembler.ts`), and on finish appends `assistant/message` with
  `usage` and `sourceEventSeqs`. `max-tokens` finishes are recorded as durable events with
  empty content kept out of derived history (`docs/agent-lifecycle.md:74`).
- The LLM seam (`ctx.llm`, `packages/llm/llm/src/index.ts:284-928`): adapters register on
  provider routes via `registerAdapter` (`index.ts:338`); `stream(options)` runs the
  `llm/stream` waterfall (retry/replay/routing interceptors, `index.ts:913-927`) then the
  adapter's raw chunk stream (`index.ts:843-900`); `prepareCall(config, signal)` resolves the
  exact-model capability (context window, default `maxTokens`, reasoning efforts) and binds
  the adapter registration for the request (`index.ts:779-814`); `resolveCallConfig` rejects
  unsupported reasoning efforts (`index.ts:730-769`). The provider-neutral vocabulary is in
  `packages/llm/llm/src/types.ts` (`ContentBlock` union incl. `text`/`reasoning`/`image`/
  `tool-call`/`tool-result`; `FinishReason`; `TokenUsage` with disjoint cache fields).
- Request headers are logged as `request/header` events (reason `initial` | `resume` |
  `change`) and *replayed* — later steps derive their call config from the log, not from
  fresh options (`agent.ts:419-437`, `session/src/index.ts:670-680`).

### D.4 Tool execution inside a step

`packages/core/agent-loop/src/tool-calls.ts:59-289` (`executeToolCalls`):
1. Parse each `tool-call` block's raw JSON args (invalid JSON preserved as text,
   `tool-calls.ts:104-110`), each with the initiating agent and the step signal.
2. Classify the first pending call via `ctx.tools.executionMode` (`parallel` vs
   `exclusive`, `tool-calls.ts:88`); run one barrier/pool `runGroup`.
3. `runGroup` logs `tool/call`, runs ordered `prepare` (pre-execute + guards — the only
   ordered awaits), overlaps `dispatch` (around-wrapper + body) up to
   `maxParallelToolCalls`, commits results in **model order** through `finalize`/`finish`,
   appends `tool/result` (citing the call seq), and forwards `additionalContexts` into the
   next-step inbox (`tool-calls.ts:121-246`, `268-289`).
4. On abort: drains started calls, records synthetic `ABORTED_BEFORE_DISPATCH` results for
   the rest, and returns with the signal still aborted (`tool-calls.ts:237-242`, `249-259`).

### D.5 The web chat path

`session.prompt` RPC (`packages/host/apiproxy/src/api-proxy.ts:2461-2517`): validates a
client timezone, preflights image capability against the current model, materializes durable
content, builds a `UserMessage` with an rpcId source, then `agent.followup(message)` (or
`agent.steer`). UI rendering consumes `session/event` (durable) plus the `agent/*` live
events; the host pushes projection baselines and changes (`docs/architecture.md:121`).

---

## E. The UI model: how the web GUI represents an agent

The GUI is not a React app under `apps/web` (that file is only the mount point,
`apps/web/src/main.ts:1-10`); the UI ships as **client plugins** under `packages/client/`
(`ui-*` packages) composed by `dsh-client-modules` and served by the host
(`docs/capability-seams.md:464`; config catalog lines 3032-3061 list the `dsh-client-ui-*`
plugins).

**There is no "agent builder" form** (no name/description/system-prompt/tool-picker/model
fields for a persisted agent record). Instead, the GUI exposes the agent space through:

1. **Agent presets roster (`ui-agent-preset`)** — `AgentPresetSection.tsx` renders the
   preset roster as cards grouped by trust (`system`/`user`): pick the default (writes the
   `agent-presets` settings `default` field, `settings-store.ts:37-50`), view a shipped
   preset's `cordis.yml` read-only, **copy** a preset into a new user preset (the only
   create path besides conversation), open/delete user presets, and a "creator draft"
   button that starts a session on the self-referential `cordis` preset so the agent itself
   authors a new preset in conversation (`AgentPresetSection.tsx:12-229`, `232-420`).
   A per-session switch also exists: `agentPreset.select` recomposes a live session onto a
   new preset and logs `agent-preset/selected` (`api-proxy.ts:3087-3114`).

2. **Model selection (`ui-model-selection`)** — a per-session provider/model/reasoning
   picker driven by `session.models` / `session.selectModel`; the host validates the route
   (`ctx.llm.resolveCallConfig`), applies it to the session's selection ref for the next
   assembled step, and saves it as the default when allowed
   (`api-proxy.ts:2272-2331`; `ui-model-selection/src/client/directory.ts:63-123`).
   The per-session selection installs through `installModelSelection` on the agent's scope
   (`api-proxy.ts:1154-1181`; `packages/core/agent/src/model-selection.ts:39-75`).

3. **Settings pages (`ui-settings*`)** — a generic settings UI rendering the redacted
   namespace descriptors with schema-driven forms (`dsh-client-schema-form`); the Models
   page (`ui-settings-models`) joins the configurable-provider directory, settings
   namespaces, and credential state into provider rows: it derives the API-key reference
   (`deriveKeyRef`, `store.ts:69-71`), writes provider profiles into the provider's settings
   namespace, and stores key *values* through `credentials.set` (`store.ts:1-120`).

4. **Tool rendering (`ui-tool`)** — the chat renders tool calls/results as cards driven by
   the tool's `presentCall`/`presentResult` intents plus the durable `tool/result` `meta`
   (`ToolCallTree.tsx`, `ToolDetails.tsx`, `toolviews/`); the `code-dispatch` events render
   `run_code` sub-calls through the same code path (`packages/core/tools/src/types.ts:36-56`).

5. **Other per-agent controls** — permission-preset switch (`ui-permission-presets`), plan
   mode (`ui-plan`), goal UI (`ui-goal`), job controls (`ui-jobs`), subagent tree
   (`ui-subagent`), skill catalog (`ui-skill`), plugin inventory (`ui-settings-plugin-inventory`),
   and the conversation/chat canvas (`ui-conversation`) with message items, reasoning rows,
   and command cards.

**Mapping to the underlying model:** the UI never constructs an `AgentOptions` object with a
system prompt and a tool list. What a user *does* map onto: (a) picking a **preset** →
chooses which `cordis.yml` plugin subtree gets mounted into the next session's agent scope
(`api-proxy.ts:1227-1248`); (b) picking a **model** → writes the session selection that the
`agent/request` waterfall snapshots (`model-selection.ts:39-75`); (c) editing **settings** →
writes redacted namespaces consumed live by plugins (`installSettingsSection`); (d)
switching **permission presets** → writes sandbox + approval knob events; (e) **authoring a
preset** (copy or conversation) → creates new `cordis.yml` composition files. Tools are
therefore configured by composition (which plugins/preset rows are loaded), not selected per
agent in a form.

---

## F. Key concepts DSH has that a typical LangChain-based platform lacks — and vice versa

### F.1 Concepts DSH has that typical LangChain platforms (e.g. LangConfig) lack

1. **The session log is the agent's source of truth, and model-visible == logged.**
   History, header, tools, usage, todos, and errors all derive from one append-only
   `SessionEvent` log (`docs/architecture.md:92-96`). There is no separate conversation
   table; the "agent" and its "memory" are the same object. LangChain platforms typically
   store agent configs in a DB and chat history separately.
2. **The agent is a live handle, not a record.** `ctx.agents` is a runtime registry of
   `Agent` objects; "creating an agent" runs the factory + setup window and publishes into
   the registry; there is no persisted "agent definition" row that a REST CRUD manipulates.
3. **Everything is a replaceable plugin on a shared context (Cordis).** The model adapter,
   tool registry, session log, and even the agent loop itself are plugins
   (`docs/architecture.md:9-13`); every registration is an effect that unwinds on unload,
   and composition is layered from patchable `cordis.yml` rows (profiles/bundles/patches,
   `docs/architecture.md:15-37`).
4. **Per-agent scoped registrations.** `agent.ctx` + `dsh-scope` give every agent its own
   layer of tools/prompt sections/variables/restrictions/guards that shadow globals and
   unwind on disposal (`docs/glossary.md:11-21`). Sub-agents inherit via lineage data
   (`parentSession`, `delegationDepth`), not scope nesting.
5. **Waterfall events as the extension mechanism.** `agent/pre-step`, `agent/request`,
   `llm/stream`, `tools/pre-execute|execute|post-execute` are expert waterfalls whose
   listeners call `next()`; `agent/turn-stopping` is a serial checkpoint. Policy (hooks,
   approval, sandbox, spill, retry) attaches at documented extension points without forking
   the loop (`docs/architecture.md:104-128`).
6. **A first-class guarded tool pipeline** with monotonic guards, one-shot approval,
   output-schema enforcement, cooperative timeouts, cancellation contracts, and
   `additionalContexts`/`concludesTurn` — plus **Code Mode** (`run_code` + generated
   TS/Python SDK) where the model programs against the tool set.
7. **Capability seams with swappable providers**: filesystem, subprocess, shell, sandbox,
   web search/fetch, terminals, persistence, settings, credentials, subagents (spawn/fork/
   ACP/Codex/Claude Code/SDK), LSP, spill, attachments, workflow engine — one interface,
   many backends (`docs/capability-seams.md` table).
8. **User-settings seam with namespaces + wire redaction + revisions.** Configuration is
   runtime-reloadable, per-namespace, layered (defaults → base → user), secret-redacted, and
   conflict-checked — versus a static `.env` + restart model.
9. **Credentials as references.** Secrets live in a credential store referenced by env-var
   name; adapters resolve per request so a rotated key reaches the next request
   (`packages/credentials/credentials/src/index.ts`).
10. **Agent-level runtime facilities beyond the loop**: same-session **goals**
    (`ctx.goals` + `create_goal/get_goal/update_goal` tools, `packages/goal/*`), **Ralph**
    fresh-agent loops, the **workflow** script engine (subagent fan-out), **background
    jobs** (`job_*` tools over any producer), **plan mode** (`exit_plan_mode`),
    **compaction** (pressure-triggered summarization + tool-result pruning), **session
    search/query tools**, **skills** (catalog + `skill` tool), **schedules**, and dynamic
    self-referential **Cordis packages** (`cordis_*` tools) — none of which are typical in
    a LangChain platform.
11. **Session persistence with packed/zstd JSONL or SQLite event logs** and replayable
    chunk-level transcripts, cold resume, and session export.
12. **Tool-catalog and config-catalog are generated and completeness-guarded** so a new
    tool/provider cannot ship undocumented (`docs/tool-catalog.md:8-10`).

### F.2 Concepts a typical LangChain-based platform (LangConfig) has that DSH lacks

1. **A persisted, user-facing agent record** — name, description, avatar, system prompt,
   per-agent model, tool list — stored in a relational DB (LangConfig: SQLAlchemy models +
   Alembic; `AgentFactory.create_agent`, `DeepAgentFactory.create_deep_agent`) with REST
   CRUD and an **agent builder UI form** (`src/features/agents/`). DSH's GUI deliberately
   has no such form: an agent's behavior is its composition, not a record.
2. **Graph-based workflow authoring.** LangGraph gives a visual canvas where nodes/edges/
   state are first-class and agents can be plain graph nodes. DSH has a *script* workflow
   engine (JS orchestration of subagents) but no visual graph editor.
3. **RAG / knowledge bases.** LangChain platforms typically integrate a vector store and a
   document-upload/knowledge API (LangConfig: `POST /api/knowledge/documents`, pgvector).
   DSH's memory model is the session log + workspace files + skills; there is no vector
   index or document corpus abstraction.
4. **Familiar Python/LangChain tool ecosystem.** LangChain tools, `@tool` decorators,
   LangSmith tracing, and the huge third-party integration surface. DSH defines its own
   `defineTool` + schema DSL and ships its own tool packages (bash/fs/web/terminal/LSP/
   subagent/…).
5. **Multi-tenant SaaS posture.** LangConfig targets a hosted multi-tenant app (workspaces,
   users, orgs). DSH is a local-first harness: one home directory, one user document, one
   credentials file, loopback-trust web gateway (`packages/client/connection` trusted-hosts
   fence; `config-catalog.md:390-413`).
6. **Per-agent persisted "session" CRUD with titles/avatars in a DB.** DSH sessions are
   files (JSONL/SQLite) under project directories with derived titles
   (`dsh-session-title`); there is no agents/sessions REST resource tree managed by an ORM.
7. **Explicit deployment of "guardrails" as agent settings** (allowed tools, max steps,
   temperature, system prompt) — in DSH these live in composition config and policy
   plugins rather than per-agent form fields.
8. **A stable public REST/OpenAPI surface.** DSH's host gateway is a private JSON-RPC-style
   carrier (`connection` RPC; `docs/capability-seams.md:467`) rather than a documented
   REST API consumed by third parties.

### F.3 Where the two overlap

Both have: providers/models with per-request API keys; tools with JSON-schema params;
chat/turn execution with streaming; approval/permission concerns (LangConfig via
deepagents' interruption & human-approval; DSH via `ctx.approval` + permission presets);
subagent/delegation; sessions and titles; workspace/cwd notion; SSE/streaming to the UI.
The philosophical difference: LangConfig treats the **agent as a configured artifact** the
user assembles in a GUI, while DSH treats the **agent as a composed runtime** whose
definition is the plugin tree + session log, with configuration (settings/credentials/
presets/model selection) layered around it.

---

## Appendix: Key file map

| Concern | Files |
| --- | --- |
| Agent interface / events / registry | `packages/core/agent/src/runtime-types.ts`, `index.ts`, `types.ts`, `inbox.ts`, `model-selection.ts` |
| Agent driver + factory | `packages/core/agent-loop/src/agent.ts`, `index.ts`, `tool-calls.ts`, `constants.ts` |
| Session log | `packages/core/session/src/types.ts`, `index.ts`, `surface.ts`, `json.ts`, `preparation.ts` |
| System prompt assembly | `packages/core/system-prompt/src/index.ts` |
| Tool registry + pipeline + code mode | `packages/core/tools/src/index.ts`, `schema.ts`, `code-mode.ts`, `json-schema.ts`, `presentation.ts`, `types.ts` |
| Settings seam + redaction | `packages/settings/settings/src/index.ts`, `redact.ts`, `types.ts`; provider `packages/settings/settings-file/src/index.ts` |
| Credentials seam | `packages/credentials/credentials/src/index.ts` (+ `credentials-local`) |
| LLM seam + adapters | `packages/llm/llm/src/index.ts`, `types.ts`, `message.ts`, `call-config.ts`, `retry-policy.ts`; `packages/llm/llm-deepseek/src/index.ts`, `llm-pi-ai/src/config.ts` |
| Agent presets | `packages/preset/agent-presets/src/preset.ts`, `discovery.ts`, `mount.ts`, `session.ts` |
| Scoped registration | `packages/core/scope/src/index.ts`, `store.ts` |
| Default model selection | `packages/core/agent-default-model/src/index.ts` |
| Web host gateway | `packages/host/apiproxy/src/api-proxy.ts`, `api/sessions.ts`, `fetch/handler.ts` |
| Base composition | `packages/bundle/base/cordis.patch.yml` |
| Web GUI (client plugins) | `packages/client/ui-agent-preset`, `ui-model-selection`, `ui-settings-models`, `ui-tool`, `ui-conversation`, `ui-permission-presets`, `ui-plan`, `ui-subagent`, `ui-settings*` |
| Generated catalogs | `docs/tool-catalog.md`, `docs/config-catalog.md`, `docs/capability-seams.md`, `docs/persistence-catalog.md` |

**Key caveat for the comparison:** several doc statements above (e.g. the exact list of
shipped tool names and config fields) are *generated* artifacts (`docs/tool-catalog.md`,
`docs/config-catalog.md`) that reflect the source at generation time; line numbers in this
report for those files refer to the checked-out copies. The runtime sources cited under
`packages/` are authoritative.
