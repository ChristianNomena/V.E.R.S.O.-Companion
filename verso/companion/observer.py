"""
V.E.R.S.O. - Benevolent Partner Observer (Pillar 2)
Consented observation loop over what the user looks at (active app/window,
screenshots, clipboard), with session-only memory and an anti-noise
spontaneous decision filter. Runs on its own thread, independent from Pillar 1.
"""

import logging
import os
import platform
import threading
import time
import uuid
from typing import Callable, List, Optional, Tuple

import pyperclip

from verso.config import (
    COMPANION_CONTEXT_WINDOW_MINUTES,
    COMPANION_MAX_ASK_IMAGES,
    COMPANION_MAX_CLIPBOARD_CHARS,
    COMPANION_MIN_SNAPSHOTS_FOR_SPONTANEOUS,
    COMPANION_OBSERVE_INTERVAL_SECONDS,
    COMPANION_SPONTANEOUS_EVERY_N_TICKS,
    COMPANION_SPONTANEOUS_MIN_INTERVAL_SECONDS,
)
from verso.database import (
    count_session_snapshots,
    get_recent_snapshots,
    insert_interaction,
    insert_snapshot,
    purge_all_companion_data,
    purge_session,
)
from verso.database.models import ContextSnapshot
from verso.sentinel.clipboard_sensor import ClipboardSensor
from verso.sentinel.screenshot_sensor import ScreenshotSensor
from verso.sentinel.window_sensor import WindowSensor
from verso.services.muse_client import MuseClient

logger = logging.getLogger(__name__)

SPONTANEOUS = "SPONTANEOUS"
ASKED = "ASKED"


# Apps never recorded: our own windows (and the dev harness) are not user activity.
EXCLUDED_OBSERVATION_APPS = frozenset(
    {"V.E.R.S.O.", "verso", "Python", "python", "python3", "Flet", "flet"}
)


def _snapshot_time(snap: ContextSnapshot) -> str:
    ts = snap.timestamp
    return ts.strftime("%H:%M:%S") if hasattr(ts, "strftime") else str(ts)


def format_timeline(snapshots: List[ContextSnapshot]) -> str:
    """Renders ordered snapshots as a compact, LLM-friendly chronology.

    Consecutive snapshots of the same app + window collapse into one timed run
    so the model sees activity spans instead of repeated identical lines.
    """
    lines: List[str] = []
    run: List[ContextSnapshot] = []

    def flush() -> None:
        if not run:
            return
        first = run[0]
        app = first.app_name or "?"
        title = first.window_title or "(untitled)"
        if len(run) == 1:
            head = f"[{_snapshot_time(first)}]"
        else:
            head = f"[{_snapshot_time(first)} → {_snapshot_time(run[-1])}] (x{len(run)})"
        line = f"{head} {app} — {title}"
        clips: List[str] = []
        for snap in run:
            if snap.clipboard_text:
                excerpt = " ".join(snap.clipboard_text.split())[:120]
                if excerpt and excerpt not in clips:
                    clips.append(excerpt)
            if len(clips) >= 2:
                break
        if clips:
            line += ' | clipboard: "' + '" / "'.join(clips) + '"'
        if any(snap.screenshot_path for snap in run):
            line += " | [screenshot]"
        lines.append(line)

    for snap in snapshots:
        if run and (snap.app_name, snap.window_title) == (run[-1].app_name, run[-1].window_title):
            run.append(snap)
        else:
            flush()
            run = [snap]
    flush()
    return "\n".join(lines)


