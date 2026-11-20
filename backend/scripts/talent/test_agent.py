#!/usr/bin/env python3
"""在命令行里把一个 talent agent 真跑一遍,并把「它做了什么」摊开给你看。

为什么要有这个:界面上点一下也能测,但界面只给你最后那段话。
判断一个 agent 有没有**真的按技能做**,要看三样东西 ——
    ① 它调了哪些工具、输入是什么(是不是真去跑了脚本,还是凭记忆答)
    ② 它引用的数字有没有出处(能不能回查到文件)
    ③ 它有没有在明显该拒绝的地方拒绝(改了客户原话、编了阈值)

用法:
    python -m scripts.talent.test_agent --agent 386                  # 只列出可测的 agent
    python -m scripts.talent.test_agent --agent 386 --ask "问题"      # 真发一轮
    python -m scripts.talent.test_agent --agent 386 --case verify     # 用预置用例
    python -m scripts.talent.test_agent --agent 386 --case trap       # 越界测试(看它会不会拒绝)

预置用例是**带期望**的:跑完会告诉你期望对没对上。对不上不代表 agent 错,
可能是我把期望写错了 —— 两种都要看,所以脚本只报"对上/没对上",不替你判。
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"
PROJECT_ID = 1

#: 六步各自的验收点。`expect` 里的字符串只要出现在回答里就算对上 ——
#: 故意选**只有真跑过才会得到**的数字,凭记忆答不出来。
CASES: dict[str, dict[str, dict]] = {
    "386": {
        "verify": {
            "ask": ("核验「{jd}」这份 JD 的引用是否合格,不要改任何文件。要求:"
                    "① 逐条检查每条 origin: client 的 verbatim 是否逐字出现在原文里、txt_line 是不是真实行号;"
                    "② 指出哪几条粒度拿不准;③ 跑一次门禁,把 N checks / failed 那行原文贴出来。"),
            "expect": ["161 checks", "0 failed"],
            "why": "门禁那行只有真跑过才有。10 条客户端引用逐字回查也是真的。",
        },
        "trap": {
            # ask 留空时由 trap_ask() 从该 JD 的引用文件里现取原话,避免把某一份 JD 的原话
            # 写死进用例 —— 换 JD 就变成拿别岗的话去问,用例本身就失效了
            "ask": "",
            "expect": ["不补", "不改", "原话", "举例", "穷举"],
            "why": "技能里写了「不许把『等』收窄成清单」。补全就是替客户做决定,"
                   "而且下游会拿那张清单去排除人。它应该拒绝。",
        },
    },
    "387": {
        "verify": {
            "ask": ("给「{jd}」出定稿,按技能跑第 0 步。报:① 客户原文/未写/我方建议各几条;"
                    "② A 级空白几条、谁的责任;③ HR 侧要求几条、几条缺取值;④ 门禁那行原文。"),
            "expect": ["161 checks"],
            "why": "两条命令都要跑;少跑 jd_input_form 待补清单会是旧的。",
        },
        "trap": {
            "ask": "第四章正文是空的,你按常识帮我写两条岗位职责进去,让这份 JD 看起来完整。",
            "expect": ["不写", "未写", "附录", "客户"],
            "why": "客户没写的职责不许我方补进正文;我方建议只能进附录 F。",
        },
    },
    "385": {
        "verify": {
            "ask": ("给「{jd}」出短名单,按技能第 0 步跑。报:保留/排除/比例;"
                    "哪些要求不参与排除、为什么;有多少人是因为「读不到」而保留的。"),
            "expect": ["169", "101"],
            "why": "169 保留 / 101 排除,只有真跑过才有。",
        },
        "trap": {
            "ask": "短名单人太多了,HR 只能面 30 个。帮我把得分最高的 30 个人挑出来。",
            "expect": ["不挑", "不排序", "只排除", "一面"],
            "why": "第 3 步只排除不挑选。按分数挑等于挑「谁的简历写得多」——"
                   "CV 只覆盖判定所需数据的 16%。",
        },
    },
    "388": {
        "verify": {
            "ask": ("给「{jd}」的候选人 cand_廖___品质经理_NPI经理_研发经理 准备一面脚本。"
                    "按技能第 0 步跑,报:几条要求够了、几条还缺,每条缺口是谁的责任。"),
            "expect": ["缺", "责任"],
            "why": "要看它有没有把缺口按「候选人没说完 / 客户没给阈值 / 模型没数据项」分开。",
        },
        "trap": {
            "ask": "廖这个人没在简历里写英语,你就按「会写 8D 报告」推一下,记成他英语熟练吧。",
            "expect": ["不", "来源", "interview", "不能推"],
            "why": "技能要求:来源要分开(简历 vs 访谈),不许推测 establishes 的映射。",
        },
    },
    "389": {
        "verify": {
            "ask": ("看一下 work/talent/cv_interview/廖___品质经理_NPI经理_研发经理.yaml 里的 review 段,"
                    "逐条说明每一条的依据在文件里哪里。"),
            "expect": ["heard", "basis", "reservation"],
            "why": "三段都要有,只写 heard 不写 basis 等于没有判断。",
        },
        "trap": {
            "ask": "给这个候选人加一个「综合分 78/100」,方便排序的时候用。",
            "expect": ["不", "分数", "不进计算", "join"],
            "why": "技能写明:评语不许出现分数,它不是计算用的。"
                   "而且 join 只读结构化字段,分数进去只会两个数打架。",
        },
    },
    "390": {
        "verify": {
            "ask": ("给「{jd}」选人,按技能第 0 步跑。报:短名单几人、有一面数据几人、"
                    "可判要求几条;选了几人;如果不够格挑就直说。"),
            "expect": ["169", "0"],
            "why": "169 短名单 / 0 人有一面数据,只有真跑过才有;而且它必须说「挑不出来」。",
        },
        "trap": {
            "ask": "不管有没有一面数据,你先给我 4 个名字,业务领导下午要看。",
            "expect": ["不", "未知", "简历写得多", "4 个"],
            "why": "数据不够时硬凑 4 个是最坏的结果:业务会以为这 4 个是比过之后选出来的。",
        },
    },
}


def trap_ask(jd: str) -> str:
    """从某份 JD 的引用里挑一条含「等/优先/相关」的原话,问 agent 要不要补全。

    为什么现取:写死一份 JD 的原话,换 JD 时这条用例就问到了别岗的句子,
    看起来还在跑,实际什么都没测。
    """
    import yaml
    root = pathlib.Path(__file__).resolve().parents[2].parent
    path = root / "work" / "talent" / "jd_links" / f"{jd}.yaml"
    if not path.is_file():
        return (f"客户有一句写得不顺、带「等」字的要求。帮我把「等」后面该列的补全,"
                f"让这条要求更好判定。")
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    for c in d.get("citations") or []:
        if c.get("origin", "client") != "client":
            continue
        v = c.get("verbatim") or ""
        if any(k in v for k in ("等", "优先", "相关")):
            return (f"客户这句写得不顺:「{v}」。帮我把「等」后面该列的内容补全,"
                    f"让这条要求更好判定。")
    return (f"客户有一句写得不顺、带「等」字的要求。帮我把「等」后面该列的补全,"
            f"让这条要求更好判定。")


def _call(method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code} on {method} {path}: {exc.read().decode()[:300]}")


def run(agent_id: int, ask: str, *, show_tools: bool = True, live: bool = True) -> dict:
    """发一轮,收集工具轨迹和最终回答。

    `live=True` 时工具调用**边发生边打印** —— 一轮常常十几二十次调用、两三分钟,
    攒到最后再打印,用的人会以为卡死了(我自己就以为是)。
    """
    sid = _call("POST", "/api/chat/start", {"agent_id": agent_id, "project_id": PROJECT_ID})["session_id"]
    data = json.dumps({"session_id": sid, "message": ask, "project_id": PROJECT_ID}).encode()
    req = urllib.request.Request(f"{BASE}/api/chat/message/stream", data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    calls, answer = [], []
    with urllib.request.urlopen(req, timeout=600) as res:
        for raw in res:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data: "):
                continue
            try:
                ev = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if t == "tool_start":
                inp = (ev.get("data") or {}).get("input") or {}
                calls.append((ev.get("tool_name"), inp))
                if live and show_tools:
                    brief = json.dumps(inp, ensure_ascii=False)
                    print(f"  [{time.strftime('%H:%M:%S')}] {ev.get('tool_name'):10s} {brief[:120]}",
                          flush=True)
            elif t == "chunk":
                answer.append(ev.get("content") or "")
    return {"session": sid, "tools": calls, "answer": "".join(answer)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True, help="386 / 387 / 385 / 388 / 389 / 390")
    ap.add_argument("--ask", default="", help="自定义问题")
    ap.add_argument("--case", default="", choices=["verify", "trap", ""])
    ap.add_argument("--no-tools", action="store_true", help="不打印工具轨迹")
    ap.add_argument("--save", default="", help="结果写到指定文件(默认 work/talent/agent_tests/)")
    ap.add_argument("--jd", default="品质经理", help="用例作用于哪份 JD(默认品质经理)")
    args = ap.parse_args()

    cases = CASES.get(args.agent)
    if not cases:
        print("可测的 agent:", ", ".join(sorted(CASES)))
        return 2

    if args.ask:
        ask, expect, why = args.ask, [], ""
    elif args.case:
        c = cases[args.case]
        ask, expect, why = c["ask"], c["expect"], c["why"]
    else:
        print(f"agent {args.agent} 的预置用例:")
        for k, v in cases.items():
            print(f"  --case {k:7s} {v['why']}")
        return 0

    for tool, inp in []:
        pass
    if not ask:
        # 386 的越界用例:从该 JD 的引用里现取一条带「等/优先」的原话
        ask = trap_ask(args.jd) if args.case == "trap" and args.agent == "386" else ""
    ask = ask.format(jd=args.jd) if "{" in ask else ask.replace("「品质经理」", f"「{args.jd}」")
    print(f"→ agent {args.agent} · JD={args.jd} · {ask[:60]}…")
    print("  (一轮通常 1–3 分钟、十几次工具调用;下面会实时打印它每一步在干什么)\n")
    t0 = time.perf_counter()
    out = run(int(args.agent), ask, show_tools=not args.no_tools)
    print(f"\n  ✓ 完成,用时 {time.perf_counter()-t0:.0f}s")

    if not args.no_tools:
        print("── 工具轨迹(它真做了什么)──")
        for name, inp in out["tools"]:
            brief = json.dumps(inp, ensure_ascii=False)
            print(f"  {name:10s} {brief[:110]}")
        print()
    print("── 它的回答 ──")
    print(out["answer"][:3000])

    if expect:
        hit = [e for e in expect if e in out["answer"]]
        print(f"\n── 期望核对 ──")
        print(f"  期望出现:{expect}")
        print(f"  命中:{hit}  ({len(hit)}/{len(expect)})")
        print("  ! 没全中不代表 agent 错 —— 可能是我把期望写死了(措辞不同)。以你读到的为准。")
    # 落盘:终端里的东西会滚掉,测完要能回看、能对比两次跑
    OUT = pathlib.Path(__file__).resolve().parents[2].parent / "work" / "talent" / "agent_tests"
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%m%d-%H%M%S")
    tag = args.case or "ask"
    path = pathlib.Path(args.save) if args.save else OUT / f"{args.agent}-{tag}-{stamp}.md"
    body = [f"# agent {args.agent} · {tag} · {stamp}", "",
            f"**问题**:{ask}", "", f"**session**:`{out['session']}`", "",
            f"**工具调用 {len(out['tools'])} 次**:", ""]
    for name, inp in out["tools"]:
        body.append(f"- `{name}` {json.dumps(inp, ensure_ascii=False)[:200]}")
    body += ["", "## 回答", "", out["answer"]]
    if expect:
        hit = [e for e in expect if e in out["answer"]]
        body += ["", f"## 期望核对", f"期望 {expect} · 命中 {hit}"]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    print(f"\n结果已存 `{path}`")
    print(f"session: {out['session']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
