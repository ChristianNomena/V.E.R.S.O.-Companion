"""
V.E.R.S.O. - Background Workers
Executes autonomous ghost tasks on the Verso in non-blocking background threads.
"""

import logging
import os
import threading
from typing import Callable, Optional

from verso.database import insert_task
from verso.services.muse_client import MuseClient
from verso.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class WorkerManager:
    """Manages background task execution threads."""

    def __init__(
        self,
        deliverables_dir: str = "deliverables",
        on_status_change: Optional[Callable[[str], None]] = None,
        on_task_completed: Optional[Callable[[], None]] = None,
    ) -> None:
        self.deliverables_dir = deliverables_dir
        self.on_status_change = on_status_change
        self.on_task_completed = on_task_completed
        self.muse_client = MuseClient()
        os.makedirs(self.deliverables_dir, exist_ok=True)

    def execute_intention(self, trigger_source: str, context_details: str) -> None:
        """Runs the background task in an isolated thread to never block the user."""
        worker_thread = threading.Thread(
            target=self._run_task,
            args=(trigger_source, context_details),
            daemon=True,
            name="VersoWorkerThread",
        )
        worker_thread.start()

    def _run_task(self, trigger_source: str, context_details: str) -> None:
        try:
            if self.on_status_change:
                self.on_status_change(f"Verso at work: processing {trigger_source}...")

            # 1. Ask Muse AI (or mock fallback)
            prompt = f"Analyze incoming message and draft response: {context_details}"
            result = self.muse_client.generate_response(prompt, context=context_details)

            # 2. Write deliverable file (SLACK_DRAFT.md for Slack intentions)
            filename = (
                "SLACK_DRAFT.md"
                if trigger_source == "SLACK_INTENT"
                else "DELIVERABLE.md"
            )
            filepath = os.path.join(self.deliverables_dir, filename)

            content = result.get(
                "content",
                f"# V.E.R.S.O. Deliverable\n\nGenerated for {context_details}\n",
            )
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

            # 3. Persist executed task record to database
            action_title = result.get(
                "action_title",
                "Drafted Slack Response" if trigger_source == "SLACK_INTENT" else "Backstage Task",
            )
            try:
                insert_task(
                    action_title=action_title,
                    trigger_source=trigger_source,
                    status="COMPLETED",
                )
            except Exception as db_exc:
                logger.error("Failed to persist task record: %s", db_exc)

            notification_text = result.get(
                "notification",
                f"Deliverable ready in {self.deliverables_dir}/{filename}",
            )

            # 3. Notify user with native macOS banner and chime
            NotificationService.notify(
                title="V.E.R.S.O.",
                message=notification_text,
                subtitle="Slack Intent Handled"
                if trigger_source == "SLACK_INTENT"
                else "Backstage Task Ready",
                sound=True,
            )

            if self.on_status_change:
                self.on_status_change("Listening attentively on the Verso.")

            if self.on_task_completed:
                self.on_task_completed()

        except Exception as exc:
            logger.error("Error executing background worker task: %s", exc)
            if self.on_status_change:
                self.on_status_change("Error during backstage execution.")
