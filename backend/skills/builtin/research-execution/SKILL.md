---
name: research-execution
description: >-
  Execute web research for a question or a list of sub-questions: climb the tool ladder (web_search →
  tavily_search → web_fetch), reflect with think_tool after every search round, self-count against a hard
  cap of 5 searches, prefer primary sources, cross-check key facts, and return findings with source URLs —
  never fabricate. Use when you are asked to research a topic, find current information, gather sources or
  evidence, verify a claim, or collect the material for a report.
tags: [research, web-search, evidence, citations, fact-checking, sources, think-tool, budget, anti-loop]
triggers:
  - "when the user asks to research a topic or find current information"
  - "when you need sources or evidence for a claim"
  - "when a planning step produced sub-questions to answer"
  - "when gathering material before writing a report"
  - "before stating any fact you have not verified with a tool"
compatibility: >-
  Requires a host agent carrying web_search / tavily_search / web_fetch. think_tool is strongly
  recommended (it is how you count the budget and avoid looping) and the graphindex tools are needed
  only for internal documents. This skill itself enables no tools.
author: LangConfig
---

This skill is **know-how, not capability**: it enables no tools. The host agent must already carry the
search tools listed under [Requirements](#requirements-provided-by-the-agent-not-by-this-skill) — an agent
without them can follow the discipline but cannot gather anything.

## Tool ladder — climb it in order

Do not reach for the most expensive tool first. Work down the ladder and only climb further when the rung
you are on cannot answer the question.

1. **web_search**:
   - **STRATEGY**: USE THIS FIRST FOR BROAD RESEARCH.
   - Use for: initial topic overview, key facts, latest developments, names, dates.
   - Why: the cheapest entry point — batch 2-4 query variants in ONE round instead of one at a time.
2. **tavily_search**:
   - **STRATEGY**: USE FOR DEPTH AND TO VERIFY, AFTER THE FIRST PASS.
   - Use for: multi-source summaries, comparisons, "current state of X", and verifying what web_search claimed.
   - Why: blends several sources, so it is the right rung for ground truth on a specific point.
3. **web_fetch**:
   - **STRATEGY**: USE SPARINGLY — at most 2 pages per task.
   - Use for: reading one promising page in full when a snippet is not enough — exact figures, tables,
     methodology, dates, wording.
   - Why: it resolves the "I only saw the snippet" risk, but it is the most expensive call.
4. **think_tool**:
   - **STRATEGY**: USE AFTER EVERY SEARCH ROUND.
   - Use for: reflection, planning the next step, and counting the budget.
5. **graphindex_search** / **graphindex_load**:
   - **STRATEGY**: USE BEFORE THE OPEN WEB when the question concerns the organisation's own documents.
   - Why: internal sources outrank public ones for internal questions.

**CRITICAL: Use think_tool after each search to reflect on results and plan the next step.**
Do not open a new search round without having called think_tool since the previous one.

Never claim a precise detail you only saw in a snippet if the page is fetchable — fetch it, or mark it
unverified.

## Reflect after every search round (`think_tool`)

After each search tool call, use `think_tool` to analyze the results:

- **Count**: state it explicitly — `searches used: n/5` (see the cap below).
- What key information did I find?
- What's missing?
- Do I have enough to answer the task comprehensively?
- Should I search more or provide my findings?
- **Budget Consideration**: am I using the budget efficiently (n/5 used)? Should I switch to the other
  search tool for the remaining queries?
- **Source Quality**: are the sources reliable and authoritative? Do I need to verify information with
  additional sources?
- **Search Strategy**: what should my next search focus on to fill remaining gaps?

If you cannot name a next search focus, you are looping, not researching — stop and write up what you have.

## Budget — self-tracked, hard cap

The tools report no remaining budget, so **you** are the counter, and the cap is absolute:

- **HARD CAP: 5 search calls per task** (`web_search` + `tavily_search` combined). This is a ceiling, not a
  target — 2-3 is the normal case, 5 is the maximum.
- **Never exceed 5, and never state a budget other than 5.** Do not invent a larger number.
- **Self-count (MANDATORY)**: the tools report no remaining budget, so YOU are the counter. Every
  `think_tool` call must state the count against 5, e.g. `searches used: 3/5`.
- `web_fetch` draws on the same budget: at most 2 pages.
- **At the cap:** if you reach 5 and gaps remain, stop searching, write up what you have, and list the
  remaining gaps. An explicit gap beats one more search.

**Stop Immediately When**:
- You have comprehensive information covering what the question asked
- You have 3+ relevant high-authority sources for the key facts
- Your last 2 searches returned similar information

**ANTI-LOOP RULE (MANDATORY — do not skip)**:
- NEVER call a search tool with the exact same query twice in one research session. Repeating an identical
  query is FORBIDDEN — it wastes budget and never returns new information.
- If a search returns no usable content (empty result, fetch error, or irrelevant pages), do NOT retry the
  same query. Change the keywords, try a different search tool, or move on and use the best source you
  already have.
- Maximum 2 attempts per individual fact. If still not found, record the gap in your findings and continue —
  never loop.
- If your last 2 searches returned nothing new, STOP searching and write up your findings from what you have.
- If the primary search tool returns a rate-limit or "temporarily unavailable" message, switch to the other
  search tool for the remaining queries — do not retry the same one.

## Procedure

Think like a human researcher with limited time. Follow these steps:

1. **Read the question carefully** — what specific information does the user need?
2. **Start with `web_search`** — batch 2-4 query variants in ONE round for broad coverage.
3. **Follow with `tavily_search`** — deep dive on specific points and verify what you found.
4. **Use `web_fetch` as needed** — only when a snippet is not enough.
5. **After each search, pause and assess** — do I have enough to answer? What's still missing?
6. **Execute narrower searches as you gather information** — fill in the gaps.
7. **Stop when you can answer confidently** — don't keep searching for perfection.

## Query craft

- Write **2-4 variants**, not one. Include the topic's own language *plus* English when the subject is
  regional (e.g. Chinese + English for a China-market question) — coverage differs significantly.
- Reformulate after a weak pass: entity + year, the primary source's own vocabulary ("10-K", "annual
  report", "guideline", "standard"), or a narrower sub-question.
- **Check dates.** For "current", "latest" or year-scoped questions, discard stale material and state the
  period your findings cover.
- When a plan produced sub-questions, answer each one explicitly and in order. Do not silently drop the
  hard ones.

## Preferred sources, ranked

1. **Primary/official** — the organisation's own filings, annual and interim reports, investor
   presentations, standards, official documentation, press releases.
2. **Regulatory & statistical** — regulators, statistical agencies, central banks, courts.
3. **Peer-reviewed & institutional** — journals, IEA/IRENA-class institutions, universities.
4. **Reputable financial/business press** — Reuters, Bloomberg, FT, WSJ, CNBC, Nikkei.
5. **Wire/aggregator/listicle** — a *lead*, never evidence. Trace it back to the primary source before
   citing it.

## Verification — the non-negotiable

- **Never fabricate.** Every factual claim must trace to a result you actually retrieved. If a tool returned
  nothing, write "not found" rather than filling the gap from memory.
- **Cross-check** any number, date, name or price against at least two independent sources.
- **When sources conflict**, present both and flag the disagreement — do not silently pick one.
- Separate *what the source says* from *what you infer*. Mark estimates as estimates.
- Quote sparingly and exactly; a mis-quoted source is worse than no quote.

## Output shape

Return findings, not an essay:

- **Every fact and figure carries its source URL inline.**
- **`### Sources`** at the end: the URLs you actually used (not merely searched).
- **`Unverified: ...`** as the last line for anything you could not confirm (or `Unverified: none`).
- Keep each finding to one or two sentences; the writer step expands them, not you.
- **No process narration.** Do not write "I will now search…", "Let me reflect…", or "I have strong
  information from N searches" — no commentary about your own steps, and no restating these instructions.
- If you saved a file, report its **exact** path and name, copied from the tool result.
- Hand this structure to a writer step unchanged so the citations survive into the final document.

## Stopping rule

Stop when every sub-question has at least one credible source, or at the 5-search cap, or after roughly
**three** reformulation attempts on the same question — then report the gap. Searching beyond that costs
tokens without improving the answer. "Confidently incomplete" beats "endlessly thorough".

## Not this skill's job

- **Decomposing** a broad topic into sub-questions → use the `research-planner` skill first.
- **Emitting** the finished document as a file → use the `document-deliverables` skill.

This skill covers the middle: gathering and verifying the material.

## Requirements (provided by the agent, not by this skill)

| Tool | Needed for |
|---|---|
| `web_search` | discovery and quick facts (rung 1) |
| `tavily_search` | multi-source summaries and verification (rung 2, recommended) |
| `web_fetch` | reading full pages (rung 3) |
| `think_tool` | the post-search reflection + budget count (strongly recommended) |
| `graphindex_search` / `graphindex_load` | internal documents, when the question concerns them |

Tools are selected on the **agent**, so this skill attaches unchanged to a research agent, a fact-checking
agent, or an orchestrator that only delegates.

---

*Origin: LangConfig **hello** agent (id 159, category `general`) — three research rules (search with
`web_search`/`web_fetch`, verify with real tool results instead of fabricating, plan long tasks with
`write_todos`). Reconverted and reconfirmed against agent **212** (`origin_research_execution`), whose prompt
is the validated pattern: the tool ladder, the 7-step Procedure, the Hard Limits (including the self-counted
5-search cap and the ANTI-LOOP RULE), the `think_tool` requirement and the output contract are ported from it
— the guardrails verbatim, because when the cap was uncounted and loosely worded the agent invented a larger
budget ("4/8") and overshot, while the exact wording produced consistent "searches used: n/5" compliance.
This skill adds what no single agent prompt carried: ranked source tiers, a verification section, a stopping
rule and the requirements table. Deliberately left agent-side: role, language, workspace, and the choice of
file tool (`write_file` on 212 / `save_document` on 211). Its document/file-output half lives in the
`document-deliverables` skill.*
