# Phase 1: Settings Page — UI to Backend Flow

> How a user configures API keys, model cards, model defaults, embedding, local models, workspace settings, appearance, and about — in the frontend, and how those settings flow through the API to PostgreSQL storage and runtime retrieval.

---

## Settings Page Overview

**File**: [`src/pages/SettingsPage.tsx`](../../../src/pages/SettingsPage.tsx) → [`src/features/settings/ui/SettingsLayout.tsx`](../../../src/features/settings/ui/SettingsLayout.tsx)

The Settings page is a tabbed interface with the following sections (sidebar-driven via [`SettingsSidebar.tsx`](../../../src/features/settings/ui/SettingsSidebar.tsx)):

| Tab | UI Component | Description |
|---|---|---|
| **General** | Inline form in `SettingsPage.tsx` | App name, auto-save, notifications, log level |
| **API & Providers** | Inline form in `SettingsPage.tsx` | API keys for LLM providers (Anthropic, OpenAI, Google, etc.) |
| **Model Cards** | [`ModelCardsSettings.tsx`](../../../src/features/settings/ui/ModelCardsSettings.tsx) | Visual grid of all available models — each card has API key status, capabilities, and a **Playground button** (opens [`ModelPlaygroundModal.tsx`](../../../src/features/settings/ui/ModelPlaygroundModal.tsx) for live testing) |
| **Embedding** | (form) | Embedding model selection (PostgreSQL/pgvector) |
| **Model Defaults** | [`ModelDefaultsSettings.tsx`](../../../src/features/settings/ui/ModelDefaultsSettings.tsx) | Default model, temperature, routing strategy, fallback chain |
| **Local Models** | [`LocalModelsSettings.tsx`](../../../src/features/settings/ui/LocalModelsSettings.tsx) | Ollama / LM Studio / vLLM / LiteLLM provider config |
| **Local Workspace** | [`LocalWorkspaceSettings.tsx`](../../../src/features/settings/ui/LocalWorkspaceSettings.tsx) | File system access for coding agents |
| **Appearance** | (form) | Theme (light/dark), language |
| **About** | (form) | Version info, docs link |

> **Header Playground button removed (2026-06-23):** The global "Playground" nav button in [`ModernHeader.tsx`](../../../src/components/layout/ModernHeader.tsx) was redundant — the same playground capability now lives inside each model card (click the play icon → opens ModelPlaygroundModal).

The page uses a single `currentCategory` state variable (`general` | `api-keys` | `model-cards` | `embedding` | `model-defaults` | `local-models` | `local-workspace` | `appearance` | `about`) to switch between sections via a sidebar. Each tab is rendered in a `switch` statement on the `currentCategory` value.

## Navigation Architecture

The app has **two parallel navigation surfaces**:

### Surface A — Global Header (`ModernHeader.tsx`)

```
┌────────────────────────────────────────────────────────────────────────────┐
│  [🏠 Home] [⚡ Studio] [📚 Library] [🧠 Knowledge] [🔧 Tools]               │
│  [📝 Prompt] [🎯 Skills] [👥 Community] [🤖 DeepAgent Studio]            │
└────────────────────────────────────────────────────────────────────────────┘
   ↑ 9 destinations (no Playground button as of 2026-06-23 — moved into Model Cards)
```

### Surface B — Settings Sidebar (`SettingsSidebar.tsx`)

```
┌─────────────────────────┐  ┌──────────────────────────────────────────┐
│  ⚙ Settings Sidebar     │  │  Active Tab Content                      │
│                         │  │                                          │
│  ▸ General              │  │   <ModelCardsSettings />                 │
│  ▸ API & Providers      │  │   ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐  │
│  ▸ Model Cards    ◀ active│  │   │DS-V3 │ │MiniMax│ │Claude│ │ GPT-5│  │
│  ▸ Embedding            │  │   │ ✓ready│ │ ✓ready│ │ ⚠key │ │ ✓ready│ │
│  ▸ Model Defaults       │  │   │ [▶]  │ │ [▶]  │ │ [▶]  │ │ [▶]  │  │
│  ▸ Local Models         │  │   └──────┘ └──────┘ └──────┘ └──────┘  │
│  ▸ Local Workspace      │  │     ↑                                      │
│  ▸ Appearance           │  │     └── click ▶ → ModelPlaygroundModal   │
│  ▸ About                │  │                                          │
└─────────────────────────┘  └──────────────────────────────────────────┘
```

