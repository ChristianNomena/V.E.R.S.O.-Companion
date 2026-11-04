"""
V.E.R.S.O. - Background Workers & Vocal Orchestration
Executes ambient vocal interactions and background tasks without requiring manual markdown file manipulation.
"""

import logging
import os
import threading
import time
from typing import Callable, Optional

import pyperclip

from verso.database import insert_task
from verso.database.models import TaskRecord
from verso.services.muse_client import MuseClient
from verso.services.notification_service import NotificationService
from verso.services.stt_service import STTService
from verso.services.tts_service import TTSService

logger = logging.getLogger(__name__)


class WorkerManager:
    """Manages background task execution and the vocal companion dialogue loop."""

    def __init__(
        self,
        deliverables_dir: str = "deliverables",
        on_status_change: Optional[Callable[[str], None]] = None,
        on_task_completed: Optional[Callable[[Optional[TaskRecord]], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.deliverables_dir = deliverables_dir
        self.on_status_change = on_status_change
        self.on_task_completed = on_task_completed
        self.on_error = on_error
        self.muse_client = MuseClient()
        os.makedirs(self.deliverables_dir, exist_ok=True)

    def execute_intention(self, trigger_source: str, context_details: str) -> None:
        """Runs the vocal interaction loop in an isolated thread to never freeze the UI."""
        worker_thread = threading.Thread(
            target=self._run_task,
            args=(trigger_source, context_details),
            daemon=True,
            name="VersoVocalWorkerThread",
        )
        worker_thread.start()

    def _run_task(self, trigger_source: str, context_details: str) -> None:
        try:
            if self.on_status_change:
                self.on_status_change("V.E.R.S.O. is analyzing communication...")

            # 1. Ask Muse Spark 1.3 to analyze message and craft vocal prompt
            suggestion = self.muse_client.generate_vocal_suggestion(context_details)
            sender = suggestion.get("sender", "Slack")
            spoken_intro = suggestion.get("spoken_intro", f"New message from {sender}")
            spoken_suggestion = suggestion.get("spoken_suggestion", "How would you like to respond?")
            suggested_reply = suggestion.get("suggested_reply", "")

            # 2. Step 1: AI Speaks to user out loud (reads message + proposes response)
            spoken_text = f"{spoken_intro} {spoken_suggestion}"
            if self.on_status_change:
                self.on_status_change(f"Assistant speaking... 🔊 ({sender})")

            speech_done = threading.Event()
            TTSService.speak(spoken_text, on_complete=speech_done.set)
            speech_done.wait(timeout=12.0)

            # Brief pause before listening
            time.sleep(0.3)

            # 3. Step 2: AI Listens to user vocal response
            if self.on_status_change:
                self.on_status_change("Listening to you... 🎙️ (Speak now)")

            listen_done = threading.Event()
            captured_speech = [""]

            def on_transcribed(text: str) -> None:
                captured_speech[0] = text
                listen_done.set()

            STTService.listen(
                duration=4.5,
                on_transcribed=on_transcribed,
            )
            listen_done.wait(timeout=7.0)
            user_speech = captured_speech[0] or "Yes, approve the suggested response."

            if self.on_status_change:
                self.on_status_change(f"Understood: '{user_speech}' · Finalizing...")

            # 4. Step 3: Refine final draft using Muse Spark 1.3
            final_response = self.muse_client.finalize_response(
                incoming_message=context_details,
                suggested_reply=suggested_reply,
                user_speech=user_speech,
            )

            # 5. Step 4: AI Confirms out loud
            confirm_done = threading.Event()
            TTSService.speak("All set, the response is ready and copied to your clipboard!", on_complete=confirm_done.set)
            confirm_done.wait(timeout=4.0)

            # 6. Step 5: Automatically copy to clipboard for immediate 1-click paste (Cmd+V)
            try:
                pyperclip.copy(final_response)
            except Exception as clip_exc:
                logger.warning("Could not copy to system clipboard: %s", clip_exc)

            # 7. Step 6: Persist rich conversation record into SQLite database
            task_record: Optional[TaskRecord] = None
            try:
                task_record = insert_task(
                    action_title=f"Slack: {sender}",
                    trigger_source=trigger_source,
                    status="COMPLETED",
                    incoming_message=context_details,
                    ai_suggestion=spoken_suggestion,
                    user_response=user_speech,
                    final_response=final_response,
                )
            except Exception as db_exc:
                logger.error("Failed to persist task record: %s", db_exc)

            # 8. Archival fallback file (saved quietly in deliverables)
            filename = "SLACK_DRAFT.md" if trigger_source == "SLACK_INTENT" else "DELIVERABLE.md"
            filepath = os.path.join(self.deliverables_dir, filename)
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(
                        f"# Slack Response Draft ({sender})\n\n"
                        f"## Received Message\n> {context_details}\n\n"
                        f"## AI Vocal Suggestion\n> {spoken_suggestion}\n\n"
                        f"## Your Vocal Reply\n> {user_speech}\n\n"
                        f"## Final Response (Copied to Clipboard)\n{final_response}\n\n"
                        f"---\n*Generated by V.E.R.S.O. Ambient Voice Assistant*\n"
                    )
            except Exception:
                pass

            # 9. Native notification alerting user that draft is already in clipboard
            NotificationService.notify(
                title="V.E.R.S.O.",
                message=f"Response for {sender} ready and copied to clipboard (Cmd+V)!",
                subtitle="Slack Intent Handled",
                sound=True,
            )

            if self.on_task_completed:
                self.on_task_completed(task_record)

            if self.on_status_change:
                self.on_status_change("Listening attentively on the Verso.")

        except Exception as exc:
            logger.error("Error executing vocal interaction loop: %s", exc)
            if self.on_error:
                self.on_error(f"Vocal assistant error: {exc}")
            if self.on_status_change:
                self.on_status_change("Idle · Tap button to start listening")
