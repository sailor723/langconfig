"""Tutorial samples: three business questions a user can CLICK through, and a deterministic reset.

The problem this solves: a guided intake still asks a person to type nine answers before they can see
anything happen. For a first walkthrough that is too much — someone learning the tool should be able to
press a button and watch the whole pipeline (intake → interpretation → declaration → verification →
proposal → apply) run on a question they recognise, then undo it and try their own.

So each sample here is:

* **business answers only** — the exact text a user would have typed (the panel fills them in),
* **the declaration it will produce** (so a second run can tell "already added"),
* **the value(s) it must produce** — the number(s) that make the demo verifiable, not decorative,
* **a reset** that removes the declaration it added, deterministically (see `reset`).

The reset is not "edit the ontology by hand": it finds the metric's declaration block in the installed
files, removes exactly that block, stages the result through the publish channel (compile + gates), and
only then installs it — so a reset is a recorded publish like every other change, with a note saying it
was the tutorial's reset. That is the difference between a demo and a mess.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Each sample is a business question, its answers, the metric it produces and the numbers it must give.
SAMPLES: list[dict] = [
    {
        "id": "damaged-by-route-version",
        "title": "按线路版本看破损箱数",
        "blurb": "把破损箱数按线路版本分开，看「并线」前后货损有没有变差。会跨 站点→行程→线路 两张关联。",
        "ontology_keys": ["logistics"],
        "metric": "damagedBoxesByRouteVersion",
        "answers": {
            "name": "按线路版本看破损箱数",
            "question": "并线前后破损有没有变多？",
            "arithmetic": "把每个站点的破损箱数加起来，按线路版本分开",
            "grain": "一次配送里的一个站点",
            "scope": "全部",
            "dimensions": "按线路版本（v1 是并线前，v2 是并线后）",
            "unit": "箱",
            "expected": "两个版本各几千箱，v2 比 v1 多一千多",
            "purpose": "判断并线有没有让货损变差、要不要调整装载",
        },
        "expect": {"rows": 2, "values": {"v1": "3490", "v2": "4654"}},
        "why_it_is_not_one_table": "破损箱数记在站点上，版本是线路的属性：站点→行程→线路，两跳都由已声明的关联推出来。",
    },
    {
        "id": "baskets-per-1k-km",
        "title": "每千公里漏筐数",
        "blurb": "周转筐的丢失强度：一共丢了几个筐 ÷ 一共跑了多少公里 × 1000。跨颗粒度比率。",
        "ontology_keys": ["logistics"],
        "metric": "basketsMissingPer1kKm",
        "answers": {
            "name": "每千公里漏筐数",
            "question": "每跑一千公里会丢几个筐？",
            "arithmetic": "一共丢了多少个筐 ÷ 一共跑了多少公里，再乘 1000",
            "grain": "一次配送里的一个站点（漏筐是记在站点上的）",
            "scope": "全部",
            "dimensions": "",
            "unit": "个（每千公里）",
            "expected": "一百一十左右",
            "purpose": "看周转筐损失是不是集中在某些线路",
        },
        "expect": {"rows": 1, "values": {"basketsMissingPer1kKm": "112.95050870839799966"}},
        "why_it_is_not_one_table": "分子在站点上，分母是里程——里程记在线路上，每趟按所用线路计一次，JOIN 来自 :routeOf。",
    },
    {
        "id": "temp-excursion-by-vehicle",
        "title": "按车辆看温控超标站点数",
        "blurb": "哪台车的温控超标最多。用到一个已声明的定义类（温控超标站点）+ 站点→行程→车辆 两跳。",
        "ontology_keys": ["logistics"],
        "metric": "tempExcursionStopsByVehicle",
        "answers": {
            "name": "按车辆看温控超标站点数",
            "question": "哪台车温控超标最多？",
            "arithmetic": "数一数温控超标的站点，按车辆分开",
            "grain": "一次配送里的一个站点",
            "scope": "只看温控超标的站点",
            "dimensions": "按车辆（车牌）",
            "unit": "站",
            "expected": "每台车几十站，最高的五十几站",
            "purpose": "判断冷链问题是不是集中在某几台车",
        },
        "expect": {"rows": 60, "values": {"top": "沪A62447=58", "total": "1930"}},
        "why_it_is_not_one_table": "「温控超标」不是一个字段名，是一条公理（:TempExcursionStop）；车牌在车辆上，两跳。",
    },
]


class SampleError(RuntimeError):
    """A sample request that cannot be honoured; the reason is meant for the user."""


def _db():
    from db.database import SessionLocal
    return SessionLocal()


def sample_by_id(sample_id: str) -> dict:
    for s in SAMPLES:
        if s["id"] == sample_id:
            return s
    raise SampleError(f"no sample {sample_id!r} — available: "
                      + ", ".join(s["id"] for s in SAMPLES))


def _declared_metric(key: str, metric: str) -> bool:
    """Is `metric` declared in the installed ontology? (a text scan: the question is about files)"""
    from services import ontology_publish

    folder = ontology_publish.ONTOLOGIES / key
    pattern = re.compile(rf"^:{re.escape(metric)}\s", re.M)
    for path in folder.rglob("*.ttl"):
        if ".staging" in path.parts or ".backup" in path.parts:
            continue
        try:
            if pattern.search(path.read_text(encoding="utf-8")):
                return True
        except (OSError, UnicodeDecodeError):
            continue
    return False


def list_samples(db: Optional[Session] = None, key: Optional[str] = None) -> list[dict]:
    """The samples for this ontology, each marked installed / not, so the panel can offer reset."""
    own = db is None
    db = db or _db()
    try:
        out = []
        for s in SAMPLES:
            if key and key not in s["ontology_keys"]:
                continue
            out.append({
                "id": s["id"],
                "title": s["title"],
                "blurb": s["blurb"],
                "metric": s["metric"],
                "answers": s["answers"],
                "expect": s["expect"],
                "why_it_is_not_one_table": s["why_it_is_not_one_table"],
                "installed": _declared_metric(key, s["metric"]) if key else False,
            })
        return out
    finally:
        if own:
            db.close()


# ────────────────────────────────────────────────────────────── reset
def _strip_block(text: str, metric: str) -> tuple[str, bool]:
    """Remove one declaration block (`:metric a owl:... ; ... .`) and nothing else.

    The block starts at a line that begins with `:metric` and ends at the first line ending with a
    statement terminator (` .`). Turtle statements in these files are one-per-block, so this is exact —
    and the caller re-runs the compiler and the gates afterwards, which is what proves it.
    """
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^:{re.escape(metric)}\s", line):
            start = i
            break
    if start is None:
        return text, False
    end = None
    for j in range(start, len(lines)):
        stripped = lines[j].strip()
        if stripped.endswith(" .") or stripped == "." or stripped.endswith("."):
            end = j
            break
    if end is None:
        raise SampleError(f"could not find the end of the :{metric} block — refusing to cut blindly")
    # swallow one trailing blank line so the file does not accumulate holes
    stop = end + 1
    if stop < len(lines) and lines[stop].strip() == "":
        stop += 1
    return "".join(lines[:start] + lines[stop:]), True


def reset(key: str, sample_id: str, *, actor: str = "tutorial-reset",
          apply_now: bool = True) -> dict:
    """Undo a sample: remove its declaration through the publish channel, then install the result.

    Nothing is edited in place. The removal is staged (compile + gates run on the staging copy) and only
    then installed, so the ledger shows a reset like it shows every other change — with the gate summary
    that made it legal. If the removal leaves a metric that something else referenced (a ratio naming it
    as numerator), the compile gates say so and nothing is installed.
    """
    from services import ontology_publish

    sample = sample_by_id(sample_id)
    if key not in sample["ontology_keys"]:
        raise SampleError(f"sample {sample_id!r} does not apply to ontology {key!r}")
    metric = sample["metric"]

    live = ontology_publish.ONTOLOGIES / key
    if not live.is_dir():
        raise SampleError(f"no installed ontology {key!r}")

    files: dict[str, str] = {}
    for path in sorted(live.rglob("*.ttl")):
        if ".staging" in path.parts or ".backup" in path.parts:
            continue
        rel = str(path.relative_to(live))
        text = path.read_text(encoding="utf-8")
        new_text, removed = _strip_block(text, metric)
        if removed:
            files[rel] = new_text
    if not files:
        return {"ok": False, "reset": True, "already_absent": True, "metric": metric,
                "reason": f":{metric} is not declared in {key} — nothing to reset"}

    staged = ontology_publish.stage(key, files, actor=actor,
                                   note=f"tutorial reset: remove :{metric} (sample {sample_id})")
    report = staged.get("report") or {}
    result = {
        "ok": bool(staged.get("ok")),
        "reset": True,
        "metric": metric,
        "files": sorted(files),
        "staged_id": staged.get("staged_id"),
        "report": {"compile": report.get("compile"), "gates_ok": report.get("gates_ok"),
                   "gates_fails": report.get("gates_fails") or [],
                   "new_refusals": report.get("new_refusals") or [],
                   "gates_not_run": report.get("gates_not_run") or []},
    }
    if not staged.get("ok"):
        result["reason"] = ("the removal did not pass the channel: "
                            + (staged.get("error") or "a new refusal appeared — something else "
                               "still refers to this metric"))
        return result

    if not apply_now:
        result["reason"] = "staged; a person applies it like any other publish"
        return result

    applied = ontology_publish.apply(staged["staged_id"], actor=actor, confirmed=True,
                                     git_commit=True)
    result["applied"] = bool(applied.get("ok"))
    result["git_commit"] = applied.get("git_commit")
    result["workbench_reloaded"] = applied.get("workbench_reloaded")
    if not applied.get("ok"):
        result["ok"] = False
        result["reason"] = applied.get("error") or "apply failed"
    return result
