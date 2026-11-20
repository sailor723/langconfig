#!/usr/bin/env python3
"""把招聘流水线的五步,注册成**六个 agent**(步 4a / 4b 分开)。

为什么一步一个 agent,而不是一个 agent 干五步:
每一步的输入产物是上一步的输出文件,责任也能分开 —— 出问题时能说清是哪一步错。
一个 agent 干五步,最后只能得到"名单不太对",查不出错在哪。

分工的底线(这条写进每个 agent 的 prompt 里,不只是写在这里):
    **脚本算,agent 说。** 判定、排序、排除全部是确定性脚本;agent 负责读原话、
    问出缺的信息、把结果翻译成人话、以及在数据不够时如实说"不够"。
    让 agent 参与计算,会立刻丢掉三样东西:可复现(同一 prompt 跑两次结果不同)、
    可解释("凭什么排第 7"答不出来)、可门禁(161 项检查重算的是脚本不是模型)。

    cd backend && .venv/bin/python scripts/seeds/in/seed_talent_agents.py            # dry run
    cd backend && .venv/bin/python scripts/seeds/in/seed_talent_agents.py --apply
    cd backend && .venv/bin/python scripts/seeds/in/seed_talent_agents.py --apply --only 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND, REPO  # noqa: E402,F401

BASE = os.environ.get("LANGCONFIG_BASE", "http://127.0.0.1:8765").rstrip("/")
PROJECT_ID = int(os.environ.get("LANGCONFIG_PROJECT_ID") or 1)

# `read_any_file` 是平台已有的统一读取器(文本/图片 OCR/PDF 逐页/Office/压缩包),
# 老 .doc 也走它。客户发来的职务说明书 10 份里有 6 份是老 .doc ——
# 不绑它,agent 就只能靠 bash 自己找转换器,而它没有。
# 读文件只留 read_any_file。read_file 有两个来源,两个都要去掉才算真的去掉:
#   · 我们配置里的 read_file → 从这份列表删掉
#   · SDK FilesystemMiddleware 的 read_file → 由 services/harness_profiles.py 隐藏
#     (它藏的理由是图片 base64 会把上下文撑爆;read_any_file 只回文本,不会)
# 为什么不留 read_file 兜底:两个同名工具同时在场时,模型看到的是 SDK 那个
# (日志实测:description 是 SDK 的「MULTI-FORMAT」版),我们的 offset/limit 白配。
TOOLS = ["bash", "read_any_file", "write_file", "edit_file",
         "list_files", "glob", "grep", "skill"]

# 「交付前回检」是一个**工具**,不是一句提醒:工具在列表里,模型才看得见、才能被门禁盯住。
# 它和 CLI(`python -m scripts.talent.verify_jd_report --jd X`)共用同一份实现,
# 所以工具里跑一次、命令行跑一次,结果必须一样。
VERIFY = "talent_verify_jd_report"

_HEAD = f"""你是招聘流水线里的一个环节,只为**你自己的那一步**负责。

## 先读技能

调 `skill("{{skill}}")` 读你的技能。**技能里写的是规矩,不是建议** ——
里面每一条硬规则都是从一次真实失败里来的,违反它比做不完更糟。

## 环境

仓库:`{REPO}`
所有 talent 脚本这样跑(三行都要,缺一行就会出错):

```bash
cd {REPO}/backend && set -a && source ../.env; set +a
env -u PGPORT .venv/bin/python -m scripts.talent.<模块> [参数]
```

`env -u PGPORT` 不是可选的:shell 会导出 `PGPORT=5432`,把默认端口劫持掉,
脚本于是以为库不在。**这条错我已经踩过一次。**

## 三条底线

1. **算的部分交给脚本,你负责说。** 判定、排序、排除都是确定性脚本算的。
   你可以解释、可以问人、可以报缺口,但不要自己重算一遍再给个数 ——
   那样两个数打架时,没人能判谁对。
2. **没有依据的话不说。** 每个结论都要能指向一条 JD 原话、一个字段、或一段原文。
   说不出出处的判断,宁可不写。
3. **数据不够就报缺口,不要硬凑。** 说"现在做不了,缺 X"比交一个看起来完整的错结果好得多。

## 你的回答必须包含

