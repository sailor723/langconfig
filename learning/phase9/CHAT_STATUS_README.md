# Phase 9 Chat — Current Status & Open Issues

> New conversation starting point. The previous conversation ran out of
> context. This document captures the working baseline, the broken case,
> and what was tried but not yet landed.

## TL;DR

- **Working**: `pdf_chat` agent (legacy path) and "ungrouped doc" chat in
  the Knowledge panel — both render cleanly, multi-turn memory works,
  language preference remembered, doc routing correct.
- **Broken**: `graphindex_chat` agent (Phase 9 path) — for "no tool"
  responses (greetings, identity questions) the assistant bubble shows
  the previous turn's content. For "with tool" responses the LLM's raw
  `<think>` / `<tool_call>` XML leaks into the chat and the Markdown
  renderer turns it into a `md ) **` artifact.
- **Backend LLM call itself is fine.** LangSmith traces show correct
  responses for every turn. The bug is in how the chat path streams the
  LLM's content to the UI.

## 1. Graphindex build & query under Phase 9

### What Phase 9 is

- `learning/phase9/graphindex_chat_agent.py` builds a **deep agent** via
  `deepagents.create_deep_agent` with:
  - System prompt for progressive disclosure (route → load → synthesize)
  - 5 graphindex tools:
    - `route_query_tool` (LLM-semantic routing over the doc catalog)
    - `load_multi_doc_tool` (load primary + supporting docs by name)
    - `read_doc_tool` (raw re-read)
    - `list_docs_tool` / `fetch_catalog_tool` (browse)
  - `MemorySaver` checkpointer (per-project_id, per-thread_id)
  - `ContextVar` for active project_id and doc scope (set per request)
- Module-level `@lru_cache(maxsize=4)` on `get_graphindex_chat_agent`
  keyed by `project_id`, so a project switch doesn't rebuild.

### How it's queried (chat path)

`POST /api/chat/message/stream` in `backend/api/chat/routes.py`:

1. The route looks up `agent_config` by `agent_id` (91 for
   `graphindex_chat`). When `use_phase9_graphindex` is true, the route
   dispatches to `_generate_stream_phase9`.
2. `_generate_stream_phase9` is a **thin async wrapper** that:
   - Imports the phase9 module via a module-level cache
     (`_PHASE9_AGENT_MODULE`, see commit `0d748a0`). Loading the module
     on every request used to wipe `@lru_cache` and `MemorySaver`,
     which broke multi-turn memory.
   - Calls `stream_graphindex_chat_events(...)` which sets the
     `ContextVar`s, then drives the agent via `agent.stream(..., stream_
     mode="values")` and yields the full graph state after each node.
   - The wrapper **diffs** state messages against the previous state to
     detect: new AI tool calls (`tool_start` SSE), tool results
     (`tool_end` SSE), and final AI text content (`chunk` SSE).
   - On the final AI message, it strips `<think>...</mm:think>` and
     `<tool_call>...</tool_call>` from `msg.content` via a regex
     (`re.sub(..., re.DOTALL)`), then yields the diff as chunks.
3. The `chat_session` row is saved in DB with the assistant's final
   `full_response`.

### What's broken about this streaming path

The state-diff + regex approach has three concrete problems:

1. **Cross-chunk split**: the regex `<think>.*?</mm:think>` requires
   both the opening and closing tag in the same `msg.content` string.
   The streaming chunks can split these blocks mid-way. The
   `7aada79` commit tried to handle the open-block case via
   `r"<think>.*?(?:</mm:think>` (alternation with `$`) but the chunks are
   still split across multiple state updates, so the regex still misses
   the closing tag.
2. **`<tool_call>` XML leak**: Minimax M3 sometimes emits the tool call
   as raw text in `msg.content` alongside the structured `tool_calls=
   [...]` field. The XML looks like
   `<tool_call>\n<invoke name="...">...</invoke>\n</tool_call>` and
   leaks into the chat. The ReactMarkdown renderer then sees
   `[...](...md)**` and renders a partial link as the `md ) **` artifact.
3. **No-tool assistant message never created**: the `complete` event
   handler in the frontend (`useChatStreaming.ts`) was the only place
   that created the assistant bubble for no-tool responses. The Phase 9
   path never sent `complete`, so the bubble was missing — the user
   saw the previous turn's content. Fix `b43645e` (always create
   bubble on first chunk) is in but the UI display was still off
   because of (1) and (2).

### What was tried (and reverted / not landed)

- **`b43645e` (LANDED)**: streaming frontend no longer buffers pre-tool
  chunks into a `thinkingBufferRef`; the first chunk creates the
  assistant message. This unblocks no-tool responses.
