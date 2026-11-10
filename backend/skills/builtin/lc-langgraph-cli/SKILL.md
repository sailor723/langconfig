---
name: "Langgraph Cli（LangGraph CLI）"
description: >-
  用 langgraph CLI 脚手架、开发、构建或部署 LangGraph 应用时，调用本技能。涵盖 langgraph new、dev、
  build、up、deploy 以及 langgraph.json 配置。
tags:
  - "langgraph"
  - "cli"
  - "langchain-skills"
  - "skills"
triggers:
  - "要用 langgraph CLI 脚手架、开发、构建或部署应用时"
  - "需要写或改 langgraph.json 时"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
  - "skill"
author: "langchain-skills (MIT), adapted for LangConfig"
version: "1.0"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-langgraph-cli/SKILL.md
---

## Instructions（指令）

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/langgraph-cli`（MIT，原样收录于 `vendor/upstream-skills/langchain-skills/skills/langgraph-cli/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


<overview>
`langgraph` CLI 负责 LangGraph 应用的整个生命周期——从脚手架出一个新项目，一直到把它部署到 LangGraph Platform（LangSmith Deployments）。

核心命令：
- **`langgraph new`** — 按模板脚手架出一个项目
- **`langgraph dev`** — 本地运行，支持热重载（不需要 Docker）
- **`langgraph build`** — 构建 Docker 镜像
- **`langgraph up`** — 用 Docker Compose 在本地起服务
- **`langgraph deploy`** — 发布到 LangGraph Platform
- **`langgraph dockerfile`** — 生成 Dockerfile

除 `new` 之外，所有命令都读项目根目录下的 `langgraph.json` 配置文件。
</overview>

## When to use（何时使用）

用户想做下面这些事时，用这个技能：
- 脚手架出一个新的 LangGraph 项目
- 起一个本地开发服务器，或一个像生产的环境
- 构建或部署一个 LangGraph 应用
- 看懂或修改 `langgraph.json` 配置
- 管理 LangSmith Deployments（列出、删除、看日志）

## Installation（安装）

```bash
# Python
pip install 'langgraph-cli[inmem]'   # includes langgraph dev support
pip install langgraph-cli             # without dev server (build/up/deploy only)

# if using UV as package manager
uv add "langgraph-cli[inmem]"       # includes langgraph dev support
uv add langgraph-cli                # without dev server (build/up/deploy only)

# JavaScript
npx @langchain/langgraph-cli         # use on demand
npm install -g @langchain/langgraph-cli  # install globally (available as langgraphjs)
```

## Commands（命令）

### `langgraph new [PATH]`

按模板脚手架出一个新项目。

```bash
langgraph new                          # interactive template selection
langgraph new ./my-agent               # create in specific directory
langgraph new --template agent-python  # skip prompt, use template directly
```

可用模板：`deep-agent-python`、`deep-agent-js`、`agent-python`、`new-langgraph-project-python`、`new-langgraph-project-js`

### `langgraph dev`

起一个本地开发服务器，支持热重载。不需要 Docker。

```bash
langgraph dev                              # default: localhost:2024
langgraph dev --port 8000                  # custom port
langgraph dev --config ./langgraph.json    # explicit config path
langgraph dev --no-reload                  # disable hot reload
langgraph dev --no-browser                 # don't auto-open LangGraph Studio
langgraph dev --host 0.0.0.0              # bind to all interfaces (trusted networks only)
langgraph dev --tunnel                     # expose via Cloudflare tunnel for remote access
langgraph dev --debug-port 5678            # enable remote debugger (requires debugpy)
langgraph dev --n-jobs-per-worker 20       # max concurrent jobs per worker (default: 10)
```

### `langgraph build`

为 LangGraph API 服务器构建 Docker 镜像。

```bash
langgraph build -t my-image                # required: tag the image
langgraph build -t my-image --no-pull      # use locally-built base images
langgraph build -t my-image -c langgraph.json  # explicit config
langgraph build -t my-image --base-image langchain/langgraph-server:0.2.18  # pin base version
```

### `langgraph up`

用 Docker Compose 启动 LangGraph API 服务器（自带 Postgres）。

