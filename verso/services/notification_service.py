"""
V.E.R.S.O. - Notification Service
Provides reliable native desktop notifications across platforms:
- macOS: AppleScript (osascript) with native sounds and subtitles
- Windows: Native PowerShell Toast with fallback to Plyer and console
- Linux: Native notify-send with fallback to Plyer and console
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
            return result.returncode == 0
        except Exception as exc:
            logger.error("Failed to send macOS notification: %s", exc)
            return False

    @classmethod
    def _notify_windows(cls, title: str, message: str) -> bool:
        """Windows notification using native PowerShell Toast or Plyer."""
        # 1. Native Windows PowerShell toast notification (zero external dependencies)
        try:
            escaped_title = title.replace("'", "''")
            escaped_msg = message.replace("'", "''")
            ps_script = f"""
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
            $template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
            $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template)
            $text = $xml.GetElementsByTagName('text')
            $text[0].AppendChild($xml.CreateTextNode('{escaped_title}')) > $null
            $text[1].AppendChild($xml.CreateTextNode('{escaped_msg}')) > $null
            $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('V.E.R.S.O.').Show($toast)
            """
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                timeout=5,
            )
            if res.returncode == 0:
                return True
        except Exception as exc:
            logger.debug("PowerShell toast notification failed: %s", exc)

        # 2. Plyer fallback
        try:
            from plyer import notification

            notification.notify(
                title=title,
                message=message,
                app_name="V.E.R.S.O.",
                timeout=5,
            )
            return True
        except Exception:
            pass

        print(f"[V.E.R.S.O. Notification] {title}: {message}")
        return False

    @classmethod
    def _notify_linux(cls, title: str, message: str) -> bool:
        """Linux notification using notify-send or Plyer."""
        # 1. Native notify-send command
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

        # 2. Plyer fallback
        try:
            from plyer import notification

            notification.notify(
                title=title,
                message=message,
                app_name="V.E.R.S.O.",
                timeout=5,
            )
            return True
        except Exception:
            pass

        print(f"[V.E.R.S.O. Notification] {title}: {message}")
        return False
