#!/usr/bin/env python3
"""Deterministic shortlist: the gate, the score, the reason, and who was left out.

Why this file exists and why it is NOT an agent. The list must be reproducible: run it twice,
get the same bytes; change a weight, see exactly which rows moved and why. An LLM in this path
would make "why is she ranked 7th?" unanswerable — so the agent layer sits *on top* of this
output (explaining it), never inside it.

Three artefacts, each answering one question:

    candidate_skill_evidence  — 这个技能从哪来？（文件 / 抽取方式 / 片段）
    fit_component             — 这一分从哪来？（要求 / 实际 / 权重 / 贡献 / 缺什么）
    v_shortlist               — 名单本身，按 (名单类型, 信息完整度, 分数) 排序

The gate (决定 D8/D10): a candidate is 合格 when **every assessable essential requirement**
is covered at ≥ 0.5. Years and education do not gate (D10) — they score.

The two lists (决定 O4 / 用户的"两层都出"):
    qualified  — 过闸门
    near       — 未过闸门，但分数 ≥ 60，且**写明差哪一项**

Inside each list, complete-information candidates rank before partial ones (O4 实测：
纯按分数排时 top-12 里信息完整者 0/12，加完整度后 11/12)。

Usage:
    python -m scripts.talent.shortlist --build            # 建表 + 灌数 + 建视图
    python -m scripts.talent.shortlist --report           # 打印每个岗位的名单摘要
    python -m scripts.talent.shortlist --report --role 业务跟单 --top 10
"""
from __future__ import annotations

import argparse
import collections
import os
import pathlib
import sys

import psycopg2
from psycopg2.extras import execute_values

BACKEND = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from scripts.talent.fit import score_from_parts  # noqa: E402

#: 闸门阈值：每条要求的覆盖率必须达到这个值才算"满足"
GATE_COVERAGE = 0.5
#: "接近"名单的门槛分数
NEAR_SCORE = 60.0

DDL = """
CREATE TABLE IF NOT EXISTS candidate_skill_evidence (
    candidate   text NOT NULL,
    skill       text NOT NULL,
    category    text,
    source_file text,
    method      text,          -- 'ocr' | 'filename'
    span        text,          -- 命中片段；OCR 原文未留存时为 NULL（见 grill.md 硬限制 1）
    PRIMARY KEY (candidate, skill)
);

CREATE TABLE IF NOT EXISTS fit_component (
    candidate      text NOT NULL,
    role           text NOT NULL,
    component      text NOT NULL,   -- 'skills' | 'years' | 'education'
    requirement_id text NOT NULL DEFAULT '',  -- skills 行指向 requirement；years/education 用 '' 作哨兵（主键列不能为 NULL）
    label          text,
    required       numeric,
    actual         numeric,
    weight         numeric NOT NULL,
    contribution   numeric NOT NULL,
    met            boolean,
    PRIMARY KEY (candidate, role, component, requirement_id)
);
"""

VIEW = """
DROP VIEW IF EXISTS v_shortlist;
CREATE VIEW v_shortlist AS
WITH agg AS (
    SELECT
        f.candidate,
        f.role,
        round(sum(f.contribution)::numeric, 2) AS score,
        -- 完整度 = **观测到的权重占比**：值真的读到了才算，行存在不算
        round(100.0 * sum(f.weight) FILTER (WHERE f.actual IS NOT NULL)
              / sum(f.weight), 1) AS completeness,
        bool_and(COALESCE(f.met, true)) AS gate_passed,
        (array_agg(f.label ORDER BY f.component) FILTER (WHERE f.met IS FALSE))[1] AS first_gap,
        count(*) FILTER (WHERE f.met IS FALSE) AS gaps
    FROM fit_component f
    GROUP BY f.candidate, f.role
)
SELECT candidate, role, score, completeness, first_gap, gaps,
       CASE WHEN gate_passed                THEN 'qualified'
            WHEN score >= %(near)s          THEN 'near'
            ELSE 'excluded' END             AS list_kind,
       -- 决定 O4：完整信息与部分信息**分两张名单**，不在同一张里比高低
       CASE WHEN NOT gate_passed            THEN NULL
            WHEN completeness = 100         THEN 'A_qualified_full'
            ELSE                                 'B_qualified_partial' END AS list_bucket
FROM agg;
"""




