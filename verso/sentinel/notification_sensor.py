"""
V.E.R.S.O. - Cross-Platform Notification Sensor
Monitors system notifications for notifications emitted by Slack or web
browsers: macOS (usernoted SQLite), Windows (wpndatabase.db SQLite), and
Linux (DBus Notify calls observed via dbus-monitor).
"""

import logging
import os
import platform
import plistlib
import re
import shutil
import sqlite3
import subprocess
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Known browser identifiers across operating systems
BROWSER_IDENTIFIERS = (
    "chrome",
    "safari",
    "firefox",
    "arc",
    "brave",
    "msedge",
    "edge",
)


def get_default_notification_db_path() -> Optional[str]:
    """Resolves the system notification database path for the current OS."""
    current_os = platform.system()
    if current_os == "Darwin":
        return os.path.expanduser(
            "~/Library/Group Containers/group.com.apple.usernoted/db2/db"
        )
    elif current_os == "Windows":
        local_app_data = os.getenv("LOCALAPPDATA", "")
        if local_app_data:
            return os.path.join(
                local_app_data, "Microsoft", "Windows", "Notifications", "wpndatabase.db"
            )
    return None


def _unescape_dbus_string(value: str) -> str:
    return value.replace('\\"', '"').replace("\\\\", "\\")


class DbusNotifyParser:
    """Incremental parser for `dbus-monitor` output of Notify method calls.

    A Notify call carries (app_name, replaces_id, app_icon, summary, body,
    actions, hints, expire_timeout). The first four string arguments are the
    ones we need; the call is complete when the trailing int32 arrives.
    """

    def __init__(self) -> None:
        self._active = False
        self._strings: List[str] = []

    def feed(self, line: str) -> Optional[Dict[str, Any]]:
        if "member=Notify" in line:
            self._active = True
            self._strings = []
            return None
        if not self._active:
            return None
        stripped = (line or "").strip()
        match = re.match(r'^string "(.*)"$', stripped)
        if match:
            if len(self._strings) < 4:
                self._strings.append(_unescape_dbus_string(match.group(1)))
            return None
        if stripped.startswith("int32 "):
            self._active = False
            if len(self._strings) >= 4:
                app_name, _icon, summary, body = self._strings[:4]
                return {
                    "app_identifier": app_name,
                    "title": summary,
                    "subtitle": "",
                    "body": body,
                }
            self._strings = []
        return None


