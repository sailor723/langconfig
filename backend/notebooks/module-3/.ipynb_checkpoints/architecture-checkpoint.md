# Phase 1 (ERP-only) Agent Architecture

This diagram explains the Phase 1 architecture in `notebooks/module-3`.

## Component View

```mermaid
flowchart TB
  user[User / Business Analyst] -->|Draft PRD idea| agent["Phase 1 Agent Runtime<br/>phase1_agent.py"]

  subgraph config["Configuration - File Driven"]
    agents_md["AGENTS.md<br/>Global rules & boundaries"]
    subagents_yaml["subagents.yaml<br/>clarifier / prompt-architect / reviewer"]
    skills_dir["skills/<br/>workflow skill instructions"]
  end

  agent --> agents_md
  agent --> subagents_yaml
  agent --> skills_dir

  subgraph artifacts["Artifacts - Source of Truth on Disk"]
    prd["artifacts/prd.md<br/>PRD (aligned to .docx template)"]
    metrics["artifacts/ERP_指标口径字典模板.md<br/>ERP metrics dictionary"]
    sys_prompt["artifacts/system_prompt.md<br/>System prompt (ERP-only)"]
    sys_prompt_review["artifacts/system_prompt_review.md<br/>Prompt review report"]
  end

  agent <-->|read/write| artifacts

  erp[(Standard ERP Data Source)] -->|exports / query results| agent

  agent -->|Generate| sys_prompt
  agent -->|Review| sys_prompt_review

  metrics -.enforces.-> agent
  prd -.grounds.-> sys_prompt
```

## Workflow View (Phase 1)

```mermaid
sequenceDiagram
  autonumber
  participant U as User / Customer
  participant A as Phase 1 Agent
  participant FS as Filesystem (artifacts/)
  participant ERP as Standard ERP (exports/results)

  U->>FS: Write artifacts/prd.md (customer input)
  A->>FS: Read artifacts/prd.md
  A->>FS: Read artifacts/ERP_指标口径字典模板.md (if exists)
  A->>FS: Write artifacts/system_prompt.md (ERP-only system prompt)
  A->>FS: Write artifacts/system_prompt_review.md (pass/revise/blocked)
  A->>U: Confirm outputs
```

## Tooling-Level View (Agent / TODO / Tools / Subagents)

This view shows how the Deep Agents runtime is assembled (middleware + tools) and how each element contributes to the end-to-end workflow.

```mermaid
flowchart LR
  subgraph runtime["Deep Agents Runtime"]
    A["Main Agent<br/>create_deep_agent(...)"]

    subgraph mw["Middleware Stack"]
      T["TodoListMiddleware<br/>(write_todos tool)"]
      F["FilesystemMiddleware<br/>(ls/read_file/write_file/edit_file/glob/grep)"]
      S["SubAgentMiddleware<br/>(task tool)"]
      Sum[SummarizationMiddleware]
      Cache[Prompt caching / patch toolcalls]
    end

    A --> mw
  end

  subgraph skills["Workflow Skills - Instruction Files"]
    SI[prd-intake]
    SG[system-prompt-generator]
    SR[reviewer]
  end

  subgraph subagents["Specialists - subagents.yaml"]
    C[clarifier]
    P[prompt-architect]
    R[reviewer]
  end

  subgraph tools["Built-in Tools Exposed to Agent"]
    todo[write_todos]
    ls[ls]
    read[read_file]
    write[write_file]
    edit[edit_file]
    glob[glob]
    grep[grep]
    exec["execute<br/>(optional; backend-dependent)"]
    task["task<br/>(call subagents)"]
  end

  A --> skills
  A --> tools

  task --> subagents

  subgraph artifacts["Artifacts Output - Phase 1"]
    PRD["artifacts/prd.md<br/>(customer input, read-only)"]
    MET["artifacts/ERP_指标口径字典模板.md<br/>(metrics dictionary)"]
    SP["artifacts/system_prompt.md<br/>(ERP-only)"]
    SPR[artifacts/system_prompt_review.md]
  end

  write --> artifacts
  read --> artifacts

  SI -->|reads| PRD
  SI -->|may request| MET
  SG -->|reads| PRD
  SG -->|reads| MET
  SG -->|writes| SP
  SR -->|reads| SP
  SR -->|writes| SPR

  ERP[(Standard ERP<br/>exports/query results)] --> read
```

## Key Design Rules (Why This Works)

- PRD is the single source of truth for scope, boundaries, approvals, and fallback behavior.
- Phase 1 is ERP-only: no cross-system joins unless explicitly moved to a later phase.
- The metrics dictionary is mandatory when present: analyses must cite its version and assumptions.
- Review is not optional: every key output should produce a review status (pass/revise/blocked).
