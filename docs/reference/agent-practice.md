# Working with agents — practice, not configuration

**What this is:** eight exercises that teach how an agent in this platform actually behaves,
written from the *usage* side. Setting an agent up is covered in
[`../usage.md`](../usage.md) §5; what to write inside a skill is
[`skill-authoring.md`](skill-authoring.md). This page is about the part nobody documents:
what to say, what to expect back, and how to tell a good run from a confident-sounding bad
one.

**Why exercises instead of prose:** every failure in this list was observed on this install,
and each one has a *specific* symptom you can recognise next time. Each section is one task
you can run in five minutes, with the outcome that tells you whether the agent is working
with you or just talking.

The one idea underneath all eight: **an agent's answer is a claim; the filesystem and the
tool results are the evidence.** Most practice is learning to look at the evidence.

---

## P1 — Ask it who it is, before you ask it for anything

**Do:** start a chat and send, with no other instruction:

> In three lines: which agent are you, what is the absolute path of your workspace, and
> which account are you working for?

**Expect:** the agent's own id and workspace path, then the account that is signed in —
display name, username and id. The workspace path must be under `…/users/<your id>/`.

**Why it matters:** the prompt carries three blocks — `Identity` (agent id + workspace),
`Who you are working for` (the account, from the signed-in session), and a
`workspace boundary` rule. The default `AGENTS.md` template (and the mirror in `CLAUDE.md`)
tells every agent to state the account when it introduces itself and to say plainly that it
cannot see another account's files — so a correct first message proves the whole chain. If
any part of it is wrong you will spend the next hour blaming the model for something the
platform told it.

**What "wrong" looks like:** it names an account that is not yours, or a `users/<other id>/`
path. That is a platform bug, not a prompt problem — report it and check
`scripts/verify_tenant.sh`, which asserts exactly this for two accounts.

**Rule:** *one question at the start of every session, and only one.*

---

## P2 — Changing behaviour: the rule you write versus the behaviour you get

The template's standard content — workspace map, path map, the file list — is scaffolding.
Nobody needs to learn it, and editing it teaches nothing. The part worth practising is the
one skill that decides whether an agent is useful: **writing a rule that changes behaviour,
and proving it did.**

### Four levers, and what each one can actually change

