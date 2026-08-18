# LangConfig — 团队安装指南（中文版）

> 在全新机器上从 zip 包安装 LangConfig：PostgreSQL 安装、uv、解压、依赖同步、
> 数据库种子（含工作区配置）、LLM API Key、健康检查与启动。

---

## 0. 你会收到什么

`langconfig.zip`（约 12 MB）包含完整源码，不含密钥/构建产物（无 `.env`、
`node_modules`、`.venv`、`data`、`backend/outputs`、git 历史）。数据库种子会
恢复一个**与机器无关的基线**：44 个深度智能体、28 个 LLM 模型、58 个工具、
19 个技能。**你的工作区路径和 API Key 在下面步骤中本地添加——zip 里不包含
任何机器相关的信息。**

---

## 1. PostgreSQL — 安装与配置

> ⚠️ **在启动 Postgres 之前务必先做这一步：** `docker compose` 在 compose
> 时会读取 `.env` 来决定宿主机端口。如果你在创建 `.env`（第 5 步）之前就启动
> 容器，`POSTGRES_PORT` 会回退为 `5432`，文档中的 `5433` 映射不会生效。
> **推荐顺序：先创建 `.env`（第 5 步），再启动 Postgres（本步骤）**——或者内联
> 传参：`POSTGRES_PORT=5433 docker compose up -d postgres`。

选择**一种**模式，并记下三项凭据——整个应用（后端、Alembic、种子脚本、
docker-compose、SQL 智能体）都从它们派生连接信息。

| 项目 | 默认值 | 使用位置 |
|---|---|---|
| 数据库名 | `langconfig` | `.env` 中的 `POSTGRES_DB` |
| 用户名 | `langconfig` | `.env` 中的 `POSTGRES_USER` |
| 密码 | `langconfig_dev` | `.env` 中的 `POSTGRES_PASSWORD` |
| 主机 / 端口 | `localhost`：原生 **5432**，Docker **5433** | `.env` 中的 `POSTGRES_PORT` |

### 方案 A — Docker（最简单，团队推荐）

```bash
# 在解压后的目录中执行
docker compose up -d postgres
# 容器：langconfig-postgres，宿主机端口 5433（→ 容器 5432）
# 健康检查：docker ps   →  "langconfig-postgres  0.0.0.0:5433->5432/tcp"
```

### 方案 B — 原生 PostgreSQL 16（macOS Homebrew）

```bash
brew install postgresql@16
brew services start postgresql@16
# 端口 :5432；创建角色 + 数据库（或让 seed_all.py 自动创建——当应用用户
# 能以超级用户连接时它会自动建库）：
psql postgres -c "CREATE ROLE langconfig LOGIN PASSWORD 'langconfig_dev' CREATEDB;"
psql postgres -c "CREATE DATABASE langconfig OWNER langconfig;"
```

### 方案 C — 原生 PostgreSQL 16（Ubuntu / WSL2）

```bash
sudo apt install -y postgresql-16 postgresql-16-pgvector   # pgvector 用于向量嵌入
sudo service postgresql start
sudo -u postgres psql -c "CREATE ROLE langconfig LOGIN PASSWORD 'langconfig_dev' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE langconfig OWNER langconfig;"
```

> 角色需要 `CREATEDB` 权限，因为 `seed_all.py` 第 1 步会在数据库缺失时创建它，
> 第 10 步会为 Graph Studio 创建 `chinook` 示例数据库。

---

## 2. 安装 uv（Python 3.13 管理器）

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# 然后重启你的 shell 或执行：  source ~/.local/bin/env   （路径会自动添加）

