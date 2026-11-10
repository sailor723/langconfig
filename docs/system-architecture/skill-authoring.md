# Skill authoring — how to turn a working agent into a reusable skill

**Status:** working method, validated on `research-execution` (agent 212 → skill). Date: 2026-10-03.

The purpose of this doc: stop the most common mistake — *"I have a prompt that works, so I'll paste it into a
skill."* That produces a skill that only fits the agent it came from. A skill is not a prompt; it is the part
of a prompt that is **true for every agent that could load it**.

---

## 1. The mental model

| | Agent prompt | Skill |
|---|---|---|
| Audience | one agent | any agent that loads it |
| Contains | role, task, tools, language, workspace, install rules | portable know-how only |
| Enables tools? | yes (it selects them) | **no — it enables nothing** |
| Fails when | it is too generic | it is too specific |

So the conversion is a **classification**, not a copy.

## 2. Sort the prompt into four buckets

Every sentence goes into exactly one bucket. Only **C** becomes the skill.

| Bucket | What belongs there | Where it goes | Example from agent 212 |
|---|---|---|---|
| **A. Identity & task** | who the agent is, what it is for, workspace, language, tone | agent prompt | `<Task>` block; "please answer in Chinese"; identity block |
| **B. Tool inventory** | which tools exist and which to prefer *by name* | agent prompt — the skill may only state **requirements** | "You have access to research tools…" |
| **C. Portable know-how** | how to do the work well: budgets, anti-loop, reflection, source ranking, verification, output contract, stopping rule | **the skill** | Hard Limits; ANTI-LOOP RULE; Show Your Thinking; `### Sources` contract |
| **D. Install-specific rules** | this platform's file tools, panel names, quirks | agent prompt | "use `write_file` only, never `save_document`, files appear in the Files panel" |

**Rule of thumb:** if the sentence would still be correct on a *different* agent, on a *different* platform,
it can be bucket C. If it names a tool, a path, a model or a language — it is A/B/D.

## 3. Guardrails are copied verbatim

Behavioural guardrails are enforcement text, not prose. Copy them **word for word**; rewrite the framing
around them freely.

Measured evidence from agent 212:

| Wording | Observed behaviour |
|---|---|
| Cap split across "simple 2-3 / complex up to 5 / always stop after 5 *if you cannot find*", no counting rule | agent invented a ceiling of **8**, self-reported "4/8", and used **6** searches |
| `HARD CAP: 5 search calls per task … never state a budget other than 5 … At the cap: stop and list the gaps` + `searches used: n/5` in every reflection | two consecutive runs reported **"4/5"** and used **5** and **4** searches |

The only change was wording. Treat the anti-loop rule, stop conditions and hard caps this way.

## 4. The recipe

1. **Make the agent work first.** You need a measured baseline to test the skill against. Record it
   (searches used, budget statement, tool order, output path).
2. **Annotate the prompt with the four buckets.** Physically mark A/B/C/D — everything in C is skill candidate.
3. **Write the skill in "do X" voice.** Tool references should be *classes* of capability
   (`web_search` / `tavily_search` / `web_fetch` are generic; `save_document` is not). Paste bucket-C
   guardrails verbatim.
4. **Add the sections an agent prompt doesn't need but a skill does:**
   - what + when, in the `description` (this is the entire discovery surface);
   - verification rules;
   - ranked source tiers;
   - a stopping rule;
   - `## Not this skill's job` — explicit hand-offs to sibling skills;
   - `## Requirements (provided by the agent, not by this skill)` — a table naming the tools the host agent
     must carry.
5. **Frontmatter** — what is enforced and what is decoration:

   | Key | Reality |
   |---|---|
   | `name` | must equal the directory name, lowercase kebab-case. A violation only **warns** — the skill still loads |
   | `description` | *what + when*, ≤1024 chars; longer is **silently truncated**. This single line is how the model discovers the skill |
   | `tags`, `triggers` | UI/metadata only — the deepagents SDK **ignores** them |
   | `allowed-tools` | parsed and rendered into the prompt, but **never enforced** — metadata, not a permission system |
   | `author`, `license`, `compatibility` | metadata (`compatibility` truncates at 500) |

6. **Sync and verify.** The DB row is the runtime source of truth (see §5). After editing `SKILL.md`:
   `POST /api/skills/reload-all` with body `[]`, then confirm the DB `instructions` length, the `description`,
   and the **level-1 catalog line** the model actually reads.
7. **Test the skill as a behaviour spec.** Minimum checks:
   - **Discovery** — does an agent that was never told the skill name load it from the catalog?
   - **Compliance** — does it obey the cap, the anti-loop rule and the output contract?
   - **A/B** the wording when you change a guardrail: ≥3 samples per arm, compare medians.

