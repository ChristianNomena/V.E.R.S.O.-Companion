"""
V.E.R.S.O. - Sentinel Engine
Orchestrates background sensors (window, clipboard) and applies cooldown rules
before triggering autonomous background workers.
"""

import logging
import threading
import time
from typing import Callable, Optional

from verso.sentinel.clipboard_sensor import ClipboardSensor
from verso.sentinel.window_sensor import WindowInfo, WindowSensor

logger = logging.getLogger(__name__)


class Sentinel:
    """Background system monitor for active window and clipboard changes."""

    def __init__(
        self,
        poll_interval: float = 2.0,
        cooldown_seconds: float = 30.0,
        on_context_detected: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.poll_interval = poll_interval
        self.cooldown_seconds = cooldown_seconds
        self.on_context_detected = on_context_detected

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
        self._thread = threading.Thread(target=self._loop, daemon=True, name="VersoSentinelThread")
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
        # 1. Check Window
        window_info = WindowSensor.get_active_window()

        # 2. Check Clipboard
        new_clipboard = self.clipboard_sensor.get_new_content()

        now = time.time()
        trigger_context: Optional[str] = None
        trigger_payload: str = ""

        if new_clipboard:
            trigger_context = "clipboard"
            trigger_payload = new_clipboard
        elif not window_info.is_empty and window_info.app_name != "Antigravity":
            trigger_context = "window"
            trigger_payload = window_info.display_text

        if trigger_context and self.on_context_detected:
            # Check cooldown
            cache_key = f"{trigger_context}:{trigger_payload}"
            if (cache_key != self._last_detected_key) or (now - self._last_trigger_time > self.cooldown_seconds):
                self._last_detected_key = cache_key
                self._last_trigger_time = now
                self.on_context_detected(trigger_context, trigger_payload)
