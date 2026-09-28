
# LangConfig System Architecture

> Visual overview of the LangConfig platform (Agent IDE). Built with Mermaid — open this
> file in the IDE Markdown preview to render the diagrams.

---

## 1. What is LangConfig?

LangConfig is a **visual platform for building, testing, and shipping LangChain agents and
LangGraph workflows**. It works as a full **Agent IDE ("Workbench" mode)** — you design
agents on a canvas, configure tools/middleware/skills in side panels, chat with them to
verify behavior, and finally **export them as standalone Python** that runs outside the
platform (just like you develop in VS Code, then ship the app).

The product is a **dually-kept system**: a lightweight React IDE shell (Obsidian/VS Code
style: activity bar, sidebar, tabbed workspace, bottom panel) in front of a FastAPI
backend that compiles persisted agent definitions into real LangGraph executables at
runtime.

### Tech stack

| Layer        | Technology                                                                                       |
| ------------ | ------------------------------------------------------------------------------------------------ |
| Frontend     | React 19 + TypeScript + Tailwind CSS 4 + ReactFlow                                               |
| Backend      | Python 3.11/3.13 + FastAPI + LangChain V1 + LangGraph + deepagents 0.7.1                         |
| Database     | PostgreSQL 16 + pgvector + SQLAlchemy + Alembic                                                  |
| Runtime libs | deepagents SDK, langchain/langgraph, LLM providers (DeepSeek / OpenAI-compatible), Tavily search |

### The five-layer mental model

```mermaid
flowchart TB
    L1["1 · UI LAYER<br/>React IDE shell (src/)"]
    L2["2 · API LAYER<br/>FastAPI routers (backend/api/)"]
    L3["3 · SERVICE LAYER<br/>Builders, exporters, workspace (backend/services/)"]
    L4["4 · CORE ENGINES<br/>workflows, codegen, skills, middleware (backend/core/)"]
    L5["5 · DATA & RUNTIME LIBS<br/>PostgreSQL + deepagents/langchain"]

    L1 --> L2 --> L3 --> L4 --> L5
    L3 --> L5
    L4 --> L5

    classDef layer fill:#f8fafc,stroke:#64748b,color:#111;
    class L1,L2,L3,L4,L5 layer;
```

Each layer has a **strict responsibility**:

1. **UI** — renders canvas/editors, never talks to the DB; only calls the typed API clients in `src/lib/api/`.
2. **API** — FastAPI routers are thin *controllers*: validate input, delegate to services, stream SSE. They contain almost no business logic.
3. **Service** — *builders* (`AgentFactory`, `DeepAgentFactory`), *exporters* (codegen in `api/agents/deep_agents.py` + bundle in `services/agent_bundle.py`), workspace/memory/scheduler managers.
4. **Core engines** — reusable engines: workflow executor, checkpointing, events, codegen, skills registry, middleware, context management.
5. **Data & runtime** — PostgreSQL tables and the external SDKs the services orchestrate.

> **The key architectural rule:** agents are *not* stored as executable code — they are stored
> as **JSON config rows** in PostgreSQL and **compiled into LangGraph graphs at runtime** by
> the service layer. This is why you can edit an agent in the UI and immediately re-run it.

---

## 2. What is an AI agent?

An **AI agent** is a software system that uses a large language model (LLM) to *act*, not just
answer: given a goal it plans a sequence of steps, calls tools (search, databases, files, APIs,
shell), observes the results, and iterates until the goal is done. The classic loop:

```text
goal → LLM reasons about steps → pick a tool → execute → observe result → feed back → repeat → deliver
```

| | Chatbot | AI agent |
|---|---|---|
| Input | a question | a *goal* |
| Output | a reply | an *outcome* |
| Loop | single turn, stops | plan → act → observe → iterate |
| Tools | none or fixed | arbitrary tools, chosen by the model |
| State | conversation only | conversation + memory + external state |
| Example | "What is the weather?" | "Book a flight under ¥6,000 and email the itinerary" |

Agents differ wildly across **who they serve** and **how they are built**:

1. **Consumer assistant products** — closed, hosted, chat-first (豆包 / Doubao, ChatGPT, Copilot).
2. **Personal / messaging / desktop-workbench agents** — self-hosted or a desktop app, talk to
   you through chat apps, operate your machine (OpenClaw, Hermes Agent, WorkBuddy).
3. **Coding agents / agent IDEs** — operate inside a repo or IDE (Claude Code, Cursor, MarsCode).
4. **Developer frameworks & runtimes** — the building blocks used to *construct* any of the above (LangChain, LangGraph, Deep Agents).

LangConfig sits in the **4th** category: a visual IDE on top of the LangChain stack, used to
build and ship agents of the other three kinds (§3–§4).

---

## 3. The agent landscape — OpenClaw · Hermes · Doubao · the LangChain stack

### 3.1 OpenClaw — the personal messaging agent

**What.** Open-source (MIT) autonomous agent by Austrian developer Peter Steinberger. Launched
Nov 24, 2025 as *Clawdbot*, renamed *Moltbot* (Jan 2026, after an Anthropic trademark complaint)
then *OpenClaw*. TypeScript/Node gateway + Swift mobile client; runs locally on your machine;
one of the fastest-growing open-source projects ever (~247k GitHub stars by Mar 2026). You talk
to it through messaging apps — WhatsApp, Telegram, Discord, Slack, Signal, iMessage, and 15+
more.

**How it works.** A persistent gateway daemon:

1. a message arrives on any channel → resolved to a per-session transcript;
2. the LLM plans and streams back tool calls;
3. tools execute (shell, files, browser via Playwright, email, APIs); results are appended to
   the transcript and the LLM is called again — a tool loop;
4. a final reply is delivered on the originating channel.

Between messages a **heartbeat** wakes the agent for background work (email, calendar, cron).
It ships 100+ pre-built **skills**, persistent memory (`SOUL.md` / `MEMORY.md` / `AGENTS.md`),
subagents, and a Docker sandbox, and works with Anthropic, OpenAI, DeepSeek, and local models.

**Typical use.** A 24/7 personal assistant inside your chat app: "research three competitors and
draft a summary", book travel, send email, manage files, run scheduled tasks. The software is
free; the ongoing cost is your LLM API spend (~$5–20/month light use, more for heavy use).

**Pros / cons.**

| Pros | Cons |
|---|---|
| Free, MIT, massive community | Self-hosting setup is technical |
| Provider-agnostic, local-first (data on your machine) | Broad system access = real security risk |
| 20+ messaging platforms | Token costs grow with use |
| Skills / plugins / browser automation | Single-user personal automation — no team governance |
| Browser + shell + cron out of the box | Not a framework: you consume it, you don't build products on it |

### 3.2 Hermes Agent — the self-improving agent (Nous Research)

**What.** Open-source, self-improving agent framework from Nous Research (the team behind the
Hermes fine-tuned models), released Feb 25, 2026. Python 3.11+, open source, provider-agnostic
(OpenRouter, Anthropic, OpenAI, DeepSeek, Gemini, local models). One of the fastest-growing
agent frameworks of 2026 — tens of thousands of GitHub stars within weeks of release. Runs in
the terminal, a desktop app, and 16+ messaging platforms (Telegram, Discord, Slack, WhatsApp,
Signal, Matrix, iMessage, WeChat).

**How it works.** A closed self-improvement loop:

- after any complex task (≥5 tool calls) it **auto-writes a reusable skill** — a Markdown skill
  doc capturing the approach, edge cases, and domain knowledge;
- skills are refined on reuse, so the agent gets measurably better at *your* workflows (Nous
  benchmarks: 40% faster research once 20+ skills accumulate);
- a **three-layer memory** (user profile / session / long-term; pluggable backends: built-in,
  Honcho, Mem0) persists identity, preferences, and lessons across sessions;
- planning → execution → memory → skills layers, MCP server integration for external tools,
  `delegate_task` subagents, credential pooling, and local / Docker / SSH / serverless
  execution backends.

**Typical use.** A self-hosting research / ops agent on a cheap VPS that accumulates your
personal skill library; scheduled research and content work; coding and infrastructure
automation; one agent reachable from Telegram, Discord, and WhatsApp.

**Pros / cons.**

| Pros | Cons |
|---|---|
| Self-improving, compounding skill library | Young project (2026) — maturity/stability risk |
| Persistent memory + provider-agnostic | Autonomous self-modification needs skill review & isolation |
| MCP integration, subagents | Single-user focus — not an enterprise governance model |
| Cheap to run ($5 VPS) | Not a general framework for shipping agent products |
| Huge community momentum | Auto-generated skills can contain risky operations if unreviewed |

### 3.3 豆包 Doubao — ByteDance's all-scenario assistant platform

**What.** ByteDance's AI assistant and agent platform (launched Aug 2023 as "Grace";
international version *Dola*). China's #1 AI app (~170M monthly active users, 100M+ daily
active users). Built on the Doubao (formerly 云雀/Lark) LLM family — text, image, audio, video,
1M+ token context — and wired into ByteDance's ecosystem (Douyin, Toutiao, Feishu/Lark). For
developers it is exposed through the Volcano Engine (火山引擎) API; sibling products include
**Coze (扣子)** — a no-code agent builder — and **MarsCode**, a coding agent.

**How it works.** A multimodal LLM plus a product-level agent framework. In 2026 ByteDance
restructured Doubao into three modes:

- **Quick** — fast Q&A and retrieval;
- **Expert** — deep reasoning (math, long documents, legal logic), powered by Doubao 2.0 Pro
  with a native agent architecture;
- **Task** — autonomous agent execution: decompose → plan → invoke tools → deliver, including
  scheduled background tasks, zero-code webpage/PPT generation, and Excel→charts visualization.

**Typical use.** Everyday consumer AI: Chinese writing / summarization / study, image and
audio/video generation, meeting minutes, deep-research reports. For business: Volcano Engine
APIs and Coze no-code agents. Free consumer tier; paid tiers since June 2026 (Standard ¥68/mo,
Enhanced ¥200/mo, Professional ¥500/mo).

**Pros / cons.**

| Pros | Cons |
|---|---|
| Best-in-class Chinese-language output | Closed source, hosted — privacy / jurisdiction concerns |
| Free consumer tier + multimodal | Not a framework: you can't re-orchestrate or self-host the logic |
| Massive distribution, cheap tokens | Consumer-shaped — weak for custom enterprise coding workflows |
| No-code agent building via Coze | You don't own the data, prompts, or behavior |
| Task Mode = real autonomous execution | English / code output lags Western assistants |

### 3.4 WorkBuddy — Tencent's all-scenario AI office workstation

**What.** Tencent's all-scenario AI agent desktop workstation — the "AI colleague" (AI 数字同事)
of Tencent Cloud's "Buddy" family (alongside the CodeBuddy coding agent). Built by the Tencent
Cloud CodeBuddy team: internal pilot (2,000+ Tencent employees, Jan 2026) → closed beta (Feb
2026) → public launch (Mar 9, 2026). A Windows/macOS desktop app that wraps autonomous agent
execution into a no-deploy, out-of-the-box package — by Tencent's own numbers one of China's
most widely used productivity agent tools by daily active users (~8.85M monthly visits by Mar
2026). Its technical foundation is same-origin with the open-source OpenClaw project.

**How it works.** Three working modes that scale autonomy against risk:

- **Ask** — pure Q&A / consultation, no file operations, zero risk;
- **Plan** — proposes a step-by-step execution plan and waits for approval before touching anything;
- **Craft** — full autonomous execution: decompose → plan → execute multi-step tasks on local
  files, delivering checkable artifacts (documents, spreadsheets, PPT, charts).

On top of that: **100+ out-of-the-box expert Skills** (updated weekly, plus custom skills);
**Expert Groups** (专家团) that package multi-agent collaboration — Skill (capability) → Expert
(capability + experience) → Expert Group (multiple experts + a collaboration process); a
**sandbox** for safe execution; MCP protocol support; and multiple model providers (including
Tencent's Hunyuan family). **Remote control:** send commands from your phone via IM apps (WeChat,
Enterprise WeChat, QQ, Slack, Telegram, Discord, DingTalk, Feishu) to run tasks on your machine.
The office ecosystem: Tencent Docs integration brings human-AI co-writing into
Word/Excel/PPT/Markdown (July 2026, WorkBuddy V5.3+).

**Enterprise edition** (June 5, 2026): WorkBuddy Enterprise AI Workspace — a three-tier
progressive framework (Expert Layer: Skills, MCP, data/knowledge connectors, harness; Assistant
Layer: a 24/7 assistant with memory and self-evolution; Team Layer: shared context and a
"Context Flywheel"); three core offerings (CodeBuddy for development teams, WorkBuddy for
business teams, Managed Agents); and a unified admin platform with SaaS / dedicated-VPC /
private deployment modes.

**Typical use.** Everyday office automation: document processing, data analysis and reports,
meeting minutes, PPT generation, competitor research, and remote task scheduling from your
phone. Personal tiers from ¥99/mo (free trial tier); team plans from ~$40/seat/month; enterprise
SaaS from ¥198/user/month.

**Pros / cons.**

| Pros | Cons |
|---|---|
| No-deploy, pre-integrated, sandboxed — low adoption risk | Closed source, hosted — data flows through Tencent Cloud (private deploy needs the enterprise tier) |
| 100+ skills + Expert Groups (multi-agent parallel) | A workplace product — not a framework for building agent products |
| Ask / Plan / Craft dial autonomy against risk | Deep customization needs the enterprise/private edition |
| Office ecosystem (Tencent Docs human-AI co-writing) | China-first; international footprint still maturing |
| Remote control via IM apps (phone → machine) | Desktop app, per-user view — team governance sits in the enterprise edition |

### 3.5 LangChain — the framework (abstractions)

**What.** The most widely used open-source **agent framework**. The official docs call it "the
agent framework: abstractions and integrations for models, tools, and agent loops" — a
standardized vocabulary (model/chat interfaces, tool schemas, content blocks, the agent loop)
plus **600+ integrations** (models, vector stores, document loaders, tools). v1.0 (Oct 2025)
slimmed the `langchain` namespace down to the essential agent building blocks —
`langchain.agents` (`create_agent`), `langchain.messages`, `langchain.tools`,
`langchain.chat_models` (`init_chat_model`), `langchain.embeddings` — and moved legacy chains,
retrievers, and the hub into a separate `langchain-classic` package.

**How it works.** Since v1.0, `create_agent` (which replaced the older
`langgraph.prebuilt.create_react_agent`) is the standard entry point, and it runs **on the
LangGraph execution engine under the hood**. You declare a model, a list of tools, and a system
prompt; `create_agent` assembles the "reason → pick tool → execute → feed back" loop as a
LangGraph graph, customized with a **middleware array** instead of subclassing. The docs call
middleware *the defining feature of `create_agent`*: composable hooks run before/after the model
and before/after each tool, letting you **monitor** (logging, analytics, debugging), **modify**
(prompts, tool selection, output formatting), **control** (retries, fallbacks, early
termination), and **enforce** (rate limits, guardrails, PII detection). Prebuilt middleware
includes `PIIMiddleware`, `SummarizationMiddleware`, `HumanInTheLoopMiddleware`,
`ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`, `ModelFallbackMiddleware`, Anthropic
prompt caching, a to-do list, an LLM tool selector, and context editing.

