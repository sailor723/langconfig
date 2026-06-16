"""Change model back to agnes-2.0-flash."""
import json
from db.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    r = conn.execute(text("SELECT id, config FROM deep_agent_templates WHERE id = 40")).fetchone()
    cfg = dict(r[1]) if r[1] else {}
    cfg["model"] = "agnes-2.0-flash"
    conn.execute(
        text("UPDATE deep_agent_templates SET config = :cfg WHERE id = 40"),
        {"cfg": json.dumps(cfg)}
    )
    conn.commit()
    print("✅ Model set back to agnes-2.0-flash")