## 5. How skills are served in LangConfig (db mode)

| Fact | Consequence for authors |
|---|---|
| The **DB row** is what `SkillsMiddleware` serves; `SKILL.md` on disk is the git-tracked source | editing the file alone changes nothing until you reload |
| `_stage_skill_catalog` re-serialises **every** skill row to storage on each agent build under `skills/<source_type>/<skill_id>/SKILL.md` | no per-skill staging step; but see the next row |
| Storage keys are **written, never pruned** | moving a skill between roots (personal → builtin) leaves the old object behind |
| Sources are handed to the middleware in order `[/skills/builtin, /skills/personal]` and the middleware merges by **name, last source wins** | a stale personal copy **shadows** the current builtin one — check before promoting a skill: the old duplicate leaves a storage object behind (see the row above) |
| `config.skills` (the Skills picker) has **no runtime effect** in db mode | pinning ≠ enabling. Discovery is library-wide |
| `SkillsMiddleware.before_agent` loads `skills_metadata` **once per thread** | the catalog is frozen for that conversation; a new/edited skill needs a new chat |
| The catalog is metadata only; level 2 is `read_file` on the path, level 3 is whatever that body references | the skill must be readable **as a file**, and the agent must carry a file-reading tool |

## 5b. Skills that ship scripts (`scripts/`, `references/`)

A skill whose value is *running* something — `build-ontology-from-db` ships three Python
scripts — needs three things a markdown-only skill never did. All three were broken in this
platform and are now fixed; each failed silently in a different way:

| Requirement | Why a markdown-only skill never needed it | How it broke, and the fix |
|---|---|---|
| the skill's **sibling files are staged**, not just `SKILL.md` | level-3 references were all prose before | db mode saved only the rendered `SKILL.md`. `_stage_skill_catalog` now persists every file under the skill prefix and mirrors it under `assets_root` (`Staged 69 skill asset file(s) for 45 skill(s)`) |
| the **mirror is served, not DbBackend** | a virtual path is unreadable to a shell | sources become `skills/<type>` on disk so `SkillsMiddleware` reads through the sandbox (`Serving skills from the sandbox mirror … execute stays available`) |
| the backend still **exposes `execute`** | file-only skills need only `read_file` | `supports_execution()` tests `isinstance(backend, SandboxBackendProtocol)` and the format-aware wrapper was not one → no `execute` tool at all. `FormatAwareBackend.wrap()` returns a subclass that registers *as* `SandboxBackendProtocol` |

One more trap that costs a run every time it is missed: **file-tool paths and shell paths
differ.** `read_file` accepts the virtual root (`/skills/builtin/<s>/SKILL.md`); `execute`
runs on the real filesystem rooted at the workspace, where the same file is
`skills/builtin/<s>/SKILL.md`. An agent not told this tries `/skills/...`, gets "no such
file", and *copies the script elsewhere to run it* — which works, so nothing looks broken,
while the staged copy was never exercised. The factory appends a "Shell paths vs. file-tool
paths" block whenever a sandbox is active, and
`scripts/test_ontology_skill_platform_agent.py` asserts **P3d: the script ran from the
mirror, not a copy.**