**Typical use.** Standard tool-calling agents and RAG apps; quick prototypes; a uniform way for
a team to build LLM features. (This repo's normal agents are built this way:
`AgentFactory.create_agent` — §11.)

### 3.6 LangGraph — the runtime (durable execution)

**What.** A low-level orchestration framework and **agent runtime**: you define nodes, edges,
and a state schema (`StateGraph`) and get production infrastructure — durable execution (resume
after failures), streaming, human-in-the-loop interrupts, and thread-level + cross-thread
persistence. Used in production by Klarna, Uber, J.P. Morgan, and LinkedIn.

**How it works.** The graph engine persists each state transition to a checkpointer (Postgres
in this repo), streams `values`/`updates`/messages, and supports the `interrupt()` primitive for
human approval — so long-running, stateful agents can pause, resume, and survive restarts.

**Typical use.** Workflows that branch, retry, fan out, or need gates; multi-agent topologies
(supervisor, swarm); anything that must run for a long time and resume reliably. (This repo:
workflow execution engine §12 + Graph Studio §13.)

### 3.7 Deep Agents — the harness (batteries included)

**What.** LangChain's "batteries-included agent harness" — the `deepagents` SDK (v0.6.12, June
2026; this repo pins 0.7.1). It bundles everything a *long-horizon autonomous* agent needs so
one starts working out of the box: a planning/todo tool, a pluggable filesystem, sub-agents
with isolated context windows, context summarization, persistent memory, skills, and
human-approval gates.

**How it works.** Deep Agents adds **no new runtime** — it is a curated preset of the same
middleware you could pass to `create_agent`, wired to a detailed system prompt and compiled onto
the LangGraph engine. Any LangGraph `CompiledStateGraph` can be handed to a Deep Agent as a
sub-agent, so custom orchestration plugs in alongside the defaults instead of replacing them.

**Typical use.** Long-running, multi-step, non-deterministic tasks: research, coding,
go-to-market automation. (This repo's DeepAgents are built by
`DeepAgentFactory.create_deep_agent` with a skills + middleware + sandbox pipeline — §11.)

### 3.8 One stack, three rungs — not three competitors

Official LangChain guidance frames these as **Framework / Runtime / Harness** — "composition,
not migration":

| | LangChain | LangGraph | Deep Agents |
|---|---|---|---|
| Layer | Framework | Runtime | Harness |
| Value add | Abstractions + integrations | Durable execution, streaming, HITL, persistence | Predefined tools, prompts, subagents |
| You write | model + tools + middleware | nodes, edges, state schema | a prompt + tools; defaults do the rest |
| Reach for it when | standard tool/RAG loop | branching, retries, fan-out, gates | long-horizon autonomous task |

A useful analogy that circulates in the community: **LangChain = 流水线 (pipeline)**,
**LangGraph = 图 / 交通枢纽 (graph / traffic hub)**, **Deep Agents = 大脑 / 项目经理 (brain /
project manager)** — the pipeline speeds up development, the graph keeps everything running,
and Deep Agents plans and delegates.

```mermaid
flowchart TB
    H["Deep Agents · harness<br/>planning · filesystem · subagents · skills"]
    F["LangChain · framework<br/>create_agent · middleware · integrations"]
    R["LangGraph · runtime<br/>StateGraph · durable execution · HITL · persistence"]
    M["Models · tools · vector stores · LangSmith observability"]

    H --> F --> R --> M

    style H fill:#fde68a,stroke:#b45309,color:#111
    style F fill:#bbf7d0,stroke:#15803d,color:#111
    style R fill:#ddd6fe,stroke:#6d28d9,color:#111
```

### 3.9 The Activities sidebar — where the stack shows up in LangConfig

The three rungs above are not just abstract libraries — each maps to a first-class workspace in
LangConfig's VS Code-style **Activities sidebar**, alongside the workflow canvas (the fourth
surface):

| Activity | What you build | Stack rung | Entry point |
|---|---|---|---|
| **Agents** (users icon) | Normal tool-calling agents via the 4-section editor (Overview · Prompt · Tools · JSON) | LangChain framework | `AgentFactory.create_agent` |
| **DeepAgents** (brain icon) | Long-horizon autonomous agents: skills + middleware + sandbox | Deep Agents harness | `DeepAgentFactory.create_deep_agent` |
| **Workflows** (branch icon) | Visual workflows — nodes + edges drawn on a canvas, stored as JSON in Postgres | LangGraph runtime (visual) | Workflow Studio, executor §12 |
| **Graph** (network icon) | Introspect and run code-defined LangGraph graphs (`backend/langgraph/*.py`) | LangGraph runtime (code) | Graph Studio §13 |

So the IDE itself is organized around the stack: the framework (Agents), the harness
(DeepAgents), and both faces of the runtime (Workflows visually, Graph by introspection). §2's
"four categories" taxonomy and this sidebar are the same answer seen from two sides.

---

## 4. Value proposition & use cases — LangChain stack vs Doubao · WorkBuddy · OpenClaw · Hermes

The six tools in this document live in **two different worlds**. OpenClaw, Hermes, Doubao, and
WorkBuddy are *products you use*; LangChain, LangGraph, and Deep Agents are *building blocks you
build with*. Comparing them on the same axis is like comparing a kitchen with a restaurant.

| Axis | LangChain stack (LangChain / LangGraph / DeepAgents) | OpenClaw | Hermes Agent | WorkBuddy | 豆包 Doubao |
|---|---|---|---|---|---|---|
| Category | Dev framework + runtime + harness | Personal messaging agent | Self-improving personal agent | Personal AI agent workstation ("AI colleague") | Consumer assistant product |
| You are | a developer building systems | an end-user delegating | an end-user delegating | an end-user delegating (workplace) | a consumer |
| Orchestration | explicit graph, durable, HITL, checkpointed | session transcript + tool loop | planning + skill loop | Ask / Plan / Craft modes + Expert Groups | product-managed Task Mode |
| Data & runtime | yours — your DB, your infra, your models | your machine, your keys | your VPS, your keys | Tencent Cloud (closed); enterprise tier can private-deploy | ByteDance cloud (closed) |
| Extension | code + middleware + skills | skills + plugins | self-authored skills + MCP | 100+ skills + MCP connectors + custom skills | Coze no-code |
| Multi-agent | supervisor / swarm / subagents (explicit) | subagents (basic) | `delegate_task` subagents | Expert Groups (skill → expert → expert group) | product-managed |
| Best for | production agent systems, enterprise workflows | 24/7 personal automation via chat | self-hosted compounding research/ops agent | everyday office automation — docs, data, meetings, reports | everyday consumer AI (esp. Chinese) |
| Security & privacy | encrypted secrets, self-hosted DB, HITL gates, audit log | broad system access — your permissions | skills need review + isolation | sandboxed execution + Ask/Plan/Craft gates; enterprise admin & audit | vendor cloud, Chinese jurisdiction |

### 4.1 Security & data privacy

Where your data lives decides everything — and it is the sharpest differentiator between the
self-hosted LangChain stack and the hosted consumer products.

| Security axis | LangChain stack (LangConfig) | OpenClaw | Hermes Agent | WorkBuddy | 豆包 Doubao |
|---|---|---|---|---|---|---|
| Where data lives | your PostgreSQL + your infra; `STORAGE_MODE=db` puts even skills/files in the DB | your local machine | your VPS | Tencent Cloud (Chinese jurisdiction); enterprise tier private/VPC deploy | ByteDance cloud (Chinese jurisdiction) |
| Transparency | open source (MIT) — fully auditable | open source (MIT) | open source | closed source | closed source, black box |
| Secrets | encrypted at rest (`encryption.py`, settings documents `models.api_keys`, §16.2) | env keys on disk | env keys on disk | managed by Tencent Cloud | managed by ByteDance |
| Action safety | sandboxed shell, workspace-scoped filesystem, HITL approval gates, audit log | broad system access — permissions are on you | skills need review + container isolation | sandbox + Ask/Plan/Craft gates; enterprise permission & audit admin | platform-managed, no per-org policy |
| Auditability | `execution_events` + `audit_logs` (Postgres), Langfuse/LangSmith tracing | session transcripts on disk | local logs | enterprise admin console (usage, member stats, audit) | vendor-side, limited export |
| Compliance | deploy in your region, you own retention (GDPR, HIPAA…) | personal tool (n/a) | personal tool (n/a) | hosted in China; private tier for data residency | vendor compliance; jurisdiction questions for enterprises |

Takeaways:

- **LangConfig / the stack** — data never leaves your infrastructure; every run is checkpointed
  to Postgres, every action lands in an audit log; risky tools sit behind approval gates
  (`hitl` routes); secrets are encrypted at rest; and `STORAGE_MODE=db` moves even skills and
  files into *your* database instead of a vendor's bucket.
- **OpenClaw / Hermes** — local-first is privacy-friendly and works offline, but both receive
  *broad* access to your machine and chat accounts; there is no team policy or review layer, so
  safety rests on your own discipline (and, for Hermes, on reviewing its auto-written skills).
- **Doubao** — the least control: prompts, documents, and outputs flow through ByteDance
  infrastructure under Chinese jurisdiction. Fine for personal use; a blocker for enterprises
  with data-residency or secrecy requirements.
- **WorkBuddy** — the most "ready-to-use" of the products: sandboxed, an Ask/Plan/Craft risk
  dial, and a genuine enterprise tier with an admin console and private deployment. But it is
  closed source and Tencent-hosted by default: prompts, files, and outputs run through Tencent
  infrastructure unless you take the private edition, and you cannot re-orchestrate or self-host
  the product logic itself.

**Purely local — and it scales outward.** Skills, prompts, tools, checkpoints, and outputs are
plain artifacts you can run entirely on-prem: no vendor round-trip for any of them. When you
outgrow one machine the stack *expands* instead of replacing you — swap in cloud models, add
S3 storage (`STORAGE_MODE=s3`), deploy the same exported agents to your own servers. OpenClaw
is an all-in-one agent bolted to one machine; Doubao and WorkBuddy are 100% vendor-hosted
(WorkBuddy only leaves the cloud in its private enterprise edition); only the stack lets
you start local and scale on your own terms.

**Enterprise-grade open source.** The LangChain ecosystem — LangChain, LangGraph, LangSmith,
plus a rich community of tools, templates, and integrations — is maintained by a company with
a large contributor community, which is what enterprises need: auditability, governance,
integration partners, and support paths. OpenClaw is essentially one maintainer's all-in-one
personal agent (hard to extend to team/enterprise needs); Doubao's and WorkBuddy's enterprise
stories are vendor terms on closed clouds (WorkBuddy's private edition still runs Tencent's
closed software on your hardware).

### 4.2 Who it's for — users & use cases

| Persona | Use case | Best tool | Why |
|---|---|---|---|
| Consumer | everyday Q&A, Chinese writing, image/audio/video generation | 豆包 Doubao | free, multimodal, best-in-class Chinese |
| Individual power user | 24/7 personal assistant in WhatsApp/Telegram/email | OpenClaw · Hermes | local, chat-native, autonomous, self-improving |
| Workplace individual / enterprise employee | everyday office automation — documents, data reports, meeting minutes, PPT | WorkBuddy | no-deploy, out-of-the-box, 100+ skills, remote IM control |
| Researcher | long-horizon research, literature surveys, deep-dive reports | Deep Agents (LangConfig) · Doubao Deep Research | planning + subagents + context management; Doubao for consumer-grade |
| Strategy & business analyst | deep research on strategy — competitor scans, market reports, decision memos | Deep Agents (LangConfig) | planning + subagents + long-horizon research |
| Developer | quick tool-calling / RAG agents | LangChain `create_agent` | fastest standard agent loop, 100+ integrations |
| Platform engineer | durable, stateful, HITL, multi-agent production workflows | LangGraph | durable execution, checkpoints, interrupts, persistence |
| AI product teams | build and ship an AI app on your own data/model | LangConfig (stack + export) | visual build + standalone Python export |
| Ops & automation teams | cron schedules, file-watch triggers, background jobs | LangConfig | `schedules`, `triggers`, `background_tasks`, `webhooks` routers |
| Data analysts | CSV → SQLite → charts, dashboards, presentations | LangConfig | `analysis`, `presentations`, `data_dashboard` pipeline |
| Business systems / enterprise IT | DB CRUD + agent on existing transactional systems (CRM, ERP, finance) | LangConfig | SQL tools + graph orchestration + HITL approval against your existing Postgres/DBs |
| No-code / AI app builders | assemble AI apps visually, zero code, full ownership | LangConfig | canvas + graph editing + standalone export (Coze if product-managed is fine) |
| Learners & educators | learn LangChain / LangGraph by doing | LangConfig | live graph visualization, step-through runs, state inspector, run console |

### 4.3 Head-to-head — LangChain stack vs Doubao · OpenClaw · Hermes

