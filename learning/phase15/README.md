# Phase 15 — Unified Agent Platform, Deep Research, and Runtime Workspace

> Goal: define a clear architecture for how `langconfig`, `deepagents-quickstarts`, and `agent-workspace` fit together without forcing a premature code merge.
>
> This phase is a planning and system-design phase. It documents the product and engineering model we aligned on:
>
> - `LangConfig` is the **Platform Layer**
> - `deepagents-quickstarts` is the **Deep Research / Custom Solution Layer**
> - reports, DBs, HTML, JSON, and `SKILL.md` files live in the **Artifact Layer**
> - `agent-workspace` is the best candidate for the **Runtime UI Layer**
> - execution should be understood as **Batch vs Online**

---

## Why This Phase Exists

We now have three related but different repositories:

- `langconfig`
- `deepagents-quickstarts`
- `agent-workspace`

All three are about agent systems, but they do not play the same role.

If we describe them only by repo name, the system feels fragmented.

If we describe them by architecture role, the picture becomes clearer:

- one layer builds capability
- one layer packages deeply tuned business workflows
- one layer stores durable business outputs
- one layer exposes those outputs to users
- one layer explains whether execution is batch or interactive

This phase captures that model.

---

## The Five-Layer Model

```text
┌────────────────────────────────────────────────────────────┐
│ 1. Platform Layer                                         │
│    LangConfig                                             │
│    - agent IDE                                            │
│    - skills / tools / prompts / workflows                 │
│    - runtime configuration                                │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│ 2. Deep Research / Custom Solution Layer                  │
│    deepagents-quickstarts                                 │
│    - highly tuned business workflows                      │
│    - deep research pipelines                              │
│    - code-first orchestration                             │
│    - artifact-producing batch solutions                   │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│ 3. Artifact Layer                                         │
│    reports / DB / HTML / JSON / SKILL.md / dashboards     │
│    - durable business outputs                             │
│    - intermediate and final deliverables                  │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│ 4. Runtime UI Layer                                       │
│    agent-workspace (primary) + LangConfig runtime surfaces  │
│    - reports                                              │
│    - analysis                                             │
│    - agent chat                                           │
│    - doc chat                                             │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│ 5. Batch vs Online Execution Layer                        │
│    - batch for long multi-step generation                 │
│    - online for interactive runtime work                  │
└────────────────────────────────────────────────────────────┘
```

---

## 1. Platform Layer

### Definition

The **Platform Layer** is the general-purpose agent IDE and operating platform.

Its job is to define reusable agent capability rather than to encode one specific business solution.

### Current Repo

- `langconfig`

### What Belongs Here

- agent builder
- skill builder
- tool builder
- prompt builder
- workflow canvas
- model/runtime configuration
- execution control
- reusable chat/runtime framework

### Why `LangConfig` Fits Here

The codebase is primarily builder-first and configuration-first.

Representative areas:

- `src/features/agents/`
- `src/features/skills/`
- `src/features/tools/`
- `src/pages/PromptAssemblyPage.tsx`
- `backend/api/agents/`
- `backend/api/skills/`
- `backend/api/tools/`

### Short Meaning

`LangConfig` is the **Agent Studio**.

It builds capability.

---

## 2. Deep Research / Custom Solution Layer

### Definition

The **Deep Research / Custom Solution Layer** contains highly customized, code-defined, business-specific agent workflows.

This layer is broader than "workflow" in the generic low-code sense.

It includes:

- deep research
- survey generation
- business model synthesis
- action survey generation
- strategic consensus pipelines
- other highly tuned business flows

### Current Repo

- `deepagents-quickstarts`

### Why We Renamed It

At first, "Workflow Layer" sounded reasonable.

But it was too generic.

The workflows in `deepagents-quickstarts` are:

- highly custom
- artifact-heavy
- phase-based
- deeply tuned
- partly deterministic and partly agentic
- strongly tied to business folder/file conventions

That means they are not the same thing as a normal visual workflow in `LangConfig`.

So the better name is:

- **Deep Research / Custom Solution Layer**

### Important Nuance

This does **not** mean `LangConfig` can never support similar flows.

It means:

- these workflows are **not ideal** to model in LangConfig's current builder abstraction
- they are better treated as **code-first applied solutions**

### Short Meaning

`deepagents-quickstarts` is the **Applied Intelligence Engine**.

It applies capability to real business problems.

---

## 3. Artifact Layer

### Definition

The **Artifact Layer** stores the durable business outputs generated by the system.

These outputs may be:

- source artifacts
- intermediate artifacts
- final deliverables
- runtime companion artifacts

### Current Examples

From `deepagents-quickstarts`:

- `reports/...`
- research reports
- survey outputs
- business model outputs
- strategic consensus outputs
- final rendered exports

