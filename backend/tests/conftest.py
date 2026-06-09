"""Pytest fixtures for database tests."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from db.database import engine as _db_engine
from db.database import SessionLocal

TEST_USER = 9999


@pytest.fixture(scope="session")
def db_engine():
    """Provide the database engine for direct SQL queries."""
    return _db_engine


@pytest.fixture(scope="function")
def db_session():
    """Provide a fresh database session for each test with cleanup."""
    session = SessionLocal()
    try:
        yield session
    finally:
        # Clean up test data
        try:
            session.execute(text("DELETE FROM conversation_archives WHERE session_id LIKE 'test-%' OR session_id LIKE 'int-test-%'"))
            session.execute(text(f"DELETE FROM user_profiles WHERE user_id = {TEST_USER}"))
            session.commit()
        except Exception:
            session.rollback()
        session.close()