- **Native multi-agent, by design.** Collaboration is a first-class pattern in the stack:
  supervisor / swarm / sub-agents (Deep Agents' `delegate_task`), LangGraph sub-graphs, and
  shared graph state — so you compose specialized agents (planner, coder, reviewer, executor),
  each with isolated context, coordinated by explicit edges. OpenClaw and Hermes each run *one*
  agent loop on *one* machine; Doubao's multi-agent behavior is opaque and product-managed.
- **vs 豆包 (Doubao)** — Doubao is a closed product: fixed model, product-managed
  orchestration, data in ByteDance's cloud, and **no setup transparency** — prompts, tools,
  and the graph behind your agent are black-box; you cannot inspect, version, or reproduce
  them. The stack wins where you need *control* — choose the model, define the graph, own the
  data, self-host, ship code. Doubao wins on zero-setup consumer experience and
  Chinese-language quality at scale.
- **vs OpenClaw** — OpenClaw is a *personal* agent for one machine, reached through chat apps.
  LangGraph / Deep Agents are for *systems*: multi-tenant, durable, auditable, deployable
  anywhere. They answer different questions — "automate my Mac" vs "operate a production
  service". LangConfig can build an OpenClaw-style assistant *and* a corporate workflow in the
  same IDE.
- **vs Hermes** — Hermes's self-improving skill loop is genuinely novel; LangConfig's
  SkillsMiddleware provides the same progressive-disclosure skills (a `SKILL.md` catalog read
  on demand — §14) but under *your* control: skills are reviewed, stored in Postgres when
  `STORAGE_MODE=db`, and part of an auditable, governed runtime rather than an autonomous
  self-modifying agent.
- **vs WorkBuddy** — WorkBuddy is a *ready-made* personal agent workstation: no deploy,
  pre-integrated, sandboxed, with an excellent enterprise tier. The stack answers a different
  question: *you* are the builder — the graph is explicit, the middleware is yours, the data
  stays on your infrastructure, and you ship runnable code. WorkBuddy executes *inside its own
  product*; the stack delivers agents you can export and run anywhere. LangConfig can build a
  WorkBuddy-style office assistant *and* a governed enterprise workflow in the same IDE.

### 4.4 Why the LangChain stack wins where it wins

- **Over Doubao** — Doubao is closed: you cannot change its orchestration, choose its model,
  self-host it, or own the data it touches. LangGraph gives you explicit, checkpointed control
  flow; you pick any provider (the shipped `DEFAULT_MODEL` is Claude Haiku 4.5, with DeepSeek available); and you ship runnable code
  instead of renting a feature.
- **Over OpenClaw / Hermes** — those are single-user personal agents wired to *one machine* and
  its chat apps. The LangChain stack is engineered for *systems*: durable state that survives
  restarts, human-in-the-loop approvals, multi-agent topologies, Postgres persistence, team
  governance, and deployment anywhere.
- **Over WorkBuddy** — WorkBuddy automates *its own* workspace: you work inside Tencent's
  product, on Tencent's cloud, with the skills Tencent ships. The stack is the *build layer*:
  any provider, your data, your graph, exportable code, deployable anywhere — including inside
  an enterprise's own infrastructure, which is exactly where WorkBuddy's private edition still
  runs Tencent's closed software.

### 4.5 LangConfig's unique value proposition

LangConfig is a **visual Agent IDE ("Workbench") on exactly this stack** — LangChain V1 +
LangGraph + DeepAgents 0.7.1 (see §1 and §11). Agents are stored as JSON config and **compiled
into real LangGraph executables at runtime**, which combines the convenience of a product with
the control of a framework:

| Capability | Doubao / OpenClaw / WorkBuddy | LangConfig (on the LangChain stack) |
|---|---|---|
| Build without code | Coze no-code (product-managed) | Visual canvas + graph editing, *and* full code access |
| Runtime control | none (fixed product) | explicit graph, interrupts, checkpoints, Postgres |
| Human-in-the-loop | no | yes (`hitl` routes, approval gates) |
| Autonomy dial | none — the product decides | per-workflow: fully autonomous, or HITL-gated |
| Multi-agent | product-managed | supervisor / swarm / subagents, wired by you |
| Data ownership | vendor cloud | your PostgreSQL, your files, your skills |
| Setup transparency | opaque prompts/graphs (black box) | inspectable JSON config compiled to a visible, versioned graph |
| Ship it | n/a (you stay in the product) | export standalone Python that runs anywhere |
| Learn by doing | n/a | live graph visualization, step-through runs, state inspector — a built-in way to learn LangGraph |

### 4.6 Use-case decision rule

- everyday consumer help, Chinese-language work → **Doubao**;
- everyday office automation on a desktop workstation — docs, data, meetings, PPT → **WorkBuddy**;
- a 24/7 personal assistant inside WhatsApp/Telegram → **OpenClaw** (or **Hermes** if you want a
  self-improving skill library);
- building an agent *product or enterprise workflow* — tool-calling/RAG → **LangChain
  `create_agent`**; branching/durable/stateful/HITL → **LangGraph**; long-horizon autonomous
  research/coding → **Deep Agents**;
- you want to build, test, and *ship* any of those visually → **LangConfig**, which rides the
  same stack and exports runnable Python;
- working against existing transactional / legacy business systems — DB CRUD + agent (SQL
  tools, graph orchestration, HITL approval on your Postgres) → **LangConfig**;
- assembling AI apps with no code but full ownership → **LangConfig** (Coze if
  product-managed is fine);
- learning LangChain / LangGraph visually → **LangConfig** — the canvas shows the real graph,
  and you step through runs and inspect state as you learn.

### 4.7 Platform + ready-to-use agents — a differentiator

Most products are either a **platform** (you build everything) or a **product** (you consume what
we ship). LangConfig is deliberately **both**: the same IDE that incubates new agents also ships a
**starter line of enterprise agents**, pre-built on the stack above and stored exactly like any
other agent — a `deep_agent_templates` row you can inspect, edit, and export.

| Ready-to-use agent | What it does | Built on |
|---|---|---|
| **Enterprise strategic consultancy agent** | Long-horizon deep research: market/competitor scans, strategy memos, and decision support with citations — a DeepAgent with planning, subagents, and context management | Deep Agents |
| **Enterprise ontology management agent** | Govern your domain model: create, version, and audit entities/relations; map business terms to a canonical ontology; validate schemas and flag drift | LangChain + skills + workflows |
| **Enterprise admin agent** | Everyday operations over your systems: DB CRUD on existing transactional databases, HITL approval gates, report and audit pulls — the "DB CRUD + agent" pattern | LangGraph + SQL tools |
| **The Agent IDE (LangConfig)** | The fourth "agent" is the incubator: build, test, and ship the next enterprise agent visually — no code, full ownership, standalone export | The whole stack |

Why this is a differentiator:

- **Two lanes, one stack.** Ready-made agents give instant value to non-developers; the IDE gives
  developers a place to evolve them. Neither lane exists in the alternatives: Doubao/Coze manage
  agents in their cloud, OpenClaw/Hermes are single-agent personal tools, WorkBuddy's agents stay
  inside its own workspace, and bare LangChain/LangGraph ship no productized agents at all.
- **Pre-built ≠ black box.** Unlike product agents, every ready-made agent is a config you can
  open in the IDE — inspect its graph, edit the prompt, swap tools, and re-export. The starter
  line is a *starting point*, not a walled garden.
- **The line grows through the platform.** New use cases are incubated in the IDE and, after
  review, can be promoted into the ready-made library — a flywheel that product-only vendors
  can't replicate.

---

## 5. The layer map (everything at a glance)

```mermaid
%%{init: {"themeVariables": {"fontSize": "18px"}}}%%
flowchart TB
    subgraph UI["1 · FRONTEND LAYER — React 19 + TypeScript + Tailwind 4"]
        direction LR
        A1["IDE shell<br/>components/layout2/"]
        A2["Features<br/>workflows · agents · graph studio · chat"]
        A3["API clients<br/>lib/api/ (typed)"]
    end

    subgraph API["2 · API LAYER — FastAPI · 43 routers (main.py)"]
        direction LR
        R1["agents + deepagents<br/>CRUD · prompt-preview · export"]
        R2["chat + workflows<br/>SSE · orchestration · hitl"]
        R3["rag + doc_chat + memory<br/>knowledge · store · agents_md"]
        R4["tools + skills + workspace<br/>models · settings"]
        R5["graph_studio<br/>code-defined graphs · threads · SSE runs"]
    end

    subgraph SVC["3 · SERVICE LAYER — builders + managers"]
        direction LR
        F1["AgentFactory<br/>core/agents/factory"]
        F2["DeepAgentFactory<br/>services/deepagent_factory"]
        E1["export codegen<br/>api/agents/deep_agents.py + agent_bundle.py"]
        W1["WorkspaceManager<br/>+ 20 support services"]
    end

    subgraph CORE["4 · CORE ENGINES"]
        direction LR
        C1["workflows<br/>executor · checkpoints · events"]
        C2["codegen"]
        C3["skills + middleware"]
        C4["models + context"]
    end

    subgraph LIB["RUNTIME LIBRARIES"]
        direction LR
        L1["deepagents SDK"]
        L2["langchain V1 + langgraph"]
        L3["LLM providers"]
        L4["Tavily search"]
    end

    subgraph DB["5 · DATA LAYER"]
        D1(("PostgreSQL 16<br/>+ pgvector :5432"))
        D2["Tables:<br/>deep_agent_templates · custom_tools · skills<br/>workflows · agent_memories · execution_events"]
    end

    A3 --> R1
    A3 --> R2
    A3 --> R3
    A3 --> R4
    A3 --> R5

    R1 --> F1
    R1 --> F2
    R1 --> E1
    R2 --> F1
    R2 --> F2
    R3 --> F1
    R4 --> F1

    F1 --> C1
    F1 --> C3
    F1 --> C4
    F2 --> C1
    F2 --> C3
    C1 --> L2
    R5 --> L2

    F1 --> L2
    F2 --> L1
    L1 --> L2
    F1 --> L3
    F2 --> L3

    F1 --> D1
    F2 --> D1
    C1 --> D1
    D1 --> D2

    classDef ui fill:#e2e8f0,stroke:#334155,color:#0f172a,font-size:18px;
    classDef api fill:#bfdbfe,stroke:#1d4ed8,color:#1e3a8a,font-size:18px;
    classDef svc fill:#bbf7d0,stroke:#15803d,color:#14532d,font-size:18px;
    classDef core fill:#ddd6fe,stroke:#6d28d9,color:#4c1d95,font-size:18px;
    classDef lib fill:#fde68a,stroke:#b45309,color:#78350f,font-size:18px;
    classDef db fill:#fecaca,stroke:#b91c1c,color:#7f1d1d,font-size:18px;

    class A1,A2,A3 ui;
    class R1,R2,R3,R4,R5 api;
    class F1,F2,E1,W1 svc;
    class C1,C2,C3,C4 core;
    class L1,L2,L3,L4 lib;
    class D1,D2 db;
```

---

## 6. What is `backend/api/agents/deep_agents.py`?

It is the **REST API router (controller) for DeepAgents** — registered in `main.py` as the
"DeepAgents configuration and export" router. It does **not** build agents and does **not**
export by itself; it:

| Endpoint group                                                                  | Responsibility                         | Delegates to                                                 |
| ------------------------------------------------------------------------------- | -------------------------------------- | ------------------------------------------------------------ |
| `POST/GET /api/deepagents/`, `GET /api/deepagents/{id}`, `GET /templates` | DeepAgent CRUD + built-in templates    | `models.deep_agent` (DB)                                   |
| `POST /api/deepagents/prompt-preview`                                         | System-prompt assembly preview         | deepagents harness profiles (`_harness_profile_for_model`) |
| `/export`, `/code`                                                          | Export`.py` CLI / langconfig bundles | `api/agents/deep_agents.py` (codegen) + `services/agent_bundle.py` |

The actual builders are `core/agents/factory/` (normal agents) and
`services/deepagent_factory/` (deep agents) — `deep_agents.py` only exposes them over HTTP.

**The `use_deepagents` flag is the source of truth.** It lives in the agent's stored JSON
`config` and decides at runtime whether a row is treated as a normal agent or a DeepAgent:

- `api/agents/deep_agents.py` reads `config.get("use_deepagents", False)` to separate the two lists.
- `api/workflows/crud.py` checks the same flag (plus node type / `deepAgentId`) when a workflow
  node contains an agent, so the right factory is used during execution.

---

## 7. Frontend layer deep-dive (`src/`)

The UI is an **IDE shell** (Obsidian/VS Code style) that maximizes canvas space for visual
workflow design.

### The IDE shell — `src/components/layout2/`

| Component                                                          | Purpose                                                                             |
| ------------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| `AgentEditor` / `AgentHomePage`                                | 4-section structured editor (Overview · Prompt · Tools · JSON) for normal agents |
| `DeepAgentEditor` / `DeepAgentCreator` / `DeepAgentHomePage` | Same 4-section editor for DeepAgents, with export buttons                           |
| `WorkflowEditor` / `WorkflowStudioPage`                        | Visual workflow builder                                                             |
| `NodeSidebar`                                                    | Right-hand config panel for the selected canvas node                                |
| `SkillEditorTab` / `SkillBrowserSidebar`                       | Skill authoring + browsing                                                          |
| `ToolEditor`                                                     | Custom tool builder                                                                 |
| `ModelHomePage` / `SearchProvidersSidebar`                     | Model defaults + search-provider API keys                                           |
| `KnowledgeView` / `NotebookViewer`                             | RAG knowledge + notebooks                                                           |
| `PromptBrowserSidebar`                                           | Prompt library                                                                      |
| `editorChatToolbar` / `chatStore.ts` / `useLayout.tsx`       | In-editor chat + layout state                                                       |

### Feature modules — `src/features/`

| Module                                                                         | Purpose                                                                                                                                                                       |
| ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `workflows/`                                                                 | Full ReactFlow canvas (nodes, edges, node-config, toolbar, results, execution, settings)                                                                                      |
| `agents/ui/PromptCanvas.tsx`                                                 | Visual prompt editing                                                                                                                                                         |
| `deepagent-studio-v2/`                                                       | Modern DeepAgent studio:`ModernStudioCanvas`, agent picker, capability bar, main/sub-agent nodes, tool nodes, auto-layout                                                   |
| `chat/`                                                                      | Chat UI with SSE streaming (`useChatController`, `useChatStreaming`, `streamChatEvents.ts`), sessions, files, metrics, HITL interrupts, thinking blocks, analysis panel |
| `graph-studio/`                                                              | Graph Engineering activity: assistant + database sidebar, ReactFlow canvas (auto-layout, conditional edges, run-path, node-click detail popup), test-run console, inspector, chat input with interrupt — see §13  |
| `tools/ui/`                                                                  | `CustomToolBuilder` + `ToolTemplateGallery`                                                                                                                               |
| `knowledge/`, `memory/`, `settings/ui/`, `projects/AgentsMdEditor.tsx` | Supporting views                                                                                                                                                              |

### Typed API clients — `src/lib/api/`

`agents.ts`, `chat.ts`, `workflows.ts`, `tools.ts`, `skills.ts`, `documents.ts`, `files.ts`,
`projects.ts`, `schedules.ts`, `settings.ts`, `triggers.ts`, `backgroundTasks.ts` — one thin
fetch wrapper per backend domain. **The intended rule is that no component talks to the
backend directly**; everything should go through these clients, which keeps the API surface
testable and consistent. (Known drift: ~20 files still use raw `fetch`/`EventSource` outside
`lib/`, and `GoogleOAuthButton.tsx` / `usePresentationJob.ts` hardcode `localhost:8765` —
consolidating these into clients is tracked as a cleanup item.)

```mermaid
flowchart LR
    subgraph Pages["pages/"]
        P1["HomePage"] --> P2["PlaygroundPage"]
        P3["SettingsPage"] --> P4["ProjectsPage"]
        P5["AnalysisPage"] --> P6["PromptAssemblyPage"]
    end
    subgraph Shell["components/layout2/ (IDE shell)"]
        SH1["Activity Bar + Sidebar"] --> SH2["Tabbed Workspace"]
        SH2 --> SH3["NodeSidebar (config)"]
        SH2 --> SH4["Bottom Panel (chat/logs)"]
    end
    subgraph Clients["lib/api/ (typed clients)"]
        C1["agents.ts · chat.ts · workflows.ts"]
        C2["tools.ts · skills.ts · files.ts · settings.ts"]
    end
    Shell --> Clients
    Pages --> Shell
    Clients -->|"HTTP / SSE :8765"| API["FastAPI backend"]
```

---

## 8. Backend API layer — the 43 routers

`backend/main.py` registers **43 routers** on the FastAPI app. They are thin controllers:
parse the request, delegate to a service/factory, and stream the result.

| Group                | Routers (in`main.py` order)                                                                               | Purpose                                                                                                                   |
| -------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Health & debug       | `health`, `debug`                                                                                       | Liveness + dev-only diagnostics                                                                                           |
| Agents               | `agents` (templates), `agent_generator`, `action_presets`, `images`                                 | Agent-template CRUD, AI agent generation, action presets, image storage — normal agents live in `deep_agent_templates` via `/api/deepagents/` |
| DeepAgents           | `deepagents`, `chat`                                                                                    | DeepAgent CRUD/export + DeepAgent chat testing                                                                            |
| Workflows            | `workflows`, `orchestration`, `hitl`, `checkpoints`                                                 | Workflow CRUD/execute, simplified orchestration, human-in-the-loop approvals, checkpoint restore                          |
| Graph Engineering    | `graph_studio`                                                                                    | Code-defined graph hosting (`backend/langgraph/*.py`): introspection, threads, SSE runs, target-DB switching, run interrupt — see §13 |
| Chat & memory        | `memory`, `store`, `agents_md_router`, `chat_skill_review`                                          | Agent memory, long-term store, AGENTS.md (MemoryMiddleware), data-skill review                                            |
| Knowledge / RAG      | `rag`, `graphindex_chat`, `doc_chat`, `kv`, `analysis`                                            | RAG ingestion/search, graph-index chat, folder-based doc-chat, KV store, CSV→SQLite→charts                              |
| Tools & skills       | `custom_tools`, `tool_registry`, `skills`                                                             | User tools, native tool registry (single source of truth), skills system                                                  |
| Docs & classic graph | `agent_documents`, `classic_graph`                                                                     | DB-mode document library; classic LangGraph builder API                                                                   |
| Workspace & projects | `projects`, `tasks`, `workspace`, `background_tasks`                                                | Projects, task workspaces, file trees, background job queue                                                               |
| Models & settings    | `settings`, `search_providers`, `local_models`, `model_capabilities`, `model_routes`, `schemas` | Config, search-provider keys, local models, capability profiles, model invocation (Playground), structured-output schemas |
| Automation & extras  | `schedules`, `triggers`, `webhooks`, `notebooks`, `presentations`, `google_auth`                | Cron scheduling, file-watch triggers, webhook receivers, notebooks, presentation generation + OAuth                       |

```mermaid
flowchart LR
    subgraph Routers["FastAPI app (main.py)"]
        RA["agents + deepagents + chat"]
        RW["workflows + orchestration + hitl + checkpoints"]
        RG["graph_studio<br/>code-defined langgraph modules"]
        RK["rag + doc_chat + graphindex_chat + kv + analysis"]
        RT["custom_tools + tool_registry + skills"]
        RM["memory + store + agents_md"]
        RX["schedules + triggers + webhooks + notebooks"]
    end
    Routers --> SVC["Service / Factory layer"]
    SVC --> CORE["Core engines"]
    SVC --> DB[("PostgreSQL")]
    RG --> CORE
```

---

## 9. Service layer deep-dive (`backend/services/`)

This is the brain: **builders** turn persisted config into runnable graphs; **managers**
own the filesystem, workspaces, and side effects.

### Builders (compile config → LangGraph)

| Service                                                      | Entry point                                                     | Produces                                                   |
| ------------------------------------------------------------ | --------------------------------------------------------------- | ---------------------------------------------------------- |
| `core/agents/factory/assembly.py`                          | `AgentFactory.create_agent()` (L29)                           | Normal agent via langchain V1`create_agent`              |
| `services/deepagent_factory/assembly.py`                   | `DeepAgentFactory.create_deep_agent()` (L29)                  | DeepAgent via`deepagents.create_deep_agent`              |
| `services/deepagent_factory/{preflight,shared,support}.py` | helpers                                                         | Config validation, shared wiring, SDK compatibility guards |
| `api/agents/deep_agents.py` (codegen)                        | `export_deepagent()` / `download_agent_code()` | Standalone`.py` CLI or import/export bundle (`services/agent_bundle.py`) |

### Managers & support services

| Service                                                                                                                           | Responsibility                                                                      |
| --------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `workspace_manager.py`                                                                                                          | Project/task workspace directories; sandbox and filesystem backends are scoped here |
| `chat_session_manager.py`                                                                                                       | Chat session lifecycle (start/end/resume/recover)                                   |
| `conversation_context.py`, `context_window_manager.py`, `context_retrieval.py`, `context_document_indexer.py`             | Context packing, token-window management, retrieval                                 |
| `mcp_manager.py`                                                                                                                | MCP server/tool loading                                                             |
| `scheduler_service.py`, `triggers/file_watcher.py`                                                                            | Cron + file-watch triggers                                                          |
| `presentation_service.py`, `dashboard_generator.py`, `data_dashboard.py`, `data_skill_generator.py`, `csv_to_sqlite.py` | Data analysis → presentations/dashboards                                           |
| `notebook_kernel_manager.py`                                                                                                    | Python kernel for notebooks                                                         |
| `event_bus.py`, `audit_service.py`, `deepagents_instrumentation.py`                                                         | Observability, audit logs, Langfuse callbacks                                       |
| `local_model_service.py`, `llama_config.py`                                                                                   | Local model config                                                                  |
| `oauth_service.py`, `encryption.py`                                                                                           | Google OAuth + secret encryption                                                    |
| `diff_service.py`, `file_storage.py`, `image_storage.py`, `storage_estimator.py`                                          | Diff/versioning + storage                                                           |
| `agents_md_service.py`                                                                                                          | Project`AGENTS.md` for MemoryMiddleware                                           |
| `token_counter.py`, `output_formatter.py`                                                                                     | Token counting, response formatting                                                 |
| `agent_generator_service.py`, `agent_utils.py`                                                                                | AI agent generation, model resolution (`resolve_model`)                           |
| `workflow_config_service.py`                                                                                                    | Workflow config helpers                                                             |

### Dashboards — the **Analysis** activity

The Analysis activity (bar-chart icon in the ActivityBar → `/analysis` →
`src/pages/AnalysisPage.tsx`) is a **static-HTML loader plus a meta-driven chat**:
it lists `*.html` from `data/analysis_dbs/` via `GET /api/analysis/dashboards`
(parsing each file's `LangConfig Dashboard Meta` head comment for `db:`, `skills:`,
`entry:`), renders the page in an iframe via `GET /api/files/<name>` (which rewrites
Plotly's CDN URL to `/static/plotly.min.js` so pages work offline), and wires the
Chat panel to `/api/analysis/chat` using the dashboard's declared DB + skill.

Three generation regimes feed it:

| Regime | Code | LLM? | Examples |
|---|---|---|---|
| **Upload / demo** | `services/dashboard_generator.py` (`generate_dashboard`) + the prompt in `api/analysis/routes.py` (`_auto_generate_dashboard` → `_run_analysis_agent`) | ✅ yes (optional companion `.skill.md`) | `business_dashboard`, `sales_dashboard*`, `dashboard_<hash>` |
| **ERP study case** | `backend/skills/erp-analyst/9_erp_dashboard.py` | ❌ deterministic (`Mode: static-embed`) | `erp_dashboard_*.html` |
| **Sun Hing study case** | `data/analysis_dbs/gen_sunhing_kpi_dashboard.py` — one script builds the hub + 5 factor sub-dashboards (+ gantt/data) and copies the ERD/intro/employees/liability masters | ❌ deterministic (byte-stable modulo a timestamp) | `sunhing_dashboard*.html` |

See **[docs/sunhing-dashboards.md](sunhing-dashboards.md)** for the Sun Hing
producer map, the 28-KPI coverage proof, the determinism guarantee, and the known
drift risks (two divergent DB copies; copy-propagated static pages).

---

## 10. Core engines deep-dive (`backend/core/`)

Reusable engines that both agent types and workflows share.

### `core/agents/`

- `factory/` — `assembly.py` (the `AgentFactory.create_agent` builder), `llm.py` (LLM wiring + subagent construction), `prompting.py`, `validation.py`, `shared.py`
- `specialized/` — `json_agent.py`, `pandas_agent.py`, `sql_agent.py` (typed specialist agents)
- `delegation.py`, `memory.py`, `model_profiles.py`, `multimodal.py`, `templates.py`, `templates_specialized.py`, `tool_loader.py` (`ToolLoader.load_native`)

### `core/workflows/` — the execution engine (see §12)

`executor/builder.py` · `executor/execution.py` · `executor/nodes.py` · `executor/shared.py` ·
`checkpointing/manager.py` (Postgres checkpointer) · `events/emitter/` (progress, callbacks) ·
`graph.py`, `graph_state.py`, `nodes.py`, `runner.py`, `state.py` ·
`supervisor.py`, `swarm.py`, `official_patterns.py` (reusable graph topologies)

### `core/codegen/`

`langgraph.py`, `workflow_exporter.py`, and `generators/` — `api_server.py`, `custom_tools.py`,
`nodes.py`, `nodes_configurable.py`, `routing.py`, `streamlit_app.py`, `streamlit_configurable.py`,
`templates.py`, `tools.py` — turns workflows into runnable code artifacts (Streamlit apps, API servers).

### `core/context/` — `compactor.py`, `content_blocks.py`, `runtime.py`, `synthesis.py`

### `core/middleware/` — `core.py`, `advanced.py`, `deep.py`, `dynamic_tools.py`, `presets.py`,

`question_detection.py`, `routing.py`, `tool_selection.py`

### `core/skills/` — `registry.py`, `sync.py`, `matcher.py`, `loader.py`

### `core/tools/` — `factory/` (base, builders, models), `adapters/llamaindex.py`,

`templates/` (api/cms/data/database/image/notification/python/social/video), `bigtool_registry.py`,
`execution_wrapper.py`, `seed.py`, and the DSH-shaped tool surface (§16.3):
`definition.py` (declarative `ToolDefinition`), `registry.py` (DB-backed
`ToolRegistry` + ordering + `resolve_for_agent`), `pipeline.py`
(`apply_tool_pipeline` — approval guard / timeout / output-schema normalization)

### `core/models/` — `registry.py`, `router.py`, `selector.py`, `hooks.py` (model routing/capabilities)

---

## 11. Agent build pipeline (runtime)

Both agent types are compiled on every chat/execution from their stored JSON config.

### Normal agent path

`AgentFactory.create_agent()` (`core/agents/factory/assembly.py:29`) → langchain V1
`create_agent` (the same API the exported code uses). Subagents are built recursively with
`create_agent` in `core/agents/factory/llm.py:281`.

### DeepAgent path

`DeepAgentFactory.create_deep_agent()` (`services/deepagent_factory/assembly.py:29`) does, in order:

1. **Import guard** — if `deepagents` isn't installed, fall back to a regular agent (`_fallback_to_regular_agent`).
2. **Config validation** — warnings, not hard failures.
3. **Observability** — Langfuse callbacks (`_setup_callbacks`).
4. **Load base tools** — native + custom + MCP + vector store (`_load_base_tools`).
5. **Middleware tools** — from configured middleware types (`DeepAgentsMiddlewareFactory.create_all_tools`).
6. **Subagents** — compiled separately with workspace context for file-writing tools.
7. **Middleware instances** — MemoryMiddleware (AGENTS.md via FilesystemBackend), FilesystemMiddleware (scoped to task workspace; skipped when a disk backend is active because the SDK injects its own), SummarizationMiddleware (token trigger), SubAgentMiddleware (auto-created by the SDK — adds the `task` tool).
8. **Checkpointer** — PostgreSQL conversation persistence (`get_checkpointer()`).
9. **Skills staging** — stage the full skill catalog (builtin + personal roots) into `<workspace>/skills/` (config.skills only *pins* availability; discovery is metadata-driven) and point `SkillsMiddleware` at it with a `FilesystemBackend`.
10. **Sandbox** — optional `LocalShellBackend` for an `execute` shell tool.
11. **`deepagents.create_deep_agent(...)`** → compiled `LangGraph CompiledStateGraph` ready to stream.

### The full pipeline

```mermaid
flowchart LR
    P1["API call:<br/>POST /api/deepagents/{id}/chat<br/>or workflow node"] --> P2["DeepAgentFactory.create_deep_agent()"]
    P2 --> P3["Load tools<br/>native + custom + MCP<br/>(tool dedup when disk backend set)"]
    P3 --> P4["Stage skills into<br/><workspace>/skills/<br/>+ FilesystemBackend"]
    P4 --> P5["deepagents.create_deep_agent<br/>(skills, middleware, subagents)"]
    P5 --> P6["CompiledStateGraph<br/>(Postgres checkpointer)"]
    P6 --> P7["SSE stream:<br/>tool calls + final answer"]
    P7 --> P8["Conversation persisted<br/>in PostgreSQL"]

    style P5 fill:#fef3c7,stroke:#d97706,color:#111
    style P6 fill:#fee2e2,stroke:#dc2626,color:#111
```

*Normal agents follow the same path via `AgentFactory.create_agent()` → langchain V1 `create_agent`
(no skills/sandbox steps).*

### Tool deduplication note

The deepagents library always injects its own **FilesystemMiddleware** (required middleware)
with `ls / read_file / write_file / edit_file / glob / grep` tools scoped to the backend root.
When a **disk backend** (skills/sandbox/Filesystem) is active, the assembly drops our native
filesystem tools so the agent exposes one set of file tools — the backend-scoped ones win.

---

## 12. Workflow execution engine (`core/workflows/`)

Workflows are **visual graphs** (ReactFlow on the frontend) persisted as JSON nodes/edges,
then executed by this engine.

```mermaid
flowchart TB
    subgraph HTTP["API (api/workflows/ + api/orchestration/)"]
        H1["POST /api/orchestration/execute"]
        H2["GET /api/orchestration/workflows/{id}/stream<br/>(SSE)"]
        H3["GET /api/orchestration/workflows/{id}/events"]
        H4["GET /api/workflows/{id}/events<br/>GET /tasks/{id}/events"]
    end

    subgraph ENGINE["core/workflows/"]
        E1["executor/builder.py<br/>Build StateGraph from stored nodes"]
        E2["executor/execution.py<br/>Run + persist execution state"]
        E3["checkpointing/manager.py<br/>AsyncPostgresSaver checkpoints"]
        E4["events/emitter/<br/>progress + callback events"]
        E5["supervisor.py · swarm.py · official_patterns.py<br/>Multi-agent topologies"]
        E6["executor/nodes.py<br/>Node dispatch (agent / tool / deepagent / llm)"]
    end

    H1 --> E1
    H2 --> E2
    E1 --> E6
    E6 --> E4
    E2 --> E3
    E3 --> DB[("PostgreSQL<br/>executions · events")]
    E4 --> H3
    E4 --> H4

    style E2 fill:#dcfce7,stroke:#16a34a,color:#111
    style E3 fill:#fee2e2,stroke:#dc2626,color:#111
```

Key mechanics:

- **Node dispatch** — each workflow node can be an LLM call, a tool, a normal agent, a
  DeepAgent node (resolved by the `use_deepagents` flag, `executor/nodes.py:237-245`), or a
  supervisor/swarm pattern.
- **Checkpointing** — enabled by default; every execution step is checkpointed to Postgres
  via the `AsyncPostgresSaver`, so executions can be paused, resumed, and restored
  (`api/workflows/checkpoints.py` → `checkpointing/utils.py`). HITL `interrupt_before` is
  wired from `APPROVAL_NODE`s at compile time.
- **Event streaming** — the emitter pushes progress + callback events over SSE; the UI
  subscribes via `useWorkflowStream` to update the canvas live.
- **Orchestration & HITL** — `orchestration` routes drive multi-step runs; `hitl` routes
  provide human-approval interrupts mid-run.

---

## 13. Graph Engineering Studio (`api/graph_studio/`)

The **Graph Engineering** activity is the IDE-side companion to the workflow engine: it
hosts *code-defined* LangGraph agents (`backend/langgraph/*.py`) directly inside the
FastAPI process — no separate `langgraph dev` server is needed. The user picks an agent
in the sidebar, sees its graph structure on a canvas, creates threads, and test-runs it
with live SSE streaming.

### Backend — native graph hosting

`backend/api/graph_studio/routes.py` registers one router (`/api/graph-studio`, mounted in
`main.py`) exposing 13 endpoints (11 documented here plus the two marked †):

| Endpoint                                             | Purpose                                                            |
| ---------------------------------------------------- | ------------------------------------------------------------------ |
| `POST /assistants/search`                           | List code-defined assistants (registry)                            |
| `GET /assistants/{id}/graph`                        | Introspect nodes + edges (`compiled.get_graph()`) for the canvas   |
| `GET /assistants/{id}/schemas`                      | input / state / output jsonschemas (`get_*_jsonschema()`)          |
| `GET /assistants/{id}/code` †                       | Raw source of a code-defined assistant                             |
| `POST /threads/search`                              | List in-memory threads (filter by `graph_id`)                      |
| `POST /threads`                                     | Create a thread (uuid-hex id, status `idle`)                       |
| `GET /threads/{id}/state`                           | Checkpointed state via `compiled.aget_state(config)`               |
| `GET /threads/{id}/runs`                            | Run history for a thread                                           |
| `POST /threads/{id}/runs/stream`                    | SSE run — `messages/partial` · `values` · `updates`                |
| `POST /threads/{id}/runs/cancel`                    | Interrupt an in-flight run (stops at the next SSE event boundary)   |
| `GET /databases`                                    | List the Postgres databases the SQL tools can target + the active one |
| `GET /databases/summary` †                          | LLM-generated business summary of the active database              |
| `POST /databases/select`                            | Switch the SQL tools' target database at runtime (no `.env` edit)   |

Key mechanics:

- **Registry → lazy import.** `_ASSISTANT_REGISTRY` lists each assistant (`sql_agent`,
  `sql_agent_hitl`); `_load_compiled()` imports the module once via
  `importlib.util.spec_from_file_location` and caches the compiled graph. The graph
  modules import each other by plain name (e.g. `sql_setup_db`), so `backend/langgraph/`
  is put on `sys.path`. Registering a new entry is the only step needed to surface a new
  code-defined graph.
- **No service layer.** Studio endpoints call the LangGraph SDK (`get_graph`,
  `get_*_jsonschema`, `astream`, `aget_state`) directly — the graphs are *code*, not
  persisted JSON config, so there is nothing to compile at request time.
- **In-memory threads.** `_THREADS` / `_RUNS` are process-lifetime dicts (the studio is a
  scratch workspace). The compiled graph keeps its own thread-scoped checkpointer
  (`InMemorySaver`) + cross-thread memory store, so conversation state survives within the
  process — follow-ups skip the schema preamble thanks to memory.
- **SSE shape.** With a *list* of stream modes, `compiled.astream(...)` yields
  `(mode, payload)` tuples. Partial AIMessage chunks are accumulated per message id
  (content concatenation + `tool_call_chunks` merged by index), empty provider shells are
  stripped, and `values` / `updates` snapshots pass through as-is.
- **Node introspection for the popup.** `GET /assistants/{id}/graph` enriches every node
  via `_graph_node_info` / `_source_info` (`inspect.getsource`, best-effort/None-safe): a
  `kind` (`start` / `end` / `function` / `tool` / `subgraph` / `unknown`), module, file,
  line range + raw source code, `node.metadata`, and for tool-runner nodes the bound
  tools (name, description, their own source — `ToolNode.tools` or the newer
  `tools_by_name` dict). Clicking a canvas node opens a floating popup with this detail,
  deliberately different from classic LangChain Studio's inspector dock.
- **Run interrupt.** `_CANCEL_EVENTS` maps `thread_id → asyncio.Event`; the SSE generator
  checks the flag between events and raises `_RunCancelled` when the user hits Stop,
  emitting a clean `Run cancelled by user` error event — the graph checkpointer stays in
  a consistent state.
- **Target database switching.** The SQL tools in `sql_setup_db.py` resolve their database
  at call time: a runtime `_DB_OVERRIDE` (set by `POST /databases/select`) takes
  precedence over the `SQL_*` env config, so switching needs no graph re-import.
- **The SQL agents query Postgres.** `backend/langgraph/sql_setup_db.py` connects to the
  Postgres `chinook` database (read-only psycopg2 sessions; `information_schema`
  introspection emits Postgres-flavoured DDL). The target DB is configured via the
  `SQL_*` env block in the root `.env` (or a `SQL_DATABASE_URL` override) and can be
  changed at runtime from the studio's Database dropdown.
  `backend/db/setup_target_db.py` provisions any target DB (create + pgvector + all
  tables) and prints the `DATABASE_URL` to use.

```mermaid
flowchart LR
    U1["Graph activity<br/>src/features/graph-studio/"] -->|"POST /runs/stream (SSE)"| A1["api/graph_studio/routes.py"]
    U2["Assistants + threads<br/>sidebar"] -->|"search · create · state"| A1
    A1 -->|"_load_compiled<br/>(importlib · cached)"| G1["backend/langgraph/*.py<br/>sql_agent · sql_agent_hitl"]
    G1 --> L2["LangGraph SDK<br/>StateGraph · astream · InMemorySaver"]
    A1 --> L2
    L2 -->|"checkpoint + memstore"| M1["In-memory thread state"]

    style A1 fill:#dcfce7,stroke:#16a34a,color:#111
    style G1 fill:#fee2e2,stroke:#dc2626,color:#111
```

### Frontend — the Graph activity

`src/features/graph-studio/` is wired into the IDE shell as activity id `graph` (Workflow
icon, right after **Workflows** in `useLayout.tsx` / `ActivityBar.tsx`, route `/#/graph` in
`App.tsx`):

| Module                    | Purpose                                                                                                  |
| ------------------------- | -------------------------------------------------------------------------------------------------------- |
| `GraphStudioPage.tsx`    | Layout shell: canvas + resizable right rail (drag handle between them)                                     |
| `GraphStudioSidebar.tsx` | Assistant picker + **database selector** + thread list (+ new-thread button)                            |
| `GraphCanvas.tsx`        | ReactFlow canvas: BFS layered auto-layout, conditional edges (`#e8a33d`), run-path highlight, direction toggle, **node-click detail popup** |
| `RunConsole.tsx`         | "Test Run" prompt → SSE stream                                                                            |
| `Inspector.tsx`          | messages / state / raw tabs + chat input for follow-ups (thread-aware)                                    |
| `ChatInput.tsx`          | Follow-up input — send button becomes **Stop** while a run is in-flight (interrupt)                      |
| `studioStore.ts`         | `useSyncExternalStore` store (assistants, threads, live messages, run path, direction, active node, DB selection) |
| `stream.ts` / `api.ts`   | SSE parser + feature-local typed client (`hasMessagesInput` schema detection)                             |

The canvas is **generic**: any introspected graph renders with the same layered layout
(BFS from `__start__`), so the React side needs no per-agent code.

---

## 14. Skills & middleware pipeline

**Skills** give agents modular, context-aware capabilities. The pipeline is
**progressive disclosure**: the agent is given a *catalog* (name + description + path) and
reads each `SKILL.md` body on demand with its `read_file` tool — so the context window stays
small until a skill is actually needed.

```mermaid
flowchart LR
    S1["skills router (api/skills)<br/>CRUD + preflight"] --> S2["core/skills/registry.py<br/>+ matcher.py + sync.py"]
    S2 --> S3["Staging:<br/>copy equipped skills to<br/><workspace>/skills/"]
    S3 --> S4["SkillsMiddleware<br/>(deepagents, catalog in prompt)"]
    S4 --> S5["Agent reads SKILL.md on demand<br/>via read_file (FilesystemBackend)"]
```

**Middleware stack inside a DeepAgent** (in assembly order):

| Middleware              | Source                        | Effect                                                                                                      |
| ----------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------- |
| MemoryMiddleware        | deepagents SDK                | Loads project`AGENTS.md` into the system prompt (cache-controlled for Anthropic)                          |
| FilesystemMiddleware    | deepagents SDK                | File read/write scoped to the task workspace                                                                |
| SummarizationMiddleware | deepagents SDK                | Auto-compresses history past a token threshold (langchain ≥1.3.14 renamed kind`"token"` → `"tokens"`) |
| SubAgentMiddleware      | auto-created by the SDK when `subagents=` is passed | Provides the`task` tool so the main agent can delegate to subagents                                       |
| Custom middleware       | `core/middleware/deep.py`   | Self-contained TodoListMiddleware + others (guarded imports keep SDK compat)                                |
| Sandbox                 | optional`LocalShellBackend` | `execute` tool for shell/python in the workspace                                                          |

---

## 15. Export subsystem (ship it)

The "develop in the IDE, run anywhere" story. Export lives in two places: the **standalone codegen** endpoint `download_agent_code()` in `api/agents/deep_agents.py` (which inlines tool sources, skills, and LLM init into a single runnable `.py`), and the **`.langconfig` bundle** endpoints (`/export`, `build_agent_bundle`/`import_agent_bundle` in `services/agent_bundle.py`) for re-import into another LangConfig instance.

### `download_agent_code()` — a runnable repository

Generates a **zip containing a complete standalone agent project**:

```
deepagent_export/
├── README.md               # what it is + how to run
├── requirements.txt        # pinned deps
├── env_example             # API keys
├── agent_config.json       # the JSON config snapshot
├── main.py                 # CLI chat interface: python main.py "query"
├── api_server.py           # optional FastAPI server
├── agent/
│   ├── agent.py            # DeepAgent initialization (create_deep_agent / create_agent)
│   ├── prompts/system_prompt.txt
│   └── tools/custom_tools.py
├── tests/test_agent.py
├── Dockerfile / docker-compose.yml   # optional
└── ui/ (index.html, chat.js, styles.css)  # optional chat UI
```

### `build_agent_bundle()` — an interchange bundle

Exports a **langconfig bundle** (JSON + assets) that can be re-imported into another
LangConfig instance — the "package for re-use" format.

### The export path

```mermaid
flowchart LR
    U1["DeepAgentStudio → Export .py"] --> U2["POST /api/deepagents/{id}/export<br/>(or /code)"]
    U2 --> U3["download_agent_code()<br/>(api/agents/deep_agents.py)"]
    U3 --> U4["Generate standalone project<br/>(langchain create_agent + PostgresSaver)"]
    U4 --> U5["Download zip / backend/outputs/exports/*.py"]
    U5 --> U6["Run by CLI:<br/>uv run python demo2.py \"query\""]

    style U3 fill:#dcfce7,stroke:#16a34a,color:#111
```

The generated `main.py` uses the **same** langchain V1 `create_agent` API as the live
backend runtime — so what you export behaves identically to what you tested in the IDE.

---

## 16. Data layer — PostgreSQL tables

SQLAlchemy models in `backend/models/` map to these tables:

| Model (file)                                                              | Table purpose                                                                                                            |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `deep_agent.py` (`DeepAgentTemplate` / `DeepAgentConfig`)           | **`deep_agent_templates`** — both normal agents *and* deep agents, distinguished by `config.use_deepagents` |
| `custom_tool.py`                                                        | **`custom_tools`** — user tools + built-in seeds (`is_builtin=True`), each carrying code + input schema + a DSH-style `definition` JSONB (category/order/timeout/guards/output-schema, §16.3) |
| `skill.py`                                                              | **`skills`** — skill catalog                                                                                    |
| `workflow.py`, `workflow_schedule.py`, `workflow_trigger.py`        | Workflows + cron schedules + event triggers                                                                              |
| `agent_memory.py`                                                       | Long-term agent memories (pgvector)                                                                                      |
| `conversation_archive.py`                                               | Chat session archives                                                                                                    |
| `execution_event.py`                                                    | Streamed execution events                                                                                                |
| `background_task.py`                                                    | Background job queue                                                                                                     |
| `workspace_file.py`, `file_version.py`                                | Workspace files + version history                                                                                        |
| `local_model.py`, `model.py`, `search_provider.py`, `settings.py` | Model/local-model/search-provider/settings config |
| `core/settings/store.py` (`SettingsDocument`)                    | **`settings_documents`** — DSH-style per-namespace settings (ns PK, JSON document, revision); the settings source of truth (§16.2) |                                                                        |

### 16.1 The unified `models` table — cloud + local LLMs in one place

The `models` table is the single source of truth for every model the app can call. It replaces the legacy hardcoded enum (`constants/models.py`). Both managed cloud entries and user-added local entries share one schema, distinguished by `source`. The legacy `local_models` table and `/api/local-models` routes remain for local-server configuration (Ollama, LM Studio, vLLM) and surface alongside cloud rows in the unified model listing.

**Schema** (`backend/models/model.py`):

| Column | Type | Notes |
|--------|------|-------|
| `id` | SERIAL PK | autoincrement |
| `model_id` | VARCHAR UNIQUE | stable id used in API calls (e.g. `deepseek-chat`, `gpt-4o`, `local-ollama-llama3`) |
| `display_name` | VARCHAR | human-readable label shown in the UI |
| `provider` | VARCHAR (indexed) | `openai`, `anthropic`, `google`, `deepseek`, `glm`, `minimax`, `qwen`, `kimi`, `agnes`, `ollama`, `lmstudio`, `vllm`, `litellm`, `custom` |
| `source` | VARCHAR | `'cloud'` (managed) or `'local'` (user) |
| `capabilities` | JSONB | `{streaming, tools, structured_output, vision, audio, video, thinking, max_context, ...}` |
| `is_active` | BOOL | soft-delete flag |
| `base_url` | VARCHAR NULL | local-only: endpoint URL |
| `api_model_name` | VARCHAR NULL | local-only: provider's internal name (e.g. `llama3.2:latest`) |
| `api_key` | VARCHAR NULL | local-only: optional per-model key (rarely used — global keys live in the settings documents, `models.api_keys`, §16.2) |
| `is_validated`, `last_validated_at`, `validation_error` | bool/tz/varchar | local-only: connection-test result |
| `usage_count`, `last_used_at` | int/tz | usage tracking |
| `tags` | JSONB | categorization |
| `created_at`, `updated_at` | timestamptz | audit |

**Initial seed flow** (post-install / after table drop):

1. **Drop the table** (full reset):
   ```sql
   DROP TABLE IF EXISTS models CASCADE;
   ```
2. **Recreate from `models/model.py`** — the schema lives in the SQLAlchemy `Model` class, so any of the following works:
   - Run Alembic up to head (`alembic upgrade head`) — preferred for migrations,
   - Or `Base.metadata.create_all(bind=engine, tables=[Model.__table__])` from a Python shell,
   - Or apply the standalone SQL in `/tmp/create_models.sql` (kept in sync with the model).
3. **Seed from the canonical CSV** — `/tmp/models_with_url.csv` is the "initial query" written by `/tmp/export_models.py`. The seed script reads it:
   ```bash
   cd backend && DATABASE_URL="postgresql://langconfig:langconfig_dev@localhost:5432/langconfig" \
       .venv/bin/python scripts/seed_models.py
   ```
   This inserts ~28 cloud rows (skipping the 4 ollama-local rows in the CSV) with `is_active=true` and a per-provider default `capabilities` JSON.
4. **Local rows** (`source='local'`) are NOT seeded by the script — users add them through Settings > Local Models.

**Why CSV instead of hardcoded enum**: every change to the model catalog (new Gemini release, added provider, pricing update) only requires regenerating the CSV and re-running the seed. No code changes needed.

**Reads** go through `GET /api/settings/models` which returns both cloud and validated local models with full metadata. The chat + workflow engines call this once at startup.

**The provider→key mapping** is independent of `models`: cloud providers' API keys are
**wizard-only** (Phase 5, §16.2) — entered in the first-run wizard / Settings → Models and
stored Fernet-encrypted in the `models` settings document (`models.api_keys`). Resolution is
`.env` fallback → settings document (`config.get_api_key_from_db` → `core/settings`), so no
`.env` key is required. See §16.2.
### 16.2 Settings & configuration — DSH-style documents (Phase 5)

> Full design + migration record: `docs/settings-refactor.md` · status: ✅ done
> (`core/settings/` engine, describe/mutate API, `.env` shrink, `env_example` removed).

**What was already there (before the Phase-5 refactor):**

- The root `.env` was the canonical source for ~100 keys — API keys, LLM defaults
  (`DEFAULT_MODEL`/`DEFAULT_TEMPERATURE`/`MAX_TOKENS`), storage/workspace roots,
  the local-LLM endpoint, RAG chunking, and infra knobs. `backend/config.py`
  (pydantic-settings) read it, and ~32 modules consumed `config.Settings` fields.
- A single-row `settings` table (`id=1`, `backend/models/settings.py`) held user
  preferences, UI-set API keys (Fernet-encrypted in the `settings.api_keys`
  JSONB column), workspace permissions, model-defaults overrides, and first-run
  state. The legacy router `api/system/settings.py` (~26 endpoints) read/wrote it.
- Model management was already DB-driven (`models` table, §16.1) — that predates
  the refactor.

**What the refactor changed:**

- **Engine** — `backend/core/settings/`: namespaces (`models`, `general`,
  `workspace`, `storage`, `rag`, `search`, `onboarding`) with pydantic schemas;
  resolution = *schema defaults → user document*; secret fields are Fernet-
  encrypted at rest and redacted at the wire (UI only ever sees set/missing dots).
- **Store** — new `settings_documents` table (`ns` PK, `document` JSON, `revision`
  int) created by alembic `028_create_settings_documents`, backfilled once from
  the legacy `settings` row + the old `.env` values (existing installs keep
  their effective configuration).
- **Wire API** — `GET /api/settings/describe` (every namespace: JSON Schema,
  resolved value, user section, revision, secret positions) and
  `POST /api/settings/mutate` (path ops `set`/`unset` with an optimistic
  `expected_revision` → `409` on stale writes). The legacy settings-document
  endpoints were deleted; only utilities remain (model registry, key test,
  setup status/complete, storage-mode runtime switch, workspace-path validate,
  guardrails, directory browser).
- **Runtime accessors** — `core/settings/runtime.py` (`runtime_get`,
  `local_llm_config`) replace direct `config.Settings` reads across ~13 consumer
  modules (agent factory, workflow executor, doc-chat, model routes, storage,
  workspace manager, local-model service, llama config, langgraph SQL agent, …),
  with seed-default fallbacks so behavior is identical pre/post migration.
- **Bootstrap** — `seed_all.py` gains a `seed_settings` step and the backend
  boot runs idempotent `ensure_settings_seeded()`; defaults come from
  `core/settings/defaults.py::get_defaults()` (mirrors the old `.env` values).
- **`.env` shrunk to bootstrap** — `POSTGRES_*` + `API_KEY_ENCRYPTION_KEY`
  (+ optional `ENVIRONMENT` and infra overrides). `env_example` was **deleted**;
  `scripts/setup.py` now **generates** the minimal `.env` (with a randomly
  generated encryption key).
- **API keys are wizard-only** — entered in the first-run wizard /
  Settings → Models, stored encrypted in `models.api_keys`; resolution is
  `.env` fallback → settings document (`config.get_api_key_from_db` → engine).
- The legacy single-row `settings` table remains as an inert shim (its data was
  consumed by the 028 backfill; the new API never writes it).

**The end-state model:**

```
resolved value  =  pydantic schema defaults  →  DB user document (namespace)
consumers read via core/settings/runtime.py (runtime_get / local_llm_config)
.env            =  POSTGRES_* + API_KEY_ENCRYPTION_KEY (+ optional infra)
first boot      =  seed_all / ensure_settings_seeded → documents
first browser   =  wizard (API key + workspace) → Settings (everything else)
```

**Namespaces (v1):**

| ns | Schema | Contents |
|----|--------|----------|
| `models` | `ModelsSettings` | `api_keys` (13 providers + langsmith_/google_/slack_/discord_, `role='secret'`), default_model, default_temperature, max_tokens, primary_model, fallback_models, top_p, routing_strategy, token limits, local-LLM endpoint |
| `general` | `GeneralSettings` | app_name, language, theme, auto_save, toggles |
| `workspace` | `WorkspaceSettings` | workspace_path, permissions, base_dir |
| `storage` | `StorageSettings` | mode (local/db), base_dir, documents_base_dir |
| `rag` | `RagSettings` | embedding_model, chunk_size, chunk_overlap |
| `search` | `SearchSettings` | tavily/serper keys (`role='secret'`) |
| `onboarding` | `OnboardingSettings` | setup_complete, api_key_set, workspace_set |
| `runtime` | `RuntimeSettings` | User-adjustable runtime knobs (mirror the legacy `.env` overrides — see "Config architecture" below): workspace root, backup dir, storage mode, ollama embed model, langsmith tracing/project, db pool size / max overflow, rate-limit on/off + r/min, performance monitoring + slow thresholds + log toggles, analysis recursion limit + dashboard / chat timeouts, execution history rows / retention days / auto-cleanup |

**Wire format (abridged):**

```json
GET /api/settings/describe
→ { "namespaces": [{ "ns": "models", "schema": {…}, "value": {…},
                     "user": {…}, "revision": 2, "writable": true,
                     "secrets": [{ "path": ["api_keys","deepseek_api_key"], "set": true }] }] }

POST /api/settings/mutate
{ "ns": "models",
  "ops": [{ "op": "set", "path": ["api_keys","deepseek_api_key"], "value": "sk-…" }],
  "expected_revision": 2 }
→ 200 { "ns": "models", "value": {…redacted…}, "revision": 3, "secrets": […] } | 409 on stale
```

#### Config architecture — three tiers (operator / runtime / secrets)

The root `.env` is split into three tiers; each lives where it belongs:

| Tier | What | Where | Source of truth at runtime |
|---|---|---|---|
| **Operator-only** | Infrastructure the user must not touch: `POSTGRES_*`, `API_KEY_ENCRYPTION_KEY`, `ENVIRONMENT`, `TEST_DATABASE_URL`, `SQL_POSTGRES_DB`, `GOOGLE_REDIRECT_URI`, `OLLAMA_BASE_URL`, `SQL_ECHO`, `RATE_LIMIT_CLEANUP_INTERVAL` | `.env` (read once at boot) | `.env` |
| **User-adjustable runtime** | Team-tunable knobs: workspace path, backup dir, storage mode, ollama embed model, langsmith tracing/project, db pool size / max overflow, rate-limit on/off + r/min, performance monitoring + slow thresholds + log toggles, analysis recursion limit + dashboard / chat timeouts, execution history rows / retention days / auto-cleanup | `.env` (bootstrap default) → DB `runtime` namespace → Settings panel UI | `runtime` settings document; `.env` is read only as the first-boot seed |
| **API keys (secrets)** | OpenAI / Anthropic / Google / DeepSeek / MiniMax / Qwen / Kimi / GLM / Cohere / Replicate / Tavily / Serper / Agnes + LangSmith + Google OAuth client + Slack + Discord webhooks | DB `models.api_keys` field (Fernet-encrypted) → Settings → Models UI | DB; `.env` is only an emergency bootstrap for legacy upgrades |

Three concurrent sources for the same value is intentional:
1. **Operator-only** stays in `.env` because it must exist before the DB is reachable
   (e.g. the very first `start.sh --be` boot).
2. **User-adjustable runtime** reads `.env` at pydantic-settings init, then a
   `model_validator(mode="after")` in `config.Settings` overrides every field with
   `runtime_get("runtime", field, fallback)` so the DB always wins once the
   team has set anything. The Settings panel calls `mutateNs("runtime", ops)`
   to update values — backend restart not required (the field is read per-`Settings()`
   instantiation in consumer modules).
3. **API keys** are in the DB only. Legacy `.env` keys can be imported once via
   `backend/scripts/import_api_keys_to_db.py` (idempotent). After that the DB
   is the single source — `.env` has no `*_API_KEY` lines at all.

The `env_example` template (committed) is split into the same three sections
with explicit `OPERATOR-ONLY` / `USER-ADJUSTABLE` / `API KEYS — DO NOT PUT IN
.env` headers so the team can copy it as their `.env` and know which lines
matter for which tier.

### 16.3 Tools — DSH-shaped definitions on the compile model (Phase 6)

> Full design + phase record: `docs/tools-refactor.md` · status: ✅ Phases A+B.

LangConfig's tool system compiles **DB rows → runnable tools** at runtime
(`custom_tools` → `ToolFactory` codegen → `StructuredTool`), and the tool source
is split between the seed-time implementations (`tools/native_impl.py`, baked
into rows by `seed_builtin_tools.py`) and the 9 legacy-only harness tools
(`tools/native_tools.py`: injected-state, Playwright, TODO/VFS helpers).
Phases A+B added the DSH-style declarative surface on top of that compile model:

- **`ToolDefinition`** (`core/tools/definition.py`) — the DSH `defineTool`
  analog: `category`, `order`, `section`, `timeout_ms`, `is_concurrency_safe`,
  `output_schema`, `guard` (approval/confirmation), `presentation`
  (icon/requires_api_key/hidden). Stored as a `definition` JSONB column on
  `custom_tools` (alembic `029`), populated for every built-in by the seeder
  (category + seed order) and attached as `tool.metadata["definition"]` by
  `ToolFactory.create_tool`.
- **`ToolRegistry`** (`core/tools/registry.py`) — the single surface for
  definitions + ordering: `list_definitions()` merges DB rows (built-in +
  project-scoped custom) with the 9 legacy tools (synthesized definitions),
  ordered by `definition.order`; `resolve_for_agent()` returns the ordered,
  deduplicated, alias-resolved tool set an agent config selects (native + cli +
  custom + memory/rag). `run_code` is reserved for Code Mode (Phase C).
- **Execution pipeline** (`core/tools/pipeline.py`) — `apply_tool_pipeline()`
  wraps every compiled tool whose definition requests enforcement, wired into
  `AgentFactory.create_agent` after tool assembly: **guard.approval** (blocked
  until `ApprovalGate.grant()` — HITL seam), **timeout_ms** (`asyncio.wait_for`),
  **output_schema** (declared now, enforced gradually). Additive — tools without
  enforcement pass through untouched.

```
custom_tools rows (code + input_schema + definition JSONB)   tools/native_tools.py (9 legacy)
        │ ToolFactory.create_tool() (compiles row → StructuredTool)   │ synthesized definitions
        │ attaches definition metadata                               ▼
        ▼                                          ToolRegistry.list_definitions() (ordered)
   ToolLoader (native/custom/cli/memory/rag)
        │
        ▼
   apply_tool_pipeline(tools)  →  AgentFactory.create_agent() → CompiledStateGraph
```

Registry + definitions are the surface Phase C (Code-Mode `run_code` + generated
Python SDK) and Phase D (ordered prompt guidance, tool packages) build on.


---
| `user_profile.py`                                                       | User profile                                                                                                             |
| `audit_log.py`                                                          | Audit trail                                                                                                              |
| `oauth_token.py`, `presentation_job.py`                               | OAuth tokens + presentation jobs                                                                                         |
| `analysis_chat.py`, `custom_schema.py`                                | Analysis chats + structured-output schemas                                                                               |
| `storage_object.py`                                                   | **`storage_objects`** — durable artifact blobs (BYTEA), the DB-as-store seam (Phase 1, §19)                              |

```mermaid
flowchart TB
    subgraph PG["PostgreSQL 16 + pgvector (:5432)"]
        T1["deep_agent_templates<br/>(normal + deep agents, use_deepagents flag)"]
        T2["custom_tools · skills"]
        T3["workflows + schedules + triggers"]
        T4["agent_memories (pgvector) · conversation_archives"]
        T5["execution_events · background_tasks · audit_logs"]
        T6["workspace_files · file_versions · local_models · settings · storage_objects"]
        T7["settings_documents<br/>(DSH-style namespace settings, §16.2)"]
    end
    T1 --> T2
    T1 --> T3
    T1 --> T4
    T3 --> T5
    T4 --> T5
```

### 16.4 Seeding principle — one-time bootstrap, then the DB is authoritative

**Invariant:** seeding runs **once** (first install / explicit `--replace`). After
that the PostgreSQL database is the single source of truth for user state —
agents, tools, API keys, and settings — and the runtime reads from it live.
Seeding is a **setup/migration tool, never part of the runtime path**.

**One-time seeding:**

| Seed | Entry point | Behavior |
|------|-------------|----------|
| Settings documents | `core/settings/seed.py::ensure_settings_seeded()` (runs on every boot) | Writes a default document **only for namespaces with no row** (`row_exists`); existing documents are never touched |
| Built-in tools | `scripts/seeds/seed_builtin_tools.py` (setup only) | Creates missing `custom_tools` rows; existing built-in rows are **updated only with an explicit `--refresh`**; user-owned rows with the same id are never touched |
| Agents / tools dumps | `scripts/seeds/seed_all.py` (setup only, `--replace` opt-in) | Seeds tables only when **empty** (`count == 0`); `--replace` truncates before restoring dumps — documented as destructive |

`main.py` boot runs **only** `ensure_settings_seeded()` (idempotent) — no
tool/agent seeding happens at runtime.

**After first-time setup, the DB is authoritative and the runtime reads live:**

- **Agents** — `deep_agent_templates.config` JSON is the source of truth;
  every chat rebuilds the agent from the stored config (prompt, tools, skills,
  subagents, middleware, plugins). User edits persist; nothing re-seeds.
- **API keys** — single table: the `models` settings document's `api_keys`
  field (Fernet-encrypted, §16.2). Tools read it **live on every call** via
  `config.get_api_key_from_db` (`tavily_search`, `web_search`'s provider path,
  LLM `resolve_model`). An adhoc Settings save is picked up on the next call —
  no re-seed, no restart. Keys are never part of seeding.
- **Built-in tools** — loaded **DB-first** (`ToolLoader._load_builtin_from_db`):
  the row's self-contained code is authoritative; the seed source
  (`tools/native_impl.py`) only supplies it at seed/refresh time. Tool code
  reads keys from the DB at runtime, so a user's key change needs no tool
  refresh.

```
first install  =  seed_all / seed_builtin_tools / ensure_settings_seeded  (once)
after that     =  DB is authoritative
runtime        =  agent builds from deep_agent_templates.config
                 tools load from custom_tools rows (DB-first)
                 API keys read live from models.api_keys per call
                 settings read from settings_documents per namespace
```

**Operational notes:**

- `seed_all.py --replace` truncates `deep_agent_templates` / `custom_tools` —
  a deliberate force-reload. Do not run it casually; it discards user edits.
- The `step_deep_agents` catch-up branch reloads the agent dump when the table
  has **fewer rows than the dump** (partial install). If you intentionally
  delete agents, run `seed_all` afterwards only with awareness that this
  branch can re-add the canonical set; to fully honor "user edits win", that
  branch should fire only when the table is empty (see `scripts/seeds/seed_all.py`).
- To propagate a `tools/native_impl.py` code fix into existing built-in rows,
  run `seed_builtin_tools.py --refresh` once (setup step) — runtime never
  re-seeds.

### 16.9 AGENTS.md — two layers, one filename (clarification)

The codebase has **two distinct things** both named `AGENTS.md`. They are
different concerns and live in different places — only one of them travels
with the agent.

| Layer | Storage | Scope | Loaded by | Editable via |
|---|---|---|---|---|
| **Agent's own AGENTS.md / CLAUDE.md** | `deep_agent_templates.agent_docs` (JSON, e.g. `{"AGENTS.md": "...", "CLAUDE.md": "..."}`) | **per-agent** — travels with the agent regardless of which project it's bound to | baked into the agent's `system_prompt` at seed time + materialized into the agent's workspace at chat time (`api/chat/messages.py:_materialize_agent_docs`) — **re-baked with the session's workspace root each chat** (§16.10) | the agent editor's "Docs" tab |
| **Per-project AGENTS.md** | `<workspace>/<vault_key>/AGENTS.md` (filesystem file) | **per-project** — only loaded when an agent joins that project | `deepagents.MemoryMiddleware` (if `disable_memory_middleware=False`) | `api/agents_md/routes.py` (project-level) |

**Product rule: AGENTS.md and CLAUDE.md belong to the agent** — they describe
the agent's identity and instructions. The per-project filesystem file is a
*separate* thing (shared project context / team conventions) that happens to
share the filename for compatibility with `MemoryMiddleware`. The two do not
conflict; the per-project file is additional context, not a replacement for
the agent's own docs.

When the team reads "the agent's AGENTS.md", they should think of the DB
column. When the team reads "the project's AGENTS.md", they should think of
the filesystem file at `<root>/<vault_key>/AGENTS.md`.

### 16.10 Agent workspaces — vault-scoped roots + per-session identity re-bake

Every agent gets a persistent filesystem workspace; the root is resolved per
chat session by
`services/workspace_manager.py::WorkspaceManager.resolve_agent_workspace`:

| # | Condition | Root |
|---|---|---|
| 1 | `agent.workspace_path` set (user-defined, `deep_agent_templates.workspace_path`) | used as-is (absolute) or anchored to the vault root (relative) |
| 2 | session bound to a project (`chat_sessions.project_id`) | `{base}/{vault_key}/agents/{agent_key}/` |
| 3 | neither | legacy `{base}/agents/agent_{id}/` |

- `vault_key` = the project's **slugified name** (`my-project` → `my-project`;
  collision → `-{id}`; fallback = raw id); `agent_key` = the agent's
  **slugified name** (CJK preserved; fallback `agent_{id}`).
- Every root carries the canonical skeleton — `upload/` (user knowledge),
  `generated/` (deliverables), `skills/` (staged catalog), `other/` (scratch) —
  plus `AGENTS.md` / `CLAUDE.md` at the root.
- The agent's filesystem tools are scoped to the root.
  `services/workspace_filesystem_backend.py` (`WorkspaceFilesystemBackend`)
  re-bases an absolute workspace path the agent learned from its identity back
  to a virtual relative path, so it writes into the workspace instead of a
  nested `<workspace>/Users/…` tree.

**Identity is re-baked per session.** The workspace root is project-bound, but
the stored identity (`config.system_prompt` + `agent_docs`) is per-agent and
was baked at creation with the legacy root (agents are created
project-agnostic; the binding lives on `chat_sessions.project_id`). Both chat
entry points in `api/chat/messages.py` (non-streaming `POST /message` and
streaming `POST /message/stream`) therefore:

1. resolve the root from the session's `project_id` (+ `vault_key`/`agent_key`);
2. strip the stale identity block from the system prompt and rebuild it with
   the resolved root, embedding re-baked docs
   (`core/agents/identity.py::build_identity_system_prompt`);
3. materialize AGENTS.md / CLAUDE.md into the resolved root with the root
   re-baked inside (`refresh_doc_identity`), so MemoryMiddleware and the Files
   panel see the correct path — the DB row stays the canonical authored copy.

Files stranded in nested `Users/` trees by the pre-fix absolute-path bug are
rescued by the one-shot `backend/scripts/rescue_stranded_workspace_files.py`
(run `--dry-run` first; moves each file into the agent's current vault-scoped
`generated/`/`upload`/`other` and prunes the empty trees).

---

## 17. Request lifecycle — sequence diagrams

### DeepAgent chat (SSE)

```mermaid
sequenceDiagram
    participant UI as React ChatPage
    participant API as api/chat/messages.py<br/>POST /api/chat/message/stream
    participant F as DeepAgentFactory
    participant DA as deepagents SDK
    participant LG as LangGraph graph
    participant DB as PostgreSQL

    UI->>API: POST /message/stream (agent_id, message)
    API->>F: create_deep_agent(config, project_id, task_id)
    F->>DA: create_deep_agent(...) with middleware/skills
    DA->>LG: compiled CompiledStateGraph
    API->>LG: astream_events(input)
    loop tool calls / tokens
        LG-->>API: agent events (tool_call, tool_result, tokens)
        API-->>UI: SSE chunk
    end
    LG-->>DB: checkpoint save (state + messages)
    LG-->>API: final answer
    API-->>UI: SSE [done]
```

### Workflow execution

```mermaid
sequenceDiagram
    participant UI as Workflow Canvas
    participant API as api/workflows/execution.py
    participant ENG as core/workflows/executor
    participant CP as checkpointing/manager
    participant DB as PostgreSQL

    UI->>API: POST /workflows/{id}/execute
    API->>ENG: build graph from stored nodes + edges
    ENG->>ENG: dispatch nodes (agent / deepagent / tool / llm)
    ENG->>CP: save checkpoint per step
    CP->>DB: upsert execution state
    ENG-->>API: progress events
    API-->>UI: SSE /workflows/{id}/events
    UI->>API: GET /workflows/{id}/stream (poll/stream results)
```

---

## 18. Development topology

Two long-running processes + one database. The root `.env` (loaded by `backend/config.py`)
is **minimal after Phase 5** (§16.2): `POSTGRES_*` + `API_KEY_ENCRYPTION_KEY` (+ optional
infra overrides). Everything user-facing — LLM defaults, API keys, storage/workspace roots,
RAG — lives in PostgreSQL settings documents; the database drives the app, not the env file.

```mermaid
flowchart LR
    subgraph FRONT["Vite dev server (:1421)"]
        F["React 19 app<br/>npm run dev"]
    end
    subgraph BACK["uvicorn (:8765, reload)"]
        B["FastAPI app<br/>uv run python main.py"]
    end
    subgraph DATA["PostgreSQL 16 (:5432)"]
        P[("pgvector + Alembic migrations")]
    end
    F -->|"HTTP / SSE<br/>localhost:8765"| B
    B -->|"SQLAlchemy<br/>DATABASE_URL (root .env)"| P

    style B fill:#dcfce7,stroke:#16a34a,color:#111
    style P fill:#fee2e2,stroke:#dc2626,color:#111
```

**Gotcha:** a second, stale Postgres container (`langconfig-postgres`) may exist — the app
always loads the root `.env` (→ `:5432`, fully migrated). Standalone
scripts must load the root `.env` *before* importing `db.database` — from the `backend/`
cwd that's `load_dotenv("../.env")`, or better, derive the path from `__file__` (see
`tools/seed_builtin_tools.py`) — otherwise they miss the `.env` and report phantom
`UndefinedColumn` errors.

