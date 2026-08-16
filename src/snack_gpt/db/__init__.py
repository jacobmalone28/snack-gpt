"""Database configuration and utilities."""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from snack_gpt.config import settings

# Create engine with WAL mode for SQLite
engine = create_engine(
    settings.database_url,
    echo=settings.database_echo,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

# Enable WAL mode for SQLite if applicable
if "sqlite" in settings.database_url:
    with engine.begin() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():  # type: ignore[no-untyped-def]
    """Dependency for FastAPI to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