uv --version          # 验证
```

需要 Python **3.13+**（仓库要求 `>=3.13`）。如果你的系统 Python 版本较旧，
uv 可以自动拉取：

```bash
uv python install 3.13
```

---

## 3. 解压安装包

```bash
unzip langconfig.zip -d langconfig
cd langconfig
ls          # AGENTS.md  backend/  docker-compose.yml  docs/  package.json  src/  start.sh  scripts/ ...
```

---

## 4. 同步 Python 依赖（`uv sync`）

项目的 Python 清单是 **`backend/pyproject.toml`**（FastAPI、LangChain 1.x、
LangGraph、deepagents 0.7.1、pgvector、Playwright 等）。`uv sync` 读取它并创建
`backend/.venv`。

```bash
cd backend
uv sync                 # 创建 .venv/ 并安装所有锁定依赖
uv run python -c "import fastapi, langgraph, deepagents; print('deps OK')"
```

> `backend/requirements.txt` 也存在，作为 pip 备选方案
> （`pip install -r requirements.txt`），但 **`uv sync` 是标准路径**。
> 前端依赖是独立的：`cd .. && npm install`（仅 UI 需要；纯后端 API 不需要）。

---

## 5. 配置 `.env`（含工作区）——必须在种子之前，按所有者划分

`.env` 是**引导默认值**（首次启动时读取一次）。用户可调的运行时设置和所有
API Key 都在数据库中，可通过 Settings 面板修改。三个分区，按顺序如下：

```bash
# backend/../.env  （仓库根目录）
# 从仓库里的 env_example 模板开始（已提交），再修改以下三个分区：

# ════ OPERATOR-ONLY（基础设施 — 不要让用户改） ════
POSTGRES_HOST=localhost
POSTGRES_PORT=5433          # docker；原生用 5432
POSTGRES_DB=langconfig
POSTGRES_USER=langconfig
POSTGRES_PASSWORD=langconfig_dev
API_KEY_ENCRYPTION_KEY=用 `openssl rand -hex 32` 的输出替换
ENVIRONMENT=development
TEST_DATABASE_URL=postgresql+asyncpg://langconfig:langconfig_dev@localhost:5433/langconfig_test
SQL_POSTGRES_DB=chinook
GOOGLE_REDIRECT_URI=http://localhost:8765/api/auth/google/callback
OLLAMA_BASE_URL=http://localhost:11434
SQL_ECHO=false
RATE_LIMIT_CLEANUP_INTERVAL=300

# ════ USER-ADJUSTABLE（引导默认值 — UI 启动时会覆盖） ════
# 这些值会在首次启动时种入 'runtime' 命名空间。改这里等于改默认值；
# 团队一旦在 Settings 面板里设了值，UI 始终胜出。
LANGCONFIG_WORKSPACE_ROOT=backend/.workspace_data
STORAGE_MODE=db
OLLAMA_EMBED_MODEL=nomic-embed-text:latest
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=langconfig
BACKUP_DIR=./backups
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
ANALYSIS_RECURSION_LIMIT=1000
ANALYSIS_DASHBOARD_TIMEOUT=600
ANALYSIS_CHAT_TIMEOUT=120
MAX_EXECUTION_HISTORY_PER_WORKFLOW=100
EXECUTION_HISTORY_RETENTION_DAYS=90
AUTO_CLEANUP_EXECUTION_HISTORY=true
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS_PER_MINUTE=1000
PERFORMANCE_MONITORING_ENABLED=true
SLOW_REQUEST_THRESHOLD_MS=1000
LOG_SLOW_QUERIES=true
SLOW_QUERY_THRESHOLD=1.0
LOG_ALL_REQUESTS=false

