"""
Generate per-milestone PMO data for Sun Hing Vision Group.

Replaces the old monthly-summary raw_pmo with individual milestone records.
~30 individual milestones across 5 phases of the transformation program.

Output: inserts into sunhing_kpi.db raw_pmo table
"""

import sqlite3, pathlib, random
from typing import List, Dict

DB_DIR = pathlib.Path(__file__).parent
DB_PATH = DB_DIR / "sunhing_kpi.db"

# PMO Phases — dimension-level metadata for the transformation program
PHASES = [
    ("P1", "Planning & Setup",          "2026-09", 5, "PMO Director", 800),
    ("P2", "Legal Entity Restructuring", "2026-10", 8, "Legal Counsel", 2500),
    ("P3", "Eco-Partner Onboarding",     "2026-11", 7, "Partnership VP", 1500),
    ("P4", "Operations Transition",      "2026-12", 6, "Operations Director", 2000),
    ("P5", "Digital & Process",          "2027-01", 5, "CTO", 1200),
]

# Phase metadata for dim_pmo_phase table
PHASE_METADATA: List[Dict] = [
    {"phase_id": "P1", "phase_name": "Planning & Setup",
     "phase_name_cn": "规划与筹备", "start_month": "2026-09", "end_month": "2026-10",
     "phase_owner": "PMO Director", "milestone_count": 5, "budget_allocated_wan": 800},
    {"phase_id": "P2", "phase_name": "Legal Entity Restructuring",
     "phase_name_cn": "法人实体重组", "start_month": "2026-10", "end_month": "2026-12",
     "phase_owner": "Legal Counsel", "milestone_count": 8, "budget_allocated_wan": 2500},
    {"phase_id": "P3", "phase_name": "Eco-Partner Onboarding",
     "phase_name_cn": "生态伙伴导入", "start_month": "2026-11", "end_month": "2027-01",
     "phase_owner": "Partnership VP", "milestone_count": 7, "budget_allocated_wan": 1500},
    {"phase_id": "P4", "phase_name": "Operations Transition",
     "phase_name_cn": "运营过渡", "start_month": "2026-12", "end_month": "2027-02",
     "phase_owner": "Operations Director", "milestone_count": 6, "budget_allocated_wan": 2000},
    {"phase_id": "P5", "phase_name": "Digital & Process",
     "phase_name_cn": "数字化与流程", "start_month": "2027-01", "end_month": "2027-02",
     "phase_owner": "CTO", "milestone_count": 5, "budget_allocated_wan": 1200},
]

# Individual milestones
MILESTONES = [
    # Phase 1: Planning
    ("P1", "MS-001", "PMO office established",                    "2026-09-10", "completed", 1),
    ("P1", "MS-002", "Transformation roadmap v1 approved",        "2026-09-20", "completed", 1),
    ("P1", "MS-003", "Stakeholder communication plan",            "2026-09-25", "completed", 1),
    ("P1", "MS-004", "Risk register created",                     "2026-09-28", "completed", 1),
    ("P1", "MS-005", "Initial budget allocation approved",        "2026-10-05", "completed", 1),

    # Phase 2: Legal Entity Restructuring
    ("P2", "MS-006", "Entity split legal framework designed",     "2026-10-10", "completed", 1),
    ("P2", "MS-007", "泰阳花制造 entity registration filed",       "2026-10-15", "completed", 1),
    ("P2", "MS-008", "光龙光学 partnership agreement signed",      "2026-10-20", "completed", 1),
    ("P2", "MS-009", "光龙模具 entity registration completed",     "2026-10-25", "completed", 1),
    ("P2", "MS-010", "Asset transfer agreement template",         "2026-11-05", "completed", 1),
    ("P2", "MS-011", "光龙电镀 registration filed",               "2026-11-10", "completed", 1),
    ("P2", "MS-012", "倍崇德 brand entity separate accounting",   "2026-11-18", "completed", 1),
    ("P2", "MS-013", "一零一品牌管理 IP transfer completed",       "2026-12-05", "completed", 1),

    # Phase 3: Eco-Partner Onboarding
    ("P3", "MS-014", "Eco-partner selection criteria finalized",  "2026-11-08", "completed", 1),
    ("P3", "MS-015", "光龙装配 operations transfer plan",         "2026-11-22", "completed", 1),
    ("P3", "MS-016", "光龙质检 SLA agreement signed",             "2026-12-02", "completed", 1),
    ("P3", "MS-017", "Partner profit-sharing model implemented",  "2026-12-15", "completed", 1),
    ("P3", "MS-018", "光龙装配 production ramped to 80%",         "2027-01-10", "completed", 1),
    ("P3", "MS-019", "光龙物流 contract signed",                  "2027-01-15", "completed", 1),
    ("P3", "MS-020", "光龙技术服务 team deployed",               "2027-01-25", "completed", 1),

    # Phase 4: Operations Transition
    ("P4", "MS-021", "Production line reallocation plan",         "2026-12-08", "completed", 1),
    ("P4", "MS-022", "春阳花精密制造 facility upgrade",           "2026-12-20", "completed", 1),
    ("P4", "MS-023", "Quality control handover to 光龙质检",       "2027-01-08", "completed", 1),
    ("P4", "MS-024", "Logistics transition to 光龙物流",          "2027-01-22", "completed", 1),
    ("P4", "MS-025", "新溢越南 setup initiated",                  "2027-02-05", "in_progress", 0),
    ("P4", "MS-026", "Legacy system migration phase 1",           "2027-02-15", "in_progress", 0),

    # Phase 5: Digital & Process
    ("P5", "MS-027", "Digital asset management platform MVP",     "2027-01-12", "completed", 1),
    ("P5", "MS-028", "KPI dashboard system deployed",             "2027-01-28", "completed", 1),
    ("P5", "MS-029", "Eco-partner data exchange API v1",          "2027-02-10", "completed", 1),
    ("P5", "MS-030", "Cross-entity financial reporting system",   "2027-02-20", "in_progress", 0),
    ("P5", "MS-031", "AI-assisted production planning pilot",     "2027-02-25", "not_started", 0),
]

