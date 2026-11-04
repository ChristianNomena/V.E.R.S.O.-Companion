"""
V.E.R.S.O. - Database Models (Pillar 1: The Inverse OS)
Defines the local data model for tracking Slack intentions and background executions.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class TaskRecord(SQLModel, table=True):
    """Represents a background task executed silently on the Verso."""

    __tablename__ = "task_record"

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    trigger_source: str = Field(
        default="SLACK_INTENT",
        nullable=False,
        description="Source of the trigger, e.g. SLACK_INTENT",
    )
    action_title: str = Field(
        ...,
        nullable=False,
        description="Concise descriptive title of the action performed",
    )
    status: str = Field(
        default="COMPLETED",
        nullable=False,
        description="Completion status, e.g. COMPLETED",
    )
