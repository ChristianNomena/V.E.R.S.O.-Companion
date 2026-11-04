"""
V.E.R.S.O. - Text-to-Speech (TTS) Service
Provides zero-latency, cross-platform vocal output allowing the AI companion
to speak directly to the user out loud.
"""

import logging
import platform
import subprocess
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class TTSService:
    """Handles vocal synthesis output for the companion assistant."""

    _current_process: Optional[subprocess.Popen] = None
    _lock = threading.Lock()

    @classmethod
    def speak(
        cls,
        text: str,
        on_started: Optional[Callable[[], None]] = None,
        on_complete: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Speaks text out loud in a non-blocking background thread.
        Calls on_started when speech starts and on_complete when finished.
        """
        if not text or not text.strip():
            if on_complete:
                on_complete()
            return

        thread = threading.Thread(
            target=cls._speak_sync,
            args=(text, on_started, on_complete),
            daemon=True,
            name="VersoTTSThread",
        )
        thread.start()

    @classmethod
    def _speak_sync(
        cls,
        text: str,
        on_started: Optional[Callable[[], None]] = None,
        on_complete: Optional[Callable[[], None]] = None,
    ) -> None:
        current_os = platform.system()
        cls.stop()  # Stop any ongoing speech

        if on_started:
            try:
                on_started()
            except Exception as exc:
                logger.error("Error in on_started callback: %s", exc)

        try:
            if current_os == "Darwin":
                # Use default system voice (e.g. Samantha / Alex on macOS)
                cmd = ["say", text]
                with cls._lock:
                    cls._current_process = subprocess.Popen(cmd)
                cls._current_process.wait()

            elif current_os == "Windows":
                escaped = text.replace('"', '""')
                ps_script = (
                    f'Add-Type -AssemblyName System.Speech; '
                    f'$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; '
                    f'$synth.Speak("{escaped}")'
                )
                with cls._lock:
                    cls._current_process = subprocess.Popen(
                        ["powershell", "-NoProfile", "-Command", ps_script]
                    )
                cls._current_process.wait()

            else:
                # Linux fallback
                with cls._lock:
                    cls._current_process = subprocess.Popen(["spd-say", text])
                cls._current_process.wait()

        except Exception as exc:
            logger.warning("TTS execution skipped or interrupted: %s", exc)
        finally:
            with cls._lock:
                cls._current_process = None
            if on_complete:
                try:
                    on_complete()
                except Exception as exc:
                    logger.error("Error in on_complete callback: %s", exc)

    @classmethod
    def stop(cls) -> None:
        """Stops any currently active spoken playback."""
        with cls._lock:
            if cls._current_process and cls._current_process.poll() is None:
                try:
                    cls._current_process.terminate()
                except Exception:
                    pass
                cls._current_process = None