**Gotcha (Graph Studio):** the `backend/langgraph/*.py` modules build their chat model with
`init_chat_model(...)`. Since Phase 5 the key resolves via `config.get_api_key_from_db`
(`.env` fallback → settings document, §16.2), so a key entered in Settings works without
`.env`; until one is entered, `/api/graph-studio` introspection can still fail with a
pydantic `ValidationError` (HTTP 500).

---

## 19. Storage strategy: DB as the permanent store (enterprise-ready)

> **Status (2026-08-03):** All four phases of the storage strategy are shipped —
> Phase 1 (abstraction, commit `3aa794d`), Phase 2 (write-through wiring), Phase 3
> (deepagents `DbBackend`, skills 100% DB-managed in `STORAGE_MODE=db`), and Phase 4
> (FS→DB migration tool). `storage_objects`, `services/storage/`, and `STORAGE_MODE`
> are all live; flip `STORAGE_MODE=db` after running `uv run python -m tools.migrate_storage`.
>
> **Phase 5 update:** the storage mode is now also a settings-document value
> (`storage.mode`, §16.2) — the Settings UI runtime switch persists there and
> overrides the `.env`/config default at boot; `STORAGE_MODE` in `.env` is only
> the base default.

### The vision

The filesystem is the *personal / local-dev* default. For **enterprise**, the durable home
for all artifacts — skills, workspace files, uploaded documents, outputs, versions — is the
**database**, with **object storage** (S3 / MinIO / Tencent COS / Aliyun OSS / R2) for large
blobs. The filesystem stays only for what is genuinely **ephemeral**: task scratch,
staging dirs, export zips, local sandboxes.

