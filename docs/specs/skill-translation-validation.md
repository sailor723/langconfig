# Skill translation — validation report

Scope: the 102 builtin skills in `backend/skills/builtin/` are now Chinese, with the English they came from
archived in `backend/skills/en-originals/` (101 translations + 1 skill authored in Chinese, `sql-analyst`).
This file records what was **verified**, with the evidence, and what is **only known** — written after the fact
of the work, in the discipline `to-validation` asks for: criteria first, then evidence, then a verdict per
criterion, and never the author's own summary standing in as proof.

## 0. The gap this file exists to close

Every check during the translation proved *shape*: same `##` heading count, same fence count, Chinese dense
enough, frontmatter pointing at the archive, `SkillLoader` parses it, no placeholder triggers. All of that can
hold while the meaning is wrong, and for a while the only quality evidence was my own spot-reading plus each
translator's self-report — the exact failure mode `to-validation` names in its first line (*"you are the
checker, not the author"*).

So the honest status at the time the work was "finished" was **UNVERIFIABLE for meaning**, PASS for shape. What
follows is what was done about that.

## 1. Criteria — written before the review

| # | Criterion | What counts as evidence |
|---|---|---|
| C1 | A translated skill has the structure of its original: no dropped or invented `##` section, no added or removed code block | `tests/test_skill_translations.py::test_structure_matches_the_english_original`, 101 parametrised cases |
| C2 | `## Instructions` / `## Examples` still work as loader delimiters | `test_the_loader_delimiters_survive_translation`, `test_the_loader_still_parses_the_chinese_skill` |
| C3 | The text an agent reads is Chinese, in proportion to how much English there was | `test_a_translated_skill_is_actually_chinese` (floor = 0.6 CJK per English **prose** word), `test_an_authored_in_chinese_skill_really_is_chinese`, `test_a_pending_skill_really_is_english` |
| C4 | No identifier, number, URL or path was lost; no code block was translated | `tests/test_skill_translation_fidelity.py`, 202 cases, driven by `scripts/skill_translation_fidelity.py` |
| C5 | Frontmatter records provenance, and a skill is in exactly one language state | `test_the_frontmatter_records_where_english_lives`, `test_every_skill_is_in_exactly_one_language_state` |
| C6 | Every skill still loads through the app's own loader, with a declared tool list the loader can see | `tests/test_imported_skills.py` (824 cases), `SkillLoader` over 102/102 |
| C7 | A skill an agent is told to consult exists under the id it is named by | `test_a_referenced_skill_id_is_the_id_that_exists`, `test_every_in_document_anchor_resolves` |
| C8 | The meaning survived: nothing invented, nothing dropped, no reversed condition, no broken contract | Independent review — four reviewers who did not translate, English against Chinese, `PASS`/`PARTIAL`/`FAIL` with `file:line` |

C8 is the one a machine cannot check, and it is the one this document exists for. Its evidence is the review
section below; where a reviewer sampled rather than read a file in full, that is said so.

## 2. Evidence — the mechanical layers

Run as of the last commit of the translation work:

```
backend$ .venv/bin/python -m pytest tests/test_skill_translations.py \
      tests/test_imported_skills.py tests/test_skill_translation_fidelity.py \
      tests/test_skill_tool_lang.py tests/test_skill_categories.py -q
1535 passed, 1 skipped

$ python scripts/skill_translation_fidelity.py
101 skill(s) keep every prose token and every code block
0 skill(s) lost a token or changed a code block  (0 changed a block whose info string says it is code)

$ python scripts/skill_zh.py status
skills 102 · translated 101 · authored in zh 1 · pending English 0

$ ./scripts/housekeeping_verify.sh
PASS 855 passed  ·  PASS tsc: no type errors  ·  PASS vite build  ·  == 3 passed, 0 failed

$ curl -s -X POST localhost:8765/api/skills/reload-all
{"status":"reloaded","skill_count":110}
```

Verdicts for the mechanical criteria: **C1–C7 PASS**, with the caveats recorded in §4.

### What the mechanical layer actually caught

It is worth writing down what these checks found, because it is the argument for having them:

