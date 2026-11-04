"""
V.E.R.S.O. - Database Engine & Operations
Agnostic database connection supporting SQLite multi-threading and CRUD functions.
"""

import logging
from typing import Generator, List
from sqlmodel import Session, SQLModel, create_engine, select

from verso.config import DATABASE_URL
from verso.database.models import TaskRecord

logger = logging.getLogger(__name__)

# Multi-thread SQLite support
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


def init_db() -> None:
    """Initializes the database schema and ensures all tables exist."""
    SQLModel.metadata.create_all(engine)
    logger.info("Database schema initialized.")


def get_session() -> Generator[Session, None, None]:
    """Provides a database session context."""
    with Session(engine) as session:
        yield session


def insert_task(
    action_title: str,
    trigger_source: str = "SLACK_INTENT",
    status: str = "COMPLETED",
) -> TaskRecord:
    """
    Inserts a newly executed task record into the database.

    Args:
        action_title: Title of the action performed.
        trigger_source: Source of the trigger (defaults to SLACK_INTENT).
        status: Task completion status (defaults to COMPLETED).

    Returns:
        TaskRecord: The persisted task instance with assigned ID.
    """
    with Session(engine) as session:
        task = TaskRecord(
            action_title=action_title,
            trigger_source=trigger_source,
            status=status,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        logger.info("Task record #%s saved: %s", task.id, task.action_title)
        return task


def get_recent_tasks(limit: int = 20) -> List[TaskRecord]:
    """
    Retrieves the most recent task records ordered by timestamp descending.

    Args:
        limit: Maximum number of records to return.

    Returns:
        List[TaskRecord]: Recent task instances.
    """
    with Session(engine) as session:
        statement = select(TaskRecord).order_by(TaskRecord.timestamp.desc()).limit(limit)
        return list(session.exec(statement).all())
