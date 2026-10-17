# DeepSeek image-to-text (vision) model

**Status:** the catalog row is added by the seed (`backend/scripts/seeds/in/upsert_model.py --preset deepseek-flash`,
`backend/scripts/seeds/in/upsert_model.py`). Applying it to a live database is a
per-environment step — follow the runbook below.

## 1. What the model is

DeepSeek exposes exactly **one** image-input model. Per the vendor docs:

| | `deepseek-flash` | `deepseek-v4-pro` |
|---|---|---|
| Vendor model version | DeepSeek-V4.1-Flash | DeepSeek-V4-Pro-0813 |
| **Vision (image input)** | **✓** | ✗ not supported |
| Context length | 1M | 1M |
| Max output | 384K | 384K |
| Tool calls / JSON output | ✓ / ✓ | ✓ / ✓ |
| Thinking mode | both, thinking is default | both |
| Input price (peak, cache miss) | $0.30 / 1M | $1.32 / 1M |
| Output price (peak) | $1.20 / 1M | $3.96 / 1M |
| Concurrency | 2500 | 500 |

- `deepseek-v4-flash` and `deepseek-v4-flash-vision-exp` are **retired names that
  still work**: requests are served by DeepSeek-V4.1-Flash and billed at the
  Flash price. Prefer the canonical `deepseek-flash`.