**Rule: DB holds durable artifacts; the filesystem holds transient working files.**

### Blob vs object storage — the decision

Not either/or — a **hybrid** selected by size threshold + `STORAGE_MODE`:

| Storage                                      | Best for                                          | Trade-off                                                                    |
| -------------------------------------------- | ------------------------------------------------- | ---------------------------------------------------------------------------- |
| Postgres BYTEA (`storage_objects`)         | Skills, configs, small artifacts (< ~1 MB)        | Transactional, zero infra, same backup — bloats DB, poor for large/media    |
| Object storage (S3 / MinIO / COS / OSS / R2) | Uploaded RAG docs, images, large outputs, exports | Built for big blobs + streaming, cheap, multi-node — needs a service/vendor |

**Enterprise pattern:** DB row = *metadata + object key*; the *blob* lives in object
storage. The `StorageBackend` interface makes the physical choice config-driven, so the
same callers work unchanged in every mode.

### A single seam: `StorageBackend`

Every writer in the platform talks to one object-addressed interface, so the physical
backend changes per deployment (`local` / `db` / `s3`) without touching any caller.

```mermaid
flowchart LR
    subgraph Callers["Writers"]
        W1["FileStorage<br/>uploaded RAG docs"]
        W2["WorkspaceManager<br/>agent outputs"]
        W3["Skills<br/>SKILL.md content"]
    end
    W1 --> IF["StorageBackend<br/>save(key, content) · read(key)<br/>exists · delete · list · stat"]
    W2 --> IF
    W3 --> IF
    IF --> L1["LocalStorageBackend<br/>disk (personal default)"]
    IF --> L2["DbStorageBackend<br/>Postgres BYTEA · small payloads"]
    IF --> L3["ObjectStorageBackend<br/>S3 / COS / OSS · large blobs"]
    L1 --> T1["STORAGE_MODE=local"]
    L2 --> T2["STORAGE_MODE=db"]
    L3 --> T3["STORAGE_MODE=s3"]
```

