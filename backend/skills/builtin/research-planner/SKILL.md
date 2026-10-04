---
name: research-planner
description: >-
  Decompose a broad research topic into 4-8 focused, independent sub-queries that can be
  researched in parallel, covering concepts, entities, timelines, relationships and
  perspectives. Use when planning research, scoping a topic, breaking a question into
  searchable sub-questions, or before a multi-step web-research run.
tags: [research, planning, decomposition, sub-queries, methodology]
triggers:
  - "when user asks to research a topic or plan a study"
  - "when a broad question needs breaking into sub-questions"
  - "when user says 'research plan', 'sub-queries' or 'decompose this topic'"
  - "before multi-step web research"
allowed-tools: []
author: LangConfig
---

Decompose a research topic into a comprehensive set of focused, independent sub-queries. The expertise
this encodes is information architecture, research methodology and query formulation.

**This skill needs no tool calls.** It is pure reasoning: read the topic, return the plan. Do not
search, fetch or write files as part of producing the decomposition.

## Process

1. Understand the scope and depth the main topic requires.
2. Identify key concepts, entities, timelines, relationships and perspectives.
3. Formulate **4-8** specific questions that, answered collectively, give complete coverage.
4. Ensure the questions are independent and can be researched **in parallel**.

## Constraints

- Questions must be specific and answerable through web research.
- Avoid overlap between questions — two questions that return the same sources are one question.
- Cover all essential aspects of the topic; do not stop at the first obvious angle.
- When the topic has a time dimension, scope it explicitly (e.g. "as of 2026") rather than leaving
  it open.

## Output

Return **only** a JSON array of strings — no prose, no headings, no code fence, no commentary
before or after:

```json
[
  "What are the current market trends in X?",
  "Who are the key players in Y?",
  "What are the technical challenges in Z?"
]
```

**CRITICAL: the response must be ONLY the JSON array — nothing else.** No preamble, no explanation, no
summary of the plan in prose.

If the host agent supports structured output, enforce this shape with a schema rather than relying
on the instruction alone — for example
`response_format={"type": "array", "items": {"type": "string"}}`.
Prompt-only contracts are reliable on a fresh turn and drift on follow-ups; the schema is not.

## Using the result

The sub-queries are deliberately independent, so the caller can:

- run them as a **parallel fan-out** (LangGraph `Send`, or one subagent per query), or
- issue them as separate searches and synthesise afterwards, or
- hand them to a writer/critic step as a research checklist.

For a single-topic question that one search would answer, skip this skill — decomposition is
overhead when the answer is not multi-hop.

---

*Reconverted from the LangConfig **Research Planner** agent (id 161, category `system`, authored base 944
chars). Ported from it: the process, the constraints and the JSON-only output contract with its CRITICAL
emphasis. Added during conversion: the description in what+when form for skill discovery, the
structured-output recommendation, the parallel-fan-out note, and the "skip this skill when the answer is not
multi-hop" guard. Left agent-side: the role/identity framing, the model, the language preference and the
baked workspace blocks. This skill needs no tools — it is pure reasoning and enables nothing.*
