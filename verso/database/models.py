"""
V.E.R.S.O. - Database Models
Defines the local data model for tracking Slack intentions, background executions,
and the Benevolent Partner session memory (Pillar 2).
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


class ContextSnapshot(SQLModel, table=True):
    """One consented observation snapshot of user activity (Pillar 2, session-only)."""

    __tablename__ = "context_snapshot"

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    session_id: str = Field(nullable=False, index=True)
    app_name: str = Field(default="", nullable=False)
    window_title: str = Field(default="", nullable=False)
    clipboard_text: Optional[str] = Field(
        default=None,
        description="Clipboard content at capture time, stored only when it changed",
    )
    screenshot_path: Optional[str] = Field(
        default=None,
        description="Local path of the session screenshot (purged with the session)",
    )


class CompanionInteraction(SQLModel, table=True):
    """Spontaneous or on-demand exchanges with the companion (Pillar 2, session-only)."""

    __tablename__ = "companion_interaction"

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    session_id: str = Field(nullable=False, index=True)
    interaction_type: str = Field(
        nullable=False,
        description="'SPONTANEOUS' or 'ASKED'",
    )
    message: str = Field(
        nullable=False,
        description="Advice or opinion formulated by V.E.R.S.O.",
    )
    question: Optional[str] = Field(
        default=None,
        description="User question for ASKED interactions",
    )
    status: str = Field(
        default="UNREAD",
        nullable=False,
        description="Notification/read status, e.g. UNREAD or READ",
    )