### What already exists (foundation)

| Asset            | DB foundation today                                                                     | Gap closed by this design                                                            |
| ---------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Workspace files  | `workspace_files` (metadata, tags, agent/workflow/task context) + `file_versions`   | content is on disk; only paths in DB →`storage_objects` BYTEA rows / object store |
| Skills           | `skills` table already holds the SKILL.md body in `instructions`                    | the`backend/skills/**/SKILL.md` git mirror becomes optional                        |
| Uploaded docs    | `FileStorage` service                                                                 | hardwired to`./data/documents/` → route through the backend                       |
| Agent file tools | deepagents`BackendProtocol` is pluggable (`ls/read/write/glob/grep/download_files`) | a`DbBackend` maps `/skills/<name>/SKILL.md` → DB rows                           |
| Runtime flag     | `config.py` pydantic settings (root `.env`)                                         | new`STORAGE_MODE` env key (`local` \| `db` \| `s3`)                          |

### Why this composes with deepagents

`SkillsMiddleware` only calls `backend.ls()` + `backend.download_files()` on the
`BackendProtocol` — it never touches the disk itself. So a DB-backed implementation of that
protocol gives **skills 100% in DB** while preserving progressive disclosure (metadata
catalog in the system prompt, SKILL.md body read on demand) and the agent's `read_file`
tool works transparently against the DB.