| Defect | Caught by |
|---|---|
| `skill()` returned `Error loading skill …: 'StructuredTool' object is not callable` for **every** skill — an internal helper had been decorated `@tool` | Adding the first test that ever *called* the tool |
| `web-search`'s `allowed_tools` split per character, painting `**Allowed Tools:** [, ", w, e, b, …` into every prompt | `test_allowed_tools_is_a_list_of_tool_names` |
| `allowed-tools` (Anthropic spelling) never read by the loader, so 16 skills' tool lists never reached a prompt | `test_the_loader_sees_a_declared_tool_list` |
| Six guards silently running on an empty parameter set after the provenance/floor markers were translated | Fixing the markers; 308 passed + 6 empty → 614 passed |
| `implement` had lost its provenance block entirely | Fidelity check (C4) |
| `edit-ontology-metrics` said `atRiskDriver` where the English now says `atRiskDrivers` | C4 |
| Four skills called the verification floor 本仓库的地板 where 54 called it 本仓库的底线 | C6 (the moment `implement` gained a provenance block it looked generated, so it owed a floor) |
| `data-analysis` rendered "3x larger" as 大三倍 — **4× in Chinese** | C4 after two refinements of the severity rule |
| 58 skills addressed `ecosystem-primer` when the id is `lc-ecosystem-primer` | C7 |
| `chief-of-staff`'s sibling paths rewritten into prose (`` `..the `retro` skill/SKILL.md` ``) | **Not** caught mechanically — no rule for it survived the false-positive test (§4) |

## 3. Evidence — the meaning layer

Four independent reviewers, none of them a translator of the skills they read, each given the same instruction:
read the Chinese against the archived English, report `PASS` / `PARTIAL` / `FAIL` per skill, put every defect on
a `file:line`, and do not edit anything.

- **A** — the development loop: `grilling`, `to-spec`, `to-tickets`, `to-validation`, `implement`, `tdd`,
  `triage`, `retro`
- **B** — the indexes and research: `code-review`, `setup-matt-pocock-skills`, `ask-matt`, `wayfinder`,
  `handoff`, `claude-handoff`, `research`, `research-planner`
- **C** — LangChain's official set: `lc-langchain-fundamentals`, `lc-langgraph-fundamentals`,
  `lc-deep-agents-core`, `lc-langchain-rag`, `lc-eval-engineering`, `lc-langchain-middleware`
- **D** — ontology and data: `build-ontology-from-db` (45 KB), `answer-ontology-question`,
  `build-ontology-dashboard`, `edit-ontology-metrics`, `data-analysis`, `software-factory`, `chief-of-staff`

29 of 101 translations, chosen because they are the ones an agent is most likely to act on: the loop this
session itself used, the two indexes that tell an agent which skill to load, the official LangChain set, and the
ontology family where a softened refusal would cost money.

**All four reported.** 29 skills read in full: **12 PASS, 17 PARTIAL, 0 FAIL.**

| Reviewer | Skills | PASS | PARTIAL | FAIL |
|---|---|---|---|---|
| A — development loop | grilling, to-spec, to-tickets, to-validation, implement, tdd, triage, retro | triage | 7 | 0 |
| B — indexes and research | code-review, setup-matt-pocock-skills, ask-matt, wayfinder, handoff, claude-handoff, research, research-planner | code-review, setup-matt, ask-matt, handoff, research, research-planner | wayfinder, claude-handoff | 0 |
| C — LangChain official | lc-langchain-fundamentals, lc-langgraph-fundamentals, lc-deep-agents-core, lc-langchain-rag, lc-eval-engineering, lc-langchain-middleware | — | 6 (all register/terminology; no technical statement changed) | 0 |
| D — ontology and data | build-ontology-from-db, answer-ontology-question, build-ontology-dashboard, edit-ontology-metrics, data-analysis, software-factory, chief-of-staff | 5 | 2 | 0 |

No `FAIL`: nothing a reviewer read would make an agent do something wrong or unsafe. Notably, D confirmed that
every measured claim in the 45 KB `build-ontology-from-db` survived as a measurement — 213 calls split 69/68/29/15,
0.94596, 46.1 %, `columns_missing` 104→77→66→56→46→37→0 — and that no refusal was softened. C confirmed the
parameter-level facts in the LangChain set: `allowed_decisions`, the `yield`/`NotImplementedError` warning, the
FAISS/pickle warning, "interrupts must precede execution", "same embedding model for index and query".

### What the reviews found — and what was done

**The one that mattered most: five skills had lost the frontmatter that code reads.** `grilling`, `to-spec`,
`to-tickets`, `to-validation` and `implement` — the five translated by hand — kept only
`name`/`lang`/`translated`/`source`/`description`. Missing: `tags` (the sidebar taxonomy), `triggers` (the cues
`core/skills/matcher.py` reads), `allowed_tools` (the `**Allowed Tools:**` prompt line), `author`/`version` (the
MIT attribution), and `params` — which `core/skills/params.py` binds and renders as "do not re-derive these".
`to-tickets` was telling the reader to read `spec_path` while nothing declared it. All five frontmatters are
rebuilt from the archive; guard: `test_the_frontmatter_keeps_every_key_the_original_had`.

