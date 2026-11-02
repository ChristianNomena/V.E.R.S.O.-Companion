"""
V.E.R.S.O. - Background Workers
Executes autonomous ghost tasks on the Verso in non-blocking background threads.
"""

import logging
import os
import threading
from datetime import datetime
from typing import Callable, Optional

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
                self.on_status_change(f"Verso at work: analyzing {trigger_source}...")

            # 1. Ask Muse AI (or mock fallback)
            prompt = f"Generate proactive assistance for the user regarding: {context_details}"
            result = self.muse_client.generate_response(prompt, context=context_details)

            # 2. Write deliverable file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"deliverable_{timestamp}.md"
            filepath = os.path.join(self.deliverables_dir, filename)

            content = result.get("content", f"# V.E.R.S.O. Deliverable\n\nGenerated for {context_details}\n")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

            notification_text = result.get("notification", "V.E.R.S.O. has completed a background task.")

            # 3. Notify user (native notification)
            NotificationService.notify(
                title="V.E.R.S.O.",
                message=notification_text,
                subtitle="Backstage deliverable ready",
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
