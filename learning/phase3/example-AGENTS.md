# My First Project — Project Base Configuration

<!-- This file defines the PROJECT BASE for My First Project (project_id=1). -->
<!-- It's loaded into every DeepAgent's system prompt via MemoryMiddleware. -->
<!-- Edit it to update the LLM, tools, and conventions for this project. -->
<!-- Agents can also update it at runtime via the `edit_file` tool. -->

---

## How Settings Are Resolved (Important!)

There are **4 settings locations** in this system. When you (the agent) need
to know what's configured, here's the precedence (highest first):

| Priority | Location | What it contains |
|---|---|---|
| **1** | `agent.config.*` | **The actual values used when this agent runs** |
| 2 | `project.configuration.*` | Project-level defaults (only used if agent doesn't override) |
| 3 | `settings` (global) | App-wide defaults (UI, services) |
| 4 | hardcoded | Last-resort fallback |

**Example**: For `demo_deep_agent` (id=84):
- ✅ `agent.config.model` = `minimax-m3` ← **THIS is what's actually used**
- ❌ `project.configuration.default_model` = `gpt-4o` ← IGNORED (agent overrides)
- ❌ `settings.default_model` = `deepseek:deepseek-chat` ← IGNORED

**When in doubt, trust the agent's own config, not the project defaults.**

---

## Project Base

This section describes the project's intent and what tools/agents it has.

### Identity

| Field | Value |
|---|---|
| Project name | My First Project |
| Project ID | `1` |
| Description | A test project |
| Status | Active (ready for agents) |
| Created | 2026-05-31 |
| Updated | 2026-06-17 |

### Knowledge Base

- **Indexed nodes**: 496 documents/chunks
- **Embedding dimension**: 384
- **Indexing status**: Ready
- **Use for**: Semantic search via RAG.

### Tools Available (project-wide)

All agents in this project have access to:

- **Native tools** — filesystem, git, web search, time, sequential-thinking, etc.
- **Math tools** — `math_add`, `math_multiply`, `math_subtract`, `math_divide`, `math_sqrt`
- **Memory tools** — `memory_store`, `memory_recall` (via SimpleMemory)
- **Custom tools** — User-defined tools (per-agent)
- **MCP tools** — Optional Model Context Protocol integrations

### LLM Models Used in This Project

This project does not lock the LLM — different agents can use different models.
Models currently in use across agents:

- `minimax-m3` (MiniMax M3) — 6 agents (e.g. demo_deep_agent, doc-chat, research_1)
- `deepseek-chat` / `deepseek:deepseek-chat` — 13 agents
- `claude-sonnet-4-5-20250929` (Anthropic) — 5 agents (Deep Researcher/Architect/...)

**Project default (overridable per agent)**: `gpt-4o`
**Note**: The project default is NOT auto-applied. Each agent has its own model in `agent.config.model`.

---

## Conventions

### Code Style

- **Python**: 3.13
- **TypeScript**: strict mode
- **Formatting**: Let the project's linter handle it
- **Tests**: Run before committing

### Common Commands

```bash
# Backend
cd backend
.venv/bin/python -m pytest                    # run tests
.venv/bin/uvicorn main:app --port 8765        # run server

# Frontend
npm run dev                                     # start dev server
npm run build                                   # production build
npm run tsc -- --noEmit                        # type check
```

### Working Style

- Prefer small, focused changes
- Verify with smoke tests after each change
- Use the chat interface to test agents interactively
- This is a **test project** — feel free to experiment, but log destructive actions

---

## Memory Guidelines

Use the `memory_store` tool to save:
- Important conventions discovered during the session
- Decisions and their rationale
- Patterns or anti-patterns to avoid

Use `memory_recall` to retrieve them in future sessions.

The `AGENTS.md` file (this file) is for **project-level static context** that all agents
should always see. Use `memory_store`/`memory_recall` for **agent-level dynamic facts**.

---

## Notes for the Agent

- **Trust the agent's own config first.** Project defaults are only used if the agent doesn't override.
- This is a **test project** for trying out different agent configurations
- When uncertain, ask the user before making irreversible changes
- Update this file (via `edit_file`) if you learn something useful about the project
- Different agents in this project use different LLMs — check `agent.config.model` to know which one