A second platform fix came out of the same test: **`tool_end` events carried
`"output": null`** for any tool returning an object (`ToolMessage`, a pydantic model, or
deepagents' `ExecuteResponse`), because `make_json_safe` only kept primitives. The agent
could still act, but the UI showed an empty result and the test could not see stdout.
`make_json_safe` now unwraps `.content`, dataclasses and `model_dump()` before giving up.

## 5c. Which root a skill belongs in, and who can see it


Two roots, and the difference is now enforced rather than nominal:

| Root | Who sees it | Path |
|---|---|---|
| **builtin** | everyone, every agent | `backend/skills/builtin/<skill_id>/SKILL.md` |
| **personal** | one account | `backend/skills/personal/<user id>/<skill_id>/SKILL.md` |

Personal skills used to sit in one flat `personal/` folder shared by every account, and the
`skills` table had no owner column — so "personal" meant nothing. Migration `036` added
`owner_id` (NULL = builtin, shared; set = that account's) and `UNIQUE(owner_id, skill_id)`
so two accounts may each own a skill with the same id. The loader discovers one level
deeper, and **refuses a flat `personal/<skill>/` layout** rather than adopting it back into
the shared namespace. Move folders with `scripts/adopt_personal_skills.py`.

The test for which root: **would a new colleague need this on day one, for work that is not
yours?** If yes it is `builtin` (`code-review`, `web-search`, `sql-analyst`, `git-workflow`).
If it names your company, your market, or your data, it is `personal` (`sunhing-analyst`,
`a-share-research`, `erp-analyst`). Of this install's 25 "personal" skills, 16 were generic
and moved; see `scripts/reclassify_skills.py`.

Two consequences worth designing around, because progressive disclosure puts **every**
skill's name + description into **every** agent's prompt:

- **A shared agent that pins a personal skill cannot see it.** `config.skills` lists ids; a
  skill the calling account does not own is skipped, with a log line. That is the intended
  behaviour — the alternative (falling back to the owner's copy) would undo the isolation.
- **Two skills that claim the same trigger make the model guess.** This is a real
  collision, not a theoretical one: `code-review` and `git-workflow` both listed "pull
  request", and a "review this PR" request matched both. Review owns the *content* of a
  review; git-workflow owns branch/merge/rebase/release mechanics and says so in its own
  body. When adding a skill, grep the other triggers for its main words first.

## 5d. Skills that hand artifacts to a workbench

A skill can produce something another program must load — here an ontology workbench that
reads ONE profile file and nothing else. Two facts from that build are worth generalising:

**The credential belongs in configuration, not in the conversation.** The agent's
`datasource` names a Settings → Databases entry; the factory exports it to the sandbox as
`PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGPASSWORD` and tells the prompt the target
*without* the secret. Measured: the agent ran `psql -c 'select current_database()'` and got
`clinic_db`; no DSN and no password appeared in any message. A prompt that carries a DSN
leaks it into the transcript, the checkpoint and every log line.

**The loader's requirements belong in configuration too.** `config.workbench` carries the
profile filename, the fields the workbench fixes (namespace, overlay name, guard limits,
feature flags), the values the build must *decide* from the introspected data (window vs
refuse, big tables, samples, labels, aliases) and the gate ids that must be green. The
skill body stays host-agnostic — it says *what* to decide and *why*, never what this
workbench wants. Measured: with the contract in the prompt and nothing about the profile in
the user's message, the agent wrote the profile to the specified filename, copied the fixed
fields verbatim, and wrote its own reasoning for each decided value.

Two things the build proved about gate ids: naming them in the contract makes the agent
**report numbers** instead of claiming success, and an agent that cannot run a gate says so
(the compiler lived in another repository, so it said "not run" — the honest answer).

## 5e. Which language a skill is written in

**The text an agent reads is Chinese.** `backend/skills/builtin/<id>/SKILL.md` holds the Chinese body;
the English it came from is archived to `backend/skills/en-originals/<id>/SKILL.md`, which sits *outside*
both scanned roots (`builtin/`, `personal/`) so nothing stages it, indexes it, or puts it in a context
unless a caller asks for `skill(id, lang="en")` by name.

| State | Where it is declared | What the test asserts |
|---|---|---|
| translated | an archive exists at `en-originals/<id>/SKILL.md` | the body is Chinese, its structure matches the original, `lang: zh` and `source:` are in the frontmatter |
| authored in Chinese | `backend/skills/zh-native.txt` | there is no English original; the body is Chinese |
| still English | `backend/skills/pending-zh.txt` | the body really is English — the list cannot drift into a wish-list |

Every skill is in exactly one state, checked in both directions
(`backend/tests/test_skill_translations.py`): a skill in two lists fails, a skill in none fails, and a
skill listed as pending whose body is already Chinese fails.

**Three things a translation can silently break**, all now guarded:

1. **`## Instructions` and `## Examples` are delimiters, not prose.** `SkillLoader._parse_body_sections`
   and `skill_row_to_markdown` match those words by prefix. Translating the heading to `## 指令` does not
   raise — it switches the file to "the whole body is the instructions", `examples` becomes `None`, and the
   DB round-trip writes a second English heading back. Write `## Instructions（指令）`: the word stays, the
   Chinese sits beside it. 66 of 102 skills carry that heading.
2. **A dropped step is a different procedure under the same name.** Heading count and code-fence count must
   match the archived original; a loader cannot see the difference, so the test does.
3. **Code stays, templates translate.** A fence holding code, a command, a tree, a diff or a query is
   byte-identical to the source; a fence holding a document template an agent will fill in and show a person —
   a PR body, a ticket body, a report skeleton — is prose in a box, and translating it is the point. When in
   doubt: will a human read this text, or a machine run it?
4. **A translation that gave up.** Measured across the hand translations, Chinese runs 1.14–1.91 CJK
   characters per English word, so the floor is `max(3, 0.6 × English words)` — proportional, because a
   translation cannot be larger than its source. A fixed floor of 200 failed the two-line demo skills, which
   is the wrong direction for a guard to fail.

Move a skill with the script, never by hand:

```bash
python scripts/skill_zh.py archive <id>      # freeze the English (only needed when translating from a
                                             # file whose archive is missing)
python scripts/skill_zh.py check   <id>      # validate the staged translation, change nothing
python scripts/skill_zh.py promote <id>      # archive, install, drop from pending-zh.txt
python scripts/skill_zh.py status            # how many skills are in which language
```

`check` and `promote` run *the same checks as the test* before the file can become the version agents read:
structure parity, delimiter preservation, CJK density, frontmatter provenance, and a real `SkillLoader`
parse of the staged text. After promoting, `POST /api/skills/reload-all` (or a restart) re-syncs the DB —
the catalog is what agents actually see.

Translations stay in `backend/skills/.zh-staging/<id>.md` while in flight; that directory is gitignored,
because a half-checked translation must never look like a language the library has.

## 6. Measuring — use the checkpointer, not the chat log

`chat_sessions.tool_calls` **double-counts batched tool calls** (observed: 16 recorded vs 12 real; 10
"searches" vs 6 real in one run). It made a correct run look like it violated the anti-loop rule.

Read the real history from the LangGraph checkpointer instead:

```python
url = engine.url.render_as_string(hide_password=False).replace("postgresql+psycopg2://", "postgresql://")
async with AsyncPostgresSaver.from_conn_string(url) as cp:
    t = await cp.aget_tuple({"configurable": {"thread_id": session_id}})
msgs = t.checkpoint["channel_values"]["messages"]        # one entry per real tool call
```

Also remember: `temperature=0.0` still varies run to run. Two runs with identical settings produced
"wrote a file" and "answered inline" on the same request — never conclude from n=1.

## 7. What a skill must never contain

Tools · model names · identity/workspace paths · language preference · absolute paths · this platform's file
or panel rules · secrets · "you are a…" framing. If it needs a capability, it **states the requirement**; the
agent supplies the tool.

## 8. Pitfalls

| Pitfall | Reality |
|---|---|
| "Pinning a skill makes it used" | `config.skills` is inert in db mode |
| "The catalog limits what the agent can find" | discovery is library-wide; agent 115 loaded `global-equity-research` with nothing pinned |
| "Editing SKILL.md is live" | reload required, and the catalog is frozen per existing thread |
| "Moving a skill is clean" | storage is never pruned → stale shadow wins the merge |
| "Bigger skill = better" | it is loaded into context on demand; 9 KB is fine, 50 KB taxes every call |
| "The agent's self-report is evidence" | 212 once reported a filename that existed only in a phantom tree |

## 9. Worked example — agent 212 → `research-execution`

The same prompt, sorted:

| Bucket | Content | Destination |
|---|---|---|
| A | `<Task>` block ("answer the user's question by gathering real information"), role framing | stayed on 212 |
| B | "You have access to research tools" | stayed on 212; the skill only declares a `Requirements` table |
| **C** | tool ladder, `think_tool` reflection, hard cap, self-count, Stop-Immediately-When, ANTI-LOOP, inline-URL + `### Sources` + unverified contract | **→ the skill** |
| D | "one write path: `write_file` only", filename reporting, Files-panel behaviour | stayed on 212 |

Resulting fidelity (measured with `difflib` on the extracted blocks):

| Block | Similarity | Note |
|---|---|---|
| `think_tool` requirement | 100% | verbatim |
| Stop Immediately When | 100% | verbatim |
| Self-count line | 99% | verbatim (backticks added around `think_tool`) |
| ANTI-LOOP RULE | 89% | verbatim + one added rate-limit line |
| Tool ladder | 48% | their STRATEGY / Use for / Why structure, our real tools (no `serper_*`, no `wikipedia_search`) |
| Reflection questions | 50% | their questions + a `Count` bullet |
| Hard cap block | 46% | the cap lines verbatim; the surrounding "simple/complex" lines rewritten |

Additions the skill has that no single agent prompt needs: ranked source tiers, a verification section,
`graphindex_*` as the internal-documents rung, a stopping rule, requirements table, and hand-off notes to
`research-planner` / `document-deliverables`.

## 10. Author checklist

```
[ ] baseline recorded for the source agent (searches, budget statement, output path)
[ ] prompt annotated A / B / C / D
[ ] only bucket C moved into the skill
[ ] all guardrails pasted verbatim (cap, anti-loop, stop conditions)
[ ] tool references are capability classes, not this install's tool names
[ ] description states what + when, ≤1024 chars
[ ] name == directory name, kebab-case
[ ] sections present: tool ladder · reflection · budget · query craft · ranked sources ·
    verification · output contract · stopping rule · not-this-job · requirements
[ ] reload-all run; DB instructions + description + level-1 catalog line verified
[ ] behaviour test: discovery by a skill-less agent, cap compliance, output contract
[ ] changes A/B tested with ≥3 samples, measured from the checkpointer
```

---

*Companion docs: `docs/deepagents-study.md` (how the deep-agent runtime and skills are actually wired, with
the verified findings this method is based on), `docs/deepagent-vs-dsh.md` (gap list).*
