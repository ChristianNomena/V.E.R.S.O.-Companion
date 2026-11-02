"""
V.E.R.S.O. - Database Engine & Connection
Agnostic database connection supporting SQLite multi-thread and external DBMS.
"""

from typing import Generator
from sqlmodel import Session, SQLModel, create_engine

from verso.config import DATABASE_URL

# Multi-thread SQLite support
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


def init_db() -> None:
    """Initializes the database schema."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """Provides a database session context."""
    with Session(engine) as session:
        yield session