### Data Flow — Header → Settings → Backend

```
User clicks "Settings" link in Studio
        │
        ▼
SettingsPage mounts
        │
        ▼
SettingsLayout renders sidebar (9 tabs) + active panel
        │
        ├── user clicks "Model Cards" ──► ModelCardsSettings fetches:
        │                                 GET /api/settings/available-models
        │                                 GET /api/settings/api-keys  (masked)
        │                                 GET /api/models (cloud models from DB)
        │
        └── user clicks ▶ on a model card ──► ModelPlaygroundModal:
                                              ├─ preset that model
                                              ├─ POST /api/chat/playground
                                              │     (live test)
                                              └─ streams response back
```

### Data Loading Pattern

All settings are loaded on mount via `loadSettings()`:

```typescript
const loadSettings = async () => {
  // 1. Load API keys (masked status only — never raw keys)
  const keysResponse = await apiClient.getApiKeys();

  // 2. Load general settings
  const generalResponse = await apiClient.getGeneralSettings();

  // 3. Load local models settings
  const localModelsResponse = await apiClient.getLocalModelsSettings();

  // 4. Load workspace settings
  const workspaceResponse = await apiClient.getWorkspaceSettings();

  // 5. Load model defaults
  const modelDefaultsResponse = await apiClient.getModelDefaultsSettings();
};
```

Each setting section has its own `GET` endpoint and corresponding `POST/PUT` endpoint for saving.

---

## 1. API Key Flow — User Input to PostgreSQL

This section traces what happens when a user types an API key in Settings → API & Providers and clicks "Save API Keys".

### Step-by-Step Flow

```
User types "sk-ant-..." in the Anthropic field
  │
  ├─ 1. React state update: setApiKeys({...apiKeys, anthropic: "sk-ant-..."})
  │     (SettingsPage.tsx line 659)
  │
  ├─ 2. User clicks "Save API Keys" button
  │     (SettingsPage.tsx line 875-886)
  │
  ├─ 3. Frontend builds keysToSave object
  │     const keysToSave = {};
  │     if (apiKeys.anthropic) keysToSave.anthropic_api_key = apiKeys.anthropic;
  │     if (apiKeys.tavily)    keysToSave.tavily_api_key = apiKeys.tavily;
  │     // ... only non-empty keys are included
  │
  ├─ 4. HTTP POST to backend
  │     apiClient.setApiKeys(keysToSave)
  │     → POST /api/settings/api-keys
  │     Body: { anthropic_api_key: "sk-ant-...", minimax_api_key: "...", ... }
  │     (api-client.ts line 517-528)
  │
  ├─ 5. Backend receives request
  │     @router.post("/api-keys")
  │     async def set_api_keys(keys: APIKeySet, db: Session)
  │     (settings.py line 137-138)
  │
  ├─ 6. Pydantic validation
  │     class APIKeySet(BaseModel):
  │         openai_api_key: Optional[str] = None
  │         anthropic_api_key: Optional[str] = None
  │         google_api_key: Optional[str] = None
  │         cohere_api_key: Optional[str] = None
  │         replicate_api_key: Optional[str] = None
  │         deepseek_api_key: Optional[str] = None
  │         glm_api_key: Optional[str] = None
  │         minimax_api_key: Optional[str] = None
  │         tavily_api_key: Optional[str] = None
  │     (settings.py line 19-29)
  │
  ├─ 7. Encrypt each key
  │     api_keys["anthropic"] = encryption_service.encrypt(keys.anthropic_api_key)
  │     api_keys["tavily"]    = encryption_service.encrypt(keys.tavily_api_key)
  │     (settings.py line 144-160)
  │
  ├─ 8. Encryption internals
  │     class EncryptionService (singleton):
  │         _initialize():
  │             key_str = os.getenv("APP_ENCRYPTION_KEY", "default-fallback")
  │             salt = b'langconfig_salt'
  │             kdf = PBKDF2HMAC(SHA256, 32, salt, 100000 iterations)
  │             key = base64.urlsafe_b64encode(kdf.derive(key_str.encode()))
  │             self._fernet = Fernet(key)
  │         encrypt(data):
  │             return self._fernet.encrypt(data.encode()).decode()
  │     (encryption.py)
  │
  ├─ 9. Store in PostgreSQL
  │     settings.api_keys = api_keys
  │     flag_modified(settings, "api_keys")   # ← Required for JSON column mutation tracking
  │     db.commit()
  │     (settings.py line 162-164)
  │
  └─ 10. Response back to frontend
       return {"message": "API keys saved successfully"}
       → setApiKeySaveMessage('API keys saved successfully!')
       → setApiKeys({ anthropic: '', openai: '', ... })  # Clear input fields
```