#: 决定 C 的披露层：公理（必要条件）与闸门（够不够）**分歧必须看得见**，
#: 不许一方默默盖掉另一方。三种状态：
#:   agree_qualified  两边都说合格
#:   axiom_only       推理机推得出来，但复合要求没达标 —— "会，但不够"
#:   gate_only        复合要求达标，但推理机推不出来 —— 通常是技能类别不在公理里
DISAGREEMENT_VIEW = """
DROP VIEW IF EXISTS v_axiom_vs_gate;
CREATE VIEW v_axiom_vs_gate AS
WITH ax AS (
    SELECT replace(role_class, 'matches_', 'role_') AS role, candidate FROM candidate_match
), g AS (
    SELECT role, candidate, list_kind, score, completeness FROM v_shortlist
)
SELECT
    coalesce(ax.role, g.role)                       AS role,
    coalesce(ax.candidate, g.candidate)             AS candidate,
    (ax.candidate IS NOT NULL)                      AS axiom_entailed,
    coalesce(g.list_kind, 'not_in_gate')            AS gate_kind,
    g.score, g.completeness,
    CASE WHEN ax.candidate IS NOT NULL AND g.list_kind = 'qualified' THEN 'agree_qualified'
         WHEN ax.candidate IS NOT NULL                                THEN 'axiom_only'
         WHEN g.list_kind = 'qualified'                               THEN 'gate_only'
         ELSE 'agree_rejected' END                  AS verdict
FROM ax FULL OUTER JOIN g ON g.role = ax.role AND g.candidate = ax.candidate;
"""