- Sources: [Vision guide](https://api-docs.deepseek.com/guides/vision/),
  [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing),
  [`GET /models`](https://api-docs.deepseek.com/api/list-models).
- Payload shapes accepted (OpenAI-compatible chat completions, `content` as an
  array): base64 data URL, public `http(s)` URL (≤8192 chars), or a Files API
  `file_id`. Formats JPEG/PNG/GIF/WebP; ≤600 images per request; ≤32 MiB inline
  (≤64 MiB via `file_id`); ~1024 tokens per image; optional `detail` of
  `low|high|original|auto`.

## 2. How the app already handles images

Nothing new was needed on the send path — it existed, but the model was missing
from the catalog:

| Layer | File | Role |
|---|---|---|
| Upload UI | `src/components/common/AttachmentUploader.tsx` | Image/doc picker (max 3 files, 5 MB, `image`+`document`) |
| Node config | `src/features/workflows/node-config/NodeConfigPanel.tsx` | "Multimodal Input" toggle + per-node attachments |
| Run request | `backend/api/workflows/execution.py` (`WorkflowExecuteRequest.attachments`) | Workflow-level attachments as base64 |
| Merge | `backend/core/workflows/executor/nodes.py` | workflow attachments + node attachments → message |
| Builder | `backend/core/agents/multimodal.py` (`create_multimodal_message`) | `{"type":"image_url","image_url":{"url":"data:image/png;base64,…"}}` |
| LLM | `backend/services/agent_utils.py` (`resolve_model`/`create_llm_with_fallbacks`) | Any `deepseek*` id → `init_chat_model(model_provider="deepseek")` → `langchain-deepseek`'s `ChatDeepSeek` (a `BaseChatOpenAI`), so image blocks serialize straight to the wire |

## 3. Runbook (hand this to whoever owns the environment)

### Step 0 — Prerequisites

```bash
cd /path/to/langconfig
docker-compose up -d postgres            # the app DB is on :5433 (NOT :5432)
cd backend && uv run alembic upgrade head
uv run python -c "from db.database import engine; print(engine.url)"   # sanity check
```

You also need a DeepSeek API key. There is no provider key in `.env`; keys live
in the encrypted settings document, set via **Settings → Models → DeepSeek**.

### Step 1 — Add the catalog row

The catalog is the PostgreSQL `models` table (`source='cloud'`), and every model
picker reads it. Three equivalent routes — pick one:

**(a) GUI (no terminal).** Settings → **Models** → press the **Add model** button
at the bottom of the section (it is separate from **Add provider**; per-provider
cards carry the same shortcut). In the form choose the **Provider** from the
dropdown, fill *Model ID* (`deepseek-flash`), an optional display name, max
context, and tick **Vision (image input)** → **Add model**. Registered models are
listed on their provider's card with a **Remove** button. The form writes the same
`POST /api/settings/models` endpoint and refreshes the shared model cache, so
every picker updates without a browser reload.

> The provider dropdown offers only the providers the backend can route
> (`CHAT_PROVIDERS`) — openai, anthropic, google, deepseek, glm, minimax, qwen,
> kimi, agnes. Choosing anything else would silently fall back to the
> OpenAI-compatible endpoint.

**(b) Idempotent script** (adds/updates only this row):

```bash
cd backend
uv run python scripts/seeds/in/upsert_model.py --dry-run --preset deepseek-flash   # inspect first
uv run python scripts/seeds/in/upsert_model.py --preset deepseek-flash             # commit
```

**(c) REST** (also the way to do it from a remote box):

```bash
curl -sS -X POST http://localhost:8765/api/settings/models \
  -H 'Content-Type: application/json' \
  -d '{"model_id":"deepseek-flash","display_name":"DeepSeek Flash (V4.1, Vision)",
       "provider":"deepseek",
       "capabilities":{"streaming":true,"tools":true,"structured_output":true,
                       "vision":true,"max_context":1000000,"max_output":384000}}'
```

> Alternative — a full re-seed (`uv run python scripts/seeds/in/seed_all.py`) also adds
> the row, but it **deletes every `source='cloud'` row first**, including any
> model added through the UI. Prefer (a)–(c).

> The live catalog and `seed_models.py` had already drifted apart (28 vs 34 ids
> before this change), so a re-seed is never the safe way to add one model.

### Step 2 — Verify the catalog

```bash
cd backend
uv run python scripts/seeds/in/upsert_model.py --show deepseek-flash
curl -sS http://localhost:8765/api/settings/models | python -m json.tool | grep -A8 deepseek-flash
```

Then check the GUI: the model appears in **Settings → Models → Default model**, in
the agent editor's model picker, and on workflow agent nodes as
“DeepSeek — DeepSeek Flash (V4.1, Vision)”. Rows added through the form (route a)
refresh the shared model cache themselves, so pickers update within ~1s without a
browser reload; rows added by script/REST need a page refresh, because mounted
pickers only refetch when the cache is empty.

> Backend restart: `core/models/registry.py` loads the `models` table **once at
> import**, and `core/middleware/routing.py` selects models from that registry by
> capability. Model *selection* and LLM construction query the DB per call, so they
> work immediately; if you use capability-based routing, restart the backend to
> pick up a new row.

### Step 3 — Store and test the key

Settings → Models → **DeepSeek** → paste the API key → **Test**.

Headless equivalent:

```bash
curl -sS -X POST http://localhost:8765/api/settings/api-keys/test \
  -H 'Content-Type: application/json' -d '{"provider":"deepseek"}'
```

Note: this connection test calls `deepseek-chat` (`PROVIDER_TEST_MODELS` in
`backend/api/system/settings.py:94`) — it validates the key, not the vision route.

### Step 4 — Prove image → text end to end

```bash
cd backend
uv run python scripts/test_deepseek_vision.py --dry-run    # payload only, no tokens
uv run python scripts/test_deepseek_vision.py              # real call, ~1 image
uv run python scripts/test_deepseek_vision.py --image ~/shot.png --prompt "Extract the table as CSV"
```

The script resolves the key exactly as the app does, renders a test PNG, builds
the message with the app's own `create_multimodal_message`, calls
`deepseek-flash` through the same client class, and asserts the answer contains
the image text. Exit codes: `0` verified, `1` call/assertion failed, `2` no key.

### Step 5 — Use it

- **Default model:** Settings → Models → Default model → `deepseek-flash`
  (writes `primary_model` in the `models` settings namespace).
- **Per agent:** set `model` to `deepseek-flash` in the agent/DeepAgent config.
- **Per workflow node:** select it on the agent node, enable **Multimodal Input**,
  and attach up to 3 images; or pass attachments for the whole run:

```bash
curl -sS -N -X POST http://localhost:8765/api/orchestration/execute \
  -H 'Content-Type: application/json' -d @- <<'JSON'
{
  "workflow_id": 12,
  "input_data": {"query": "Transcribe the text in the attached screenshot"},
  "attachments": [
    {"type": "image", "name": "shot.png", "mime_type": "image/png",
     "data": "<base64, no data: prefix>"}
  ]
}
JSON
```

An `http(s)` URL may be used instead of `data` (`{"type":"image","url":"https://…"}`).
(Note: `AGENTS.md` still says `POST /api/workflows/{id}/execute`; the live mount
is `POST /api/orchestration/execute` — `backend/api/workflows/execution.py:30`.)

### Step 6 — Rollback

In the GUI: Settings → Models → the model is listed on its provider's card with a
**Remove** button (no need to open Edit). Headless equivalents:

```bash
cd backend
uv run python scripts/seeds/in/upsert_model.py --deactivate deepseek-flash   # hide from pickers
curl -sS -X DELETE http://localhost:8765/api/settings/models/deepseek-flash   # remove
```

## 4. Known gaps (do not assume these work)

1. **Agent chat cannot send images.** `SendMessageRequest`
   (`backend/api/chat/schemas.py:32`) has no `attachments` field, and the chat UI
   has no uploader — images work only in workflow runs and agent-node configs.
   Supporting chat needs a backend+frontend change.
2. **No capability gating.** `check_model_multimodal_support()`
   (`backend/core/agents/multimodal.py:301`) is never called, so attaching an
   image while the node is set to `deepseek-chat` / `deepseek-v4-pro` produces an
   upstream API error instead of a clear validation message.
3. **Don't use the DSH checkout as the client.** `deepseek-harness`
   `packages/llm/llm-deepseek/src/serialize.ts:66` throws `UNSUPPORTED_CONTENT`
   on image blocks and `adapter.ts` declares `inputModalities: ['text']` — image
   requests through that adapter cannot work.
4. **Text-only fallback exists:** the builtin `read_image` tool
   (`backend/tools/native_impl.py:2040`) OCRs a workspace image with the system
   `tesseract` binary — useful when a workflow must stay on `deepseek-chat`.
   The `read_any_file` reader (`backend/core/graphs/read_file.py`) extends that
   fallback to PDFs: a page with no text layer is rendered at 150 dpi and OCR'd
   (the first few image-only pages also get a vision description when vision is
   on), so a scanned contract no longer reads as "no extractable text found".
5. **Pricing keys:** the seed writes `input_price`/`output_price`, while
   `core/models/registry.py:421` reads `price_per_1m_input`/`price_per_1m_output`.
   The new `deepseek-flash` row writes both spellings; older rows do not, so
   registry cost lookups return 0 for them.

## 5. Catalog corrections made alongside this change

- Added `deepseek-flash` (vision) as the `deepseek-flash` preset in
  `backend/scripts/seeds/in/upsert_model.py` (originally to `CLOUD_MODELS` in the
  now-removed hardcoded `backend/scripts/seed_models.py`).
- `deepseek-v4-pro`: removed the incorrect `vision: true` **and** `audio: true`
  flags (vendor docs: text-only), refreshed prices.
- `deepseek-v4-flash`: kept (exports and skills reference it) but relabelled as a
  legacy alias of DeepSeek-V4.1-Flash, with Flash pricing.
- `_SUPPORTED_MODELS_FALLBACK` in `backend/services/agent_utils.py` now includes
  the DeepSeek vision ids for DB-less bootstrapping.