class NotificationSensor:
    """
    Sensor that observes system notifications to detect incoming Slack messages.
    Supports macOS (usernoted SQLite), Windows (wpndatabase.db SQLite), Linux
    (DBus via dbus-monitor), and simulation channels.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        simulation_file: str = "deliverables/.simulate_slack.txt",
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.current_os = platform.system()
        self.db_path = db_path if db_path is not None else get_default_notification_db_path()
        self.simulation_file = simulation_file
        self.on_error = on_error
        self.last_rec_id: int = -1
        self._permission_warned: bool = False
        self._initialized: bool = False
        # Linux DBus monitor state
        self._linux_queue: List[Dict[str, Any]] = []
        self._linux_lock = threading.Lock()
        self._dbus_process: Optional[subprocess.Popen] = None
        self._dbus_thread: Optional[threading.Thread] = None
        self._linux_rec_counter: int = 0
        self._linux_warned: bool = False

    def check_permission(self) -> Tuple[bool, str]:
        """
        Verifies if system notifications can be read on the current OS.
        Returns (True, "") if accessible, or (False, error_reason) if blocked.
        """
        if self.current_os == "Darwin":
            if not self.db_path or not os.path.exists(self.db_path):
                return True, ""
            try:
                conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(rec_id) FROM record;")
                conn.close()
                return True, ""
            except (PermissionError, sqlite3.OperationalError):
                return False, (
                    "Full Disk Access permission is required to read notifications. "
                    "Enable it in: System Settings > Privacy & Security > Full Disk Access."
                )
            except Exception as exc:
                return False, f"Notification database access error: {exc}"
        elif self.current_os == "Windows":
            if self.db_path and os.path.exists(self.db_path):
                try:
                    conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
                    conn.close()
                    return True, ""
                except Exception as exc:
                    return False, f"Windows notification database access error: {exc}"
        return True, ""

    # -- Linux DBus monitoring ------------------------------------------

    def _enqueue_linux_notification(self, notif: Dict[str, Any]) -> None:
        self._linux_rec_counter += 1
        entry = dict(notif)
        entry["rec_id"] = 500000 + self._linux_rec_counter
        with self._linux_lock:
            self._linux_queue.append(entry)

    def _ensure_linux_monitor(self) -> None:
        """Starts the dbus-monitor reader thread on Linux (once)."""
        if self.current_os != "Linux":
            return
        if self._dbus_process is not None and self._dbus_process.poll() is None:
            return
        if shutil.which("dbus-monitor") is None:
            if not self._linux_warned:
                self._linux_warned = True
                logger.warning(
                    "dbus-monitor not found: Linux notification listening is disabled. "
                    "Install dbus tools (e.g. 'dbus' package) to enable it."
                )
            return
        try:
            self._dbus_process = subprocess.Popen(
                [
                    "dbus-monitor",
                    "--session",
                    "type='method_call',interface='org.freedesktop.Notifications',member='Notify',eavesdrop=true",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except Exception as exc:
            logger.warning("Could not start dbus-monitor: %s", exc)
            self._dbus_process = None
            return
        self._dbus_thread = threading.Thread(
            target=self._read_dbus_monitor, daemon=True, name="VersoDbusMonitorThread"
        )
        self._dbus_thread.start()
        logger.info("Linux DBus notification monitor started.")

    def _read_dbus_monitor(self) -> None:
        parser = DbusNotifyParser()
        process = self._dbus_process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                emitted = parser.feed(line)
                if emitted:
                    self._enqueue_linux_notification(emitted)
        except Exception as exc:
            logger.debug("DBus monitor reader stopped: %s", exc)

    def _drain_linux_notifications(self) -> List[Dict[str, Any]]:
        self._ensure_linux_monitor()
        with self._linux_lock:
            queued = list(self._linux_queue)
            self._linux_queue.clear()
        return [n for n in queued if self._is_slack_notification(n)]

    def close(self) -> None:
        """Stops the Linux DBus monitor process, if running."""
        if self._dbus_process is not None and self._dbus_process.poll() is None:
            try:
                self._dbus_process.terminate()
            except Exception:
                pass
        self._dbus_process = None

    def initialize_baseline(self) -> None:
        """Sets the baseline rec_id to ignore notifications created before app launch."""
        if self.current_os == "Linux":
            self._ensure_linux_monitor()
            return
        if not self.db_path or not os.path.exists(self.db_path):
            return

        try:
            if self.current_os == "Darwin":
                conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(rec_id) FROM record;")
                row = cursor.fetchone()
                if row and row[0] is not None:
                    self.last_rec_id = int(row[0])
                conn.close()
                self._initialized = True
        except (sqlite3.OperationalError, PermissionError):
            pass

    def get_new_slack_notifications(self) -> List[Dict[str, Any]]:
        """
        Polls for new notifications originating from Slack (desktop app or browser tab).
        Returns a list of parsed notification dictionaries.
        """
        results: List[Dict[str, Any]] = []

        # 1. Check for manual simulation file if present (works identically on Mac, Windows, Linux)
        simulated = self._check_simulation()
        if simulated:
            results.append(simulated)

        # 2. Linux: drain notifications observed over DBus
        if self.current_os == "Linux":
            results.extend(self._drain_linux_notifications())
            return results

        # 3. Query system notification database if supported on current OS
        if not self.db_path or not os.path.exists(self.db_path):
            return results

        if self.current_os == "Darwin":
            results.extend(self._poll_macos_notifications())
        elif self.current_os == "Windows":
            results.extend(self._poll_windows_notifications())

        return results

    def _poll_macos_notifications(self) -> List[Dict[str, Any]]:
        """Queries macOS usernoted SQLite database."""
        results: List[Dict[str, Any]] = []
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            cursor = conn.cursor()

            if self.last_rec_id < 0:
                cursor.execute("SELECT MAX(rec_id) FROM record;")
                row = cursor.fetchone()
                if row and row[0] is not None:
                    self.last_rec_id = int(row[0])
                conn.close()
                return results

            query = """
                SELECT record.rec_id, app.identifier, record.delivered_date, record.data
                FROM app
                INNER JOIN record ON app.app_id = record.app_id
                WHERE record.rec_id > ?
                ORDER BY record.rec_id ASC;
            """
            cursor.execute(query, (self.last_rec_id,))
            rows = cursor.fetchall()

            for row in rows:
                rec_id, app_id, delivered_date, data = row
                if rec_id > self.last_rec_id:
                    self.last_rec_id = rec_id

                notification = self._parse_macos_payload(
                    rec_id=rec_id,
                    app_identifier=app_id or "",
                    data=data,
                )

                if notification and self._is_slack_notification(notification):
                    results.append(notification)

            conn.close()
            if self._permission_warned:
                self._permission_warned = False
                if self.on_error:
                    self.on_error("")

        except (PermissionError, sqlite3.OperationalError) as exc:
            error_msg = (
                "Full Disk Access permission is required to read notifications. "
                "Enable it in: System Settings > Privacy & Security > Full Disk Access."
            )
            if not self._permission_warned:
                logger.warning(
                    "Cannot read macOS Notification Center database (%s). "
                    "Full Disk Access permission is required. "
                    "Enable Full Disk Access for your Terminal or IDE in: "
                    "System Settings > Privacy & Security > Full Disk Access.",
                    exc,
                )
                self._permission_warned = True
            if self.on_error:
                self.on_error(error_msg)

        return results

    def _poll_windows_notifications(self) -> List[Dict[str, Any]]:
        """Queries Windows wpndatabase.db SQLite database if accessible."""
        results: List[Dict[str, Any]] = []
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            query = """
                SELECT PrimaryId, Type, Payload, ArrivalTime
                FROM Notification
                ORDER BY ArrivalTime DESC
                LIMIT 5;
            """
            cursor.execute(query)
            rows = cursor.fetchall()
            for row in rows:
                # Windows notifications store XML or text in Payload
                payload = str(row[2]) if row[2] else ""
                if "slack" in payload.lower():
                    results.append(
                        {
                            "rec_id": row[0],
                            "app_identifier": "Slack",
                            "title": "Slack",
                            "subtitle": "",
                            "body": payload,
                        }
                    )
            conn.close()
        except Exception as exc:
            logger.debug("Windows notification query skipped: %s", exc)
        return results

    def _parse_macos_payload(
        self, rec_id: int, app_identifier: str, data: Optional[bytes]
    ) -> Optional[Dict[str, Any]]:
        """Extracts title, subtitle, and body text from macOS binary plist blob."""
        title = ""
        subtitle = ""
        body = ""

        if data:
            try:
                plist = plistlib.loads(data)
                req = plist.get("req", {})
                title = req.get("titl") or req.get("title") or ""
                subtitle = req.get("subt") or req.get("subtitle") or ""
                body = req.get("body") or ""
            except Exception as exc:
                logger.debug("Failed to decode notification plist: %s", exc)

        return {
            "rec_id": rec_id,
            "app_identifier": app_identifier,
            "title": title,
            "subtitle": subtitle,
            "body": body,
        }

    def _is_slack_notification(self, notif: Dict[str, Any]) -> bool:
        """Determines if the notification originated from Slack or a browser Slack tab."""
        app_id_lower = notif["app_identifier"].lower()
        title_lower = notif["title"].lower()
        subtitle_lower = notif["subtitle"].lower()
        body_lower = notif["body"].lower()

        if "slack" in app_id_lower:
            return True

        for browser in BROWSER_IDENTIFIERS:
            if browser in app_id_lower:
                if (
                    "slack" in title_lower
                    or "slack" in subtitle_lower
                    or "slack" in body_lower
                ):
                    return True

        return False

    def _check_simulation(self) -> Optional[Dict[str, Any]]:
        """Checks if a simulated Slack message file was dropped into deliverables/."""
        if not os.path.exists(self.simulation_file):
            return None

        try:
            with open(self.simulation_file, "r", encoding="utf-8") as f:
                content = f.read().strip()

            os.remove(self.simulation_file)

            if not content:
                return None

            logger.info("Simulated Slack notification detected.")
            return {
                "rec_id": 999999,
                "app_identifier": "com.tinyspeck.slackmacgap",
                "title": "Slack | Team Lead",
                "subtitle": "Project inquiry",
                "body": content,
            }
        except Exception as exc:
            logger.error("Error reading simulation file: %s", exc)
            return None
