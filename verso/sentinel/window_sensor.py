"""
V.E.R.S.O. - Window Sensor
Lightweight cross-platform active window and application detector,
optimized for macOS (AppleScript / System Events) with Windows & Linux support.
"""

import logging
import platform
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowInfo:
    """Represents the currently active application and window."""
    app_name: str
    window_title: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.app_name.strip() and not self.window_title.strip()

    @property
    def display_text(self) -> str:
        """User-friendly representation of the active window."""
        if self.app_name and self.window_title:
            return f"{self.app_name} - {self.window_title}"
        return self.app_name or self.window_title or "Unknown"

    def __str__(self) -> str:
        return self.display_text


class WindowSensor:
    """Detects the foreground application and window title across operating systems."""

    @classmethod
    def get_active_window(cls) -> WindowInfo:
        """
        Retrieves the active application and window title.
        Guaranteed not to raise an exception; returns fallback on error.
        """
        current_os = platform.system()

        try:
            if current_os == "Darwin":
                return cls._get_macos_window()
            elif current_os == "Windows":
                return cls._get_windows_window()
            elif current_os == "Linux":
                return cls._get_linux_window()
            else:
                return WindowInfo(app_name="UnsupportedOS", window_title="")
        except Exception as exc:
            logger.warning("Error reading active window: %s", exc)
            return WindowInfo(app_name="Unknown", window_title="")

    @classmethod
    def _get_macos_window(cls) -> WindowInfo:
        """
        Reads the active app and window title on macOS.
        Uses AppleScript without blocking, handling apps with or without Accessibility rights.
        """
        script = '''
tell application "System Events"
    set frontApp to first application process whose frontmost is true
    set appName to name of frontApp
    set winTitle to ""
    try
        set winTitle to name of front window of frontApp
    end try
end tell

-- Optional browser-specific fallback if window title is empty
if winTitle is "" then
    if appName is "Safari" then
        try
            tell application "Safari" to set winTitle to name of current tab of front window
        end try
    else if appName is "Google Chrome" then
        try
            tell application "Google Chrome" to set winTitle to title of active tab of front window
        end try
    end if
end if

return appName & "|||" & winTitle
'''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split("|||", 1)
                app_name = parts[0].strip() if len(parts) > 0 else ""
                win_title = parts[1].strip() if len(parts) > 1 else ""
                return WindowInfo(app_name=app_name, window_title=win_title)
            else:
                return WindowInfo(app_name="Unknown", window_title="")
        except subprocess.TimeoutExpired:
            logger.warning("Timeout while detecting macOS active window")
            return WindowInfo(app_name="Timeout", window_title="")
        except Exception as exc:
            logger.warning("Failed to detect macOS active window: %s", exc)
            return WindowInfo(app_name="Error", window_title="")

    @classmethod
    def _get_windows_window(cls) -> WindowInfo:
        """Reads the active window on Windows using ctypes."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return WindowInfo(app_name="Desktop", window_title="")

            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()

            return WindowInfo(app_name="Windows", window_title=title)
        except Exception as exc:
            logger.warning("Failed to detect Windows active window: %s", exc)
            return WindowInfo(app_name="Windows", window_title="")

    @classmethod
    def _get_linux_window(cls) -> WindowInfo:
        """Reads the active window on Linux using xdotool if available."""
        try:
            res = subprocess.run(
                ["xdotool", "getwindowfocus", "getwindowname"],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            if res.returncode == 0:
                return WindowInfo(app_name="Linux", window_title=res.stdout.strip())
        except Exception:
            pass
        return WindowInfo(app_name="Linux", window_title="")
