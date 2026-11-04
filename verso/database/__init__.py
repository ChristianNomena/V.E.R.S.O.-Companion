"""
V.E.R.S.O. - Database Package
"""

from verso.database.database import (
    count_session_snapshots,
    engine,
    get_recent_snapshots,
    get_recent_tasks,
    get_session,
    get_session_interactions,
    init_db,
    insert_interaction,
    insert_snapshot,
    insert_task,
    mark_interaction_read,
    purge_all_companion_data,
    purge_session,
    update_task_title,
)
from verso.database.models import CompanionInteraction, ContextSnapshot, TaskRecord

__all__ = [
    "engine",
    "init_db",
    "get_session",
    "insert_task",
    "get_recent_tasks",
    "update_task_title",
    "TaskRecord",
    "ContextSnapshot",
    "CompanionInteraction",
    "insert_snapshot",
    "get_recent_snapshots",
    "count_session_snapshots",
    "purge_session",
    "purge_all_companion_data",
    "insert_interaction",
    "get_session_interactions",
    "mark_interaction_read",
]
