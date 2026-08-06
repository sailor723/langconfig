# Smoke test for the classic-LangGraph builder backend.
#
# 1. POST the odd/even spec (mirrors backend/scripts/langgraph_tutorial_odd_even.py)
# 2. Run it 5 times with different inputs
# 3. Confirm final_state.evens / final_state.odds match the tutorial's behavior
import os
import sys
import json
import urllib.request
from pathlib import Path

API = "http://localhost:8765/api/classic-graphs"


SPEC = {
    "name": "Classic Odd/Even Demo",
    "description": "Faithful LangGraph tutorial: classify integers into evens/odds lists.",
    "spec": {
        # State channels with explicit reducers — the same as the pure-LangGraph tutorial.
        "state_fields": [
            {"name": "evens", "reducer": "add", "default": []},
            {"name": "odds",  "reducer": "add", "default": []},
            {"name": "last_number", "reducer": "last", "default": None},
        ],
        "nodes": [
            # Each node is a Python function: state in, partial state dict out.
            {
                "id": "generate",
                "kind": "function",
                "code": "return {'last_number': int(state['input'])}",
            },
            {
                "id": "handle_even",
                "kind": "function",
                "code": "return {'evens': [state['last_number']]}",
            },
            {
                "id": "handle_odd",
                "kind": "function",
                "code": "return {'odds': [state['last_number']]}",
            },
        ],
        "edges": [
            {"source": "START", "target": "generate"},
            # Real add_conditional_edges — a Python route expression over state
            # mapped to a path_map of branch names.
            {
                "source": "generate",
                "kind": "conditional",
                "route": "int(state['last_number']) % 2 == 0",
                "path_map": {"true": "handle_even", "false": "handle_odd"},
            },
            {"source": "handle_even", "target": "END"},
            {"source": "handle_odd", "target": "END"},
        ],
    },
}


def http(method, url, body=None):
    req = urllib.request.Request(url, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    else:
        data = None
    with urllib.request.urlopen(req, data=data, timeout=15) as r:
        return r.status, json.loads(r.read() or b"{}")


def main():
    # Upsert by deleting any prior copy with the same name, then POST.
    _, existing = http("GET", API)
    for g in existing:
        if g["name"] == SPEC["name"]:
            http("DELETE", f"{API}/{g['id']}")

    status, created = http("POST", API, SPEC)
    assert status == 200, f"create failed: {created}"
    gid = created["id"]
    print(f"Created graph id={gid}")

    inputs = [3, 8, 5, 12, 1, 6]
    expected_evens = [n for n in inputs if n % 2 == 0]
    expected_odds = [n for n in inputs if n % 2 == 1]

    evens_collected, odds_collected = [], []
    for n in inputs:
        status, run = http("POST", f"{API}/{gid}/run", {"input": {"input": str(n)}})
        assert status == 200, f"run failed: {run}"
        evens_collected.extend(run["final_state"].get("evens", []))
        odds_collected.extend(run["final_state"].get("odds", []))
        steps = run.get("steps", [])
        nodes_hit = [s["node"] for s in steps]
        print(f"  input {n:>3} -> {nodes_hit}")

    print("=" * 60)
    print(f"evens: {evens_collected}  (expected {expected_evens})")
    print(f"odds : {odds_collected}   (expected {expected_odds})")
    assert sorted(evens_collected) == sorted(expected_evens)
    assert sorted(odds_collected) == sorted(expected_odds)
    print("PASS: classic-LangGraph odd/even works end-to-end")


if __name__ == "__main__":
    main()