"""
V.E.R.S.O. - Clipboard Sensor
Monitors user clipboard updates cleanly without polling spikes or self-trigger loops.
"""

import logging
import threading
from typing import Optional, Set

import pyperclip

logger = logging.getLogger(__name__)


class ClipboardSensor:
    """Monitors clipboard changes without polling storms or self-triggering echo loops."""

    _ignored_hashes: Set[int] = set()
    _lock = threading.Lock()

    @classmethod
    def ignore_content(cls, text: str) -> None:
        """Registers text as internally generated so the sensor ignores it when copied."""
        if text and text.strip():
            with cls._lock:
                cls._ignored_hashes.add(hash(text.strip()))

    @classmethod
    def is_ignored(cls, text: str) -> bool:
        """Peeks whether a text was internally generated (no consume, thread-safe)."""
        if not text or not text.strip():
            return False
        with cls._lock:
            return hash(text.strip()) in cls._ignored_hashes

    def __init__(self) -> None:
        self._last_content: str = ""
        try:
            self._last_content = pyperclip.paste() or ""
            if self._last_content:
                self.ignore_content(self._last_content)
        except Exception:
            self._last_content = ""

    def get_new_content(self) -> Optional[str]:
        """Returns new clipboard text if changed since last check, else None."""
        try:
            current = pyperclip.paste()
            if not current:
                return None
            cleaned = current.strip()
            with self._lock:
                if hash(cleaned) in self._ignored_hashes:
                    self._last_content = current
                    self._ignored_hashes.discard(hash(cleaned))
                    return None

            if current != self._last_content:
                self._last_content = current
                return cleaned
        except Exception as exc:
            logger.warning("Error reading clipboard: %s", exc)
        return None