```bash
langgraph up                               # default port 8123
langgraph up --port 8000                   # custom port
langgraph up --watch                       # restart on file changes
langgraph up --recreate                    # force fresh build (useful for pre-deploy validation)
langgraph up --postgres-uri postgresql://...  # external Postgres
langgraph up --no-pull                     # use local images (after langgraph build)
langgraph up --image my-image              # skip build, use pre-built image
langgraph up -d docker-compose.yml         # add extra Docker services
langgraph up --debugger-port 8124          # serve debugger UI
langgraph up --wait                        # block until services are healthy
```

### `langgraph deploy`

构建并部署到 LangGraph Platform（LangSmith Deployments）。需要 Docker。在 Apple Silicon（M1/M2/M3）上，交叉编译到 `linux/amd64` 还需要 Docker Buildx。

```bash
langgraph deploy                           # deploy, name defaults to directory name
langgraph deploy --name my-agent           # explicit deployment name
langgraph deploy --deployment-type prod    # production deployment (default: dev)
langgraph deploy --tag v1.2.0              # custom image tag (default: latest)
langgraph deploy --deployment-id <id>      # update an existing deployment by ID
langgraph deploy --config ./langgraph.json # explicit config path
langgraph deploy --no-wait                 # don't wait for deployment status
langgraph deploy --verbose                 # show detailed server logs
```

前提：环境变量或 `.env` 里要有 `LANGSMITH_API_KEY`。

`langgraph deploy` 也接受构建相关参数：`--base-image`、`--pull`/`--no-pull`。

#### `langgraph deploy list`

```bash
langgraph deploy list                      # list all deployments
langgraph deploy list --name-contains bot  # filter by name
```

#### `langgraph deploy delete`

```bash
langgraph deploy delete <deployment-id>          # interactive confirmation
langgraph deploy delete <deployment-id> --force  # skip confirmation
```

#### `langgraph deploy logs`

```bash
langgraph deploy logs                                  # runtime logs, last 100
langgraph deploy logs --name my-agent                  # by deployment name
langgraph deploy logs --deployment-id <id>             # by deployment ID
langgraph deploy logs --type build                     # build logs instead of runtime
langgraph deploy logs -f                               # follow/stream logs
langgraph deploy logs --level error                    # filter by level (debug|info|warning|error|critical)
langgraph deploy logs -q "timeout"                     # search filter
langgraph deploy logs --limit 500                      # more entries
langgraph deploy logs --start-time 2026-03-08T00:00:00Z  # time range
```

### `langgraph dockerfile <SAVE_PATH>`

只生成 Dockerfile（可选还生成 Docker Compose 文件），不执行构建。

```bash
langgraph dockerfile ./Dockerfile                      # generate Dockerfile
langgraph dockerfile ./Dockerfile --add-docker-compose # also generate compose + .env + .dockerignore
```

## `langgraph.json` reference（参考）

所有 CLI 命令（`dev`、`build`、`up`、`deploy`）共用的配置文件。默认取当前目录下的 `langgraph.json`。

### Minimal config (Python)（最小配置：Python）

```json
{
    "dependencies": ["."],
    "graphs": {
        "agent": "./my_agent/agent.py:graph"
    },
    "env": "./.env"
}
```

### Minimal config (JavaScript)（最小配置：JavaScript）

```json
{
    "dependencies": ["."],
    "graphs": {
        "agent": "./src/agent.js:graph"
    },
    "env": "./.env"
}
```

### Full config with all keys（写全所有键的配置）

```json
{
    "dependencies": [".", "langchain_openai", "./local_package"],
    "graphs": {
        "agent": "./my_agent/agent.py:graph",
        "retriever": "./my_agent/rag.py:rag_graph"
    },
    "env": "./.env",
    "python_version": "3.12",
    "pip_config_file": "./pip.conf",
    "dockerfile_lines": [
        "RUN apt-get update && apt-get install -y ffmpeg"
    ]
}
```

### Key reference（键说明）