random.seed(456)

def generate_milestones():
    records = []
    for ms in MILESTONES:
        phase_id, ms_id, desc, date, status, is_ontime = ms
        records.append({
            "milestone_id": ms_id,
            "phase_id": phase_id,
            "milestone_description": desc,
            "planned_date": date,
            "actual_date": date if status == "completed" else None,
            "status": status,
            "completed_on_time": is_ontime,
        })
    return records


def recreate_pmo_table(cursor):
    cursor.execute("DROP TABLE IF EXISTS raw_pmo")
    cursor.execute("""
        CREATE TABLE raw_pmo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            milestone_id TEXT NOT NULL,
            phase_id TEXT,
            milestone_description TEXT,
            planned_date TEXT,
            actual_date TEXT,
            status TEXT,
            completed_on_time INTEGER,
            month TEXT
        )
    """)


def insert_milestones(cursor, milestones):
    for m in milestones:
        # Extract month from planned_date for grouping
        month = m["planned_date"][:7] if m["planned_date"] else None
        cursor.execute("""
            INSERT INTO raw_pmo (company_id, milestone_id, phase_id,
                milestone_description, planned_date, actual_date,
                status, completed_on_time, month)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            1, m["milestone_id"], m["phase_id"],
            m["milestone_description"], m["planned_date"],
            m["actual_date"], m["status"], m["completed_on_time"], month,
        ))


# --- dim_pmo_phase: dimension-level phase metadata ---

def generate_phases() -> List[Dict]:
    """Generate dim_pmo_phase records."""
    return PHASE_METADATA


def recreate_phase_table(cursor):
    cursor.execute("DROP TABLE IF EXISTS dim_pmo_phase")
    cursor.execute("""
        CREATE TABLE dim_pmo_phase (
            phase_id TEXT PRIMARY KEY,
            phase_name TEXT NOT NULL,
            phase_name_cn TEXT,
            start_month TEXT,
            end_month TEXT,
            phase_owner TEXT,
            milestone_count INTEGER,
            budget_allocated_wan REAL
        )
    """)


def insert_phases(cursor, phases: List[Dict]):
    for p in phases:
        cursor.execute("""
            INSERT INTO dim_pmo_phase (phase_id, phase_name, phase_name_cn,
                start_month, end_month, phase_owner, milestone_count, budget_allocated_wan)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            p["phase_id"], p["phase_name"], p["phase_name_cn"],
            p["start_month"], p["end_month"], p["phase_owner"],
            p["milestone_count"], p["budget_allocated_wan"],
        ))


if __name__ == "__main__":
    milestones = generate_milestones()
    print(f"Generated {len(milestones)} individual milestones across {len(PHASES)} phases:\n")

    for phase_id, phase_name, _, _, _, _ in PHASES:
        phase_ms = [m for m in milestones if m["phase_id"] == phase_id]
        completed = sum(1 for m in phase_ms if m["status"] == "completed")
        in_progress = sum(1 for m in phase_ms if m["status"] == "in_progress")
        print(f"  {phase_id} {phase_name}: {len(phase_ms)} milestones ({completed} done, {in_progress} in progress)")

    total_done = sum(1 for m in milestones if m["status"] == "completed")
    total_on_time = sum(1 for m in milestones if m["completed_on_time"])
    print(f"\n  Total: {len(milestones)} milestones, {total_done} completed, {total_on_time} on-time")

    # Write to DB
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # raw_pmo
    recreate_pmo_table(cursor)
    insert_milestones(cursor, milestones)

    # dim_pmo_phase
    phases = generate_phases()
    recreate_phase_table(cursor)
    insert_phases(cursor, phases)

    conn.commit()

    count = cursor.execute("SELECT COUNT(*) FROM raw_pmo").fetchone()[0]
    phase_count = cursor.execute("SELECT COUNT(*) FROM dim_pmo_phase").fetchone()[0]
    print(f"\nWritten to {DB_PATH}: {count} rows in raw_pmo, {phase_count} rows in dim_pmo_phase ✅")
    conn.close()