def connect():
    """显式的 `ONTOLOGY_DB_*`，**不用裸 `PG*`**。

    教训：本机 shell 导出了 `PGPORT=5432`，而 psycopg2 的 libpq 会静默读它 —— 于是
    `os.environ.get("PGPORT", "5433")` 拿到 5432，报一个看起来像"角色不存在"的假错。
    与 `docs` 里那条"独立脚本必须先加载 .env"是同一类坑：**别让环境变量替你选库**。
    """
    return psycopg2.connect(
        host=os.environ.get("ONTOLOGY_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("ONTOLOGY_DB_PORT", "5433")),
        dbname=os.environ.get("ONTOLOGY_DB_NAME", "talent_db"),
        user=os.environ.get("ONTOLOGY_DB_USER", "langconfig"),
        password=os.environ.get("ONTOLOGY_DB_PASSWORD", "langconfig_dev"),
    )


def load(cur):
    """一切从库里读，不在内存里另建一份真源。"""
    cur.execute("""select r.id, r.role, r.label, q.skill
                   from requirement r join requirement_skill q on q.requirement_id = r.id
                   where r.assessable and r.tier = 'essential'
                   order by r.id""")
    reqs: dict[str, dict] = collections.defaultdict(lambda: {"role": None, "label": None, "parts": []})
    for rid, role, label, skill in cur.fetchall():
        reqs[rid]["role"] = role
        reqs[rid]["label"] = label
        reqs[rid]["parts"].append(skill)

    cur.execute("select s.candidate, s.skill, k.category from candidate_skill s "
                "left join skill k on k.skill = s.skill")
    held: dict[str, set[str]] = collections.defaultdict(set)
    cat: dict[tuple[str, str], str] = {}
    for cand, skill, category in cur.fetchall():
        held[cand].add(skill)
        cat[(cand, skill)] = category

    cur.execute("select role, required_years, required_education_rank from role")
    role_meta = {r: (y, e) for r, y, e in cur.fetchall()}

    cur.execute("select id, years_experience, education_rank, source_file from candidate")
    cands = {cid: (yr, ed, src) for cid, yr, ed, src in cur.fetchall()}
    return reqs, held, cat, role_meta, cands


def build(cur, reqs, held, cat, role_meta, cands):
    cur.execute(DDL)

    # ── 证据台账：技能从哪来
    ev = []
    for cid, (_yr, _ed, src) in cands.items():
        for skill in sorted(held[cid]):
            ev.append((cid, skill, cat.get((cid, skill)), src, "ocr", None))
    cur.execute("TRUNCATE candidate_skill_evidence")
    execute_values(cur, "insert into candidate_skill_evidence values %s", ev, page_size=1000)

    # ── 构成台账：每一分从哪来
    rows = []
    by_role: dict[str, list[str]] = collections.defaultdict(list)
    for rid, info in reqs.items():
        by_role[info["role"]].append(rid)

    for rc, req_ids in sorted(by_role.items()):
        req_ids = sorted(req_ids)
        rY, rE = role_meta.get(rc, (None, None))
        for cid, (yr, ed, _src) in cands.items():
            covers = []
            for rid in req_ids:
                parts = set(reqs[rid]["parts"])
                cov = len(held[cid] & parts) / len(parts) if parts else 0.0
                covers.append(cov)
                rows.append((cid, rc, "skills", rid, reqs[rid]["label"],
                             len(parts), len(held[cid] & parts), 60.0,
                             round(60.0 * cov / len(req_ids), 4), cov >= GATE_COVERAGE))
            skills_ratio = sum(covers) / len(covers) if covers else 0.0
            score, _comp, _unk = score_from_parts(
                skills_ratio=skills_ratio, years=yr, required_years=rY,
                education_rank=ed, required_education_rank=rE)
            # years / education 的逐项记录（未知则记 met=NULL，不记 0）
            from scripts.talent.fit import years_fraction, education_fraction
            yf = years_fraction(yr)
            rows.append((cid, rc, "years", "", f"年限≥{rY}" if rY else "年限（JD 未声明）",
                         rY, yr, 25.0, 0.0 if yf is None else round(25.0 * yf, 4), None))
            ef = education_fraction(ed, rE)
            rows.append((cid, rc, "education", "", f"学历等级≥{rE}" if rE else "学历（JD 未声明）",
                         rE, ed, 15.0, 0.0 if ef is None else round(15.0 * ef, 4), None))
            _ = score
    cur.execute("TRUNCATE fit_component")
    execute_values(cur, """insert into fit_component
        (candidate, role, component, requirement_id, label, required, actual, weight, contribution, met)
        values %s""", rows, page_size=2000)
    cur.execute(VIEW, {"near": NEAR_SCORE})
    cur.execute(DISAGREEMENT_VIEW)
    return len(ev), len(rows)


def report(cur, role_filter: str | None, top: int):
    cur.execute("select list_kind, count(*) from v_shortlist group by 1 order by 1")
    print("=== 全库（跨岗位行数，一个人可进多个岗位）===")
    for k, n in cur.fetchall():
        print(f"  {k:10s} {n:6d}")

    print("\n=== 各岗位：合格 / 其中信息完整 / 接近 / 排除 ===")
    print(f"{'岗位':16s} {'合格':>5s} {'完整':>5s} {'接近':>5s} {'排除':>5s}")
    print("-" * 42)
    cur.execute("""
        select role,
               count(*) filter (where list_kind='qualified'),
               count(*) filter (where list_kind='qualified' and completeness=100),
               count(*) filter (where list_kind='near'),
               count(*) filter (where list_kind='excluded')
        from v_shortlist group by 1 order by 1""")
    for role, q, qf, n, x in cur.fetchall():
        print(f"{role:16s} {q:>5d} {qf:>5d} {n:>5d} {x:>5d}")

    where = ("where role = 'role_" + role_filter + "'") if role_filter else "where list_kind='qualified'"
    cur.execute(f"""
        select role, candidate, score, completeness, first_gap
        from v_shortlist {where}
        order by role, completeness desc, score desc, candidate
        limit {top}""")
    rows = cur.fetchall()
    if not rows:
        print("\n（该筛选下没有行）")
        return
    title = f"role_{role_filter}" if role_filter else "全库合格名单"
    print(f"\n=== {title} top {top}（按 完整度 → 分数）===")
    print(f"{'岗位':14s} {'分数':>7s} {'完整':>5s}  候选人 / 缺什么")
    for role, cid, sc, cp, gap in rows:
        g = f"  ⚠{gap}" if gap else ""
        print(f"{role:14s} {sc:>7.2f} {cp:>5.0f}  {cid[:40]}{g}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="建表、灌数据、建视图")
    ap.add_argument("--report", action="store_true", help="打印摘要")
    ap.add_argument("--role", default="", help="只看某个岗位（裸名，如 业务跟单）")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    conn = connect()
    cur = conn.cursor()
    try:
        if args.build:
            reqs, held, cat, role_meta, cands = load(cur)
            n_ev, n_fc = build(cur, reqs, held, cat, role_meta, cands)
            conn.commit()
            print(f"candidate_skill_evidence: {n_ev} 行")
            print(f"fit_component:            {n_fc} 行")
            print("v_shortlist:              已创建")
        if args.report:
            report(cur, args.role or None, args.top)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
