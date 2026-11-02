"""
V.E.R.S.O. - Notification Service
Provides reliable native desktop notifications across platforms,
with a dedicated rock-solid macOS implementation (AppleScript)
and graceful fallbacks.
"""

import logging
import platform
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


class NotificationService:
    """Unified cross-platform notification service."""

    @classmethod
    def notify(
        cls,
        title: str,
        message: str,
        subtitle: Optional[str] = None,
        sound: bool = True,
    ) -> bool:
        """
        Sends a native desktop push notification.

        Args:
            title: Notification title.
            message: Body message text.
            subtitle: Optional subtitle (macOS only).
            sound: Whether to play a system notification sound.

        Returns:
            bool: True if delivered successfully, False otherwise.
        """
        current_os = platform.system()

        if current_os == "Darwin":
            return cls._notify_macos(title, message, subtitle=subtitle, sound=sound)
        elif current_os == "Windows":
            return cls._notify_windows(title, message)
        else:
            return cls._notify_linux(title, message)

    @classmethod
    def _notify_macos(
        cls,
        title: str,
        message: str,
        subtitle: Optional[str] = None,
        sound: bool = True,
    ) -> bool:
        """Native macOS notification via osascript (no heavy dependencies)."""
        try:
            escaped_msg = message.replace("\\", "\\\\").replace('"', '\\"')
            escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')

            script = f'display notification "{escaped_msg}" with title "{escaped_title}"'
            if subtitle:
                escaped_sub = subtitle.replace("\\", "\\\\").replace('"', '\\"')
                script += f' subtitle "{escaped_sub}"'
            if sound:
                script += ' sound name "Default"'

            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return True
            else:
                logger.warning("osascript notification failed: %s", result.stderr.strip())
                return False
        except Exception as exc:
            logger.error("Failed to send macOS notification: %s", exc)
            return False

    @classmethod
    def _notify_windows(cls, title: str, message: str) -> bool:
        """Windows notification using plyer with graceful fallback."""
        try:
            from plyer import notification

            notification.notify(
                title=title,
                message=message,
                app_name="V.E.R.S.O.",
                timeout=5,
            )
            return True
        except Exception as exc:
            logger.warning("Windows plyer notification failed (%s), logging to console.", exc)
            print(f"[V.E.R.S.O. Notification] {title}: {message}")
            return False

    @classmethod
    def _notify_linux(cls, title: str, message: str) -> bool:
        """Linux notification using notify-send or plyer."""
        try:
            res = subprocess.run(
                ["notify-send", title, message],
                capture_output=True,
                timeout=5,
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass

        try:
            from plyer import notification

            notification.notify(
                title=title,
                message=message,
                app_name="V.E.R.S.O.",
                timeout=5,
            )
            return True
        except Exception as exc:
            logger.warning("Linux notification failed (%s), logging to console.", exc)
            print(f"[V.E.R.S.O. Notification] {title}: {message}")
            return False


if __name__ == "__main__":
    import sys

    print("Testing NotificationService on", platform.system())
    success = NotificationService.notify(
        title="V.E.R.S.O.",
        message="System monitor active in the background.",
        subtitle="Synchronization successful",
        sound=True,
    )
    if success:
        print("✅ Notification delivered successfully!")
        sys.exit(0)
    else:
        print("❌ Notification failed.")
        sys.exit(1)
