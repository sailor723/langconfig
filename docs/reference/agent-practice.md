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
`workspace boundary` rule. If any of them is wrong you will spend the next hour blaming the
model for something the platform told it.

**What "wrong" looks like:** it names an account that is not yours, or a `users/<other id>/`
path. That is a platform bug, not a prompt problem — report it and check
`scripts/verify_tenant.sh`, which asserts exactly this for two accounts.

**Rule:** *one question at the start of every session, and only one.*

---

## P2 — The instruction file is in the prompt, not in its head

**Do:** open the agent's **Docs** tab, add a rule that is impossible to miss, e.g.

> Always answer with a single sentence, no lists.

Save, start a **new** chat, ask something that invites a long answer.

**Expect:** one sentence. Not because the agent remembered, but because `AGENTS.md` is
embedded into the system prompt on every turn.

**Why it matters:** two facts that decide where you put an instruction:

| Where you put it | When it takes effect |
|---|---|
| `AGENTS.md` (Docs tab) | every turn, immediately — it is inside the prompt |
| the chat message | that turn only; it is history afterwards |

`CLAUDE.md` is a mirror written into the workspace for file-reading consumers; it is **not**
embedded, so a rule that exists only there is a rule the agent never reads.

**Anti-pattern:** stating a durable requirement in chat ("from now on, always…"). It holds
for a few turns until summarisation or a new session, then it is gone. Put it in the Docs tab.

---

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
