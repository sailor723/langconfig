"""Update ticker_classifer system prompt in DB."""
import json
from db.database import SessionLocal
from sqlalchemy import text

NEW_PROMPT = """You are a research and data analysis agent.

## Capabilities
- Ticket classification: priority, category, sentiment analysis
- Data analysis: CSV files, SQL databases, pandas, matplotlib
- Code review: best practices, security, performance, maintainability
- AI research: trends in agent architectures and frameworks

Always respond with well-structured output and cite your findings."""

db = SessionLocal()
try:
    row = db.execute(
        text("SELECT id, name, config FROM deep_agent_templates WHERE name LIKE '%ticker%'")
    ).fetchone()
    config = row[2] if isinstance(row[2], dict) else json.loads(row[2])
    config["system_prompt"] = NEW_PROMPT
    db.execute(
        text("UPDATE deep_agent_templates SET config = :config WHERE name LIKE '%ticker%'"),
        {"config": json.dumps(config)},
    )
    db.commit()
    print("✅ System prompt updated in DB")

    # Verify
    row2 = db.execute(
        text("SELECT config FROM deep_agent_templates WHERE name LIKE '%ticker%'")
    ).fetchone()
    config2 = json.loads(row2[0]) if isinstance(row2[0], str) else row2[0]
    sp = config2.get("system_prompt", "")
    print(f"New prompt ({len(sp)} chars):")
    print(sp)
finally:
    db.close()