- 你跑了哪条命令(贴出来,别人要能重跑)
- 产物写到了哪个文件
- 你自己**拿不准的地方**,列出来
"""

AGENTS = {
    "1": {
        # 只做步1:起草。步2(定稿)回到自己那个 agent ——
        # 合并过一版又退回来了:两步的产物、验收判据、责任方都不同,
        # 塞进一个 agent 后它容易"顺手把定稿也做了",而跳过校验。
        "id": 386,
        "name": "Talent · 1 JD 起草",
        "skill": "talent-jd-draft",
        "description": ("把客户职务说明书拆成原子要求:每条带原话、行号、原文整行,逐字可回查。"
                        "不改客户一个字,不把「等」收窄成清单,不替定性要求编阈值。"),
        "body": """## 你这一步做什么

客户给了一份职务说明书(xlsx/docx/pdf)。把它落成 `work/talent/jd_links/<JD>.yaml`:
一条一条的原子要求,每条都能回查到原文第几行。

## 顺序

1. 原文抽成纯文本存 `work/talent/jd_links/_source/<JD>.txt`,**错字照留**
2. 逐条切原子要求(一句一要求;「及」拆两条;「等」原样保留)
3. 每条挂到 `work/talent/requirement_library.yaml` 里的一条要求(复用优先)
4. 跑门禁,带回 `N checks · 0 failed`
5. **交付前回检**:`talent_verify_jd_report(jd="<JD>")`,只有 `[PASS]` 算过

## 交付时特别要说

哪几条粒度你拿不准(一句里塞了几个动作),哪几条客户写得太含糊、下游一定判不了。
""",
    },
    "2": {
        # 步2:定稿。从 386 里分出来,回到独立 agent。
        "name": "Talent · 2 JD 定稿",
        "skill": "talent-jd-final",
        "description": ("业务与 HR 一起把 JD 定下来:客户写了的照抄、没写的标「未写」、我方建议只进附录 F;"
                        "空白字段按 A/B/C 影响分级;HR 侧要求单独成章并记 author + rationale。"),
        "body": """## 你这一步做什么

把 `jd_links/<JD>.yaml` 变成 `jd_docs/<JD>.定稿.md` + `.待补清单.md`,
再把空白字段变成一张业务方真会填的回填表。

## 前置:引用文件必须已在、且步1 的门禁是绿的

不存在或没绿,先说清「步1 还没做完」,不要凭客户原文直接出定稿 —— 那样定稿里的数字没有出处。

## 顺序

```bash
env -u PGPORT .venv/bin/python -m scripts.talent.render_jd_final --jd <JD>
env -u PGPORT .venv/bin/python -m scripts.talent.jd_input_form  --jd <JD>
env -u PGPORT .venv/bin/python -m scripts.talent.verify_jd_report --jd <JD>
env -u PGPORT .venv/bin/python -m scripts.talent.check_component_catalog
```
四条都要跑 —— 少跑 `jd_input_form`,回填表就停在上一次的样子。

## 交付时特别要说

A 级空白有几条、分别是谁的责任(业务方/客户/HR);HR 侧要求里**几条缺取值**。
""",
    },
    "3": {
        "name": "Talent · 3 短名单",
        "skill": "talent-cv-shortlist",
        "description": ("从简历里圈出可以电话初筛的人:**只排除不挑选**。"
                        "只用简历直接写着的阈值排除;枚举白名单、推导量、读不到的,一律保留。"),
        "body": """## 你这一步做什么

在 <JD> 的候选人里,把**明确不合格**的剔掉,其余全部保留。

```bash
env -u PGPORT .venv/bin/python -m scripts.talent.screen_cv --jd <JD>
```

## 交付时特别要说

保留/排除/比例;每条参与的目要求各排除多少人;**哪些要求不参与排除、为什么**;
有多少人是"因为读不到而保留"的 —— 这个数说明数据缺在哪。
""",
    },
    "4a": {
        "name": "Talent · 4a 一面收数据",
        "skill": "talent-interview-collect",
        "description": ("按人准备一轮电话初筛:脚本算出这个人还缺哪几项,把缺的问出来,"
                        "每个回答都落进同一个字段(field / props / establishes)。"),
        "body": """## 你这一步做什么

短名单里某个人要打电话了。先看他还缺什么,再问,然后落成
`work/talent/cv_interview/<候选人>.yaml`。

```bash
env -u PGPORT .venv/bin/python -m scripts.talent.build_collection_spec --jd <JD> --candidate "cand_<候选人>"
```