### Rollout phases & current state

1. **Phase 1 — abstraction ✅ DONE (commit `3aa794d`)**
   - `backend/services/storage/` — `base.py` (`StorageBackend` ABC + `StorageStat`),
     `local.py` (`LocalStorageBackend`, key sanitization), `db.py` (`DbStorageBackend`,
     BYTEA), `__init__.py` (`get_storage()` factory, cached)
   - `backend/models/storage_object.py` — `storage_objects` table (unique `key`, BYTEA
     `content`, `size_bytes`, `mime_type`, timestamps)
   - Alembic `018_add_storage_objects` (idempotent existence check) — **schema only, no data moved**
   - `config.py` — `storage_mode` (`local` default) + `storage_base_dir` (`./data/storage`)
   - Tests: `backend/tests/test_storage.py` — 5 passed (roundtrip both backends, unsafe-key
     rejection, missing-key raise, upsert single-row)
   - Verified live: factory returns `LocalStorageBackend`; `DbStorageBackend` save/read/
     stat/list/delete roundtrip on Postgres `:5432`
2. **Phase 2 — wiring ✅ DONE** — route `FileStorage` (uploaded docs), `WorkspaceManager`
   (agent outputs), and skill sync (`db_row_to_fs`) through `get_storage()`; keep `local`
   as the default so behavior is unchanged until `STORAGE_MODE=db`.
   Implemented as **write-through**: in `STORAGE_MODE=db` each writer additionally persists
   to `storage_objects` — keys `documents/<rel>` (`FileStorage.save_file`/`delete_file`),
   `outputs/<rel>` (`WorkspaceManager.persist_output`, called by the agent write/edit file
   tools), `skills/<type>/<id>/SKILL.md` (`db_row_to_fs`). The on-disk copy stays the
   operational store for consumers (RAG, workspace readers); storage failures are logged and
   non-fatal (durability copy only). `local` mode is a strict no-op.
