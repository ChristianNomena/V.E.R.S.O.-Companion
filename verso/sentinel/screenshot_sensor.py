"""
V.E.R.S.O. - Screenshot Sensor (Pillar 2)
Captures what the user is looking at, without ever raising.
Session files live under the OS temp directory and are purged with the session.
"""

import logging
import platform
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


class ScreenshotSensor:
    """Session-scoped screenshot capture with graceful permission handling."""

    @staticmethod
    def base_dir(custom: Optional[PathLike] = None) -> Path:
        """Root folder holding per-session capture directories."""
        if custom is not None:
            return Path(custom)
        return Path(tempfile.gettempdir()) / "verso_companion" / "captures"

    @classmethod
    def capture(cls, session_id: str, base_dir: Optional[PathLike] = None) -> Optional[str]:
        """
        Captures the main screen into the session folder.

        Returns the file path on success, None on failure (missing permission,
        missing tool, unsupported platform). Never raises.
        """
        try:
            session_dir = cls.base_dir(base_dir) / session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            filename = datetime.now().strftime("shot_%Y%m%d_%H%M%S_%f.png")
            target = session_dir / filename

            system = platform.system()
            if system == "Darwin":
                result = subprocess.run(
                    ["screencapture", "-x", "-m", str(target)],
                    capture_output=True,
                    timeout=6,
                )
                if result.returncode == 0 and target.exists():
                    return str(target)
                target.unlink(missing_ok=True)
                return None
            if system == "Windows":
                try:
                    from PIL import ImageGrab  # optional dependency

                    ImageGrab.grab().save(str(target))
                    return str(target)
                except Exception:
                    return None
            # Linux: best-effort native tools
            for cmd in (
                ["gnome-screenshot", "-f", str(target)],
                ["import", "-window", "root", str(target)],
            ):
                try:
                    result = subprocess.run(cmd, capture_output=True, timeout=6)
                except Exception:
                    continue
                if result.returncode == 0 and target.exists():
                    return str(target)
            return None
        except Exception as exc:
            logger.warning("Screenshot capture failed: %s", exc)
            return None

    @classmethod
    def cleanup_session(cls, session_id: str, base_dir: Optional[PathLike] = None) -> None:
        """Removes every capture of a session. Never raises."""
        try:
            shutil.rmtree(cls.base_dir(base_dir) / session_id, ignore_errors=True)
        except Exception as exc:
            logger.warning("Screenshot cleanup failed: %s", exc)

    @classmethod
    def cleanup_all(cls, base_dir: Optional[PathLike] = None) -> None:
        """Removes every stored capture (stale sessions cleanup). Never raises."""
        try:
            shutil.rmtree(cls.base_dir(base_dir), ignore_errors=True)
        except Exception as exc:
            logger.warning("Screenshot cleanup failed: %s", exc)
