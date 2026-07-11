# Plan — 100% Mirror of 1.3_memory.ipynb in LangConfig UI

## Goal
Reproduce the observable behavior of `1.3_memory.ipynb` cells 2-10 in the
LangConfig UI: **conversation memory** via checkpointer + thread_id, so the
agent remembers the user's name and preferences across turns in a chat session.

## What 1.3 actually does (cell by cell)

| Cell | What it does |
|---|---|
| 0 | Load .env |
| 1 | Title: "没有记忆" (No memory) |
| 2 | Build agent with NO checkpointer |
| 3 | First turn: "你好，我是卫平，我喜欢蓝色" |
| 4 | Show response — agent says hi |
| 5 | Second turn (NEW `agent.invoke` call with no shared state): "我喜欢什么颜色？" → agent **doesn't remember** |
| 6 | Title: "记忆" (Memory) |
| 7 | Rebuild agent WITH `checkpointer=InMemorySaver()` |
| 8 | First turn with `config={"configurable": {"thread_id": "1"}}` — agent stores in thread "1" |
| 9 | Show response |
| 10 | Second turn with **same `config`** — agent retrieves history from thread "1" and **remembers** the color |

## Key insight — 1.3 has NO new tools

The notebook **only** demonstrates the `checkpointer` parameter of
`langchain.agents.create_agent()`. No new tools, no new prompts, no new
sub-agents. The behavior is automatic once a checkpointer is configured
and a `thread_id` is passed via `config.configurable`.

## Cross-check with LangConfig

| Aspect | Notebook | LangConfig | Status |
|---|---|---|---|
| `checkpointer` | `InMemorySaver()` | `get_checkpointer()` (PostgreSQL) | ✅ already wired (factory.py:535-541) |
| `thread_id` | `config.configurable.thread_id` | `config.configurable.thread_id` (uses session_id) | ✅ already wired (routes.py:500) |
| `agent.invoke(messages, config)` | yes | yes (chat routes pass config) | ✅ already wired |
| No new tools | — | — | ✅ no work needed |
| No new prompts | — | — | ✅ no work needed |

## So... nothing new to build?

Yes — **1.3's behavior is already 100% present in LangConfig**! The chat
session flow already:
1. Creates a session with a unique `session_id`
2. Uses `session_id` as the `thread_id` for langgraph
3. Passes the checkpointer via the factory

The user's chat session in LangConfig is **already equivalent** to a
notebook `thread_id`.

## What to do — testing only

### Test 1: chat session memory (matches notebook cell 10)

Use the existing UI:
1. Open any agent in chat (e.g., `2.1 TODO Demo` or create a new "no-tool" agent)
2. Send turn 1: `你好，我是卫平，我喜欢蓝色`
3. Send turn 2: `我喜欢什么颜色？`
4. Expected: agent says "蓝色" (or "blue")

### Test 2: cross-session isolation (matches notebook cell 5)

1. End the current session
2. Start a new session
3. Send: `我喜欢什么颜色？`
4. Expected: agent does NOT remember (no preference info)

### Test 3: no-checkpointer behavior

This is harder — there's no UI toggle to disable the checkpointer. To
replicate notebook cell 5, would need a "stateless" mode in the chat
session. Skipping for now.

## What I plan to do

1. **Verify** with a curl test that agent remembers within a session
2. **Document** in this README that 1.3 parity is already there
3. **Add an optional "no memory" toggle** in the chat start endpoint so users
   can test the difference (matches notebook cell 5)

### Optional enhancement: stateless chat sessions

Add `?stateless=true` to `POST /api/chat/start`:
- Skip creating a `thread_id` in the checkpointer
- Each `agent.invoke` is fresh — no history
- Matches notebook cell 5 behavior

## Files to add/modify

| File | Change |
|---|---|
| `learning/phase14/README.md` | this file |
| `backend/api/chat/routes.py` | (optional) add `stateless` param to start endpoint |
| `core/agents/factory.py` | (optional) skip checkpointer when `stateless=True` |

## Status

1.3 parity: **ALREADY ACHIEVED** via the existing PostgreSQL checkpointer
in `core/workflows/checkpointing/manager.py:535-541` and the
`thread_id = session_id` flow in `api/chat/routes.py:500`.

No code changes required. Just need to verify with a curl test.
