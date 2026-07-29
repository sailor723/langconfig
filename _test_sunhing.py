"""Test sunhing-analyst with natural language queries."""
import requests, json, sys, time

BASE = "http://localhost:8765"
DB_PATH = "data/analysis_dbs/sunhing_kpi.db"

test_questions = [
    "当前最新月份整体KPI达标率如何？哪些KPI达标了？",
    "ROE趋势怎么样？三个驱动因子分别是什么表现？",
    "协商减员完成率这个月是多少？进展到哪步了？",
]

all_ok = True
for i, q in enumerate(test_questions):
    print(f"\n{'='*60}")
    print(f"[Test {i+1}/{len(test_questions)}]")
    print(f"Q: {q}")
    print(f"{'='*60}")
    try:
        r = requests.post(f"{BASE}/api/analysis/chat", json={
            "session_id": f"test-{i}",
            "db_path": DB_PATH,
            "message": q,
            "skills": ["sunhing-analyst"],
        }, timeout=120)
        data = r.json()
        if r.status_code == 200:
            msg = data.get("message", "")
            tc = data.get("tool_calls", 0)
            tt = data.get("total_tokens", 0)
            print(f"Status: OK ({tc} tools, ~{tt} tokens)")
            print(f"\nResponse:\n{msg[:1500]}")
        else:
            print(f"Status: ERROR {r.status_code}")
            print(f"Detail: {data.get('detail', data)}")
            all_ok = False
    except Exception as e:
        print(f"Exception: {e}")
        all_ok = False

print(f"\n{'='*60}")
print(f"{'✅ All tests passed' if all_ok else '❌ Some tests failed'}")
