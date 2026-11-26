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

echo "== 1/7 预检（仓库、分支、是否脏）"
git remote get-url origin
BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "   branch: $BRANCH"
[ "$BRANCH" = "main" ] || { echo "!! 当前不是 main，先自己确认要更新哪条分支"; exit 1; }
if [ -n "$(git status --porcelain)" ]; then
    echo "!! 工作树有未提交改动，未做任何事。看这几行再决定（stash / commit / 放弃）："
    git status --short | head -20
    exit 1
fi
BEFORE=$(git rev-parse --short HEAD); echo "   HEAD before: $BEFORE"

echo "== 2/7 拉取"
git fetch --all --prune
git pull --ff-only
AFTER=$(git rev-parse --short HEAD); echo "   HEAD after:  $AFTER"

echo "== 3/7 后端依赖（uv sync）"
cd ~/langconfig/backend && uv sync -q && echo "   ok"

echo "== 4/7 前端 build（后端托管 dist/）"
cd ~/langconfig
if [ -f package-lock.json ]; then npm ci --silent 2>/dev/null || npm install --silent; else npm install --silent; fi
npm run build >/tmp/lc_build.log 2>&1 && tail -2 /tmp/lc_build.log || { echo "!! 前端 build 失败，见 /tmp/lc_build.log"; tail -20 /tmp/lc_build.log; exit 1; }

echo "== 5/7 平台库增量 seed（工具行存的是代码副本，必须 refresh）"
cd ~/langconfig/backend
.venv/bin/python scripts/seeds/in/seed_all.py 2>&1 | tail -3
.venv/bin/python scripts/seeds/in/seed_builtin_tools.py --refresh 2>&1 | tail -2

echo "== 6/7 校验：库里的 agents/tools/skills 是否等于已提交快照"
.venv/bin/python scripts/seeds/out/export_baseline.py --check 2>&1 | tail -12

echo "== 7/7 重启并验收"
if systemctl list-unit-files 2>/dev/null | grep -q '^langconfig\.service'; then
    sudo systemctl restart langconfig && sleep 3 && systemctl is-active langconfig
else
    echo "   没有 langconfig.service：这台机器可能用 start.sh/screen 起的，请自己重启后端"
fi
code=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/docs || true)
echo "   GET /docs → ${code:-无响应}"
echo "   HEAD: $(cd ~/langconfig && git rev-parse --short HEAD)"
REMOTE_SCRIPT

if [ "$PRINT" = "1" ]; then
    printf '%s\n' "$REMOTE"
    exit 0
fi

[ -n "$HOST" ] || { echo "usage: bash scripts/update_host_from_git.sh <user@host> [--port 22] [--key path]" >&2
                    echo "       bash scripts/update_host_from_git.sh --print" >&2; exit 2; }

SSH_OPTS=(-p "$PORT" -o ConnectTimeout=12 -o StrictHostKeyChecking=accept-new)
[ -n "$KEY" ] && SSH_OPTS+=(-i "$KEY")

echo "== 更新 ${HOST}（port ${PORT}）—— 下面每一步的输出来自远端"
printf '%s\n' "$REMOTE" | ssh "${SSH_OPTS[@]}" "$HOST" 'bash -s'
