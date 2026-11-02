"""
V.E.R.S.O. - Clipboard Sensor
Monitors user clipboard updates cleanly without polling spikes.
"""

import logging
from typing import Optional

import pyperclip

logger = logging.getLogger(__name__)


class ClipboardSensor:
    """Monitors clipboard changes without polling storms."""

    def __init__(self) -> None:
        self._last_content: str = ""
        try:
            self._last_content = pyperclip.paste() or ""
        except Exception:
            self._last_content = ""

    def get_new_content(self) -> Optional[str]:
        """Returns new clipboard text if changed since last check, else None."""
        try:
            current = pyperclip.paste()
            if current and current != self._last_content:
                self._last_content = current
                return current.strip()
        except Exception as exc:
            logger.warning("Error reading clipboard: %s", exc)
        return None
