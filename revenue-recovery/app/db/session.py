"""
Database engine and session management (SQLAlchemy 2.x).

Concepts for reference:
  - `engine`: manages a pool of actual DB connections. Created once per
    process.
  - `SessionLocal`: a factory that produces new Session objects. A Session
    is a "workspace" for a unit of work -- typically one request's worth
    of database operations, committed or rolled back together.
  - `Base`: the declarative base class that our ORM models (app/models/)
    inherit from. SQLAlchemy uses it to know which Python classes map to
    which database tables.

We use the `get_db` generator as a FastAPI dependency (see
app/api/routes/webhooks.py). FastAPI calls it before the route handler
runs, hands the yielded Session to the handler, and -- critically --
resumes the generator after the handler returns to close the session,
even if the handler raised an exception. This guarantees connections are
always returned to the pool.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # detect and replace dead connections automatically
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    future=True,
)


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