**Trigger lists collapsed 18 times.** Two English cues merged into one Chinese string narrows when a skill
fires; `tdd` had lost "or wants an integration test **that fails before the fix**" — the red half of
red-green-refactor. Every skill now carries as many triggers as its original, and going the other way three
archives gained the cue their Chinese already had.

**Words that carried the wrong meaning:** the map is an index "不是仓库" in a file where 仓库 means *repository*
(now 不是存储) · `to-spec` pointing at "Decisions 表 / Acceptance criteria" when its own template says `## 决定` /
`## 验收标准` · "追溯不到编译结果" where the English says *declaration* · "技能不会被传入子智能体" for "not
**inherited**" · 嵌入 as the object of 搜索 (now 嵌入向量).

**Vocabulary the family disagreed on:** `harness` was 框架 in 37 files and 脚手架 in the lc- set, colliding with
the LangChain framework named one clause earlier — all 37 now say 脚手架. 判词 → 结论 and 宣称 → 断言 everywhere
(判词 is a court's verdict; 宣称 is "proclaim", in a document about evidence). `ask-matt` called the `triage` skill
分流 while the skill, and `setup-matt-pocock-skills`, call it 分诊.

**Three things presented as skills that are not skills:** `ask-matt` offered "`clear` 技能" and "`compact` 技能"
as phase-boundary options, and `handoff` / `improve-codebase-architecture` named a "`tmp` 技能". The first two are
Claude Code commands, the third is the OS temp directory; they now say so, because an agent following the index
was calling `skill` for something that is not installed.

**Register:** 干活 / 吃透 / 打理 / 切出 / 造出 / 有名有姓 / 飘忽 / 挡在…之外 replaced with the plain technical
verb, and two calques of "X is how Y gets written down as Z" rewritten as Chinese.

### C8 verdict

**PARTIAL**, and the reason is worth stating precisely. On the 29 skills four reviewers read, meaning was
preserved: no `FAIL`, no reversed condition, no dropped caveat, no softened refusal, no invented advice, every
measured number still a measurement. The defects they found were field loss, narrowed triggers, vocabulary
drift and register — all now fixed, and the fixed set re-checked by the mechanical layers (1636 skill tests,
202 fidelity cases, 101/101 pairs clean).

The verdict is not PASS because **72 of 101 translations have had no independent read**. Nothing known is
broken; the claim that would be broken is "the whole library is reviewed", and that is not true yet.

### Unfixed, and why

| Item | State |
|---|---|
| Companion documents beside a skill (`ask-matt/PHASE-BOUNDARIES.md`, `code-review/STANDARDS-CHECKLIST.md`) are still English and have no archived original | recorded, not translated — they are level-3 references, not `SKILL.md`, and translating them means deciding whether they join the archive too |
| Word limits read "400 字以内" for "under 400 words" — ~half the budget in Chinese | consistent across the library, so no per-file defect; a one-line convention change if the tighter budget is unwanted |
| `to-tickets` keeps file header labels English (`Spec:` / `Blocked by:` / `Size:`) while its presented graph uses 被…阻塞 | a formatting convention to pick, not a mistranslation |
| Comments inside code fences are mixed (see §4 below) | allowed by the convention, untidy in practice |

## 4. What is known and not fixed

- **72 of 101 translations have had no independent read.** They passed C1–C7; nobody has compared them to their
  originals sentence by sentence. Saying "the library is verified" on that basis would be exactly the claim
  `to-validation` forbids.
- **No mechanical rule survived for "a path rewritten into prose".** Every candidate flagged 86 legitimate
  command spans (`pytest tests -q --ignore=…`, `POST /api/nl`). It stays an eye test, and that is recorded in
  §6b of `skills-and-tools-review-2026-11-09.md` rather than papered over with a noisy guard.
- **Two upstream defects are deliberately still broken** and listed in §6b: the TypeScript approval example in
  `lc-langgraph-human-in-the-loop` does not compile, and the `## This repository's floor` section is inert advice
  inside the six `lc-*-quickstart` skills.
- **`market-wizard`'s id promises market analysis and its body is generic CSV cleaning**, and six skills are
  stubs. Disclosed in the Chinese `name`/`description`; not renamed, not filled in.
- **Comments inside code fences are mixed**: `debugging` translated the comments around its `git bisect`
  commands, most skills kept theirs English. Allowed by the convention (a `#` comment is a sentence for a
  person), recorded in `skill-authoring.md` §5e as tidy-up work rather than as a defect.
