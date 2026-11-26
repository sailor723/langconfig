#!/usr/bin/env bash
# Update ONE host that runs this repo **from git**: pull → deps → build → reseed → restart → verify.
#
#   bash scripts/update_host_from_git.sh <user@host> [--port 22] [--key <ssh-key>]
#   bash scripts/update_host_from_git.sh --print          # 只打印远端要跑的脚本，不连机器
#
# 与 `.team_deploy/upgrade_host.sh`（团队 zip 流程）的分工：
#   * 这个脚本假设那台机器是自己 `git clone` 的仓库 —— 改动只落在 tracked 文件上，
#     它的 `.env`、`backend/outputs/`、业务库都不动；
#   * zip 流程会额外 dropdb/restore 业务库，是另一种更重的操作，不要混用。
#
# 两处顺序不能换：
#   1. 工具行里存的是**代码副本**（`tools/native_impl.py` 的内容被嵌进 tool 行）。改了工具却
#      不 `seed_builtin_tools.py --refresh`，进程里跑的还是旧代码 —— 这次 `db_query_langgraph`
#      与 `ontology_*` 的门就是对不上的那种"改了没生效"。
#   2. 前端是从源码 build 到 `dist/`、再由后端（:8765）托管的，所以 build 要在重启之前。
set -euo pipefail

HOST=""; PORT=22; KEY=""; PRINT=0
while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --key)  KEY="$2"; shift 2 ;;
        --print) PRINT=1; shift ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) HOST="$1"; shift ;;
    esac
done

read -r -d '' REMOTE <<'REMOTE_SCRIPT' || true
set -euo pipefail
cd ~/langconfig

echo "== 1/7 预检（仓库、分支、是否脏、是否快进）"
git remote get-url origin
BRANCH=$(git rev-parse --abbrev-ref HEAD)
UP=$(git rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>/dev/null || true)
echo "   branch: ${BRANCH}   upstream: ${UP:-<none>}"
# 只看**已跟踪**文件的改动：线上的 .env.bak-* 之类 untracked 备份不该挡住一次快进。
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "!! 有未提交的已跟踪改动，未做任何事。看这几行再决定（stash / commit / 放弃）："
    git status --short --untracked-files=no | head -20
    exit 1
fi
BEFORE=$(git rev-parse --short HEAD); echo "   HEAD before: $BEFORE"

echo "== 2/7 拉取"
git fetch --all --prune
if [ -n "${UP}" ]; then
    LOCAL_ONLY=$(git rev-list --count "${UP}..HEAD")
    if [ "${LOCAL_ONLY}" != "0" ]; then
        echo "!! 本地有 ${LOCAL_ONLY} 个 ${UP} 没有的提交 —— 这不是快进，停止（先人工确认）"
        git log --oneline "${UP}..HEAD" | head -10
        exit 1
    fi
fi
git pull --ff-only
AFTER=$(git rev-parse --short HEAD); echo "   HEAD after:  $AFTER"

echo "== 3/7 后端依赖（uv sync）"
# uv 装在 ~/.local/bin 时不在非交互 ssh 的 PATH 里：写成 `cd … && uv sync && echo ok`
# 会在 AND 列表里静默失败（set -e 不管 AND 列表的非末项），上一次就是这样跳过的。
UV=$(command -v uv 2>/dev/null || true)
[ -n "${UV}" ] || UV="$HOME/.local/bin/uv"
if [ -x "${UV}" ]; then
    cd ~/langconfig/backend && "${UV}" sync -q && echo "   ok (${UV})"
else
    echo "!! 找不到 uv（试过 PATH 与 ~/.local/bin）：后端依赖未同步。手动跑："
    echo "   cd ~/langconfig/backend && ~/.local/bin/uv sync"
fi

echo "== 4/7 前端 build（后端托管 dist/）"
cd ~/langconfig
if [ -f package-lock.json ]; then npm ci --silent 2>/dev/null || npm install --silent; else npm install --silent; fi
npm run build >/tmp/lc_build.log 2>&1 && tail -2 /tmp/lc_build.log || { echo "!! 前端 build 失败，见 /tmp/lc_build.log"; tail -20 /tmp/lc_build.log; exit 1; }

echo "== 5/7 平台库增量 seed（工具行存的是代码副本，必须 refresh）"
cd ~/langconfig/backend
.venv/bin/python scripts/seeds/in/seed_all.py 2>&1 | tail -3
.venv/bin/python scripts/seeds/in/seed_builtin_tools.py --refresh 2>&1 | tail -2

echo "== 6/7 校验：库里的 agents/tools/skills 是否等于已提交快照"
# 不阻断：这台机器自己的 agent/工具本来就可能与仓库快照不同，那不算更新失败。
.venv/bin/python scripts/seeds/out/export_baseline.py --check 2>&1 | tail -12 \
    || echo "   (STALE 不阻断；上面的差异是这台机器自己的数据，不是本次更新引入的)"

echo "== 7/7 重启并验收"
# `list-unit-files | grep` 在这台 ECS 上判过空（unit 明明在、服务明明是 active），
# 于是脚本打印"没有 langconfig.service"就跳过了重启 —— 代码更新了、进程还是旧的。
# `systemctl cat` 才是"这个 unit 存在吗"的直接答案。
if systemctl cat langconfig >/dev/null 2>&1; then
    sudo systemctl restart langconfig && sleep 3 && systemctl is-active langconfig
else
    echo "   没有 langconfig.service：这台机器可能用 start.sh/screen 起的，请自己重启后端"
fi
# 重启后进程要 10–40 秒才监听（迁移、worker、调度器都在启动路径上）。
# 立刻 curl 会拿到 000，看着像失败，其实只是还没起来 —— 所以等，而不是判死。
code=""
for i in $(seq 1 20); do
    code=$(curl -sS -o /dev/null -m 3 -w '%{http_code}' http://127.0.0.1:8765/docs 2>/dev/null || true)
    [ "${code}" = "200" ] && { echo "   GET /docs → 200（约 $((i * 3)) 秒起来）"; break; }
    sleep 3
done
[ "${code}" = "200" ] || echo "   GET /docs → ${code:-无响应}（60 秒内没起来，看 journalctl -u langconfig -n 50）"
echo "   HEAD: $(cd ~/langconfig && git rev-parse --short HEAD)"
REMOTE_SCRIPT

if [ "$PRINT" = "1" ]; then
    printf '%s\n' "$REMOTE"
    exit 0
fi

[ -n "$HOST" ] || { echo "usage: bash scripts/update_host_from_git.sh <user@host> [--port 22] [--key path]" >&2
                    echo "       bash scripts/update_host_from_git.sh --print" >&2; exit 2; }

SSH_OPTS=(-p "${PORT}" -o ConnectTimeout=12 -o StrictHostKeyChecking=accept-new)
[ -n "${KEY}" ] && SSH_OPTS+=(-i "${KEY}")
# 额外选项，空格分隔。典型用法（写不了 known_hosts 的一次性环境）：
#   SSH_EXTRA="-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no" bash scripts/update_host_from_git.sh …
# shellcheck disable=SC2206
[ -n "${SSH_EXTRA:-}" ] && SSH_OPTS+=(${SSH_EXTRA})

echo "== 更新 ${HOST}（port ${PORT}）—— 下面每一步的输出来自远端"
printf '%s\n' "$REMOTE" | ssh "${SSH_OPTS[@]}" "$HOST" 'bash -s'
