"""
V.E.R.S.O. - Database Engine & Operations
Agnostic database connection supporting SQLite multi-threading and CRUD functions.
Covers Pillar 1 task records and Pillar 2 companion session memory.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Generator, List, Optional
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from verso.config import DATABASE_URL
from verso.database.models import CompanionInteraction, ContextSnapshot, TaskRecord

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


# ---------------------------------------------------------------------------
# Pillar 2: Benevolent Partner session memory (no persistence across sessions)
# ---------------------------------------------------------------------------

def insert_snapshot(
    session_id: str,
    app_name: str,
    window_title: str,
    clipboard_text: Optional[str] = None,
    screenshot_path: Optional[str] = None,
) -> ContextSnapshot:
    """Records one consented observation snapshot for the active session."""
    with Session(engine) as session:
        snapshot = ContextSnapshot(
            session_id=session_id,
            app_name=app_name or "",
            window_title=window_title or "",
            clipboard_text=clipboard_text,
            screenshot_path=screenshot_path,
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        return snapshot


def get_recent_snapshots(
    session_id: str,
    window_minutes: int = 15,
    limit: int = 60,
) -> List[ContextSnapshot]:
    """
    Reads the session activity in chronological order (sliding window).

    Only snapshots within the last ``window_minutes`` are returned so the
    context sent to the AI stays small and fast.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, window_minutes))
    with Session(engine) as session:
        statement = (
            select(ContextSnapshot)
            .where(
                ContextSnapshot.session_id == session_id,
                ContextSnapshot.timestamp >= cutoff,
            )
            .order_by(ContextSnapshot.timestamp.asc())
            .limit(max(1, limit))
        )
        return list(session.exec(statement).all())


def count_session_snapshots(session_id: str) -> int:
    """Counts all snapshots recorded for a session (whatever their age)."""
    with Session(engine) as session:
        statement = select(ContextSnapshot.id).where(ContextSnapshot.session_id == session_id)
        return len(list(session.exec(statement).all()))


def purge_session(session_id: str) -> None:
    """Deletes every snapshot and interaction of a session (session-only memory)."""
    with Session(engine) as session:
        snapshots = session.exec(
            select(ContextSnapshot).where(ContextSnapshot.session_id == session_id)
        ).all()
        for snapshot in snapshots:
            session.delete(snapshot)
        interactions = session.exec(
            select(CompanionInteraction).where(CompanionInteraction.session_id == session_id)
        ).all()
        for interaction in interactions:
            session.delete(interaction)
        session.commit()
    logger.info("Companion session '%s' purged.", session_id)


def purge_all_companion_data() -> None:
    """Deletes every companion snapshot and interaction (stale sessions cleanup)."""
    with Session(engine) as session:
        for snapshot in session.exec(select(ContextSnapshot)).all():
            session.delete(snapshot)
        for interaction in session.exec(select(CompanionInteraction)).all():
            session.delete(interaction)
        session.commit()
    logger.info("All companion session data purged.")


def insert_interaction(
    session_id: str,
    interaction_type: str,
    message: str,
    question: Optional[str] = None,
    status: str = "UNREAD",
) -> CompanionInteraction:
    """Logs a spontaneous or on-demand exchange with the companion."""
    with Session(engine) as session:
        interaction = CompanionInteraction(
            session_id=session_id,
            interaction_type=interaction_type,
            message=message,
            question=question,
            status=status,
        )
        session.add(interaction)
        session.commit()
        session.refresh(interaction)
        return interaction


def get_session_interactions(session_id: str, limit: int = 50) -> List[CompanionInteraction]:
    """Retrieves the exchanges of a session in chronological order."""
    with Session(engine) as session:
        statement = (
            select(CompanionInteraction)
            .where(CompanionInteraction.session_id == session_id)
            .order_by(CompanionInteraction.timestamp.asc())
            .limit(max(1, limit))
        )
        return list(session.exec(statement).all())


def mark_interaction_read(interaction_id: int) -> None:
    """Marks an interaction as read."""
    with Session(engine) as session:
        interaction = session.get(CompanionInteraction, interaction_id)
        if interaction and interaction.status != "READ":
            interaction.status = "READ"
            session.add(interaction)
            session.commit()
