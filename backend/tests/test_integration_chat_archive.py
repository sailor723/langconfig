"""
Full integration test: chat API → conversation archived → metadata extracted.

Simulates: greeting agent (id=10)
  Turn 1: "hi am weiping" → should archive + extract name → user_profiles
  Turn 2: "who am I" → should recall from memory
  Turn 3: "I like blue color" → should archive + extract preference
"""
import requests
import json
import sys

BASE = "http://127.0.0.1:8765"
session_id = None
user_id = 1  # default test user


def start_chat(agent_id=10):
    global session_id
    resp = requests.post(
        f"{BASE}/api/chat/start",
        json={"agent_id": agent_id, "user_id": user_id},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    session_id = data["session_id"]
    print(f"[START] session={session_id}")
    print(f"[START] agent={data.get('agent_name', '?')}")
    return session_id


def send_message(message: str, timeout=120) -> dict:
    global session_id
    resp = requests.post(
        f"{BASE}/api/chat/message",
        json={"session_id": session_id, "message": message},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data.get("message", data.get("content", ""))
    tool_calls = data.get("tool_calls", [])
    preview = content[:300].replace("\n", " ").strip() if content else "(EMPTY)"
    print(f"\n[USER] {message}")
    print(f"[AGENT] {preview}")
    if tool_calls:
        for tc in tool_calls:
            print(f"  [TOOL] {tc.get('name', '?')}")
    return data


def check_archives():
    """Check conversation_archives table."""
    from db.database import engine
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT turn_number, substring(user_message,1,40) as msg, "
                 "substring(agent_response,1,40) as resp "
                 "FROM conversation_archives WHERE session_id = :sid "
                 "ORDER BY turn_number"),
            {"sid": session_id},
        )
        rows = result.fetchall()
        if rows:
            print(f"\n[ARCHIVE] ({len(rows)} turns):")
            for r in rows:
                print(f"  turn {r.turn_number}: '{r.msg}' → '{r.resp}'")
        else:
            print(f"\n[ARCHIVE] EMPTY")
        return rows


def check_profile():
    """Check user_profiles table."""
    from db.database import engine
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT name, preferences, metadata_snapshot "
                 "FROM user_profiles WHERE user_id = :uid"),
            {"uid": user_id},
        )
        row = result.fetchone()
        if row:
            print(f"\n[PROFILE] name={row.name}, preferences={row.preferences}")
        else:
            print(f"\n[PROFILE] No profile found")
        return row


def check_memories():
    """Check agent_memories table."""
    from db.database import engine
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT memory_type, substring(content,1,60) as c "
            "FROM agent_memories WHERE project_id = 0 "
            "ORDER BY created_at DESC LIMIT 5"
        ))
        rows = result.fetchall()
        if rows:
            print(f"\n[MEMORY] ({len(rows)}):")
            for r in rows:
                print(f"  {r.memory_type}: {r.c}")
        else:
            print(f"\n[MEMORY] No memories found")
        return rows


def main():
    print("=" * 60)
    print("INTEGRATION TEST: Chat → Archive → Metadata → Memory")
    print("=" * 60)

    # Clean up test data
    from db.database import engine
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM conversation_archives WHERE user_id = :uid"), {"uid": user_id})
        conn.execute(text("DELETE FROM user_profiles WHERE user_id = :uid"), {"uid": user_id})
        conn.execute(text("DELETE FROM agent_memories WHERE project_id = 0"))
        conn.commit()
    print("✓ Test data cleaned\n")

    # Start chat
    start_chat(10)

    # Turn 1: Introduce
    print("\n--- TURN 1: hi am weiping ---")
    send_message("hi am weiping")
    rows_archive = check_archives()
    profile = check_profile()
    memories = check_memories()

    # Turn 2: Ask who I am (tests memory recall)
    print("\n--- TURN 2: who am I ---")
    send_message("who am I")
    rows_archive = check_archives()
    profile = check_profile()

    # Turn 3: State preference
    print("\n--- TURN 3: I like blue color ---")
    send_message("I like blue color")
    rows_archive = check_archives()
    profile = check_profile()
    memories = check_memories()

    # Turn 4: Ask for name + color
    print("\n--- TURN 4: what's my name and favorite color ---")
    send_message("what's my name and what's my favorite color")
    rows_archive = check_archives()
    profile = check_profile()
    memories = check_memories()

    # Final verdict
    print("\n" + "=" * 60)
    print("VERDICT")
    print("=" * 60)

    # Check archive
    if rows_archive and len(rows_archive) >= 3:
        print("✓ CONVERSATION ARCHIVED: All turns saved")
    else:
        print(f"✗ ARCHIVE FAILED: {len(rows_archive) if rows_archive else 0} turns archived")

    # Check profile
    if profile and profile.name:
        print(f"✓ METADATA EXTRACTED: name={profile.name}")
    else:
        print("✗ METADATA NOT EXTRACTED")

    # Check memories
    if memories:
        print(f"✓ MEMORY STORED: {len(memories)} memories in DB")
    else:
        print("✗ NO MEMORIES STORED")

    print("\nDone!")


if __name__ == "__main__":
    main()
