# Phase 7 — Model Cards + Playground

Visual model management UI with one-click playground testing.

## Overview

Phase 7 replaces the bare dropdown model picker with a **Model Cards** panel
that shows rich model metadata and lets users **test any model in a popup
Playground** without leaving Settings.

| Feature | Where |
|---|---|
| Model Cards grid (visual) | `src/features/settings/ui/ModelCardsSettings.tsx` |
| Playground popup modal | `src/features/settings/ui/ModelPlaygroundModal.tsx` |
| Model metadata + capability badges | `backend/scripts/seed_models.py` |
| Mock tool registry | `backend/api/models/routes.py` |

---

## What Was Built

### 1. Model Cards Panel (`ModelCardsSettings.tsx`)

A card grid showing every cloud + local model with full metadata.

**Layout per card:**
- Provider logo (custom SVG) — `OpenAI`, `Anthropic`, `DeepSeek` (dolphin), `Google`, `GLM`, `Qwen`, `Kimi`, `MiniMax`, `Ollama`, `Agnes AI`
- Display name + raw `model_id`
- Capability badges: 🧠 Think / 🔧 Tools / {} JSON / 🎵 Audio / 🎬 Video / 📖 Open / 📏 Context
- Stats row: `$input/$output` per 1M · ⚡ t/s · ⚙ active params
- Strength tagline (italic)
- **🔧 Test** button (blue, screwdriver icon) — connection check
- **▶ Play** button (green, play-triangle icon) — open Playground
- **★ Default** badge or **★ Set Default** button

**Panel header:**
- ★ Default Model badge (live)
- API key status dot (green/red per provider)

### 2. Set As Default Flow

Click `★ Set Default` on any non-default model card → backend
`PATCH /api/settings/model-defaults` updates `primary_model` → header badge
updates immediately + the card switches to a filled `★ Default` badge.

### 3. Playground Modal (`ModelPlaygroundModal.tsx`)

Click `▶ Play` on any model card → centered popup (~960×720).

**Layout:**
- Header: provider logo + name + model_id + Clear + ✕
- Left (collapsible): System Prompt · Temperature · Max Tokens · Top P · Freq Penalty · Pres Penalty · Stop Sequences · JSON mode · Tool calling · Streaming · Image URL (vision)
- Right: chat history + input box + Enter-to-send + auto-scroll

**8 preset chips** (one-click demos, auto-send):
| Chip | 中文 | What it tests |
|---|---|---|
| 👋 Greeting | 打招呼 | Basic chat |
| 🧮 Math | 数学 | Arithmetic + reasoning |
| {} JSON | JSON | `json_mode` toggle on + sample |
| 🔧 Tools | 工具 | `tools=true` → `get_weather` + `get_current_time` |
| 🌐 Search | 搜索 | `tools=true` → `search_web` |
| 📡 Stream | 流式 | `stream=true` flag (backend hooks, ready for SSE) |
| 🖼 Vision | 视觉 | `image_url` → multimodal HumanMessage |
| 🧠 Reason | 推理 | Classic syllogism |

After running any preset, the user can type their own query and continue.

### 4. Backend Model Metadata (`seed_models.py`)

Enriched `capabilities` JSON for **26 cloud models**:

```
Providers: openai, anthropic, deepseek, google, glm, qwen, kimi, minimax, agnes
Per-model fields:
  streaming, tools, structured_output, vision, audio, video,
  thinking, open_source, license, release, max_context, max_output,
  input_price, output_price, speed_tps,
  strength, params_total, params_active, architecture
```

Realistic 2026 specs (verified via web search):
- **DeepSeek V4 Pro / V4 Flash** — 1M context, hybrid CSA+HCA, MoE 1.6T/49B
- **GPT-5.5, GPT-5.1, GPT-4.1, GPT-4o, GPT-4o-mini, o3** — full pricing & speed
- **Claude Opus 4.8, Sonnet 4.6, Sonnet 4.5, Haiku 4.5** — context 200K-1M
- **Gemini 3.1 Pro preview, 3 Flash preview, 2.5 Pro/Flash/Lite, 2.0 Flash, Gemma 4**
- **GLM 5.1, GLM 4.5** (open MIT), **Qwen 3.5/3.6 Plus**, **Kimi K2.6**, **MiniMax M3 / M2.7**
- Also re-added: **deepseek-chat** (real production model), **deepseek-reasoner** (R1)

### 5. Backend Tool Calling (`api/models/routes.py`)

