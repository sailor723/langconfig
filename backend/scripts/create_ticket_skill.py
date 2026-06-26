"""Create ticket-classifier skill in PostgreSQL (persistent)."""
import sys
import os
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.database import SessionLocal
from models.skill import Skill, SkillSourceType

db = SessionLocal()
try:
    existing = db.query(Skill).filter(Skill.skill_id == "ticket-classifier").first()
    if existing:
        print("Skill 'ticket-classifier' already exists")
    else:
        skill = Skill(
            skill_id="ticket-classifier",
            name="ticket-classifier",
            description="Classifies customer support tickets by priority, category, and sentiment",
            instructions="# Ticket Classifier\n\n## Classification Rules\n\n### Priority Levels\n- **high**: Urgent, blocked, deadline, broken, crash\n- **medium**: Feature requests, account issues, billing\n- **low**: Documentation, how-to, minor feedback\n\n### Categories\n- **technical**: Bugs, errors, crashes\n- **billing**: Invoices, payments, refunds\n- **account**: Login, permissions, profile\n- **shipping**: Delivery, tracking, returns\n- **feature_request**: Suggestions\n\n### Sentiment\n- **frustrated**: Angry, demanding\n- **neutral**: Factual, polite\n- **satisfied**: Positive, appreciative",
            version="1.0.0",
            source_type=SkillSourceType.PERSONAL,
            source_path="db://personal",
            tags=["support", "classification", "ticket"],
            triggers=[],
            allowed_tools=[],
            required_context=[],
            usage_count=0,
            avg_success_rate=1.0,
            file_modified_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db.add(skill)
        db.commit()
        print("Skill 'ticket-classifier' created successfully")
except Exception as e:
    db.rollback()
    print(f"Error: {e}")
finally:
    db.close()
