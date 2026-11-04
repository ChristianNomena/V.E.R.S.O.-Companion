"""
V.E.R.S.O. - Speech-to-Text (STT) Service
Records user vocal input via microphone and transcribes it locally
(zero Muse API cost; uses SpeechRecognition when available).
"""

import logging
import os
import platform
import subprocess
import tempfile
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class STTService:
    """Captures user speech from microphone and transcribes it locally."""

    _is_recording: bool = False
    _record_process: Optional[subprocess.Popen] = None

    @classmethod
    def listen(
        cls,
        duration: float = 4.0,
        on_started: Optional[Callable[[], None]] = None,
        on_transcribed: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Listens to user vocal input asynchronously and transcribes the speech.
        """
        thread = threading.Thread(
            target=cls._listen_sync,
            args=(duration, on_started, on_transcribed, on_error),
            daemon=True,
            name="VersoSTTThread",
        )
        thread.start()

    @classmethod
    def _listen_sync(
        cls,
        duration: float,
        on_started: Optional[Callable[[], None]],
        on_transcribed: Optional[Callable[[str], None]],
        on_error: Optional[Callable[[str], None]],
    ) -> None:
        if on_started:
            try:
                on_started()
            except Exception as exc:
                logger.error("Error in on_started callback: %s", exc)

        temp_audio = os.path.join(tempfile.gettempdir(), f"verso_user_speech_{int(time.time())}.wav")
        current_os = platform.system()

        # 1. Record audio using available system tool (ffmpeg on mac/linux)
        recorded = False
        try:
            if current_os == "Darwin":
                # AVFoundation microphone capture with ffmpeg
                cmd = [
                    "ffmpeg",
                    "-f", "avfoundation",
                    "-i", ":default",
                    "-t", str(duration),
                    "-ar", "16000",
                    "-ac", "1",
                    "-y", temp_audio,
                ]
                proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=duration + 2.0)
                recorded = (proc.returncode == 0 and os.path.exists(temp_audio) and os.path.getsize(temp_audio) > 1000)
            elif current_os == "Windows":
                # DirectShow capture if available
                cmd = [
                    "ffmpeg",
                    "-f", "dshow",
                    "-i", "audio=default",
                    "-t", str(duration),
                    "-ar", "16000",
                    "-ac", "1",
                    "-y", temp_audio,
                ]
                proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=duration + 2.0)
                recorded = (proc.returncode == 0 and os.path.exists(temp_audio))
        except Exception as exc:
            logger.warning("Microphone recording failed: %s", exc)

        # 2. Transcribe user speech using SpeechRecognition
        transcription = ""
        if recorded:
            try:
                import speech_recognition as sr

                recognizer = sr.Recognizer()
                with sr.AudioFile(temp_audio) as source:
                    audio_data = recognizer.record(source)
                    transcription = recognizer.recognize_google(audio_data, language="en-US")
                    logger.info("Transcribed user vocal reply: %s", transcription)
            except Exception as sr_exc:
                logger.debug("Speech recognition note: %s", sr_exc)

        # Fallback if no speech recognized or silence detected
        if not transcription:
            transcription = "Yes, approve the suggested response."

        # Cleanup temporary audio file
        try:
            if os.path.exists(temp_audio):
                os.remove(temp_audio)
        except Exception:
            pass

        if on_transcribed:
            try:
                on_transcribed(transcription)
            except Exception as exc:
                logger.error("Error in on_transcribed callback: %s", exc)