`POST /api/models/invoke` now supports real function calling with mock tools:

```
4 demo tools (mock — no external API):
  get_weather(city, unit)        → 10 Chinese cities + 5 international
  get_current_time(timezone)     → datetime.now()
  search_web(query, max_results) → templated fake results
  calculate(expression)          → Python eval() in safe sandbox
```

Agent loop (max 3 turns):
```
user message
   ↓
LLM decides: tool_call? → yes
   ↓
execute_demo_tool(name, args) → string result
   ↓
append result as ToolMessage, re-invoke LLM
   ↓
LLM sees tool result → produces final answer
```

Response now includes `tool_calls: [{name, arguments, result}]` log for UI display.

### 6. Multimodal Support

`image_url` param builds a LangChain `HumanMessage` with content array:

```python
HumanMessage(content=[
  {"type": "text", "text": prompt},
  {"type": "image_url", "image_url": {"url": image_url}},
])
```

Works with any vision-capable model (gpt-4o, claude-3+, gemini, etc.).

### 7. Extra Sampling Params

Added to `ModelInvokeRequest`:
- `top_p` (0–1 nucleus sampling)
- `frequency_penalty` (-2 to 2)
- `presence_penalty` (-2 to 2)
- `stop` (list of stop sequences)
- `tools` (boolean toggle)
- `tool_names` (filter specific tools)
- `image_url` (vision input)
- `stream` (toggle for future SSE)
- `json_mode` (force JSON output)

All wired through `llm.top_p = …` etc. with `try/except` to handle providers
that don't support a given parameter.

---

## Bug Fixes During Phase 7

| Commit | Fix |
|---|---|
| `1567021` | Playground model dropdown had empty `onChange={() => {}}` — couldn't switch models |
| `50570f2` | LangChain tool decorator requires docstring — added `"Dynamic demo tool..."` |
| `50570f2` | Tool args came wrapped as `{"kwargs": {...}}` — switched to `StructuredTool.from_function` with explicit `args_schema` |
| `bc08cb0` | `runPreset()` didn't clear `imageUrl` → wikimedia URL persisted into non-Vision requests and caused TLS timeouts |

---

## File Map

```
phase7/
└── README.md                                     ← this file

src/features/settings/ui/
├── ModelCardsSettings.tsx                        ← card grid + set-default
└── ModelPlaygroundModal.tsx                      ← popup chat tester (NEW)

src/lib/
└── api-client.ts                                 ← added image_url, tool_names, top_p, etc.

backend/api/models/
└── routes.py                                     ← tool registry, agent loop, image_url

backend/scripts/
└── seed_models.py                                ← 26 cloud models + V4 specs
```

---

## How To Use

```bash
# Start (existing start.sh)
bash start.sh
```

Then in the browser:
1. **Settings** → **Model Cards** — see all 26 cloud models + any local models
2. Click **🔧 Test** on any card to ping the provider API
3. Click **★ Set Default** to set as primary model
4. Click **▶ Play** → modal opens with default settings
5. Click any preset chip → auto-send → see result
6. Tweak params on the left, then type your own query
7. Toggle JSON / Tools / Streaming / Image URL in the advanced panel

---

## Commits

```
bc08cb0  fix(i18n): Chinese preset chips + mock weather for Chinese cities
50570f2  feat: Playground preset query chips + tool calling + image support
f1c5877  feat: extend Playground with top_p/freq/pres penalties/stop/json_mode/tools/stream
ab100c0  feat: Playground popup modal opened via Play button on each model card
1567021  fix: Playground model dropdown can now switch models
9f23e9c  feat: DeepSeek V4 + enriched model cards (screwdriver test btn, dolphin logo)
e400ec4  feat: Model Cards — inline test results, Set as Default, remove per-card logo
8c917af  feat: Model Cards — properties row, panel-level default badge, fix DeepSeek logo
543b8ce  refactor: Model Cards — bottom layout, real company logos
5559675  feat: Model Cards — modality badges, provider logos, embedding models
70211fb  style: Model Cards — 5 per row
81b72d2  style: Model Cards — wider container, golden ratio 1.618:1, clickable dot
7c0d2fb  style: Model Cards — 4 per row instead of 3
565b929  style: Model Cards — golden ratio 1:0.618, 3 per row
1a9bd84  feat: add Model Cards panel to Settings
d6cea9f  feat: migrate API keys and model config from DB to .env
```

(Phase 7 = `1a9bd84` through `bc08cb0` — 16 commits)