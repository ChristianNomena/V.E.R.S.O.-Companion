"""
V.E.R.S.O. - Database Models
Defines the local data model for tracking Slack intentions and background executions.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class TaskRecord(SQLModel, table=True):
    """Represents a background task or vocal interaction executed on the Verso."""

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
        default="Slack Response Handled",
        nullable=False,
        description="Concise descriptive title of the action performed",
    )
    incoming_message: Optional[str] = Field(
        default=None,
        description="Incoming communication content detected",
    )
    ai_suggestion: Optional[str] = Field(
        default=None,
        description="The spoken suggestion proposed by the assistant",
    )
    user_response: Optional[str] = Field(
        default=None,
        description="The vocal command or response spoken by the user",
    )
    final_response: Optional[str] = Field(
        default=None,
        description="The final ready-to-send drafted response",
    )
    status: str = Field(
        default="COMPLETED",
        nullable=False,
        description="Completion status, e.g. COMPLETED",
    )