From `langconfig`:

- `data/analysis_dbs/sunhing_kpi.db`
- `data/analysis_dbs/sunhing_dashboard.html`
- other `sunhing*.html`
- `backend/skills/sunhing-analyst/SKILL.md`

### Why This Layer Matters

Workflows are transient.

Artifacts are durable.

This is the layer users eventually care about most, because it contains the actual business memory and business deliverables.

### Short Meaning

The Artifact Layer is the **source of outcomes**.

---

## 4. Runtime UI Layer

### Definition

The **Runtime UI Layer** is the user-facing workspace for consuming artifacts and interacting with live agents.

This is where users:

- browse results
- inspect documents
- open reports
- run chats
- ask follow-up questions
- work with dashboards and analysis

### Current Situation

Today there are two UI centers:

- `langconfig`
- `agent-workspace`

But they serve different mental models.

### LangConfig UI

Stronger at:

- builder/studio
- agent execution
- workflow execution
- analysis panel
- analysis chat

Weaker at:

- report-centered business workspace

### agent-workspace UI

Stronger at:

- reports
- source browsing
- document reading
- report/doc chat
- business-facing workspace feeling

Weaker at:

- generalized builder/studio capabilities

### Recommended Future Positioning

Based on current code and product direction:

- `agent-workspace` should become the **main runtime workspace UI**
- `LangConfig` should remain the **studio / builder UI**

### Recommended Runtime Modules

For `agent-workspace`:

- Reports
- Analysis
- Agent Chat
- Doc Chat
- Sources
- Runs

### Short Meaning

`agent-workspace` is the **Business Workspace**.

`LangConfig` is the **Studio**.

---

## 5. Batch vs Online Execution Layer

### Definition

This layer explains **how** the system runs, depending on business case.

There are two major modes:

- `Batch`
- `Online`

### Batch Execution

Best for:

- deep research
- report generation
- survey generation
- synthesis workflows
- strategic consensus
- long multi-step artifact production

Current alignment:

- mainly `deepagents-quickstarts`
- optionally surfaced through `agent-workspace`

### Online Execution

Best for:

- agent chat
- analysis chat
- doc chat
- dashboard Q&A
- interactive guided exploration

Current alignment:

- `langconfig` runtime surfaces
- parts of `agent-workspace`

### Key Principle

- **batch mode creates artifacts**
- **online mode consumes and extends artifacts**

---

## Repo Mapping

### `langconfig`

Primary roles:

- Platform Layer
- part of Runtime UI Layer
- part of Online Execution Layer

### `deepagents-quickstarts`

Primary roles:

- Deep Research / Custom Solution Layer
- strong connection to Artifact Layer
- primary Batch Execution Layer

### `agent-workspace`

Primary roles:

- Runtime UI Layer
- access point to Artifact Layer
- bridge between Batch results and Online interaction

---

## Product Interpretation

The three repos are not three unrelated products.

They are three roles in one broader system:

- `LangConfig` builds capability
- `deepagents-quickstarts` applies capability to business problems
- artifacts preserve the outputs
- `agent-workspace` exposes those outputs to users
- execution mode determines whether the experience is batch or interactive

---

## Recommended Product Positioning

### Back Office / Studio

- `LangConfig`

Responsibilities:

- agents
- skills
- tools
- prompts
- workflows
- runtime configuration

### Front Office / Workspace

- `agent-workspace`

Responsibilities:

- reports
- analysis
- agent chat
- doc chat
- source browsing
- run/result exploration

### Solution Engine

- `deepagents-quickstarts`

Responsibilities:

- deeply tuned business pipelines
- report generation logic
- survey and synthesis orchestration
- batch solution execution

---

## Architecture Principle

Builder and workspace should be connected, but not confused.

In practice:

- platform builds capability
- deep research/custom solution applies capability
- artifacts preserve outcomes
- runtime UI exposes outcomes
- execution mode determines interaction style

---

## What This Means For Future Merge Planning

Do **not** start from a full repo merge.

Start from role clarity.

Recommended sequence:

1. Keep `LangConfig` as the platform/studio.
2. Keep `deepagents-quickstarts` as the deep research/custom solution engine.
3. Treat `agent-workspace` as the future main runtime workspace.
4. Gradually bring `Analysis` and `Agent Chat` into `agent-workspace`.
5. Unify artifact access and project context.
6. Only later decide whether physical code merge is worth the cost.

---

## Final Summary

```text
LangConfig                 = Platform / Studio
deepagents-quickstarts     = Deep Research / Custom Solution Engine
Artifacts                  = durable outputs and business memory
agent-workspace              = Runtime Workspace UI
Execution                  = Batch for production, Online for interaction
```

This is the current best architecture model for thinking about the system as one product direction rather than three disconnected repos.
