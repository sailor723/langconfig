---
name: "Deepagents Typescript Quickstart"
description: "Scaffold a minimal local Deep Agent in TypeScript by following the official quickstart, using provider-native web search instead of Tavily. Use when the user wants to quickly build or try a Deep Agent locally."
tags:
  - "deepagents"
  - "typescript"
  - "quickstart"
  - "langchain-skills"
triggers:
  - "The user wants to quickly build or try a deep agent locally"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "bash"
author: "langchain-skills (MIT), adapted for LangConfig"
version: "1.0"
---

> **Provenance.** Adapted from `langchain-ai/langchain-skills → config/skills/deepagents-typescript-quickstart` (MIT, vendored at `vendor/upstream-skills/langchain-skills/skills/deepagents-typescript-quickstart/SKILL.md`).
> Changed for this repository: frontmatter fields (`tags` / `triggers` / `allowed_tools` / `author` /
> `version`), path conventions (`docs/specs`, `docs/tickets`, `work/<scope>`), tool names
> (`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`), and a verification floor
> section. Upstream's `disable-model-invocation` has no equivalent here — every skill is discoverable
> through the `skill` tool, so it is dropped rather than emulated.

## Instructions

# Deep Agents TypeScript quickstart

Follow the live docs — do not invent an alternate API from memory:

**https://docs.langchain.com/oss/javascript/deepagents/quickstart**

Fetch that page (Docs MCP or HTTP) and implement the research-agent shape it shows (`createDeepAgent`, research system prompt, invoke with a research question like “What is LangGraph?”). Requires Node 22+.

## Local setup constraints

Apply these on top of the quickstart (they keep setup minimal and model-agnostic):

1. **Ask** which provider/model to use. Showcase that Deep Agents are model-agnostic. Suggested prompt:

   > Which model should this agent use? Pass a `provider:model` string — e.g. `openai:gpt-5.5`, `anthropic:claude-sonnet-5`, `google-genai:gemini-3.5-flash`. Default if you're unsure: **`anthropic:claude-sonnet-5`**.  
   > We'll use that provider's built-in web search (no separate search API key).

2. Create a **new** directory (e.g. `deep-agent/`) and do all work there — do not pollute the open project.

3. **Do not use Tavily** (or `@langchain/tavily`). Replace the quickstart's search tool with the chosen provider's built-in web search. Look up the current export/tool shape on that provider's LangChain docs (examples as of writing — re-check if needed):

   | Provider | Built-in search tool |
   |----------|----------------------|
   | Anthropic | `@langchain/anthropic` `tools.webSearch_*()` (or equivalent dict) |
   | OpenAI | `{ type: "web_search" }` |
   | Google | `{ google_search: {} }` |

   Prefer Anthropic / OpenAI / Google so provider search is available. Only secret: that provider's API key in `.env` (gitignored). Skip LangSmith tracing unless they ask.

4. Install packages from the quickstart **minus** Tavily; add the provider package for their model.

5. Run the research example, show output, then stop. Point to `deep-agents-core` / customization / Managed Deep Agents for next steps.

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