| 键 | 必填 | 说明 |
|-----|----------|-------------|
| `dependencies` | 是 | 依赖数组。`"."` 表示在该位置按 `pyproject.toml`、`setup.py`、`requirements.txt` 或 `package.json` 找本地包。也可以写子目录路径（`"./my_pkg"`）或包名（`"langchain_openai"`）。 |
| `graphs` | 是 | 图 ID 到路径的映射。格式：`./path/to/file.py:variable`（Python）或 `./path/to/file.js:function`（JS）。这个变量必须是一个 `CompiledGraph`，或者一个返回 `CompiledGraph` 的函数。可以配多张图。 |
| `env` | 否 | `.env` 文件的路径（字符串），或者环境变量名到取值的行内映射（对象）。`langgraph dev` 和 `langgraph up` 在本地会用它。`langgraph deploy` 会读这份文件，把里面的变量作为部署的 secret 加上。 |
| `python_version` | 否 | `"3.11"`、`"3.12"` 或 `"3.13"`。默认 `"3.11"`。 |
| `node_version` | 否 | JS 项目使用的 Node.js 版本。 |
| `pip_config_file` | 否 | pip 配置文件的路径，用于自定义包索引。 |
| `dockerfile_lines` | 否 | 额外 Dockerfile 行的数组，追加在基础镜像导入之后。用来装系统包、装二进制，或做自定义初始化。 |

## Typical workflow（典型流程）

1. **脚手架** — 用 `langgraph new` 从模板建一个项目。
2. **配置** — 改 `langgraph.json`：设好依赖，把 `graphs` 指到你编译好的图，加上 `.env`。
3. **开发** — `langgraph dev`，配合热重载在本地快速迭代（不用 Docker，端口 2024）。
4. **验证** — `langgraph up --recreate`，在一个像生产的 Docker 栈里测试（端口 8123，自带 Postgres）。
5. **部署** — `langgraph deploy` 发布到 LangGraph Platform（LangSmith Deployments）。
6. **监控** — `langgraph deploy logs -f` 跟踪运行时日志；`--type build` 看构建日志。

## `langgraph dev` vs `langgraph up`（两者对比）

| 特性 | `langgraph dev` | `langgraph up` |
|---------|----------------|----------------|
| 是否需要 Docker | 否 | 是 |
| 安装 | `pip install 'langgraph-cli[inmem]'` | `pip install langgraph-cli` |
| 主要用途 | 快速开发与测试 | 像生产一样的验证 |
| 状态持久化 | 内存 / pickle 到本地目录 | PostgreSQL |
| 热重载 | 有（默认） | 可选（`--watch`） |
| 默认端口 | 2024 | 8123 |
| 资源占用 | 轻 | 重（服务器、Postgres、Redis 各要起容器） |
| IDE 调试 | 内置 DAP 支持（`--debug-port`） | 容器内调试 |

## Gotchas（坑）

- **`langgraph deploy` 需要 Docker** — 在 Apple Silicon（M1/M2/M3）上，交叉编译到 `linux/amd64` 还需要 Docker Buildx。
- **`langgraph deploy` 只能更新它自己创建的部署** — 通过 LangSmith UI 或 GitHub 集成创建的部署，不能用 `langgraph deploy` 更新，那些要在 UI 里改。
- **`dependencies` 必须把所有包都包含进来** — `langgraph.json` 里的 `dependencies` 数组必须指向你的包配置所在的位置（比如根目录用 `"."`）。真正的包是从那个位置的 `pyproject.toml`、`requirements.txt` 或 `package.json` 解析出来的。
- **`langgraph dev` 不经过 Docker 运行** — 它直接跑在你的环境里。如果你的代码依赖系统包（比如 `ffmpeg`），那这些包必须在本机装好。要验证 Docker 构建，请用 `langgraph up`。
- **JavaScript CLI** — 用 `npx @langchain/langgraph-cli <command>`（用 `npm install -g @langchain/langgraph-cli` 全局装过的话，也可以用 `langgraphjs`）。
- **API key** — `langgraph deploy` 需要 `LANGSMITH_API_KEY`。`langgraph dev` 则是可选的——没有它服务器照样跑，只是 LangSmith 里收不到 trace。也可以通过 `LANGGRAPH_HOST_API_KEY` 或 `LANGCHAIN_API_KEY` 设置。

## This repository's floor（本仓库的底线）

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  一份文档库报告）。后端测试套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能做出的宣称。
  用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句判词，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 脚手架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `ecosystem-primer` 规则——并优先选
  能胜任的最高层。
