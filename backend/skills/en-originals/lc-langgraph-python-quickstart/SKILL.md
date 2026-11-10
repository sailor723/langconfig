---
name: "Langgraph Python Quickstart"
description: "Scaffold a minimal local LangGraph agent in Python by following the official quickstart. Use when the user wants to quickly build or try a LangGraph agent locally."
tags:
  - "langgraph"
  - "python"
  - "quickstart"
  - "langchain-skills"
triggers:
  - "The user wants to quickly build or try a langgraph agent locally"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
author: "langchain-skills (MIT), adapted for LangConfig"
version: "1.0"
---

> **Provenance.** Adapted from `langchain-ai/langchain-skills → config/skills/langgraph-python-quickstart` (MIT, vendored at `vendor/upstream-skills/langchain-skills/skills/langgraph-python-quickstart/SKILL.md`).
> Changed for this repository: frontmatter fields (`tags` / `triggers` / `allowed_tools` / `author` /
> `version`), path conventions (`docs/specs`, `docs/tickets`, `work/<scope>`), tool names
> (`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`), and a verification floor
> section. Upstream's `disable-model-invocation` has no equivalent here — every skill is discoverable
> through the `skill` tool, so it is dropped rather than emulated.

## Instructions

# LangGraph Python quickstart

Follow the live docs — do not invent an alternate API from memory:

**https://docs.langchain.com/oss/python/langgraph/quickstart**

Fetch that page (Docs MCP or HTTP) and implement what it shows (calculator / math agent with the Graph API). Prefer the Graph API path over the Functional API unless the user asks otherwise. Skip IPython graph visualization.

## Local setup constraints

Apply these on top of the quickstart (they keep setup minimal and model-agnostic):

1. **Ask** which provider/model to use. Showcase that LangGraph works with any LangChain chat model. Suggested prompt:

   > Which model should this agent use? Pass a `provider:model` string — e.g. `openai:gpt-5.5`, `anthropic:claude-sonnet-5`, `google_genai:gemini-2.5-flash-lite`. Default if you're unsure: **`anthropic:claude-sonnet-5`**.

   The docs often hardcode Anthropic — replace with `init_chat_model("<MODEL>")` (or equivalent) using their choice. If using Claude Sonnet 5+, omit `temperature` / `top_p` / `top_k` (unsupported).

2. Create a **new** directory (e.g. `langgraph-agent/`) and do all work there — do not pollute the open project.

3. Only secret: the provider API key in `.env` (gitignored). No LangSmith / Tavily unless they ask. Prefer they edit `.env` themselves — don't paste keys into chat.

4. Install packages from the quickstart plus the provider package for their model.

5. Run the example (e.g. “Add 3 and 4.”), show output, then stop. Point to `langgraph-fundamentals` for next steps. For a higher-level agent API, use LangChain `create_agent` instead.

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