### SQLAlchemy Model

**File**: [`backend/models/settings.py`](../../../backend/models/settings.py)

```python
class Settings(Base):
    __tablename__ = 'settings'
    id = Column(Integer, primary_key=True, default=1)  # Single-row table (always id=1)
    api_keys = Column(JSON, default=dict)  # {"openai": "encrypted...", "anthropic": "encrypted..."}
    # ... other settings columns
```

Key detail: `flag_modified(settings, "api_keys")` is required because SQLAlchemy doesn't detect in-place mutations of JSON columns. Without it, the UPDATE won't fire.

### Loading API Keys (Display Only)

When the Settings page loads:

```typescript
const loadSettings = async () => {
  const keysResponse = await apiClient.getApiKeys();  // GET /api/settings/api-keys
  // Backend returns: [{ provider: "anthropic", is_set: true, masked_key: "sk-a...nt-3" }, ...]
  setApiKeyStatus({
    anthropic: keys.find(k => k.provider === 'anthropic')?.is_set || false,
    // ...
  });
  setApiKeys({ anthropic: '', openai: '', ... });  // Inputs stay empty — user types to replace
};
```

The frontend **never receives the actual key value**. Only `is_set: bool` and `masked_key: "sk-a...nt-3"` are returned.

### Two Save Mechanisms

