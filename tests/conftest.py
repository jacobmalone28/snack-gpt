"""Test fixtures and utilities for tests."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from snack_gpt.db import Base


@pytest.fixture
def test_db():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    yield db
    
    db.close()