- **`15b3065` (LANDED)**: backend strips `<tool_call>` blocks via regex
  `r"<tool_call>.*?(?:</tool_call>|$)"` (alternation with `$`).
- **`7aada79` (LANDED)**: same fix for `<think>` blocks.
- **Refactor to use `astream_events` (NOT LANDED, REVERTED)**: I
  refactored `_generate_stream_phase9` to use the legacy path's
  `agent.astream_events` approach (the langchain chat model emits
  `on_chat_model_stream` events that should be cleaner). Test showed
  the chunks STILL contain `<think>` (Minimax emits it as raw text in
  `content`, not a separate content block). The refactor is reverted
  in the working tree; only the regex-stripping code remains.
- **`_ThinkFilter` stateful class (NOT LANDED, REVERTED)**: a
  stateful filter that strips think/tool_call blocks across token
  boundaries. The unit test revealed a bug — when a think block
  contains a <tool_call>, the filter gets stuck in `in_think=True`
  and never outputs anything after the think block closes. The class
  was reverted before commit.

## 2. pdf_chat (working baseline)

`pdf_chat` is the agent the user demonstrated works great. It uses
the **legacy chat path** in `routes.py` (`_generate_stream_legacy`,
around line 1020+).

### Why it works

- The legacy path uses `agent_instance.astream_events(..., version="v2")`
  and processes:
  - `on_tool_start` → `tool_start` SSE
  - `on_tool_end` → `tool_end` SSE
  - `on_custom_event` → `custom_event` SSE
  - `on_chat_model_stream` → `chunk` SSE
- The `on_chat_model_stream` events are **token-level** and are emitted
  by the langchain chat model AFTER stripping `<think>` / `<tool_call>`
  from the visible text (the LLM framework handles this for OpenAI-
  compatible providers that use the chat-completions API).
- Multi-turn memory works via the agent's `MemorySaver` (the
  `thread_id` in `config.configurable` is the chat session_id).
- The frontend's `useChatStreaming.ts` creates the assistant bubble
  on the first chunk (per `b43645e`) and updates it on every
  subsequent chunk. `complete` is sent by the legacy path so the
  fallback also works.

### What the user showed

- Upload "Agus api and deep_agent_530 安装.pdf" via pdf_chat
- Multi-round Q&A in Chinese, including:
  - 申请 Agis API key 的流程
  - 部署 Deep agent 530 的步骤
  - 安装 WSL 的命令
- All responses render cleanly as Markdown (headings, code blocks,
  bullet lists, etc.). No `md ) **` artifact, no leaked `<tool_call>`
  XML.

## 3. Knowledge upload / load / chat (focus on issues)

### Upload

- UI: "Select Folder" or path-input → `POST /api/rag/ingest-folder` (or
  the equivalent UI upload flow).
- Backend: `learning/phase9/graphindex_tools.py` parses the folder
  path, derives `industry / player / sub_category / sub_department`
  from the path components, and writes to Postgres
  (`context_documents`) + Neo4j + filesystem. The on-disk file is
  named `<8-hex-content-hash>_<original-name>`.
- Verified: 5 docs in project 8 with correct hierarchy, e.g.
  `industry=electric_vehicle_industry`, `player=byd|tesla`,
  `sub_category=analysis|comparison|marketing`.

### Load (doc listing)

- UI: `KnowledgeBaseView` calls `GET /api/rag/documents?project_id=N`
  and `GET /api/graphindex/neo4j-documents?project_id=N`, merges
  them with the same name → PG copy first, virtual card for Neo4j-
  only.
- The Postgres list returns `industry / player / sub_category /
  sub_department` for each doc.
- The Neo4j list (legacy) does NOT return these fields — only
  `name / file_path / about / has_enrichment / chunk_count /
  page_count / context_doc_id / doc_index_id / project_id`.

### Chat (broken case)

- UI: chat panel + "ungrouped" doc sidebar in the Knowledge panel
  both use `DocChatPanel` which calls `sendMessage(...)` via
  `useChatStreaming`.
- The frontend streams from `POST /api/chat/message/stream` with
  `agent_id=91` (`graphindex_chat`).
- Backend dispatches to `_generate_stream_phase9` (the broken path).
- The chat panel also has `handleToolEvent` to highlight the matched
  doc in the sidebar and `setSelectedDocId` to show it in
  `DocumentViewer`. This auto-focus works (per `KnowledgeBaseView`
  callback at line 1721–1734).

### Specific user-visible issues

1. **Greeting / no-tool response**: assistant bubble shows previous
   turn's content. (Partially fixed by `b43645e` for the
   first-turn-after-page-load case; still broken when the user is
   mid-conversation.)
