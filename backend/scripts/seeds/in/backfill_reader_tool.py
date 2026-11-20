#!/usr/bin/env python3
"""给"读不了文件"的 agent 补绑 `read_any_file`。

为什么会有一批读不了文件的 agent:
    `services/harness_profiles.py` 把 SDK 的 `read_file` 从 deep-agent 的工具表里藏掉了
    (理由很硬:SDK 的 read_file 把图片以 base64 塞进**工具消息**,1.5 MB 的 PNG 变成
    ~146 万 token,请求直接 400)。藏掉之后,模型本该改用 `read_any_file`。
    但 `read_any_file` 不在 `DEFAULT_NATIVE_TOOLS` 里 —— 它只有**显式绑定**才有。
    于是凡是"没有显式绑 read_any_file"的 agent,就一个读取工具都没有了。
    实测:17 个 agent 处于这个状态,`ls`/`glob`/`grep` 还在,`execute` 也能 cat,
    但工具描述里写着「别用 cat,用 read_file」—— 一条指向不存在工具的指引。

这个脚本只做一件事:把缺的补上。**不动其它任何配置**。

    cd backend && .venv/bin/python scripts/seeds/in/backfill_reader_tool.py           # 只看
    cd backend && .venv/bin/python scripts/seeds/in/backfill_reader_tool.py --apply   # 真写

幂等:已经有 read_file 或 read_any_file 的 agent 跳过 —— 有 read_file 的说明它显式绑了
我们的原生版(带 offset/limit),不算摸黑,不必动。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("LANGCONFIG_BASE", "http://127.0.0.1:8765").rstrip("/")
READER = "read_any_file"


def _call(method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code} on {method} {path}: {exc.read().decode()[:300]}")


def tools_of(row: dict) -> list[str]:
    return list((row.get("config") or {}).get("native_tools") or [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真写库;不加只打印")
    args = ap.parse_args()

    rows = _call("GET", "/api/deepagents/") or []
    blind, ok_rf, ok_raf = [], 0, 0
    for row in rows:
        t = tools_of(row)
        if READER in t:
            ok_raf += 1
        elif "read_file" in t:
            ok_rf += 1
        else:
            blind.append(row)

    print(f"agent 总数 {len(rows)}")
    print(f"  已绑 {READER}: {ok_raf}")
    print(f"  绑了 read_file(原生版,带 offset/limit): {ok_rf}")
    print(f"  **两个都没有 → 读不了文件**: {len(blind)}")
    if not blind:
        print("\n没有要补的。")
        return 0

    print()
    for row in sorted(blind, key=lambda r: r["id"]):
        cfg = dict(row.get("config") or {})
        print(f"  {row['id']:4d} {row['name'][:40]:42s} "
              f"model={cfg.get('model') or '(未设)'} tools={len(tools_of(row))}")
        if args.apply:
            cfg["native_tools"] = tools_of(row) + [READER]
            _call("PUT", f"/api/deepagents/{row['id']}", {"config": cfg})
            got = _call("GET", f"/api/deepagents/{row['id']}")
            assert READER in tools_of(got), f"{row['id']} 写入后仍没有 {READER}"
            print(f"        → 已补 {READER}(现 {len(tools_of(got))} 个工具)")

    if not args.apply:
        print("\n(dry run;加 --apply 才写)")
    else:
        print(f"\n补完 {len(blind)} 个。**要重启后端**(或等下次装配)才对新建会话生效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
