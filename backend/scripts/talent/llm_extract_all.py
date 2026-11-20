#!/usr/bin/env python3
"""批量:270 个候选人 × (OCR + LLM 抽字段带引文)。并发跑,产出 cv_draft/。"""
from __future__ import annotations
import json, os, pathlib, sys, concurrent.futures as cf, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
ROOT = pathlib.Path(__file__).resolve().parents[3]
import psycopg2

def work(row):
    cid, src = row
    try:
        from scripts.talent import llm_extract_cv as X
        text = X.ocr(src)
        catalog = X.yaml.safe_load(X.CATALOG.read_text(encoding="utf-8"))
        skills = {c["label"]: c["id"] for c in catalog["components"]}
        raw = X._llm(X.build_prompt(text, list(skills)))
        import re
        m = re.search(r"\{.*\}", raw, re.S)
        doc = json.loads(m.group(0)) if m else {}
        bad = X.verify(doc, text, skills)
        X.DRAFT.mkdir(parents=True, exist_ok=True)
        (X.DRAFT / f"{cid}.json").write_text(json.dumps(
            {"candidate": cid, "source_file": src, "raw": doc, "verify": bad,
             "model": "deepseek-chat", "temperature": 0, "review_status": "draft"},
            ensure_ascii=False, indent=1), encoding="utf-8")
        return cid, doc, bad, None
    except Exception as e:
        return cid, None, None, str(e)[:120]

def main():
    conn = psycopg2.connect(host=os.environ["ONTOLOGY_DB_HOST"], port=int(os.environ["ONTOLOGY_DB_PORT"]),
                            dbname="talent_db", user=os.environ["ONTOLOGY_DB_USER"],
                            password=os.environ["ONTOLOGY_DB_PASSWORD"])
    with conn.cursor() as cur:
        cur.execute("select id, source_file from candidate where duplicate_of is null order by id")
        rows = cur.fetchall()
    conn.close()
    print(f"待处理 {len(rows)} 人", flush=True)
    stats = collections.Counter(); fails = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for i, (cid, doc, bad, err) in enumerate(ex.map(work, rows), 1):
            if err: fails.append((cid, err)); stats["失败"] += 1
            else:
                stats["成功"] += 1
                for f in ("age","years_experience","education_rank","major","full_time","gender"):
                    if (doc.get(f) or {}).get("value") is not None: stats[f] += 1
                stats["引文编造"] += len(bad["quote_invented"])
                stats["技能条数"] += len(doc.get("skills") or [])
            if i % 25 == 0: print(f"  {i}/{len(rows)}  {dict(stats)}", flush=True)
    print("\n完成:", dict(stats), flush=True)
    for c, e in fails[:5]: print("  失败:", c, e, flush=True)

if __name__ == "__main__":
    main()