# ════ API KEYS — 不要放进 .env ════
# 所有密钥都在加密的 models.api_keys 设置文档里
# （Settings → Models，或首次启动向导）。上方的 API_KEY_ENCRYPTION_KEY
# 是静态加密这些密钥的 Fernet 主密钥。
```

### 工作区参数

LangConfig 身份系统会在创建/回填时把每个智能体的工作区路径重新烘焙进系统
提示。给种子脚本传值有两种方式：

**A) 环境变量（团队推荐）：**
```bash
export WORKSPACE_ROOT=/Users/<you>/langconfig/backend/outputs
```
智能体解析为 `<WORKSPACE_ROOT>/agents/agent_{id}/`（有自定义 `workspace_path`
的智能体使用根目录下自己的文件夹）。

**B) 或使用默认值**——不传时，工作区管理器自动解析为
`<repo>/backend/outputs/agents/agent_{id}/`。

> `.env` 中的 `LANGCONFIG_WORKSPACE_ROOT` 是引导默认值；Settings 面板可让
> 团队在运行时覆盖。种子跑完后使用的就是 `.env` 里的值（或默认值）——
> 之后可以在 Settings 面板里改。

### 模型 token 上限（上下文 ≠ 单次输出）

当团队看到 `minimax-m3` 或 `deepseek-v4-flash` 的 "1M 上下文支持" 时，那是指
**输入 + 输出** 总预算——即 *上下文窗口*。而 `agent.config.max_tokens` 和
LLM 调用中的 `config.max_tokens` 是**单次回复输出上限**——一个独立的、
更小的数字。混淆两者会导致 API 报 `max_tokens > N` 错误。今天 curl 实测
(2026-08-18) 的实际限制：

| 模型 | 上下文窗口（`max_context`） | 单次输出上限（`max_output`） |
|---|---|---|
| `minimax-m3` (MiniMax-M3) | 1,048,576 | **524,288** |
| `deepseek-v4-flash` | 1,048,576 | **393,216** |
| `deepseek-v4-pro` | 1,048,576 | 32,768 |
| `deepseek-chat` | 1,048,576 | 8,192 |

`models` 设置文档现在同时携带 `max_context` 和 `max_output` 两个字段。在
Settings 面板里设置 `agent.config.max_tokens` 时，**不要超过**模型单次输出上限，
否则 API 会拒绝。设置字段名（`max_tokens`）是单次输出上限；registry 里的
`max_context` 是给 memory/上下文管理用的——两件事分开。

---

## 6. 配置 LLM API Key（在数据库里，不在 `.env` 里）

**所有 API Key 都在数据库里**（`models.api_keys` 设置文档），用
`.env` 上面的 `API_KEY_ENCRYPTION_KEY` 静态加密存储。`.env` 不再是 API
Key 的来源——Settings 面板（或首次启动向导）是唯一的编辑路径。

解析顺序（`config.py::get_api_key_from_db`）：
1. **PostgreSQL** — `models.api_keys` 字段（通过 Settings → Models 设置）
2. **`.env`** — 仅作为首次启动的引导默认值（已不推荐）

团队安装建议用 Settings UI：

1. **首次启动向导**——启动后打开 `http://localhost:1421`，Setup 向导会提示
   输入 API Key + 工作区路径。
2. **启动后 Settings → Models**——添加各提供商 Key（OpenAI / Anthropic /
   DeepSeek / Google / MiniMax / Tavily 等）。

> 仓库的 `env_example` 不含任何 API Key（遵循上方 "API KEYS — 不要放进
> `.env`" 分区）。如果是迁移旧的 `.env`，跑一次性脚本把 Key 移进数据库：
> `uv run python scripts/import_api_keys_to_db.py`（幂等，支持 --dry-run）。
>
> 你需要哪些 Key 取决于智能体使用的模型。种子智能体默认使用 Anthropic
> （`claude-sonnet-4-5`）/ DeepSeek 模型——至少添加与你默认模型匹配的提供商
> Key，例如 `ANTHROPIC_API_KEY` 或 `DEEPSEEK_API_KEY`（Settings → Models）。

---

## 7. 运行数据库种子

在 `backend/` 目录下执行：

```bash
cd backend
WORKSPACE_ROOT=/Users/<you>/langconfig/backend/outputs \
  uv run python scripts/seeds/seed_all.py
```

它会做什么（10 步，全部幂等）：

| 步骤 | 操作 |
|---|---|
| 1 | 创建 Postgres 角色 + 数据库（若缺失） |
| 2 | 创建所有表 + pgvector 扩展 |
| 3 | alembic stamp head |
| 4–6 | 种子设置文档、28 个模型、6 个搜索提供商 |
| 7 | 恢复 58 个工具 |
| 8 | 恢复 44 个深度智能体（与机器无关的 dump） |
| **8.5** | **身份回填**——将每个智能体的真实 id + `<WORKSPACE_ROOT>/agents/agent_{id}` + AGENTS.md/CLAUDE.md 烘焙进 `system_prompt` + `agent_docs` |
| 9 | 从 `backend/skills/` 同步 19 个技能 |
| 10 | 创建 `chinook` 示例数据库（尽力而为） |