| Mechanism | Trigger | Tavily included? |
|---|---|---|
| **Manual Save** | User clicks "Save API Keys" button ([line 875](file:///Users/weiping/dev/Learn/langchain-ai/langconfig/src/pages/SettingsPage.tsx#L875)) | ✅ Yes ([line 886](file:///Users/weiping/dev/Learn/langchain-ai/langconfig/src/pages/SettingsPage.tsx#L886)) |
| **AutoSave** | Debounced 1s after last keystroke ([line 255](file:///Users/weiping/dev/Learn/langchain-ai/langconfig/src/pages/SettingsPage.tsx#L255)) | ✅ Now included (was missing, fixed) |

**Note**: Both the `autoSave` function and the `api-client.ts` `setApiKeys` type previously lacked `tavily_api_key` — this has been fixed. The backend Pydantic model already accepted it.

### Runtime Retrieval

When an agent is executed, the API key is retrieved via this chain:

```
AgentFactory.create_agent(config)
  → config.py: PROVIDER_API_KEY_MAP["anthropic"] = "ANTHROPIC_API_KEY"
  → lookup chain:
      1. settings.api_keys.get("anthropic") → decrypt → return
      2. os.getenv("ANTHROPIC_API_KEY") → return (fallback)
      3. Raise error: "API key not found for provider: anthropic"
```

**Provider → API Key Map** ([`backend/config.py`](../../../backend/config.py)):

```python
PROVIDER_API_KEY_MAP: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "glm": "GLM_API_KEY",
    "minimax": "MINIMAX_API_KEY",
}
```

### API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/settings/api-keys` | GET | List providers with `is_set` + masked key |
| `/api/settings/api-keys` | POST | Save one or more encrypted keys |
| `/api/settings/api-keys/{provider}` | DELETE | Remove a provider's key |

### DB Query to Verify

```sql
SELECT id, api_keys->>'anthropic' AS anthropic_key,
       api_keys->>'tavily' AS tavily_key,
       api_keys->>'minimax' AS minimax_key
FROM settings
WHERE id = 1;
```

---

## 2. Model Defaults Settings

**File**: [`src/features/settings/ui/ModelDefaultsSettings.tsx`](../../../src/features/settings/ui/ModelDefaultsSettings.tsx)

The Settings page has a "Model Defaults" tab that lets users configure system-wide defaults:

```typescript
interface ModelDefaultsSettings {
  primaryModel: string;         // Default model for new agents
  fallbackModels: string[];     // Fallback models if primary fails
  temperature: number;          // 0.0–2.0 (default: 0.7)
  maxTokens: number;            // Default: 4096
  topP: number;                 // 0.0–1.0 (default: 1.0)
  routingStrategy: string;      // "balanced" | "cost_optimized" | "performance"
  dailyTokenLimit: number;      // 0 = unlimited
  monthlyTokenLimit: number;    // 0 = unlimited
  alertThreshold: number;       // Percentage before hitting limit (default: 80)
}
```

**API Endpoints**:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/settings/model-defaults` | GET | Fetch current defaults |
| `/api/settings/model-defaults` | POST | Save new defaults |

**Backend model** — stored as columns in the `settings` table: `primary_model`, `temperature`, `max_tokens_default`, `top_p`, `routing_strategy`, `daily_token_limit`, `monthly_token_limit`, `alert_threshold`, `fallback_models` (JSON column).

---

## 3. Available Models — How the Dropdown is Populated

**Hook**: [`src/hooks/useAvailableModels.ts`](../../../src/hooks/useAvailableModels.ts)
**Component**: [`src/components/common/ModelSelector.tsx`](../../../src/components/common/ModelSelector.tsx)

The model dropdown used in both Settings (Model Defaults) and Agent Builder is populated dynamically:

```
useAvailableModels()
  │
  ├─ 1. Calls apiClient.listAvailableModels()
  │       → GET /api/settings/available-models
  │
  ├─ 2. Backend returns: { models: string[], local_models: LocalModel[] }
  │     Cloud models: ["gpt-4o", "claude-sonnet-4-5", "gemini-2.5-flash", ...]
  │     Local models: [{ name: "llama3.2:latest", provider: "ollama", ... }]
  │
  ├─ 3. Cloud models mapped to display names:
  │       "claude-sonnet-4-5" → { name: "Claude Sonnet 4.5", provider: "Anthropic" }
  │       "gpt-4o" → { name: "GPT-4o", provider: "OpenAI" }
  │
  └─ 4. Local models fetched from GET /api/local-models, filtered to validated ones
```

**API Endpoint**:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/settings/available-models` | GET | Fetch cloud + local model list |

---

## 4. Model Cards — Visual Model Grid with Playground

**File**: [`src/features/settings/ui/ModelCardsSettings.tsx`](../../../src/features/settings/ui/ModelCardsSettings.tsx)
**Playground Modal**: [`src/features/settings/ui/ModelPlaygroundModal.tsx`](../../../src/features/settings/ui/ModelPlaygroundModal.tsx)

The Model Cards tab is a **visual alternative to the model dropdown**. Instead of picking a model name from a list, users see a grid of cards, each with:

| Card Element | Source | Description |
|---|---|---|
| **Model display name** | `models.name` (DB) | "Claude Sonnet 4.5", "DeepSeek V3" |
| **Provider** | `models.provider` (DB) | Anthropic / OpenAI / DeepSeek / MiniMax |
| **API key status** | `GET /api/settings/api-keys` masked | ✓ ready / ⚠ no key |
| **Capabilities** | `models.capabilities` (DB JSON) | "chat", "vision", "tools", "json_mode" |
| **Pricing** | `models.pricing` (DB JSON) | input/output $/Mtok |
| **Context window** | `models.context_window` (DB int) | tokens |
| **Playground button** ▶ | opens `ModelPlaygroundModal` | live test |

### Card Grid — Component Structure

```
┌─────────────────────────────────────────────────────────────────────┐
│ <ModelCardsSettings>                                                │
│                                                                     │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐│
│   │ Card #1     │  │ Card #2     │  │ Card #3     │  │ Card #4    ││
│   │ ┌─────────┐ │  │ ┌─────────┐ │  │ ┌─────────┐ │  │ ┌────────┐ ││
│   │ │ DS-V3   │ │  │ │ MiniMax │ │  │ │ Claude  │ │  │ │ GPT-5  │ ││
│   │ │ DeepSeek│ │  │ │ MiniMax │ │  │ │ Anthrop.│ │  │ │ OpenAI │ ││
│   │ │  ✓ready │ │  │ │  ✓ready │ │  │ │  ⚠ key  │ │  │ │ ✓ready │ ││
│   │ │ [▶]     │ │  │ │ [▶]     │ │  │ │ [▶]     │ │  │ │ [▶]    │ ││
│   │ └─────────┘ │  │ └─────────┘ │  │ └─────────┘ │  │ └────────┘ ││
│   └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

### Playground Modal — Click Flow

```
User clicks ▶ on a card
        │
        ▼
<ModelPlaygroundModal model="MiniMax-M3">
        │
        ├── shows: model name, provider, capabilities, system prompt input
        │
        ├── user types a message + clicks "Send"
        │       │
        │       ▼
        │   POST /api/chat/playground
        │     body: { model: "MiniMax-M3", messages: [...], temperature: 0.7 }
        │       │
        │       ▼
        │   backend: agent_factory.create_agent() with only this model
        │       │
        │       ▼
        │   streams response tokens back via SSE
        │
        └── user closes modal → returns to cards grid
```

### Why Model Cards Exist (vs Dropdown)

| Surface | UX | When to use |
|---|---|---|
| **Model dropdown** (in Model Defaults / Agent Builder) | Fast, compact, list | Picking the default |
| **Model cards** (in Settings) | Visual, informational, has Playground | Browsing capabilities, live testing |

### Data Sources

| Field | Source | Endpoint |
|---|---|---|
| Card list | PostgreSQL `models` table (seeded by `scripts/seed_models.py`) | `GET /api/settings/available-models` |
| API key status | PostgreSQL `settings.api_keys` (encrypted JSON) | `GET /api/settings/api-keys` |
| Playground chat | Backend agent factory | `POST /api/chat/playground` |

### Why the Header Playground button was removed (2026-06-23)

The old flow:
```
Header → Playground → "which model?" dropdown → ModelPlaygroundModal
                                              (one extra click)
```

The new flow:
```
Header → Settings → Model Cards → click ▶ (model already preset)
                          ↓ (one fewer click, one fewer decision)
```

This is a **navigation compression** — putting the playground next to the model instead of behind a separate global nav.

---

## 5. Local Models Settings

**File**: [`src/features/settings/ui/LocalModelsSettings.tsx`](../../../src/features/settings/ui/LocalModelsSettings.tsx)

Allows configuration of local LLM providers (Ollama, LM Studio):

```typescript
interface LocalModelsSettings {
  provider: string;       // "ollama" | "lm_studio"
  baseUrl: string;        // e.g. "http://localhost:11434/v1"
  modelName: string;      // e.g. "llama3.2:latest"
  apiKey: string;         // Optional, for authenticated local endpoints
}
```

**API Endpoints**:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/local-models` | GET | List available local models |
| `/api/settings/local-models` | GET | Fetch local models config |
| `/api/settings/local-models` | POST | Save local models config |

**Backend model** — stored as columns in the `settings` table: `local_provider`, `local_base_url`, `local_model_name`, `local_api_key`.

---

## 6. Local Workspace Settings

**File**: [`src/features/settings/ui/LocalWorkspaceSettings.tsx`](../../../src/features/settings/ui/LocalWorkspaceSettings.tsx)
**Backend Endpoint**: [`backend/api/system/settings.py#L443`](../../../backend/api/system/settings.py#L443) — `GET/POST /api/settings/workspace`

### What It Configures

| Setting | Control | DB Column |
|---|---|---|
| **Workspace Directory** | Text input + Browse button | `workspace_path` |
| **Allow read** | Checkbox | `workspace_allow_read` |
| **Allow write** | Checkbox | `workspace_allow_write` |
| **Require approval** | Checkbox | `workspace_require_approval` |
| **Auto-detect git** | Checkbox | `workspace_auto_detect_git` |
| **Backup before edit** | Checkbox | `workspace_backup_before_edit` |

### The Two-Workspace Architecture

There are **two separate workspace concepts** in the backend:

| | Local Workspace (User's Code) | Output Workspace (Agent's Results) |
|---|---|---|
| **Purpose** | Agents read user's source code | Agents write generated files (reports, etc) |
| **Path** | User-configured (e.g. `~/projects/app`) | `backend/outputs/project_{id}/workflow_{id}/task_{id}/` |
| **Default** | Not set (user must configure) | Always available (`backend/outputs/`) |
| **Manager** | (stored in `settings` table) | [`WorkspaceManager`](../../../backend/services/workspace_manager.py) |
| **Tools using it** | `read_file`, `ls`, `glob`, `grep` | `write_file`, `list_task_files` |
| **Security** | Trust-based (agent instructions) | `path.relative_to()` boundary check |
| **DB tracking** | No | `WorkspaceFile` table (agent, task, meta) |

### How It Works in Python

**Output workspace** — [`backend/services/workspace_manager.py`](../../../backend/services/workspace_manager.py):

```python
class WorkspaceManager:
    def __init__(self, base_dir=None):
        self.base_dir = Path(__file__).parent.parent / "outputs"

    def get_task_workspace(self, project_id, workflow_id, task_id):
        return self.base_dir / f"project_{project_id}" / f"workflow_{workflow_id}" / f"task_{task_id}"
```

**File writing** — [`backend/tools/native_tools.py#L573`](../../../backend/tools/native_tools.py#L573):

```python
def _write_file_impl(file_path, content, _workspace_context=None, ...):
    workspace_mgr = get_workspace_manager()
    if _workspace_context:
        workspace = workspace_mgr.get_task_workspace_with_override(
            project_id=_workspace_context.get('project_id'),
            workflow_id=_workspace_context.get('workflow_id'),
            task_id=_workspace_context.get('task_id'),
        )
    else:
        workspace = workspace_mgr.base_dir / "default"

    # Security: prevent path traversal
    path = (workspace / filename).resolve()
    try:
        path.relative_to(workspace.resolve())
    except ValueError:
        return "Error: Cannot write outside workspace directory"

    path.write_text(content)
    _record_file_metadata(filename, path, workspace, content,
                          workspace_context, agent_context)
```

---

## 7. General Settings

**Endpoint**: `backend/api/system/settings.py`

Stored as columns in the `settings` table:

| Setting | UI Element | DB Column |
|---|---|---|
| App Name | Text input | `app_name` |
| Auto Save | Toggle | `auto_save` |
| Auto Save Interval | Number input (seconds) | `auto_save_interval` |
| Confirm Before Delete | Toggle | `confirm_before_delete` |
| Show Notifications | Toggle | `show_notifications` |
| Check Updates | Toggle | `check_updates` |
| Telemetry | Toggle | `telemetry` |
| Log Level | Dropdown | `log_level` |

**API Endpoints**:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/settings/general` | GET | Fetch general settings |
| `/api/settings/general` | POST | Save general settings |
| `/api/settings` | POST | Update RAG settings (embedding_model, chunk_size, chunk_overlap) |

---

## API Endpoints Summary

| Endpoint | Method | Section | Purpose |
|---|---|---|---|
| `/api/settings/api-keys` | GET | API Keys | List providers + masked status |
| `/api/settings/api-keys` | POST | API Keys | Save encrypted keys |
| `/api/settings/api-keys/{provider}` | DELETE | API Keys | Remove a key |
| `/api/settings/available-models` | GET | Models | Fetch cloud + local model list (DB-backed) |
| `/api/models` | GET | Model Cards | List 23 seeded models (display cards) |
| `/api/chat/playground` | POST | Model Cards | Live test a single model (no tools) |
| `/api/settings/model-defaults` | GET | Model Defaults | Fetch defaults |
| `/api/settings/model-defaults` | POST | Model Defaults | Save defaults |
| `/api/settings/local-models` | GET | Local Models | Fetch local models config |
| `/api/settings/local-models` | POST | Local Models | Save local models config |
| `/api/local-models` | GET | Local Models | List available local models |
| `/api/settings/workspace` | GET | Workspace | Fetch workspace config |
| `/api/settings/workspace` | POST | Workspace | Save workspace config |
| `/api/settings/general` | GET | General | Fetch general settings |
| `/api/settings/general` | POST | General | Save general settings |
| `/api/settings` | POST | General | Update RAG settings |
| `/api/settings/embedding` | GET | Embedding | Fetch embedding model config |
| `/api/settings/embedding` | POST | Embedding | Save embedding model config |
| `/api/settings/appearance` | GET | Appearance | Fetch theme/language |
| `/api/settings/appearance` | POST | Appearance | Save theme/language |

> **Added in 2026-06-23 refactor:** `/api/models`, `/api/chat/playground`, `/api/settings/embedding`, `/api/settings/appearance`.
> The `/api/chat/playground` endpoint replaces the removed header Playground button — same capability, deeper in the navigation tree, with the model preset.

---

## Key Takeaways

1. **Single-row settings table** — All app configuration lives in one PostgreSQL row (`settings.id = 1`), with a mix of typed columns and a JSON `api_keys` column.
2. **API keys are encrypted at rest** — Fernet + PBKDF2 with a server-side `APP_ENCRYPTION_KEY`. The frontend never receives raw key values, only `is_set` status and a masked preview.
3. **`flag_modified()` is required for JSON columns** — SQLAlchemy doesn't detect in-place dict mutations. Without `flag_modified(settings, "api_keys")`, the UPDATE won't fire.
4. **Two save modes for API keys** — Manual button click and debounced autoSave (1s). The autoSave was previously missing `tavily_api_key` — now fixed.
5. **Setting hierarchy** — System-wide defaults (Settings) → Per-agent config overrides (Agent Builder) → Runtime overrides (deepagents library).
6. **Two workspace concepts** — Local Workspace (user's code, read-only by convention) and Output Workspace (agent-generated files, written to `outputs/` with path traversal protection).
7. **All settings are independently loadable** — Each section has its own GET/POST endpoints, allowing the frontend to load only what's needed for the active tab.
8. **Two navigation surfaces** — Global header (9 destinations, no Playground) + Settings sidebar (9 tabs). Model Cards tab is the new home for the per-model Playground.
9. **Playground lives next to the model** — Removed from header, now an action button on each Model Card. One fewer click to test, no "which model?" dropdown.