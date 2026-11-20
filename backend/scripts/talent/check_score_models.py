#!/usr/bin/env python3
"""Check `work/talent/score_models.yaml` —— 分数目录的结构校验 + 门禁实跑。

为什么要这个脚本:一个只写在 YAML 里的门禁等于注释。本仓库的规矩是
"prompt 不是门禁、文档不是门禁、能跑起来的才算"。所以这里做两件事:

  1. 结构校验 —— 每个分数都有名字 / 分母 / 闸门 / 状态;权重表能对上;
  2. 门禁实跑 —— 把 `validation[*].check` 里的 SQL 真跑一遍,并把命中行打出来。

第二件事有个陷阱,是写 score_models.yaml 时实测撞到的:
`GROUP BY role HAVING count(*) = 0` **永远返回空** —— 空名单是"没有行",
不是"计数为零的行"。所以凡是问"哪些岗是空的",SQL 必须以 `role` 表为脊柱做
LEFT JOIN。本脚本不替你修 SQL,只负责把结果如实打出来,让"没命中"可被看见。

用法:
    python -m scripts.talent.check_score_models            # 全跑
    python -m scripts.talent.check_score_models --sql-only  # 只跑 SQL 门禁
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

import psycopg2
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
SPEC = ROOT / "work" / "talent" / "score_models.yaml"

REQUIRED_SCORE_FIELDS = ("code", "name", "answers", "owner", "kind",
                         "range", "denominator", "gate", "status")
ALLOWED_STATUS = {"live", "partial", "blocked", "refused"}


def connect():
    """显式 `ONTOLOGY_DB_*`,不读裸 `PG*` —— 见 shortlist.connect() 里的同类注释。"""
    return psycopg2.connect(
        host=os.environ.get("ONTOLOGY_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("ONTOLOGY_DB_PORT", "5433")),
        dbname=os.environ.get("ONTOLOGY_DB_NAME", "talent_db"),
        user=os.environ.get("ONTOLOGY_DB_USER", "langconfig"),
        password=os.environ.get("ONTOLOGY_DB_PASSWORD", "langconfig_dev"),
    )


def load_spec() -> dict:
    with SPEC.open() as fh:
        return yaml.safe_load(fh)


def sql_of(check: str) -> str:
    """从 `check` 文本里剥出可执行 SQL:去掉 `--` 注释行,保留语句本体。"""
    body = []
    for line in check.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        body.append(line)
    return "\n".join(body).strip()


def check_structure(spec: dict) -> list[str]:
    problems: list[str] = []

    for key in ("version", "scope", "facts", "scores", "comparable", "weights",
                "refused", "validation", "open"):
        if key not in spec:
            problems.append(f"缺少顶层字段: {key}")

    for score in spec.get("scores", []):
        code = score.get("code", "<无 code>")
        missing = [f for f in REQUIRED_SCORE_FIELDS if not score.get(f)]
        if missing:
            problems.append(f"{code}: 缺 {missing}(R1/R2/R3 要求每个分数都有名字、分母、闸门)")
        status = score.get("status")
        if status not in ALLOWED_STATUS:
            problems.append(f"{code}: status={status!r} 不在 {sorted(ALLOWED_STATUS)}")
        if status == "blocked" and not score.get("blocked_on"):
            problems.append(f"{code}: status=blocked 但没写 blocked_on(退化的原因必须写明)")
        if str(score.get("denominator", "")).strip() in {"", "无"}:
            problems.append(f"{code}: denominator 为空")

    weights = spec.get("weights", {})
    counts = {k: v for k, v in weights.get("family_counts", {}).items()}
    grand = 0
    for fam, row in counts.items():
        dims = sum(row.get(d, 0) for d in "ABCDEFGH")
        if dims != row.get("total"):
            problems.append(f"{fam}: 九维合计 {dims} ≠ total {row['total']}")
        grand += row.get("total", 0)
    if counts and grand != 95:
        problems.append(f"各族合计 {grand} ≠ JD 原子要求总数 95")

    tol = float(weights.get("rounding", {}).get("sum_tolerance", 0.5))
    for fam, row in weights.get("skeleton", {}).items():
        if not isinstance(row, dict):
            continue
        total = sum(v for v in row.values() if isinstance(v, (int, float)))
        if abs(total - 100) > tol:
            problems.append(f"skeleton.{fam}: 合计 {total:.1f} 超出容差 ±{tol}")

    live = [s.get("code") for s in spec.get("scores", []) if s.get("status") == "live"]
    for gate in spec.get("validation", []):
        for target in gate.get("applies_to", []) if isinstance(gate.get("applies_to"), list) else []:
            if target not in {s.get("code") for s in spec.get("scores", [])}:
                problems.append(f"{gate.get('code')}: applies_to 指向不存在的分数 {target}")
    if not live:
        problems.append("没有任何 live 状态的分数 —— 目录与实现脱节")

    # ── 权重必须和**实际打分代码**一致 ──
    # 这个文件描述打分,但真正算分的是 fit.py 的 WEIGHTS。两边不一致时,
    # 文档会静默变成假话,而所有门禁照绿 —— 一个"描述打分却不影响打分"的文件
    # 比没有它更危险。所以这里把两边拉到一起比,并让 yaml 自己声明名字的对应关系
    # (`weights.global.maps_to`),而不是在代码里硬编码一套映射。
    glob_w = weights.get("global") or {}
    maps = glob_w.get("maps_to") or {}
    if not maps:
        problems.append("weights.global 缺 maps_to(维度名 → fit.py 的项名),无法与实现对照")
    else:
        try:
            from scripts.talent.fit import WEIGHTS as FIT_WEIGHTS
        except Exception as exc:                      # 导入失败也要红,不能静默跳过
            problems.append(f"无法导入 scripts.talent.fit.WEIGHTS: {type(exc).__name__}: {exc}")
        else:
            for dim, key in maps.items():
                want = glob_w.get(dim)
                got = FIT_WEIGHTS.get(key)
                if want is None or got is None:
                    problems.append(f"weights 对照:{dim}→{key} 有一边缺失"
                                    f"(yaml={want}, fit={got})")
                elif abs(float(want) - float(got)) > 1e-9:
                    problems.append(f"weights 不一致:{dim}={want} 但 fit.py "
                                    f"WEIGHTS[{key!r}]={got}(谁改的,同步另一边)")
            extra = [k for k in FIT_WEIGHTS if k not in maps.values()]
            if extra:
                problems.append(f"fit.py 有 yaml 没覆盖的权重项:{extra} —— 分母会算错")
    return problems


def run_gates(spec: dict, show_rows: int = 6) -> tuple[int, int]:
    """跑 `validation[*].check` 里的 SQL。

    返回 `(断言成立的门禁数, 失败的门禁数)`。
    `expect: rows` 的门禁命中即"文档描述的现状成立";`expect: no_rows` 的门禁命中就是脏数据。
    """
    conn = connect()
    conn.set_session(readonly=True)          # 只读:门禁不许改库
    ok = bad = 0
    try:
        with conn.cursor() as cur:
            for gate in spec.get("validation", []):
                code = gate.get("code", "?")
                rule = (gate.get("rule") or "").strip()
                if gate.get("kind") != "sql":
                    print(f"  {code}  · 人工门禁   {rule}")
                    continue
                sql = sql_of(gate.get("check") or "")
                if not sql:
                    print(f"  {code}  ✗ 声明 kind=sql 但没有 SQL   {rule}")
                    bad += 1
                    continue
                expect = gate.get("expect", "rows")
                if expect not in {"rows", "no_rows"}:
                    print(f"  {code}  ✗ expect={expect!r} 非法(只允许 rows / no_rows)")
                    bad += 1
                    continue
                try:
                    cur.execute(sql)
                except psycopg2.Error as exc:
                    conn.rollback()
                    print(f"  {code}  ✗ SQL 失败: {str(exc).strip().splitlines()[0]}   {rule}")
                    bad += 1
                    continue
                rows = cur.fetchall() if cur.description else []
                hit = bool(rows)
                passed = hit if expect == "rows" else not hit
                mark = "✓" if passed else "✗"
                if passed:
                    ok += 1
                else:
                    bad += 1
                detail = f"命中 {len(rows)} 行" if hit else "无命中"
                want = "应命中" if expect == "rows" else "应无命中"
                print(f"  {code}  {mark} {detail}({want})   {rule}")
                if hit and expect == "rows":
                    for row in rows[:show_rows]:
                        print("        " + " | ".join("" if v is None else str(v) for v in row))
                    if len(rows) > show_rows:
                        print(f"        …另 {len(rows) - show_rows} 行")
    finally:
        conn.close()
    return ok, bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sql-only", action="store_true", help="只跑 SQL 门禁,跳结构校验")
    args = ap.parse_args()

    spec = load_spec()
    print(f"spec: {SPEC.relative_to(ROOT)}  v{spec.get('version')}  "
          f"scores={len(spec.get('scores', []))} gates={len(spec.get('validation', []))}")

    if not args.sql_only:
        problems = check_structure(spec)
        print("\n结构校验:")
        if problems:
            for p in problems:
                print(f"  ✗ {p}")
            return 1
        print("  ✓ 全部通过")

    print("\n门禁实跑:")
    ok, bad = run_gates(spec)
    print(f"\n{ok} 条断言成立 / {bad} 条失败。")
    print("「命中」多数是**现状**,不是问题 —— 它们把今天钉住,不命中了才说明文档过期。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