class CompanionObserver:
    """
    Background observer for the Benevolent Partner mode.

    Records a snapshot every ``observe_interval`` seconds while observing,
    evaluates spontaneous interventions on a slower cadence, and answers
    on-demand questions from the session timeline.
    """

    def __init__(
        self,
        observe_interval: float = COMPANION_OBSERVE_INTERVAL_SECONDS,
        spontaneous_min_interval: float = COMPANION_SPONTANEOUS_MIN_INTERVAL_SECONDS,
        spontaneous_every_n_ticks: int = COMPANION_SPONTANEOUS_EVERY_N_TICKS,
        context_window_minutes: int = COMPANION_CONTEXT_WINDOW_MINUTES,
        on_spontaneous: Optional[Callable[[str], None]] = None,
        on_snapshot: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        muse_client: Optional[MuseClient] = None,
    ) -> None:
        self.observe_interval = max(5.0, observe_interval)
        self.spontaneous_min_interval = max(0.0, spontaneous_min_interval)
        self.spontaneous_every_n_ticks = max(1, spontaneous_every_n_ticks)
        self.context_window_minutes = max(1, context_window_minutes)
        self.on_spontaneous = on_spontaneous
        self.on_snapshot = on_snapshot
        self.on_error = on_error
        self._muse = muse_client or MuseClient()

        self.session_id = uuid.uuid4().hex[:8]
        self._is_observing = False
        self._spontaneity_enabled = True
        self._screenshots_enabled = True
        self._screenshot_failures = 0
        self._screenshot_warned = False
        self._thread: Optional[threading.Thread] = None
        self._tick_count = 0
        self._last_spontaneous_time = 0.0
        self._last_clipboard = ""
        self._eval_in_progress = False
        self._eval_lock = threading.Lock()

    @property
    def is_observing(self) -> bool:
        return self._is_observing

    @property
    def spontaneity_enabled(self) -> bool:
        return self._spontaneity_enabled

    def set_spontaneity(self, enabled: bool) -> None:
        """Enables or cuts spontaneous interventions (observation keeps running)."""
        self._spontaneity_enabled = bool(enabled)
        logger.info("Companion spontaneity %s.", "enabled" if enabled else "disabled")

    def start(self) -> Tuple[bool, str]:
        """
        Starts a fresh observation session (previous session data is purged).
        Returns (True, "") on success, or (False, error_reason) if blocked.
        """
        if self._is_observing:
            return True, ""

        try:
            purge_all_companion_data()
            ScreenshotSensor.cleanup_all()
        except Exception as exc:
            logger.warning("Companion cleanup before start failed: %s", exc)

        self.session_id = uuid.uuid4().hex[:8]
        self._tick_count = 0
        self._last_spontaneous_time = 0.0
        self._screenshot_failures = 0
        self._screenshot_warned = False
        self._screenshots_enabled = True
        self._last_clipboard = self._read_clipboard()

        # Screenshot probe: on macOS a failure almost always means the
        # Screen Recording permission is missing. Observation continues
        # without screenshots, with a clear message.
        probe = ScreenshotSensor.capture(self.session_id)
        if probe is not None:
            try:
                os.remove(probe)
            except OSError:
                pass
        elif platform.system() == "Darwin":
            self._screenshots_enabled = False
            self._screenshot_warned = True
            reason = (
                "The 'Screen Recording' permission is required for screenshots. "
                "Observation continues without screenshots."
            )
            logger.warning(reason)
            if self.on_error:
                self.on_error(reason)

        self._is_observing = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="VersoCompanionThread"
        )
        self._thread.start()
        logger.info("Companion observation started (session %s).", self.session_id)
        return True, ""

    def stop(self, purge: bool = True) -> None:
        """Stops observation and purges the session memory (snapshots, captures, exchanges)."""
        was_observing = self._is_observing
        self._is_observing = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if was_observing and purge:
            try:
                purge_session(self.session_id)
                ScreenshotSensor.cleanup_session(self.session_id)
            except Exception as exc:
                logger.warning("Companion purge on stop failed: %s", exc)
        logger.info("Companion observation stopped.")

    def get_timeline_text(self) -> str:
        """Builds the compact chronology of recent activity for the AI."""
        try:
            snapshots = get_recent_snapshots(
                self.session_id, window_minutes=self.context_window_minutes
            )
        except Exception as exc:
            logger.warning("Timeline read failed: %s", exc)
            return ""
        body = format_timeline(snapshots)
        if not body.strip():
            return ""
        return (
            f"Observed activity, oldest to newest "
            f"({len(snapshots)} snapshots, last {self.context_window_minutes} min):\n{body}"
        )

    def _recent_screenshot_paths(self, limit: int = 2) -> List[str]:
        """Latest existing screenshot files for vision answers (newest last)."""
        try:
            snapshots = get_recent_snapshots(
                self.session_id, window_minutes=self.context_window_minutes
            )
        except Exception:
            return []
        paths: List[str] = []
        for snap in reversed(snapshots):
            if snap.screenshot_path and os.path.isfile(snap.screenshot_path):
                if snap.screenshot_path not in paths:
                    paths.append(snap.screenshot_path)
            if len(paths) >= max(1, limit):
                break
        return list(reversed(paths))

    def ask(self, question: str, on_delta=None) -> str:
        """
        Answers an on-demand question from the session timeline and logs it.
        Safe to call from a worker thread; never raises for AI failures.
        When ``on_delta`` is given, answer chunks are forwarded as they are
        generated (streaming) so the UI can show the reply early.
        """
        question = (question or "").strip() or "What do you think?"
        timeline = self.get_timeline_text()
        if not timeline.strip():
            if question.lower().rstrip("?") in ("what do you think", ""):
                return (
                    "I have not observed anything yet in this session. "
                    "Enable observation and let me watch your activity for a few "
                    "moments, then ask me again."
                )
            timeline = "No specific window activity observed yet in this session (system idle)."
        screenshots = self._recent_screenshot_paths(limit=COMPANION_MAX_ASK_IMAGES)
        answer = self._muse.ask_companion(
            timeline, question, image_paths=screenshots, on_delta=on_delta
        )
        try:
            insert_interaction(self.session_id, ASKED, answer, question=question)
        except Exception as exc:
            logger.warning("Failed to log companion exchange: %s", exc)
        return answer

    def _loop(self) -> None:
        while self._is_observing:
            try:
                self._tick()
            except Exception as exc:
                logger.error("Error in companion tick: %s", exc)
                if self.on_error:
                    self.on_error(f"Observation error: {exc}")
            # Sleep in small slices so stop() reacts quickly.
            slices = max(1, int(self.observe_interval * 2))
            for _ in range(slices):
                if not self._is_observing:
                    break
                time.sleep(0.5)

    def _tick(self) -> None:
        self._tick_count += 1

        window = WindowSensor.get_active_window()
        if window.app_name in EXCLUDED_OBSERVATION_APPS:
            # Never record our own windows: they are not user activity.
            if self.on_snapshot:
                try:
                    self.on_snapshot(f"{window.display_text[:60]} (skipped)")
                except Exception:
                    pass
            return

        clipboard = self._read_clipboard()
        new_clip: Optional[str] = None
        if (
            clipboard
            and clipboard != self._last_clipboard
            and not ClipboardSensor.is_ignored(clipboard)
        ):
            new_clip = clipboard[:COMPANION_MAX_CLIPBOARD_CHARS]
        if clipboard:
            self._last_clipboard = clipboard

        screenshot: Optional[str] = None
        if self._screenshots_enabled:
            screenshot = ScreenshotSensor.capture(self.session_id)
            if screenshot is None:
                self._screenshot_failures += 1
                if self._screenshot_failures >= 3 and not self._screenshot_warned:
                    self._screenshot_warned = True
                    self._screenshots_enabled = False
                    reason = (
                        "Screenshots unavailable ('Screen Recording' permission?). "
                        "Observation continues without screenshots."
                    )
                    logger.warning(reason)
                    if self.on_error:
                        self.on_error(reason)
            else:
                self._screenshot_failures = 0

        try:
            insert_snapshot(
                self.session_id,
                window.app_name,
                window.window_title,
                clipboard_text=new_clip,
                screenshot_path=screenshot,
            )
        except Exception as exc:
            logger.error("Failed to record companion snapshot: %s", exc)

        if self.on_snapshot:
            try:
                self.on_snapshot(window.display_text[:80])
            except Exception:
                pass

        self._maybe_evaluate_spontaneous()

    def _maybe_evaluate_spontaneous(self) -> None:
        """Throttled trigger for the anti-noise spontaneous evaluation."""
        if not self._spontaneity_enabled:
            return
        if self._tick_count % self.spontaneous_every_n_ticks != 0:
            return
        if time.time() - self._last_spontaneous_time < self.spontaneous_min_interval:
            return
        with self._eval_lock:
            if self._eval_in_progress:
                return
            self._eval_in_progress = True
        # Evaluated off the observation cadence so a slow API never delays snapshots.
        threading.Thread(target=self._evaluate_spontaneous, daemon=True).start()

    def _evaluate_spontaneous(self) -> None:
        try:
            try:
                snapshot_count = count_session_snapshots(self.session_id)
            except Exception:
                snapshot_count = 0
            if snapshot_count < COMPANION_MIN_SNAPSHOTS_FOR_SPONTANEOUS:
                return
            timeline = self.get_timeline_text()
            if not timeline.strip():
                return
            result = self._muse.evaluate_spontaneous(timeline)
            message = str(result.get("message", "")).strip()
            if not result.get("speak") or not message:
                return
            self._last_spontaneous_time = time.time()
            try:
                insert_interaction(self.session_id, SPONTANEOUS, message)
            except Exception as exc:
                logger.warning("Failed to log spontaneous intervention: %s", exc)
            if self.on_spontaneous:
                try:
                    self.on_spontaneous(message)
                except Exception:
                    pass
        finally:
            with self._eval_lock:
                self._eval_in_progress = False

    @staticmethod
    def _read_clipboard() -> str:
        """Non-consuming clipboard read (never interferes with Pillar 1)."""
        try:
            return pyperclip.paste() or ""
        except Exception:
            return ""
