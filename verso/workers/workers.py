"""
V.E.R.S.O. - Background Workers & Vocal Orchestration
Executes ambient vocal interactions and background tasks without requiring manual markdown file manipulation.
"""

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

import pyperclip

from verso.database import insert_task
from verso.database.models import TaskRecord
from verso.sentinel.clipboard_sensor import ClipboardSensor
from verso.services.muse_client import MuseClient
from verso.services.notification_service import NotificationService
from verso.services.sound_service import SoundService
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
        on_quick_replies: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_speech_state: Optional[Callable[[bool, bool], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        voice_enabled: bool = True,
    ) -> None:
        self.deliverables_dir = deliverables_dir
        self.on_status_change = on_status_change
        self.on_task_completed = on_task_completed
        self.on_quick_replies = on_quick_replies
        self.on_speech_state = on_speech_state
        self.on_error = on_error
        self.voice_enabled = voice_enabled
        self.muse_client = MuseClient()
        self._is_busy: bool = False
        self._busy_lock = threading.Lock()
        self._cancel_event = threading.Event()
        os.makedirs(self.deliverables_dir, exist_ok=True)

    def cancel_current(self) -> None:
        """Cancels the in-flight vocal interaction: speech and recording stop
        immediately and the worker aborts at its next checkpoint."""
        self._cancel_event.set()
        TTSService.stop()
        STTService.stop()

    def _cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def is_busy(self) -> bool:
        """Returns True if a vocal dialogue interaction is currently running."""
        with self._busy_lock:
            return self._is_busy

    @staticmethod
    def _parse_sender_and_message(context_details: str) -> Tuple[str, str]:
        sender = ""
        clean_msg = context_details.strip()
        if "From " in clean_msg and ":" in clean_msg:
            try:
                parts = clean_msg.split("From ", 1)[1].split(":", 1)
                sender = parts[0].strip()
                clean_msg = parts[1].strip()
            except Exception:
                pass

        # Strip notification application wrappers like "Slack | Alice", "Slack - Alice", "Slack: Alice"
        for prefix in ("Slack |", "Slack -", "Slack:", "Slack"):
            if sender.startswith(prefix):
                sender = sender[len(prefix):].strip()

        if not sender or sender.lower() in ("slack", "someone"):
            if ":" in clean_msg:
                possible_name, rem = clean_msg.split(":", 1)
                if 1 <= len(possible_name.split()) <= 4 and not possible_name.lower().startswith("http"):
                    sender = possible_name.strip()
                    clean_msg = rem.strip()

        for prefix in ("Slack |", "Slack -", "Slack:", "Slack"):
            if sender.startswith(prefix):
                sender = sender[len(prefix):].strip()

        if not sender:
            sender = "Someone"

        return sender, clean_msg

    def execute_intention(self, trigger_source: str, context_details: str) -> bool:
        """
        Runs the vocal interaction loop in an isolated thread to never freeze the UI.
        Guarantees single vocal interaction: drops incoming triggers if already busy.
        """
        with self._busy_lock:
            if self._is_busy:
                logger.info(
                    "Vocal dialogue already in progress. Ignoring concurrent intention: %s",
                    trigger_source,
                )
                return False
            self._is_busy = True
        self._cancel_event.clear()

        worker_thread = threading.Thread(
            target=self._run_task,
            args=(trigger_source, context_details),
            daemon=True,
            name="VersoVocalWorkerThread",
        )
        worker_thread.start()
        return True

    def _run_task(self, trigger_source: str, context_details: str) -> None:
        try:
            sender, clean_msg = self._parse_sender_and_message(context_details)

            # -------------------------------------------------------------
            # SILENT / QUICK RESPONSE MODE (Voice Deactivated)
            # -------------------------------------------------------------
            if not self.voice_enabled:
                if self.on_status_change:
                    self.on_status_change(f"Generating quick replies for {sender}...")

                quick_data = self.muse_client.generate_quick_replies(context_details)
                if self._cancelled():
                    return
                quick_payload = {
                    "sender": sender,
                    "message": clean_msg,
                    "context_details": context_details,
                    "trigger_source": trigger_source,
                    "summary": quick_data.get("summary", ""),
                    "options": quick_data.get("options", []),
                }

                if self.on_quick_replies:
                    self.on_quick_replies(quick_payload)

                SoundService.play_chime()
                NotificationService.notify(
                    title="V.E.R.S.O.",
                    message=f"Quick replies ready for {sender} · Choose an option",
                    subtitle="Quick Replies Ready",
                    sound=True,
                )

                if self.on_status_change:
                    self.on_status_change(f"Quick replies ready for {sender} · Choose an option")
                return

            # -------------------------------------------------------------
            # VOCAL INTERACTION MODE (Voice Activated)
            # -------------------------------------------------------------
            # 1. Formulate a single, natural conversational spoken prompt (no robotic instructions)
            if clean_msg.endswith("?"):
                vocal_prompt = f"{sender} asks: '{clean_msg}'. Would you like me to reply?"
            else:
                vocal_prompt = f"{sender} sent: '{clean_msg}'. Would you like to reply?"

            if self.on_status_change:
                self.on_status_change(f"Incoming message · {sender} 🔊")

            # 2. Assistant speaks the alert naturally in one single breath
            prompt_done = threading.Event()
            TTSService.speak(vocal_prompt, on_complete=prompt_done.set)
            prompt_done.wait(timeout=20.0)
            TTSService.stop()
            time.sleep(0.1)
            if self._cancelled():
                return

            # 3. Crisp audible chime signaling microphone opening
            SoundService.play_chime()
            time.sleep(0.15)

            # 4. Immediate visual status change: listening to user now
            if self.on_status_change:
                self.on_status_change("Listening to you... (Speak now) 🎙️")
            if self.on_speech_state:
                self.on_speech_state(True, False)

            listen_done = threading.Event()
            captured_speech = [""]

            def on_transcribed(text: str) -> None:
                captured_speech[0] = text
                listen_done.set()

            def on_speech_detected(is_speaking: bool) -> None:
                if self.on_speech_state:
                    self.on_speech_state(True, is_speaking)

            # 5. Capture user speech with generous duration (5.0s)
            STTService.listen(
                duration=5.0,
                on_speech_detected=on_speech_detected,
                on_transcribed=on_transcribed,
            )
            listen_done.wait(timeout=8.0)

            if self.on_speech_state:
                self.on_speech_state(False, False)
            if self._cancelled():
                return

            # 6. Audible confirmation pop signaling recording completion
            SoundService.play_done()
            user_speech = captured_speech[0] or "Yes, approve."

            if self.on_status_change:
                self.on_status_change(f"Understood: '{user_speech}' · Drafting with Muse...")

            # 7. Refine final draft using Muse based on user's exact words
            final_response = self.muse_client.finalize_response(
                incoming_message=context_details,
                suggested_reply=f"Hi {sender}, thank you for reaching out! I am taking care of this and will follow up shortly.",
                user_speech=user_speech,
            )

            if self._cancelled():
                return

            # 8. AI confirms out loud in one short sentence
            confirm_done = threading.Event()
            TTSService.speak("All set, the response is copied to your clipboard!", on_complete=confirm_done.set)
            confirm_done.wait(timeout=8.0)
            TTSService.stop()
            time.sleep(0.1)

            # 9. Copy to clipboard for immediate 1-click paste (Cmd+V)
            ClipboardSensor.ignore_content(final_response)
            try:
                pyperclip.copy(final_response)
            except Exception as clip_exc:
                logger.warning("Could not copy to system clipboard: %s", clip_exc)

            # 10. Persist rich conversation record into SQLite database
            task_record: Optional[TaskRecord] = None
            try:
                task_record = insert_task(
                    action_title=f"{sender}",
                    trigger_source=trigger_source,
                    status="COMPLETED",
                    incoming_message=context_details,
                    ai_suggestion=vocal_prompt,
                    user_response=user_speech,
                    final_response=final_response,
                )
            except Exception as db_exc:
                logger.error("Failed to persist task record: %s", db_exc)

            # 11. Archival deliverable file
            filename = "SLACK_DRAFT.md" if trigger_source == "SLACK_INTENT" else "DELIVERABLE.md"
            filepath = os.path.join(self.deliverables_dir, filename)
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(
                        f"# Response Draft ({sender})\n\n"
                        f"## Received Message\n> {context_details}\n\n"
                        f"## Spoken Prompt\n> {vocal_prompt}\n\n"
                        f"## Your Vocal Reply\n> {user_speech}\n\n"
                        f"## Final Response (Copied to Clipboard)\n{final_response}\n\n"
                        f"---\n*Generated by V.E.R.S.O. Ambient Voice Assistant*\n"
                    )
            except Exception:
                pass

            # 12. Native notification alerting user that draft is already in clipboard
            NotificationService.notify(
                title="V.E.R.S.O.",
                message=f"Response for {sender} ready and copied to clipboard (Cmd+V)!",
                subtitle="Response Ready",
                sound=True,
            )

            if self.on_task_completed:
                self.on_task_completed(task_record)

            if self.on_status_change:
                self.on_status_change("Listening")

        except Exception as exc:
            logger.error("Error executing vocal interaction loop: %s", exc)
            if self.on_error:
                self.on_error(f"Vocal assistant error: {exc}")
            if self.on_status_change:
                self.on_status_change("Idle · Tap button to start listening")
        finally:
            with self._busy_lock:
                self._is_busy = False