2. **Tool-using response**: assistant bubble shows the LLM's raw
   `<think>...</mm:think>` and `<tool_call>...</tool_call>` text. The
   Markdown renderer turns the `<tool_call><invoke ...>` into a
   partial link artifact `md ) **`.
3. **Tree view showing "(ungrouped)"**: the user reported this earlier
   but it's actually stale data — the current DB has all 5 docs with
   `industry / player / sub_category` populated. The earlier symptom
   was likely from before the user wiped + re-uploaded the docs.
4. **Doc highlight + viewer auto-focus**: this WORKS. The chat calls
   `setSelectedDocId` and `setHighlightedDocId` via the
   `handleToolEvent` callback. The viewer loads the doc, the
   sidebar card flashes.
5. **Content size error in viewer**: separate issue — the viewer was
   sending the on-disk name (with content-hash prefix) to the
   Neo4j content API, but Neo4j nodes have the original name (no
   hash). Fixed in `8b1dda1` (strip the 8-hex prefix in
   `DocumentViewer.tsx`).

## 4. What to try next (when continuing the conversation)

The user said "use legacy as much as possible, unless legacy breaks
the deepagent framework rule". The current Phase 9 path uses
state-diffs; the legacy path uses `astream_events`. The
`astream_events` approach is what we want, but it didn't work
out-of-the-box because Minimax emits `<think>` as raw text (not
a separate content block).

Suggested next steps (in order of preference):

1. **Get `_ThinkFilter` working.** The stateful filter class
   (reverted from working tree) needs to handle:
   - Think block with <tool_call> inside (LLM weirdness)
   - Multiple think blocks in one turn
   - Open blocks (no closing tag in the same chunk)
   The unit test in `/tmp/test_filter2.py` exposed a bug — the
   filter gets stuck when a think block contains a <tool_call>.
   The fix: when in think mode and the token contains a <tool_call>
   inside the think block, just continue (the <tool_call> is also
   think content). The current code already does this correctly
   (returns "" until </think>) but the test expectation was wrong.

2. **Apply `_ThinkFilter` to the streaming output in
   `_generate_stream_phase9`.** The class is already written in
   `routes.py` (reverted from working tree). One instance per
   request, used in the `on_chat_model_stream` handler. Tokens
   are filtered before yielding.

3. **If `_ThinkFilter` still doesn't work, fall back to disabling
   streaming on the chat model.** The langchain `init_chat_model`
   has a `streaming=False` option. The non-streaming path returns
   the full message at once; we can strip `<think>` / `<tool_call>`
   from the full string and yield it as one big chunk. Less live
   feel but bulletproof.

4. **Re-test the greeting case.** After (2) or (3), verify:
   - "hi" → assistant bubble shows "Hi! How can I help..." (not
     the previous turn's BYD content)
   - "tell me Tesla europe marketshare" → assistant bubble shows
     "Tesla Europe Market Share..." in clean Markdown (no
     `md ) **` artifact)

## 5. Files / commits referenced

- `learning/phase9/graphindex_chat_agent.py` — Phase 9 deep agent
- `learning/phase9/graphindex_tools.py` — 5 graphindex tools
- `backend/api/chat/routes.py` — chat endpoint, both paths
  - `_generate_stream_phase9` — broken (current code at HEAD)
  - `_generate_stream_legacy` — works (uses `astream_events`)
- `src/features/chat/hooks/useChatStreaming.ts` — frontend streaming
  - b43645e: always add assistant message on first chunk
- `src/features/chat/hooks/useChatSession.ts` — message state +
  history loading
- `src/features/knowledge/ui/DocChatPanel.tsx` — chat panel
  - `handleToolEvent` for doc highlight + viewer
- `src/features/knowledge/ui/KnowledgeBaseView.tsx` — knowledge
  panel, doc list merge
- `src/features/knowledge/ui/DocumentViewer.tsx` — viewer (8b1dda1
  fixed the hash-prefix strip)

## 6. Test commands

```bash
# Start the chat session and capture the session_id
SESSION=$(curl -s -X POST 'http://localhost:8765/api/chat/start' \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":91}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['session_id'])")

# Stream a message
curl -N -s -X POST 'http://localhost:8765/api/chat/message/stream' \
  -H 'Content-Type: application/json' \
  -d "{\"session_id\":\"$SESSION\",\"agent_id\":91,\"message\":\"hi\",\"project_id\":8,\"scope\":[\"01_tesla_q3_strategy.md\",\"03_byd_vs_tesla_europe.md\"]}" \
  | grep "^data: "

# Tail the syslog
tail -f /tmp/backend-syslog.log | grep -E "\[CHAT|Phase 9"
```
