"""
V.E.R.S.O. - Sentinel Engine
Orchestrates background sensors (notifications, clipboard, window) and applies cooldown rules
before triggering autonomous background workers.
"""

import logging
import threading
import time
from typing import Callable, Optional, Tuple

from verso.sentinel.clipboard_sensor import ClipboardSensor
from verso.sentinel.notification_sensor import NotificationSensor
from verso.sentinel.window_sensor import WindowSensor

logger = logging.getLogger(__name__)


class Sentinel:
    """
    Background system monitor that observes incoming notifications,
    active window contexts, and clipboard changes.
    """

    def __init__(
        self,
        poll_interval: float = 1.5,
        cooldown_seconds: float = 10.0,
        on_context_detected: Optional[Callable[[str, str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_state_change: Optional[Callable[[bool], None]] = None,
        is_busy_fn: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.poll_interval = poll_interval
        self.cooldown_seconds = cooldown_seconds
        self.on_context_detected = on_context_detected
        self.on_error = on_error
        self.on_state_change = on_state_change
        self.is_busy_fn = is_busy_fn

        self.notification_sensor = NotificationSensor(on_error=self._handle_sensor_error)
        self.clipboard_sensor = ClipboardSensor()
        self._is_running = False
        self._thread: Optional[threading.Thread] = None

        self._last_detected_key: str = ""
        self._last_trigger_time: float = 0.0

    def _handle_sensor_error(self, error_msg: str) -> None:
        if error_msg:
            logger.warning("Sensor error encountered: %s", error_msg)
            if self.on_error:
                self.on_error(error_msg)
            if self._is_running:
                self.stop()
        else:
            if self.on_error:
                self.on_error("")

    @property
    def is_running(self) -> bool:
        return self._is_running

    def check_readiness(self) -> Tuple[bool, str]:
        """Checks if sensors are authorized and ready to begin monitoring."""
        return self.notification_sensor.check_permission()

    def start(self) -> Tuple[bool, str]:
        """
        Attempts to start the sentinel loop in a background thread.
        Returns (True, "") on success, or (False, error_reason) if blocked by permission/error.
        """
        if self._is_running:
            return True, ""

        ok, reason = self.check_readiness()
        if not ok:
            logger.warning("V.E.R.S.O. Sentinel blocked from starting: %s", reason)
            if self.on_error:
                self.on_error(reason)
            return False, reason

        self._is_running = True
        self.notification_sensor.initialize_baseline()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="VersoSentinelThread"
        )
        self._thread.start()
        logger.info("V.E.R.S.O. Sentinel started.")
        if self.on_state_change:
            self.on_state_change(True)
        return True, ""

    def stop(self) -> None:
        """Stops the background sentinel."""
        was_running = self._is_running
        self._is_running = False
        if self._thread and self._thread.is_alive():
            if threading.current_thread() != self._thread:
                self._thread.join(timeout=1.0)
        logger.info("V.E.R.S.O. Sentinel stopped.")
        if was_running and self.on_state_change:
            self.on_state_change(False)

    def _loop(self) -> None:
        while self._is_running:
            try:
                self._tick()
            except Exception as exc:
                logger.error("Error in sentinel tick: %s", exc)
                if self.on_error:
                    self.on_error(f"Sensor error: {exc}")
                self.stop()
                break
            time.sleep(self.poll_interval)

    def _tick(self) -> None:
        # If the assistant is currently speaking or processing a dialogue, never trigger new actions
        if self.is_busy_fn and self.is_busy_fn():
            return

        now = time.time()
        # Cooldown guard: must wait at least cooldown_seconds between any two triggers
        if now - self._last_trigger_time < self.cooldown_seconds:
            return

        # 1. Highest Priority: Incoming Slack Notification from Notification Center or Browser
        slack_notifs = self.notification_sensor.get_new_slack_notifications()
        for notif in slack_notifs:
            sender = notif.get("title") or "Slack"
            body = notif.get("body") or ""
            payload = f"From {sender}: {body}"

            cache_key = f"slack_notif:{notif.get('rec_id')}:{body}"
            if cache_key != self._last_detected_key:
                self._last_detected_key = cache_key
                self._last_trigger_time = now
                if self.on_context_detected:
                    self.on_context_detected("SLACK_INTENT", payload)
                return

        # 2. Secondary Priority: Clipboard Sensor (e.g. copied message while in Slack)
        new_clipboard = self.clipboard_sensor.get_new_content()
        if new_clipboard:
            window_info = WindowSensor.get_active_window()
            source = (
                "SLACK_INTENT"
                if "slack" in window_info.app_name.lower()
                else "CLIPBOARD"
            )

            cache_key = f"{source}:{new_clipboard}"
            if cache_key != self._last_detected_key:
                self._last_detected_key = cache_key
                self._last_trigger_time = now
                if self.on_context_detected:
                    self.on_context_detected(source, new_clipboard)
                return

        # 3. Ambient Window Sensor (monitoring)
        window_info = WindowSensor.get_active_window()
        if (
            not window_info.is_empty
            and window_info.app_name not in ("Antigravity", "V.E.R.S.O.", "Python")
        ):
            # Only trigger window context if it transitions significantly
            cache_key = f"window:{window_info.app_name}:{window_info.window_title}"
            if cache_key != self._last_detected_key and (
                now - self._last_trigger_time > self.cooldown_seconds * 2
            ):
                self._last_detected_key = cache_key
                self._last_trigger_time = now
                # Kept passive; does not override Slack intention
