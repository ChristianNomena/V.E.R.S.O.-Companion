"""
V.E.R.S.O. - Sentinel Engine
Orchestrates background sensors (notifications, clipboard, window) and applies cooldown rules
before triggering autonomous background workers.
"""

import logging
import threading
import time
from typing import Callable, Optional

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
        cooldown_seconds: float = 20.0,
        on_context_detected: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.poll_interval = poll_interval
        self.cooldown_seconds = cooldown_seconds
        self.on_context_detected = on_context_detected

        self.notification_sensor = NotificationSensor()
        self.clipboard_sensor = ClipboardSensor()
        self._is_running = False
        self._thread: Optional[threading.Thread] = None

        self._last_detected_key: str = ""
        self._last_trigger_time: float = 0.0

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self) -> None:
        """Starts the sentinel loop in a background thread."""
        if self._is_running:
            return
        self._is_running = True
        self.notification_sensor.initialize_baseline()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="VersoSentinelThread"
        )
        self._thread.start()
        logger.info("V.E.R.S.O. Sentinel started.")

    def stop(self) -> None:
        """Stops the background sentinel."""
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("V.E.R.S.O. Sentinel stopped.")

    def _loop(self) -> None:
        while self._is_running:
            try:
                self._tick()
            except Exception as exc:
                logger.error("Error in sentinel tick: %s", exc)
            time.sleep(self.poll_interval)

    def _tick(self) -> None:
        now = time.time()

        # 1. Highest Priority: Incoming Slack Notification from Notification Center or Browser
        slack_notifs = self.notification_sensor.get_new_slack_notifications()
        for notif in slack_notifs:
            sender = notif.get("title") or "Slack"
            body = notif.get("body") or ""
            payload = f"From {sender}: {body}"

            cache_key = f"slack_notif:{notif.get('rec_id')}:{body}"
            if (cache_key != self._last_detected_key) or (
                now - self._last_trigger_time > self.cooldown_seconds
            ):
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
            if (cache_key != self._last_detected_key) or (
                now - self._last_trigger_time > self.cooldown_seconds
            ):
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
            if (cache_key != self._last_detected_key) and (
                now - self._last_trigger_time > self.cooldown_seconds * 2
            ):
                self._last_detected_key = cache_key
                self._last_trigger_time = now
                # Kept passive; does not override Slack intention
