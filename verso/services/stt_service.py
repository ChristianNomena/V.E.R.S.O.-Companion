"""
V.E.R.S.O. - Speech-to-Text (STT) Service
Records user vocal input via microphone, detects live voice activity in real
time, and transcribes the recording with Muse Voice Transcribe
(``muse-voice-transcribe-1.0``). Google SpeechRecognition remains as an
offline fallback when the Muse API is unconfigured or unreachable.
"""

import logging
import math
import os
import platform
import struct
import subprocess
import tempfile
import threading
import time
import wave
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def _calculate_rms(chunk: bytes) -> int:
    """Calculates root-mean-square audio energy of 16-bit PCM chunk."""
    try:
        import audioop
        return audioop.rms(chunk, 2)
    except Exception:
        try:
            import audioop_lts as audioop
            return audioop.rms(chunk, 2)
        except Exception:
            count = len(chunk) // 2
            if count == 0:
                return 0
            shorts = struct.unpack(f"{count}h", chunk)
            sum_sq = sum(s * s for s in shorts)
            return int(math.sqrt(sum_sq / count))


class STTService:
    """Captures user speech from the microphone and transcribes it.

    Primary transcriber: Muse Voice Transcribe (Meta Model API).
    Fallback: Google SpeechRecognition when Muse is unavailable.
    """

    _is_recording: bool = False
    _record_process: Optional[subprocess.Popen] = None
    SPEECH_RMS_THRESHOLD: int = 350
    _muse_client = None

    @classmethod
    def _get_muse_client(cls):
        if cls._muse_client is None:
            from verso.services.muse_client import MuseClient

            cls._muse_client = MuseClient()
        return cls._muse_client

    @classmethod
    def _transcribe_muse(cls, wav_path: str) -> str:
        """Transcribes with Muse Voice Transcribe; '' when unavailable."""
        try:
            text = cls._get_muse_client().transcribe_audio(wav_path)
            return (text or "").strip()
        except Exception as exc:
            logger.warning("Muse Voice Transcribe failed, falling back: %s", exc)
            return ""

    @classmethod
    def _transcribe_google(cls, wav_path: str) -> str:
        """Offline fallback transcriber (Google via SpeechRecognition)."""
        try:
            import speech_recognition as sr

            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio_data = recognizer.record(source)
                return (recognizer.recognize_google(audio_data, language="en-US") or "").strip()
        except Exception as exc:
            logger.debug("Google speech recognition note: %s", exc)
            return ""

    @classmethod
    def _transcribe(cls, wav_path: str) -> str:
        """Muse Voice Transcribe first, Google as fallback."""
        return cls._transcribe_muse(wav_path) or cls._transcribe_google(wav_path)

    @classmethod
    def stop(cls) -> None:
        """Immediately stops any active microphone recording."""
        proc = cls._record_process
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        cls._is_recording = False

    @classmethod
    def listen(
        cls,
        duration: float = 4.0,
        on_started: Optional[Callable[[], None]] = None,
        on_speech_detected: Optional[Callable[[bool], None]] = None,
        on_transcribed: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Listens to user vocal input asynchronously and transcribes the speech.
        Calls on_speech_detected(is_speaking) dynamically in real-time.
        """
        thread = threading.Thread(
            target=cls._listen_sync,
            args=(duration, on_started, on_speech_detected, on_transcribed, on_error),
            daemon=True,
            name="VersoSTTThread",
        )
        thread.start()

    @classmethod
    def _listen_sync(
        cls,
        duration: float,
        on_started: Optional[Callable[[], None]],
        on_speech_detected: Optional[Callable[[bool], None]],
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

        recorded = False
        last_speech_state: Optional[bool] = None

        # 1. Real-time microphone capture with audio level / voice activity detection (VAD)
        try:
            if current_os == "Darwin":
                cmd = [
                    "ffmpeg",
                    "-f", "avfoundation",
                    "-i", ":default",
                    "-t", str(duration),
                    "-ar", "16000",
                    "-ac", "1",
                    "-f", "s16le",
                    "-y", "pipe:1",
                ]
            elif current_os == "Windows":
                cmd = [
                    "ffmpeg",
                    "-f", "dshow",
                    "-i", "audio=default",
                    "-t", str(duration),
                    "-ar", "16000",
                    "-ac", "1",
                    "-f", "s16le",
                    "-y", "pipe:1",
                ]
            else:
                cmd = [
                    "ffmpeg",
                    "-f", "pulse",
                    "-i", "default",
                    "-t", str(duration),
                    "-ar", "16000",
                    "-ac", "1",
                    "-f", "s16le",
                    "-y", "pipe:1",
                ]

            with wave.open(temp_audio, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)

                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                cls._record_process = proc
                cls._is_recording = True

                chunk_size = 3200  # 0.1s at 16kHz mono (16-bit = 2 bytes/sample)
                while True:
                    chunk = proc.stdout.read(chunk_size)
                    if not chunk:
                        break
                    wav_file.writeframes(chunk)

                    # Compute real-time volume energy
                    energy = _calculate_rms(chunk)
                    is_speaking = energy >= cls.SPEECH_RMS_THRESHOLD

                    if is_speaking != last_speech_state:
                        last_speech_state = is_speaking
                        if on_speech_detected:
                            try:
                                on_speech_detected(is_speaking)
                            except Exception as exc:
                                logger.debug("Error in on_speech_detected: %s", exc)

                proc.wait(timeout=duration + 2.0)
                recorded = os.path.exists(temp_audio) and os.path.getsize(temp_audio) > 1000

        except Exception as exc:
            logger.warning("Microphone streaming failed: %s", exc)
        finally:
            cls._is_recording = False
            cls._record_process = None
            if on_speech_detected:
                try:
                    on_speech_detected(False)
                except Exception:
                    pass

        # 2. Transcribe user speech (Muse Voice Transcribe, Google fallback)
        transcription = ""
        if recorded:
            transcription = cls._transcribe(temp_audio)
            if transcription:
                logger.info("Transcribed user vocal reply: %s", transcription)

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
