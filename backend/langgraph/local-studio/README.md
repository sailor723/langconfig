# Local Studio

A local, self-hosted clone of **LangGraph Studio**, built to run against your own `langgraph dev` server with zero cloud dependencies. It gives you the same three-pane workflow — assistant/thread list, graph canvas, and a message inspector — plus **live streaming** (token-by-token) for graph runs.

## Features

- **Assistant list** — lists every assistant exposed by the local LangGraph API.
- **Thread management** — create threads per graph, list them, select one and inspect its persisted state.
- **Graph visualization** — renders the compiled graph with [React Flow](https://reactflow.dev/) (`@xyflow/react`), layered top-down layout, start/end styling.
- **Run console** — enter a graph input as JSON and run it against the active thread.
- **Live streaming** — runs stream SSE events (`messages/partial`, `values`) and the inspector renders the assistant reply **token-by-token** as the model generates it.
- **Message inspector** — shows the full message history of the thread state, plus per-message metadata (model, token usage) and a "streaming…" indicator during runs.

## Architecture

```
Browser (React + Vite, :5173)
   │  /api/*             (Vite dev proxy)
   ▼
Express API server (:3001)
   │  /api/langgraph/*   (raw-socket proxy)
   ▼
langgraph dev server (:2024, uvicorn)
   │
   ▼
Ollama / Azure OpenAI  (the graph's LLM)
```

- The Express server in [`api/`](api/) proxies every `/api/langgraph/*` request to the local `langgraph dev` server.
- The proxy uses raw Node `http`/`https` socket piping (not `fetch`) so SSE responses stream through byte-for-byte with correct connection handling, and strips hop-by-hop headers (`transfer-encoding`, `connection`, …) so response framing is never corrupted.
- In production (`npm run build` + the Express server) the built frontend is served directly from `dist/` with an SPA fallback, so no Vite proxy is involved.

## Prerequisites

- **Node.js 20+** and a package manager (`npm` or `pnpm`).
- A running **LangGraph dev server**, e.g. from a module's studio folder:

```bash
cd module-1/studio
uv run langgraph dev --port 2024 --host 127.0.0.1
```

- The graph's **LLM backend** (e.g. Ollama with `qwen2.5:14b`, or Azure OpenAI credentials) reachable from that dev server.

## Setup & Run

```bash
cd local-studio
npm install
npm run dev
```

`npm run dev` starts both processes with `concurrently`:

- **Vite client** → http://localhost:5173
- **API server** (`nodemon`) → http://localhost:3001

Then open http://localhost:5173. If the Express API can't reach the LangGraph dev server, the UI shows an offline banner.

Useful scripts (see [`package.json`](package.json)):

| Script            | What it does                              |
| ----------------- | ----------------------------------------- |
| `npm run dev`     | Vite client + API server (hot reload)     |
| `npm run build`   | Type-check + build the frontend to `dist/`|
| `npm run check`   | Type-check only (`tsc --noEmit`)          |
| `npm run lint`    | ESLint                                    |
| `npm run preview` | Serve the production build via Vite       |

Configuration is via environment variables (loaded from `.env` if present):

| Variable             | Default             | Purpose                         |
| -------------------- | ------------------- | ------------------------------- |
| `LANGGRAPH_API_URL`  | `http://127.0.0.1:2024` | Upstream LangGraph API base |
| `PORT`               | `3001`              | Express API port                |

## Live Streaming Implementation

Run flow (see [`src/store/studioStore.ts`](src/store/studioStore.ts) → `run()`):

1. The client `POST`s to `/api/langgraph/threads/{thread_id}/runs/stream` with `stream_mode: ["messages", "values"]` (see [`src/api/client.ts`](src/api/client.ts) → `streamRun`).
2. The response is an SSE stream. [`src/api/stream.ts`](src/api/stream.ts) parses `event:` / `data:` pairs line by line.
3. Event handling:
   - **`messages/partial`** — a chunk of a message. Content is **cumulative** (each chunk replaces the previous one for the same `id`), so chunks are merged into a per-message map and the inspector re-renders → live token-by-token output.
   - **`values`** — full state snapshots; also merged into the live view so tool/human messages show up.
   - **`metadata` / `messages/metadata`** — run + message metadata (model, usage).
   - **`messages/complete`** — stream finished.
4. When the stream ends, live messages are cleared and `refreshState()` re-fetches the persisted thread state so the inspector shows the final result.

## Project Structure

```
local-studio/
├── api/
│   ├── app.ts          # Express app: health check + /api/langgraph proxy (SSE-safe)
│   ├── index.ts        # server bootstrap (loads env, listens on PORT)
│   └── server.ts
├── src/
│   ├── api/
│   │   ├── client.ts   # typed API client (assistants, threads, runs, stream)
│   │   └── stream.ts   # minimal SSE line parser
│   ├── components/
│   │   ├── AssistantList.tsx
│   │   ├── GraphCanvas.tsx   # React Flow graph visualization
│   │   ├── Inspector.tsx     # message history + streaming view
│   │   ├── RunConsole.tsx    # JSON input + Run graph
│   │   ├── ThreadPanel.tsx   # create/list/select threads
│   │   └── Empty.tsx
│   ├── pages/
│   │   └── Home.tsx          # three-pane layout
│   ├── store/
│   │   └── studioStore.ts    # zustand state + streaming orchestration
│   ├── hooks/useTheme.ts
│   ├── App.tsx
│   └── main.tsx
├── vite.config.ts      # dev proxy /api → :3001
├── nodemon.json        # API server watch config
└── package.json
```

## Troubleshooting & Known Issues

- **`400 Invalid HTTP request received` on proxied GETs.** Root cause: `express.json()` populates `req.body = {}` for GETs; writing that body to the upstream made Node emit `Transfer-Encoding: chunked`, which uvicorn/h11 rejects. Fixed in [`api/app.ts`](api/app.ts) by only forwarding a body for methods that support one and when it is non-empty.
- **Thread list empty.** Newer LangGraph dev servers persist the graph id in `metadata.graph_id`, not `assistant_id`; the client filters threads by `metadata.graph_id`.
- **`net::ERR_ABORTED` on `/runs/stream` in the Chrome console.** This is expected Chromium noise when an SSE stream's connection closes at the end of the run — it appears even when the browser talks directly to the API server with no proxies in between, the full body still arrives, and runs complete normally. Treat it as benign; it does not affect functionality.
- **`langgraph-api not installed`.** When using a `uv`-created venv there is no `pip`; install the CLI with `uv pip install -p .venv/bin/python -U "langgraph-cli[inmem]"`.
- **Studio works in Chrome but not Safari.** Safari's local-network/ITP restrictions can block `localhost` SSE; use Chrome or start `langgraph dev` with `--tunnel`.

## References

- [LangGraph Studio / dev server docs](https://langchain-ai.github.io/langgraph/)
- Approved design docs for this project live in `.trae/documents/` (`PRD-local-studio.md`, `technical-architecture-local-studio.md`).