验证结果（无论你选择什么工作区根目录都能生效）：

```bash
uv run python -c "
from db.database import SessionLocal
from models.deep_agent import DeepAgentTemplate
db = SessionLocal()
a = db.query(DeepAgentTemplate).filter_by(id=1).first()
sp = (a.config or {}).get('system_prompt','')
print('identity:', '## Identity' in sp, '| agent_id baked:', 'Agent ID**: 1' in sp, '| no placeholder:', 'WORKSPACE_BASE' not in sp and '{{' not in sp)
db.close()
"
# 预期输出：identity: True | agent_id baked: True | no placeholder: True
```

> 之后要更改工作区，只需重新运行回填：
> `uv run python scripts/backfill_agent_identity.py --workspace-root <新路径>`

---

## 8. 启动前健康检查

`scripts/health_check.sh` 会在启动完整堆栈**之前**验证 Postgres、API、
数据库连通性和种子数据：

```bash
bash scripts/health_check.sh                 # 默认后端 :8765
BACKEND_PORT=8799 bash scripts/health_check.sh   # 自定义端口
```

预期输出（全部 ✅）：

```
── [1/4] PostgreSQL ───────────────   ✅ PostgreSQL accepting connections on :5433
── [2/4] Backend API ───────────────   ✅ Backend reachable on :8765
── [3/4] Detailed health ──────────    overall: healthy | database: healthy
── [4/4] Seeded data ──────────────    ✅ deep agents in DB: 44
✅ ALL CHECKS PASSED — ready to run:  bash start.sh
```

如果失败，它会为每一步打印修复方法（启动 Postgres → 种子 → 重试）。

> 注意：该脚本需要后端**已经运行**才能检查第 2–4 步。
> 首次启动：先启动一次后端（`bash start.sh --be`），运行检查，再执行
> `bash start.sh` 启动完整堆栈。

---

## 9. 启动完整堆栈

```bash
bash start.sh
```

| 进程 | 地址 | 说明 |
|---|---|---|
| 后端（FastAPI，2 个 worker） | `http://localhost:8765` | Swagger 文档在 `/docs` |
| 前端（Vite/React） | `http://localhost:1421` | VS Code 风格 IDE 外壳 |
| PostgreSQL | `:5433`（docker）/ `:5432`（原生） | |

常用变体：

```bash
bash start.sh --be    # 仅后端（前端保持运行）
bash start.sh --fe    # 仅前端
```

首次登录：Setup 向导会询问你的 API Key + 工作区路径——这里输入的工作区应与
第 5 步的 `WORKSPACE_ROOT` 一致，这样烘焙进智能体的身份指向运行时使用的
同一个文件夹。

---

## 故障排查

| 症状 | 修复 |
|---|---|
| `psycopg ... connection refused :5432/:5433` | Postgres 未启动 → 第 1 步（`docker compose up -d postgres` / `brew services start postgresql@16`） |
| 种子第 1 步打印手动 CREATE ROLE 说明 | 应用用户无法以超级用户连接 → 运行它打印的两条 `psql` 命令，然后重新运行 `seed_all.py` |
| 健康检查后 `deep agents: 0` | 运行第 7 步；确认 `WORKSPACE_ROOT` 已导出 |
| 智能体 prompt 中出现 `WORKSPACE_BASE/` 或 `{{...}}` | 回填未运行 → `uv run python scripts/backfill_agent_identity.py --workspace-root <根目录>` |
| 前端 :1421 空白页 | `npm install` 然后 `bash start.sh --fe` |
| API Key 不生效 | 在 Settings → Models 中添加（数据库，加密）；确认 `.env` 中已设置 `API_KEY_ENCRYPTION_KEY` |
