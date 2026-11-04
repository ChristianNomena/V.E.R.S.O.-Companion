"""
V.E.R.S.O. - Database Engine & Operations
Agnostic database connection supporting SQLite multi-threading and CRUD functions.
"""

import logging
from typing import Generator, List, Optional
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from verso.config import DATABASE_URL
from verso.database.models import TaskRecord

logger = logging.getLogger(__name__)

# Multi-thread SQLite support
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


def init_db() -> None:
    """Initializes the database schema and ensures all tables and columns exist."""
    SQLModel.metadata.create_all(engine)
    if DATABASE_URL.startswith("sqlite"):
        with engine.connect() as conn:
            for col_name in ["incoming_message", "ai_suggestion", "user_response", "final_response"]:
                try:
                    conn.execute(text(f"ALTER TABLE task_record ADD COLUMN {col_name} TEXT;"))
                    conn.commit()
                except Exception:
                    # Column already exists
                    pass
    logger.info("Database schema initialized.")


def get_session() -> Generator[Session, None, None]:
    """Provides a database session context."""
    with Session(engine) as session:
        yield session


def insert_task(
    action_title: str,
    trigger_source: str = "SLACK_INTENT",
    status: str = "COMPLETED",
    incoming_message: Optional[str] = None,
    ai_suggestion: Optional[str] = None,
    user_response: Optional[str] = None,
    final_response: Optional[str] = None,
) -> TaskRecord:
    """
    Inserts a newly executed task record with conversational history into the database.
    """
    with Session(engine) as session:
        task = TaskRecord(
            action_title=action_title,
            trigger_source=trigger_source,
            status=status,
            incoming_message=incoming_message,
            ai_suggestion=ai_suggestion,
            user_response=user_response,
            final_response=final_response,
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


def update_task_title(task_id: int, new_title: str) -> Optional[TaskRecord]:
    """
    Updates the action title of an existing task record.
    """
    with Session(engine) as session:
        task = session.get(TaskRecord, task_id)
        if task:
            task.action_title = new_title.strip() or "Untitled Task"
            session.add(task)
            session.commit()
            session.refresh(task)
            logger.info("Updated task #%s title to: %s", task_id, task.action_title)
            return task
    return None
