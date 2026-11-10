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

**Status: in progress.** Verdicts are appended below as each review reports; §4 stays open until they are in.

### Reviewer verdicts

_Pending: a report is appended here for each of A–D, with the verdicts and every `file:line` defect verbatim._

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
