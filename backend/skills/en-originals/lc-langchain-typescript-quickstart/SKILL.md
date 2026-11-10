---
name: "Langchain Typescript Quickstart"
description: "Scaffold a minimal local LangChain agent in TypeScript by following the official quickstart. Use when the user wants to quickly build or try a LangChain agent locally."
tags:
  - "langchain"
  - "typescript"
  - "quickstart"
  - "langchain-skills"
triggers:
  - "The user wants to quickly build or try a langchain agent locally"
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

## Instructions

> **Provenance.** Adapted from `langchain-ai/langchain-skills → config/skills/langchain-typescript-quickstart` (MIT, vendored at `vendor/upstream-skills/langchain-skills/skills/langchain-typescript-quickstart/SKILL.md`).
> Changed for this repository: frontmatter fields (`tags` / `triggers` / `allowed_tools` / `author` /
> `version`), path conventions (`docs/specs`, `docs/tickets`, `work/<scope>`), tool names
> (`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`), and a verification floor
> section. Upstream's `disable-model-invocation` has no equivalent here — every skill is discoverable
> through the `skill` tool, so it is dropped rather than emulated.


# LangChain TypeScript quickstart

Follow the live docs — do not invent an alternate API from memory:

**https://docs.langchain.com/oss/javascript/langchain/quickstart**

Fetch that page (Docs MCP or HTTP) and implement what it shows (weather agent + `createAgent`). Requires Node 22+.

## Local setup constraints

Apply these on top of the quickstart (they keep setup minimal and model-agnostic):

1. **Ask** which provider/model to use. Showcase that LangChain is model-agnostic. Suggested prompt:

   > Which model should this agent use? Pass a `provider:model` string — e.g. `openai:gpt-5.5`, `anthropic:claude-sonnet-5`, `google-genai:gemini-2.5-flash-lite`. Default if you're unsure: **`anthropic:claude-sonnet-5`**.

   Swap the quickstart's model string for their choice (or the default).

2. Create a **new** directory (e.g. `langchain-agent/`) and do all work there — do not pollute the open project.

3. Only secret: the provider API key in `.env` (gitignored). No LangSmith / Tavily unless they ask. Prefer they edit `.env` themselves — don't paste keys into chat.

4. Install the provider package needed for their model if the quickstart's base install isn't enough.

5. Run the example, show output, then stop. Point to `lc-langchain-fundamentals` for next steps.

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
  `lc-ecosystem-primer` rule — and prefer the highest layer that does the job.