3. **Phase 3 — deepagents `DbBackend` ✅ DONE** — `services/storage/db_backend.py`
   implements `BackendProtocol` (`ls`/`read`/`write`/`edit`/`delete`/`glob`/`grep`/
   `download_files`/`upload_files`) backed by `get_storage()`; virtual path
   `/skills/<type>/<id>/SKILL.md` maps 1:1 to the storage key (an optional
   `storage_prefix` re-attaches the namespace when routed behind `CompositeBackend`).
   In `STORAGE_MODE=db`, `DeepAgentFactory` now persists each equipped skill under its
   canonical key and serves them via `DbBackend` (skills are 100% DB-managed, no FS
   staging), preserving progressive disclosure (catalog + on-demand `read`). With a
   sandbox active, a `CompositeBackend` routes `/skills/` to storage and keeps
   `execute` in the sandbox. `local` mode keeps the legacy disk staging untouched.
   Tests: `backend/tests/test_db_backend.py` (10 cases incl. recursive delete, glob
   `**`, grep truncation, traversal rejection, prefix mapping).
4. **Phase 4 — migration tool ✅ DONE** — `backend/tools/migrate_storage.py`, a
   one-shot job for the flip: copies existing FS artifacts into `storage_objects`
   under the same keys Phase 2 writes through (`documents/<rel>` from
   `FileStorage`, `outputs/<rel>` from `WorkspaceManager`, `skills/<type>/<id>/SKILL.md`
   rendered canonically from the `skills` table). Idempotent (existing keys
   skipped; `--force` overwrites), `--dry-run` to preview, forces
   `STORAGE_MODE=db`, loads the root `.env` before importing `db.database` (the
   §18 gotcha). Verified live on `:5432`: 1,301 artifacts migrated with
   content-identical spot checks, re-run skips all 1,301.
   Run: `uv run python -m tools.migrate_storage [--force] [--dry-run]`

---

## Quick reference — where things live

| Question                      | Answer                                                                                                                |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Where does an agent's workspace live? | `WorkspaceManager.resolve_agent_workspace` — user `workspace_path` → `{base}/{vault_key}/agents/{agent_key}/` (vault-scoped, per session `project_id`) → legacy `agents/agent_{id}/`; identity + docs re-baked per session (§16.10) |
| What builds a normal agent?   | `core/agents/factory/assembly.py` → `AgentFactory.create_agent`                                                  |
| What builds a DeepAgent?      | `services/deepagent_factory/assembly.py` → `DeepAgentFactory.create_deep_agent`                                  |
| What is`deep_agents.py`?    | The REST controller (CRUD + prompt-preview + export) — not the builder                                               |
| Where is export code?         | `api/agents/deep_agents.py` (`download_agent_code`/`export_deepagent`) + `services/agent_bundle.py` |
| Where do agents persist?      | `deep_agent_templates` table (flag `config.use_deepagents`)                                                       |
| How does chat stream?         | `POST /api/chat/message/stream` → SSE via `useChatStreaming` / `streamChatEvents.ts`                           |
| How do workflows run?         | `core/workflows/` executor + Postgres checkpointer, streamed over SSE                                               |
| How does Graph studio work?   | Graph activity (`/#/graph`) → `api/graph_studio/` hosts `backend/langgraph/*.py` natively (no `langgraph dev` server); threads + runs are in-memory |
| Where are code graphs?        | `backend/langgraph/*.py` — imported lazily by `api/graph_studio/routes.py` (`_load_compiled`)                     |
| How do I switch the agent's DB? | Studio Database dropdown → `POST /databases/select` (runtime `_DB_OVERRIDE`); or `SQL_*` env / `SQL_DATABASE_URL` in `.env` + restart |
| How do I stop a run?          | Chat **Stop** button → `POST /threads/{id}/runs/cancel` (next SSE event boundary)                              |
| Where do exported files land? | `backend/outputs/exports/*.py` (or download zip from `/export`)                                                   |
| Where do artifacts persist?   | `services/storage/` `StorageBackend` seam — `local` (disk) \| `db` (Postgres BYTEA) \| `s3` (object store) |

---

# Installation & Setup

LangConfig runs as two processes — a **FastAPI backend** (:8765) and a **Vite/React frontend** (:1421) — plus a **PostgreSQL 16 + pgvector** instance. Postgres runs **natively** on :5432 or in **Docker** on :5433; the mode is switched by `POSTGRES_PORT` in `.env`. Everything — the app, Alembic, seeds, `docker-compose.yml`, and the SQL agent — derives its URL from the `POSTGRES_*` block via `db/db_url.py::compose_db_url()`, so switching modes is a pure `.env` edit. Instructions below cover **macOS (Homebrew)** and **WSL2 + Ubuntu** (22.04/24.04).

## 1. Prerequisites

| Requirement | Version / Install |
|---|---|
| OS | macOS (Homebrew) or WSL2 + Ubuntu 22.04/24.04 |
| Python | **3.13** (`backend/.python-version`, `pyproject.toml` `requires-python = ">=3.13"`) |
| Node.js | **20.19+** (Vite 7 requirement) |
| uv | Python package manager — `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| PostgreSQL 16 + pgvector | native install **or** Docker (`docker compose up -d postgres`) — see step 3 |
| Docker | only needed for Docker Postgres mode |
| Git / build tools | `brew install git` / `sudo apt install -y git build-essential` / `sudo dnf install -y git gcc make` |

macOS:

```bash
brew install python@3.13 node
curl -LsSf https://astral.sh/uv/install.sh | sh
```

WSL2 / Ubuntu (ships Python 3.12 — install 3.13 via deadsnakes):

```bash
sudo add-apt-repository ppa:deadsnakes/ppa -y && sudo apt update
sudo apt install -y python3.13 python3.13-venv python3.13-dev build-essential git
curl -LsSf https://astral.sh/uv/install.sh | sh
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
nvm install 22
```

## 2. Clone & configure environment

```bash
git clone <repo-url> && cd langconfig
cp env_example .env
```

Edit `.env` minimally:

- LLM keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` (default provider is Anthropic, `DEFAULT_MODEL=claude-haiku-4-5`)
- Replace the two security placeholders (they must be **different** 64-hex strings):
  ```bash
  openssl rand -hex 32   # run twice → SECRET_KEY, API_KEY_ENCRYPTION_KEY
  ```
- Pick the DB mode — the **only** switch you need to change Postgres backends:
  ```
  POSTGRES_PORT=5432     # native (Homebrew / apt postgres)
  # POSTGRES_PORT=5433   # docker (docker compose up -d postgres)
  ```
  `DATABASE_URL` is composed from the `POSTGRES_*` block automatically, and the SQL agent (`SQL_*`) follows it too — leave the `SQL_*` connection parts commented.
- Optional: `MINIMAX_API_KEY` + `NEO4J_*` (graphindex tools); `LOCAL_LLM_HOST` (Ollama)

## 3. PostgreSQL 16 + pgvector — native OR Docker

### 3a. Native on :5432 — macOS (Homebrew)

```bash
brew install postgresql@16 pgvector
brew services start postgresql@16
pg_isready -h 127.0.0.1 -p 5432        # expect "accepting connections"
```

### 3b. Native on :5432 — WSL2 / Ubuntu (no systemd → use `service`)

Add the official PGDG apt repo — this gives you Postgres **16** plus `pgvector` (pgvector is missing from Ubuntu 22.04's default repos):

```bash
sudo apt install -y curl ca-certificates gnupg lsb-release
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor -o /usr/share/keyrings/pgdg.gpg
echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list
sudo apt update
sudo apt install -y postgresql-16 postgresql-16-pgvector
sudo service postgresql start && sudo pg_isready
```

### 3c. Docker on :5433 — any OS

```bash
# .env has POSTGRES_PORT=5433; the container publishes 5433 -> 5432 inside
docker compose up -d postgres
docker inspect langconfig-postgres --format '{{.State.Health.Status}}'   # healthy
```

### 3d. Native on :5432 — RHEL / Rocky / Alma / CentOS Stream / Fedora (dnf)

Add the PGDG yum repo (gives Postgres **16** + the `pgvector_16` extension
package), disable the distro's older `postgresql` module, then initdb + start:

```bash
sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm   # EL-8 for RHEL 8 family
sudo dnf -qy module disable postgresql
sudo dnf install -y postgresql16-server postgresql16 pgvector_16
sudo /usr/pgsql-16/bin/postgresql-16-setup initdb
sudo systemctl enable --now postgresql-16
sudo -u postgres pg_isready                                        # expect "accepting connections"
```

> Fedora ships PostgreSQL 16 + `pgvector` natively:
> `sudo dnf install -y postgresql16-server postgresql16 pgvector` (skip the
> PGDG repo step; initdb + systemctl steps are the same).

Create the app role + databases (native only — Docker does it automatically from `POSTGRES_USER`/`POSTGRES_DB`), then run the bootstrap script:

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE langconfig LOGIN PASSWORD 'langconfig_dev';
CREATE DATABASE langconfig OWNER langconfig;
CREATE DATABASE langconfig_test OWNER langconfig;   -- only needed if you run pytest
SQL

sudo -u postgres psql -d langconfig -f backend/db/init_postgres.sql
```

> **Note:** `backend/db/init_postgres.sql` enables **pgvector** and creates a legacy `vector_documents` table; on Docker it runs automatically on first boot. The full schema is built from the ORM models in step 4 — the legacy `001_initial_schema` migration chain is **not** replayable on an empty database (it starts with DROP TABLE statements).

## 4. Backend — uv, DB init & migration, seeds

```bash
cd backend
uv sync        # installs the exact Python deps from pyproject.toml / uv.lock into backend/.venv
```

### 4a. FRESH INSTALL: init schema + stamp Alembic + seeds (one command)

`scripts/seeds/seed_all.py` is the canonical bootstrap — it initializes the schema from the ORM models (the same code path the app runs at startup), stamps Alembic at HEAD, and loads every seed. All steps are idempotent and target whatever `DATABASE_URL` the `.env` resolves to (native or Docker):

```bash
cd backend && uv run python scripts/seeds/seed_all.py
```

It runs, in order:
1. `init_server` — ensures the role + database exist
2. `init_db` — `create_all` from the ORM models + pgvector (`init_db()` in `db/database.py`)
3. `alembic stamp head` — marks the schema current (no legacy migrations to replay)
4. `seed_models` / `seed_search_providers` — LLM providers + search backends
5. `custom_tools` — 53 built-in tools (dump) · `deep_agents` — agent templates (dump)
6. `skills` — `backend/skills/**/SKILL.md` synced into the DB
7. `chinook` — sample business DB for the SQL agent

For an **already-initialized** database, apply migrations instead of re-initializing:

```bash
cd backend && uv run alembic upgrade head
```

### 4b. Run the backend

```bash
cd backend && uv run python main.py      # FastAPI on http://localhost:8765
# or the one-shot launcher (starts Postgres in the configured mode, then backend + frontend):
bash start.sh
```

Verify: `http://localhost:8765/docs` (Swagger) or `http://localhost:8765/health`. On first startup the app also syncs `backend/skills/` (SKILL.md files) into the DB — expect log output about skills.

## 5. Frontend

```bash
# from the repo root
npm install
npm run dev        # Vite on http://localhost:1421
```

Open **http://localhost:1421**. WSL2 forwards localhost automatically; to reach it from another machine use the WSL IP: `wsl hostname -I`.

## 6. Tests

```bash
cd backend && uv run pytest                    # full suite
uv run pytest tests/test_db_connection.py      # single file
```

The suite uses `TEST_DATABASE_URL` (default `postgresql+asyncpg://langconfig:langconfig_dev@localhost:5432/langconfig_test`) — create that database in step 3 before running. Tests build their own schema via `init_db()` at startup, so no separate migration step is needed.

## 7. Optional extras

- **Ollama** (local LLMs/embeddings): keep `LOCAL_LLM_HOST=http://localhost:11434`; pull models such as `llama3.2`, `nomic-embed-text`, `gemma4` (used by graphindex routing)
- **Playwright** (screenshots / notebook tools): `cd backend && uv run playwright install chromium`
- **Redis** (caching/locking, optional): `brew install redis` / `sudo apt install redis-server`
- **Production frontend build**: `npm run build` (outputs to `dist/`)

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `connect: connection refused` | Postgres not running — native: `pg_isready -h 127.0.0.1 -p $POSTGRES_PORT`; docker: `docker compose up -d postgres` |
| Port 5432 already in use | Another Postgres (e.g. brew) owns 5432 — use Docker mode (`POSTGRES_PORT=5433`) or stop the other service |
| Password authentication failed | Confirm `.env` role/password match step 3 (`langconfig` / `langconfig_dev`) and `POSTGRES_PORT` matches the running server |
| Alembic "target database is not up to date" | Re-run `uv run alembic upgrade head`; on a fresh DB re-run `uv run python scripts/seeds/seed_all.py` |
| Slow `uv sync` | Fresh venv in `backend/.venv` on first run, then incremental; dspy is intentionally **not** a dependency |
| Backend :8765 unreachable | Backend must be running; from another host use the WSL IP (`wsl hostname -I`) |
| OOM during npm/uv install (WSL2) | Bump `.wslconfig` `memory=8GB` + restart `wsl --shutdown` |