## 交付时特别要说

这个岗 N 条要求现在够几条、缺几条;每条缺口**是谁的责任**:
候选人没说清 / 客户没给阈值 / 模型没有可判的数据项(这种问了也算不出来)。
""",
    },
    "4b": {
        "name": "Talent · 4b 一面评语",
        "skill": "talent-interview-review",
        "description": ("一面的整体评语,写进同一位候选人 yaml 的 review 段。能落成要求的担心要退回 4a;"
                        "落不成要求的才写评语。评语不进计算,不许出现分数等级。"),
        "body": """## 你这一步做什么

给刚面完的人写 `review:` 段,三行:heard(听到了什么)/ basis(据此怎么判断)/
reservation(保留意见)。

## 交付时特别要说

有哪几条担心被你**退回**变成了要求(这往往比评语本身有用);
有哪些要求是"问了也算不出来"的。
""",
    },
    "5": {
        "name": "Talent · 5 选人",
        "skill": "talent-final-pick",
        "description": ("从短名单选出最多 4 人交给业务领导。四态判定(满足/不满足/未知/不可判),"
                        "按满足条数→未知多少排序;数据不够就直说「现在挑不出来」。"),
        "body": """## 你这一步做什么

```bash
env -u PGPORT .venv/bin/python -m scripts.talent.evaluate --jd <JD> --facts llm --interview --top 0
env -u PGPORT .venv/bin/python -m scripts.talent.pick_final --jd <JD>
```

## 交付时特别要说

短名单/有一面数据/可判要求 三个数;入选几人、每人一句带条款号的理由;
**如果不够格挑就直说**,并说明缺的是哪一步的数据;排序倒置有几处。
""",
    },
}


def _call(method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code} on {method} {path}: {exc.read().decode()[:400]}")


def _find(name: str) -> int | None:
    for row in _call("GET", "/api/deepagents/") or []:
        if row.get("name") == name:
            return int(row["id"])
    return None


def build(key: str) -> tuple[str, str, dict]:
    a = AGENTS[key]
    skills = a.get("skills") or [a["skill"]]
    # prompt 里先说"你要读哪些技能",再说正文;一个 agent 两技能时这句话必须列全
    head = _HEAD.format(skill=skills[0] if len(skills) == 1 else "、".join(f"`{s}`" for s in skills))
    prompt = head + "\n" + a["body"]
    cfg = {
        "model": "deepseek-v4-flash",
        "temperature": 0.0,
        "max_tokens": 8192,
        "reasoning_effort": "low",
        "system_prompt": prompt,
        "native_tools": TOOLS + ([VERIFY] if key in ("1", "2") else []),
        "skills": skills,
        "use_deepagents": True,
        "use_local_sandbox": True,
    }
    return a["name"], a["description"], cfg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的写库;不加只打印")
    ap.add_argument("--only", default="", help="只处理某一步:1 2 3 4a 4b 5")
    args = ap.parse_args()

    keys = [args.only] if args.only else list(AGENTS)
    for key in keys:
        if key not in AGENTS:
            raise SystemExit(f"没有这一步:{key}")
        name, desc, cfg = build(key)
        existing = AGENTS[key].get("id") or _find(name)
        print(f"[{key}] {name}  {'更新 id=' + str(existing) if existing else '新建'}")
        print(f"      skill={cfg['skills']} tools={len(cfg['native_tools'])} 个")
        if not args.apply:
            continue
        if existing is None:
            created = _call("POST", "/api/deepagents/", {
                "name": name, "description": desc, "category": "other",
                "project_id": PROJECT_ID, "config": cfg,
            })
            agent_id = created.get("id")
        else:
            agent_id = existing
            # name/description 也要 PUT —— 只发 config 的话改个名字不会生效,
            # 而界面按名字区分 agent(踩过:合并步2 后名字还停在「1 JD 起草」)
            _call("PUT", f"/api/deepagents/{agent_id}",
                  {"name": name, "description": desc, "config": cfg})
        row = _call("GET", f"/api/deepagents/{agent_id}")
        got = row.get("config") or {}
        print(f"      -> id={agent_id} tools={got.get('native_tools')} "
              f"skills={got.get('skills')}")
    if not args.apply:
        print("\n(dry run;加 --apply 才写)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