| Lever | Changes | Cannot change |
|---|---|---|
| **System prompt** (agent's Overview tab) | role, tone, priorities, output shape, what to refuse | what the model *can* do |
| **`AGENTS.md` rules** (Docs tab) | same as above, and applied on **every** turn | ditto — it is still just text in the prompt |
| **Tools / skills** | what it *can* do at all | whether it chooses to |
| **Model** | reasoning depth, instruction-following, speed, cost | facts, or a missing tool |

Most "the agent is bad" complaints are lever 1 or 2 problems. Some are lever 3 — no amount
of prompting lets an agent read a database it has no tool for.

### A rule that works has four parts

| Part | Question it answers | Weak | Strong |
|---|---|---|---|
| **Trigger** | when does this apply? | "be careful with data" | "When the user uploads a CSV and asks for numbers…" |
| **Action** | what exactly do you do? | "analyse it well" | "…load it with `sqlite_load_csv`, then answer with one SQL query per question." |
| **Shape** | what does the output look like? | "make it clear" | "…respond with a table of the numbers, then at most three bullets of interpretation." |
| **Edge** | what if you cannot? | *(absent)* | "…if a column is missing, say which one and stop; do not invent values." |

The edge case is the one people skip, and the one that prevents invented answers.

### Run it on `prompt-lab`

A ready-made agent for these experiments: three tools (`ls`, `read_any_file`,
`save_document`), one model, one small job — so the only variable is the text. Its `AGENTS.md`
opens with four rules, each with its own experiment:

| Rule | Change this | Watch this |
|---|---|---|
| **R1** shape | "three lines" → "a three-column table" | the answer's *shape*, nothing else |
| **R2** length | 40 words → 300 | the answer's *length* |
| **R3** refusal | delete the rule | it answers from memory instead of naming the gap |
| **R4** tone | allow exclamation marks | one line, immediately visible |

Run **R3 twice** — with the rule and without it — on a question that **tempts** the failure.
Measured here, asking *"what is a typical SaaS monthly churn rate? give me a number."*:

| R3 | Answer |
|---|---|
| on | `Conclusion: I can't give you a number. Because: that needs web or database access, which I don't have.` |
| off | `Conclusion: Typical SaaS monthly churn is about 3-5% for SMB, under 1% for enterprise.` |

The second is not a lie the model chose to tell — it is the model doing what it does when nobody
has told it to stop, and the number is a plausible-sounding average with nothing behind it.

**Pick the question carefully.** Asking *"what did our website traffic look like last month?"*
gets a refusal with or without R3, because the empty workspace is its own evidence — which makes
a good-looking experiment that proves nothing. A rule's effect is only visible when the
alternative is attractive.

#### Create it by hand (5 steps, about 2 minutes)

**1.** Activity bar → **DeepAgents** → **Create**. Name `prompt-lab`, model `deepseek-chat`,
temperature `0.2`.

**2.** **Tools** — exactly these three: `ls`, `read_any_file`, `save_document`. Fewer tools is the
point (P7); it is also why R3 is demonstrable rather than theoretical.

**3.** **Overview → system prompt** — paste:

```
You are prompt-lab, a small agent that demonstrates one thing: behaviour
comes from these instructions, not from the model.

Do the user's task, following AGENTS.md exactly. If a rule and the request conflict, follow the
rule and say so.
```

**4.** **Docs → AGENTS.md** — replace everything with:

```
# prompt-lab

Three tools, one job: show that the rules below control the behaviour.
To run an experiment: change **one** rule in the Docs tab, save, start a **new** chat, ask the
same question, compare.

## Rules

- **R1 Shape** — answer in exactly three lines: `Conclusion:` / `Because:` / `Next:`. No tables.
- **R2 Length** — the whole answer fits in 40 words.
- **R3 Refusal** — if answering needs a tool you do not have (web, database), name the missing
  capability and stop. Never estimate or answer from memory as if you had checked.
- **R4 Tone** — address the user as "you", never "You", and never use exclamation marks.

## Experiments

- **R3 (run this one twice):** ask "what is a typical SaaS monthly churn rate? give me a
  number." With R3 it refuses and names the missing capability. Delete R3, run it again → it
  answers "typical SaaS monthly churn is about 3-5% for SMB", from memory, with nothing behind
  it. That difference is why refusal rules exist.
  Ask a question whose absence of evidence is *visible* (e.g. "what did our traffic look like
  last month?") and it refuses either way, because the empty workspace is proof — a rule's
  effect only shows when the alternative is tempting.
- **R1:** change "three lines" to "a three-column table" → the shape changes; nothing else does.
- **R2:** change 40 to 300 → the answer grows.
- **R4:** allow exclamation marks → visible in one line.

## Workspace

- **Workspace**: <the path the agent reports; the template fills this in>

Deliverables go in `generated/`; uploads are read from `upload/`; `other/` is scratch. Nothing
else is available: `ls`, `read_any_file` and `save_document` are the only tools — which is what
makes R3 demonstrable.
```

**5.** **Save → new chat → run the R3 question above.** Expect the three-line answer with
`Conclusion: I can't answer this — the web analytics capability is missing.`

#### Or create it with one command

```bash
cd backend
.venv/bin/python scripts/create_starter_agent.py            # create or refresh (idempotent)
.venv/bin/python scripts/create_starter_agent.py --delete    # remove it, workspace to .trash
```

The script writes the same three texts above, bakes the identity, and materializes
`AGENTS.md` / `CLAUDE.md` into the workspace — keep the two in step if you edit one.

### One worked example, because the shape is easier to copy than to describe

Task: *"turn this CSV of monthly sales into a short brief"*, running badly (a paragraph of
prose, no numbers, no file).

**Round 1 — trigger + action**

> When the user uploads a CSV and asks for a summary, load it with `sqlite_load_csv` and ask
> one SQL question at a time. Do not describe the data from its first few rows.

**Observed:** real numbers now, but a wall of text and still no file.

**Round 2 — add shape and edge**

> …respond with a table of the top five rows by revenue, then at most three bullets. Write the
> whole thing to `generated/sales-brief.md`. If a column you need is missing, name it and stop
> — do not estimate or interpolate.

**Observed:** the file exists in `generated/`, the table has five rows, three bullets, and on a
deliberately broken CSV it stops and names the missing column instead of inventing a total.

Two rounds, two rules, both verified by evidence (tool calls + the file). That is the whole
practice: the prompt is a specification you iterate against observations, not a description of
the agent you hope for.

### The loop: state → observe → sharpen → re-test

1. **Write one rule**, in your own words, in the Docs tab. One. Not a paragraph of
   aspirations.
2. **New chat** (a rule change does not reach a running conversation), then do the task.
3. **Observe the evidence**, not the prose: did it call the tool you named? Is the output the
   shape you asked for? Does the file exist?
4. **Sharpen the weakest of the four parts** — usually the trigger ("when X") or the edge
   ("if not, say so").
5. **Re-test the case that failed, plus one that used to work.** A rule that fixes one case by
   breaking two is a regression.

Two or three rounds of this beat a long prompt written in one go, and the diff between rounds
is the actual knowledge of how your agent behaves.

### Where a rule has to live to be real

| What you want | Put it | Effect |
|---|---|---|
| a durable rule | Docs → **`AGENTS.md`** | embedded into the system prompt on **every** turn |
| a one-off instruction | the chat message | that turn only; afterwards it is history |
| a team-wide default for new agents | `backend/core/agents/templates/AGENTS.default.md` | baked in when an agent is created |

`CLAUDE.md` is a mirror written to the workspace for file-reading consumers — it is **not**
embedded, so a rule that exists only there is a rule the agent never reads.

### What prompt cannot fix

- **A missing tool.** "Use the database" without a database tool produces guesses, not data.
- **A capability limit.** Ask a cheap model for long multi-step arithmetic and no prompt fixes
  it; change the model or give it a tool.
- **A platform boundary.** Reading another account's workspace is refused below the prompt.
  A rule cannot grant it, and asking the agent to try only wastes turns.
- **A fact it could look up.** "Our revenue is 12M" in a prompt goes stale; put the number in
  the task, the knowledge base, or a file the agent reads.

### Traps, in order of how often they bite

| Trap | Why it fails | Fix |
|---|---|---|
| Requirements narrated in chat | gone at the next session, or at summarisation | Docs tab |
| Adjectives instead of actions ("be thorough") | not testable, so not observable | name the step and the output |
| The key rule at the end of a long prompt | cheap models attend to the start | first lines, or a Docs rule |
| Two rules that contradict | the model picks arbitrarily, differently each run | one rule, one owner; delete the loser |
| A 6 KB `AGENTS.md` | every turn pays for it, and it competes with the task | keep the durable rules; move detail into a skill |
| Verifying by re-reading the answer | a confident sentence is not compliance | tool calls, files, output shape |

**Rule:** *one behaviour change per round, verified by evidence, then written down.*

## P3 — Skills are chosen by description, and read on demand

**Do:** ask for something a skill covers, without naming the skill ("write a short weekly
report from these notes"). Watch the tool calls. Then ask again with the phrasing the
skill's own `description` uses.

**Expect:** the agent reads that skill's `SKILL.md` with a file tool *before* producing
output. In the catalogue it only ever saw the name, the description and the path — the body
is fetched when needed (progressive disclosure).

**Why it matters:** a skill is selected from its `description`, which means:

- a vague description never gets picked, no matter how good the body is;
- two skills describing the same job make the model guess — check the other triggers before
  adding one (this happened here: `code-review` and `git-workflow` both claimed "pull
  request");
- the skill must be **readable as a file** on the staged path, and the agent needs a
  file-reading tool to open it.

**What "wrong" looks like:** the answer is plausible but generic, and no `SKILL.md` was read.
That is a description problem, not a model problem.

---

## P4 — Say what the deliverable is, and where it goes

**Do:** run the same task twice. First: *"analyse this CSV"*. Then: *"produce five charts
and a one-page summary; put the charts and the summary in `generated/`, and tell me the
filenames."*

**Expect:** the second run writes real files into the workspace's `generated/` folder, using
`upload/` as the source and `other/` only for scratch. The first run may produce a good
answer and no artefacts at all.

**Why it matters:** the workspace has a fixed shape — `upload/` (what the user gave you),
`generated/` (deliverables), `other/` (scratch). The agent knows this from
`AGENTS.md`; whether it uses it depends on you asking for a deliverable.

**Rule:** *if it should exist as a file, say the word "file" and name the folder.*

---

## P5 — Verify with the Files panel, not with the chat

**Do:** after any run that claims to have produced something, open **Files** and check:
does the file exist, is the size sane, is the timestamp from this run?

**Expect:** the Files panel lists what is **actually on disk**. It reads the workspace
directory, so it is the authority — a file it does not show does not exist, whatever the
transcript says.

**Why it matters:** "done" is a sentence the model can generate. The three failure shapes:

| Symptom | What happened |
|---|---|
| File in `other/` instead of `generated/` | your instruction did not say where |
| File exists, 0 bytes | the agent announced a write and never called the tool |
| No file at all, polite summary | the agent summarised instead of producing |

**Rule:** *a deliverable is a file you can open. Everything else is a status update.*

---

## P6 — One task per conversation

**Do:** finish a task, then ask an unrelated second task in the **same** chat. Then repeat
it in a new chat.

**Expect:** the second chat is usually better — sharper, shorter, less confused by leftover
context. The first carries the old task's assumptions, tool results and half-finished plans.

**Why it matters:** in one conversation the skill catalogue is loaded **once** (per thread),
and long histories are summarised or evicted to keep within the token limit. Both are
reasonable behaviour and both make *reuse* of a conversation a bad idea for a new task.

**Also worth knowing:** editing an agent's configuration invalidates the cached instance, so
the next message rebuilds it — that is why the first turn after an edit is slower.

**Rule:** *new task, new chat. Rename the old one so you can find it again.*

---

## P7 — Fewer tools, better answers

**Do:** give an agent the full default tool set, ask it a simple task. Then remove
everything except the two tools the task needs, and ask again.

**Expect:** the second run is faster, cheaper and more direct. With thirty tools the model
spends attention choosing; with five it just uses them.

**Why it matters:** every tool's name, description and parameter schema is in the prompt —
tools are prompt budget, and the budget competes with your instructions.

**Rule:** *add a tool when a task fails for want of it, not in anticipation.*

---

## P8 — Let it refuse

**Do:** ask for something none of its tools can do — read a file outside its workspace, query
a database it has no tool for, fetch a page when it has no fetch tool.

**Expect:** it says it cannot, and what it would need. The prompt explicitly permits refusal:
the workspace boundary says a path from the chat does not override it, and to stop and say so
rather than work around it.

**Why it matters:** a model that is not *given permission to fail* will invent a plausible
answer or a fake tool result. If yours invents instead of refusing, the fix is in the prompt
(add the boundary/refusal rule), not in the model choice.

**What "wrong" looks like:** convincing detail about a file it never opened. Check the tool
calls: no `read_file`, no result — the paragraph after it is fiction.

**Rule:** *a refusal is a correct answer; a fabricated success is not.*

---

## When not to use an agent

| Situation | Why not | Do instead |
|---|---|---|
| The answer is one SQL query or one file scan | you will spend more tokens checking its answer than writing it | SQL tool / shell, then read the result yourself |
| The exact output must be reproducible byte-for-byte | an LLM re-rolls the text every run | a script; use the agent to *write* the script once |
| It authorises money, deletes data, or sends something outward | irreversible and sometimes unattributable | a human step, always |
| The task needs a fact you can look up | answers drift, sources do not | Knowledge base / web fetch with the URL in the answer |
| You cannot describe "done" | the agent cannot either | write the acceptance check first, then delegate |

## What is yours and what is the team's

This matters as soon as there are two accounts. Practice-level version:

| Yours only | Everyone's |
|---|---|
| your workspace and files (`outputs/users/<your id>/`) | the agent library, tools, built-in skills |
| your conversations | projects, the knowledge base |
| your personal skills | **provider API keys** — the spend is the team's, whichever account runs it |
| your account and password | |

Two consequences you will meet in practice:

- **A shared agent cannot see your personal skill.** If an agent is pinned to a skill you
  own and a colleague runs it, the skill is skipped (by design). For a workflow the team
  runs, put the skill in `builtin`.
- **Nobody else can see your files, and you cannot see theirs.** If you *can*, that is a bug
  — run `scripts/verify_isolation.sh`.

## Anti-patterns, in one place

| Anti-pattern | What it costs | Instead |
|---|---|---|
| Durable rules typed into chat | they vanish at summarisation or in the next session | Docs tab (`AGENTS.md`) |
| One long chat for everything | context pollution; worse answers per task | one task per conversation |
| Letting the agent discover paths | it wastes turns `ls`-ing and sometimes guesses | say the path, or rely on the workspace map |
| Burying the key constraint at the end of a long prompt | cheap models ignore the tail | first line of the prompt, or a Docs rule |
| "Analyse this" with no deliverable | a paragraph instead of a file | name the artefact, the folder and the format |
| Trusting "done" | silent no-ops | Files panel + size + timestamp |
| Giving every tool "just in case" | prompt budget stolen from your instructions | add on demand |

---

## The five-minute habit

Before blaming a model, in this order:

1. **Ask who it is** (P1) — wrong identity means the prompt is wrong, not the model.
2. **Read the tool calls** — did it actually read the file / run the query?
3. **Open Files** — does the deliverable exist, with a sane size?
4. **Check the Docs tab** — is the rule you are relying on actually in the prompt?
5. **New chat, one task** — half the "it got worse" reports are a reused conversation.

If all five are clean and the answer is still wrong, that is a useful bug report: the
session id (visible in the chat URL and in `chat_sessions`), the tool calls with their
results, and what the Files panel shows. If the symptom is "I can see something that is not
mine" or "my own thing is missing", run the matching verifier first — it distinguishes a
platform boundary bug from a prompt problem in about a second:

```bash
cd backend
./scripts/verify_tenant.sh  <host> -u <me> -A <colleague>   # private vs shared, end to end
./scripts/verify_isolation.sh <host> -u <me> -A <colleague> # files, storage, sessions
```
