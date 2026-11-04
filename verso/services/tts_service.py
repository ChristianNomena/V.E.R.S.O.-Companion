"""
V.E.R.S.O. - Text-to-Speech (TTS) Service
Provides zero-latency, cross-platform vocal output allowing the AI companion
to speak directly to the user out loud using high-quality English voices.
"""

import logging
import platform
import subprocess
import threading
from typing import Callable, Dict, Optional

from verso.config import TTS_SPEECH_RATE, TTS_VOICE_NAME

logger = logging.getLogger(__name__)


class TTSService:
    """Handles vocal synthesis output for the companion assistant."""

    _current_process: Optional[subprocess.Popen] = None
    _process_lock = threading.Lock()
    _speech_lock = threading.Lock()
    _cached_english_voice: Optional[str] = None

    @classmethod
    def get_best_macos_voice(cls) -> str:
        """Finds the best installed English voice on macOS."""
        if cls._cached_english_voice:
            return cls._cached_english_voice

        try:
            result = subprocess.run(
                ["say", "-v", "?"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0:
                installed: Dict[str, str] = {}
                for line in result.stdout.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        voice_name = parts[0]
                        lang = parts[1]
                        installed[voice_name] = lang

                preferred_voices = [
                    TTS_VOICE_NAME,
                    "Samantha",
                    "Daniel",
                    "Alex",
                    "Karen",
                    "Fred",
                    "Victoria",
                ]
                for voice in preferred_voices:
                    if voice in installed:
                        cls._cached_english_voice = voice
                        return voice

                # Fallback to any installed English voice
                for name, lang in installed.items():
                    if lang.startswith("en_"):
                        cls._cached_english_voice = name
                        return name
        except Exception as exc:
            logger.warning("Could not query macOS voices: %s", exc)

        cls._cached_english_voice = TTS_VOICE_NAME or "Samantha"
        return cls._cached_english_voice

    @classmethod
    def is_speaking(cls) -> bool:
        """Returns True if speech playback is currently active."""
        with cls._process_lock:
            return cls._current_process is not None and cls._current_process.poll() is None

    @classmethod
    def stop(cls) -> None:
        """Immediately stops any currently active spoken playback."""
        with cls._process_lock:
            if cls._current_process and cls._current_process.poll() is None:
                try:
                    cls._current_process.kill()
                    cls._current_process.wait(timeout=0.5)
                except Exception:
                    pass
            cls._current_process = None

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
        # Halt any active speech process immediately before acquiring the lock
        cls.stop()

        # Guarantee serialized single speech execution across the application
        with cls._speech_lock:
            current_os = platform.system()

            if on_started:
                try:
                    on_started()
                except Exception as exc:
                    logger.error("Error in on_started callback: %s", exc)

            try:
                if current_os == "Darwin":
                    voice = cls.get_best_macos_voice()
                    cmd = ["say", "-v", voice, "-r", str(TTS_SPEECH_RATE), text]
                    with cls._process_lock:
                        cls._current_process = subprocess.Popen(cmd)
                    cls._current_process.wait()

                elif current_os == "Windows":
                    escaped = text.replace('"', '""')
                    ps_script = (
                        'Add-Type -AssemblyName System.Speech; '
                        '$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; '
                        '$enVoice = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq "en" } | Select-Object -First 1; '
                        'if ($enVoice) { $synth.SelectVoice($enVoice.VoiceInfo.Name) }; '
                        f'$synth.Speak("{escaped}")'
                    )
                    with cls._process_lock:
                        cls._current_process = subprocess.Popen(
                            ["powershell", "-NoProfile", "-Command", ps_script]
                        )
                    cls._current_process.wait()

                else:
                    # Linux fallback with English speech
                    with cls._process_lock:
                        cls._current_process = subprocess.Popen(["spd-say", "-l", "en", text])
                    cls._current_process.wait()

            except Exception as exc:
                logger.warning("TTS execution skipped or interrupted: %s", exc)
            finally:
                with cls._process_lock:
                    cls._current_process = None
                if on_complete:
                    try:
                        on_complete()
                    except Exception as exc:
                        logger.error("Error in on_complete callback: %s", exc)
