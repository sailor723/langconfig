#!/usr/bin/env python3
"""Import the enterprise HR graph (JSON seed) into a Neo4j instance.

Works on ANY Neo4j 5.x edition (community or enterprise) — uses only the
standard driver API, no dump/block-format requirement.

Usage (from backend/ with the project venv — it has the neo4j driver):
    uv run python scripts/seeds/in/neo4j-hr/import_hr_seed.py \
        [bolt://localhost:7687] [neo4j] [password] \
        [path/to/nodes.json] [path/to/rels.json]
"""
import json
import sys
from pathlib import Path

from neo4j import GraphDatabase

DEFAULT_URI = "bolt://localhost:7687"
HERE = Path(__file__).resolve().parent
BATCH = 200


def main() -> None:
    uri = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URI
    user = sys.argv[2] if len(sys.argv) > 2 else "neo4j"
    password = sys.argv[3] if len(sys.argv) > 3 else "password"
    nodes_path = Path(sys.argv[4]) if len(sys.argv) > 4 else HERE / "nodes.json"
    rels_path = Path(sys.argv[5]) if len(sys.argv) > 5 else HERE / "rels.json"

    nodes = json.loads(nodes_path.read_text(encoding="utf-8"))
    rels = json.loads(rels_path.read_text(encoding="utf-8"))
    print(f"seed: {len(nodes)} nodes, {len(rels)} rels -> {uri}")

    driver = GraphDatabase.driver(uri, auth=(user, password), encrypted=False)
    try:
        with driver.session() as s:
            # Nodes, grouped by label-set, with __src_id for rel linking.
            by_labels: dict[tuple, list] = {}
            for n in nodes:
                by_labels.setdefault(tuple(n["labels"]), []).append(n)
            for labels, group in by_labels.items():
                label_str = "".join(":" + l for l in labels)
                for i in range(0, len(group), BATCH):
                    batch = []
                    for n in group[i : i + BATCH]:
                        props = dict(n["props"])
                        props["__src_id"] = n["id"]
                        batch.append(props)
                    s.run(f"UNWIND $rows AS row CREATE (n{label_str}) SET n = row", rows=batch)
                print(f"  nodes {label_str}: {len(group)}")
            # Relationships, grouped by type.
            by_type: dict[str, list] = {}
            for r in rels:
                by_type.setdefault(r["tpe"], []).append(r)
            for tpe, group in by_type.items():
                for i in range(0, len(group), BATCH):
                    batch = [
                        {"s": r["s"], "t": r["t"], "p": r["props"]}
                        for r in group[i : i + BATCH]
                    ]
                    s.run(
                        f"UNWIND $rows AS row MATCH (a {{__src_id: row.s}}) "
                        f"MATCH (b {{__src_id: row.t}}) CREATE (a)-[r:{tpe}]->(b) SET r = row.p",
                        rows=batch,
                    )
                print(f"  rels {tpe}: {len(group)}")
            s.run("MATCH (n) WHERE n.__src_id IS NOT NULL REMOVE n.__src_id")
        # Verify
        with driver.session() as s:
            n = s.run("MATCH (n) RETURN count(n)").value()[0]
            r = s.run("MATCH ()-[x]->() RETURN count(x)").value()[0]
        print(f"VERIFY: nodes={n} rels={r} (expected {len(nodes)}/{len(rels)})")
        assert n == len(nodes) and r == len(rels), "MISMATCH!"
        print("OK — seed imported successfully")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
