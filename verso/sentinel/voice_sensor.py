"""
V.E.R.S.O. - Ambient Voice Sensor
Continuous background microphone monitor that detects voice activity (VAD),
ambient wake-word ("VERSO"), and closing keywords ("Thanks", "Thank you")
or a 3-second blank silence timeout while listening is active.
"""

import logging
import os
import re
import subprocess
import tempfile
import threading
import time
import wave
from typing import Callable, List, Optional

from verso.services.stt_service import STTService, _calculate_rms, build_microphone_command
from verso.services.tts_service import TTSService

logger = logging.getLogger(__name__)


def extract_wake_prompt(text: str) -> Optional[str]:
    """
    Extracts the user request associated with the 'VERSO' wake-word,
    cleanly trimming closing keywords ('Thanks', 'Thank you').
    Returns None if the wake-word is not present in the transcription.
    """
    if not text:
        return None
    match = re.search(r"\b(verso|verseau|verceau)\b", text, re.IGNORECASE)
    if not match:
        return None

    after = text[match.end():].strip().lstrip(",:;- ")
    before = text[:match.start()].strip().rstrip(",:;- ")
    closing_pattern = r"(?:[\s,;:\-–—.]*)\b(thank\s+you|thanks|thank\s+u)\b[\s.!?]*$"

    # 1. Check prompt following wake-word
    candidate_after = re.sub(closing_pattern, "", after, flags=re.IGNORECASE).strip().rstrip(",:;- ")
    if re.search(r"\w+", candidate_after):
        return candidate_after

    # 2. Check prompt preceding wake-word (e.g. "What do you think, Verso?")
    candidate_before = re.sub(closing_pattern, "", before, flags=re.IGNORECASE).strip().rstrip(",:;- ")
    if re.search(r"\w+", candidate_before):
        return candidate_before

    return "What do you think?"


def has_closing_keyword(text: str) -> bool:
    """Returns True if the transcribed text contains 'Thanks' or 'Thank you'."""
    if not text:
        return False
    return bool(re.search(r"\b(thank\s+you|thanks|thank\s+u)\b", text, re.IGNORECASE))


class VoiceSensor:
    """
    Monitors ambient microphone stream for real-time speech, the 'VERSO' wake-word,
    and closes vocal messages upon 'Thanks'/'Thank you' or a 3-second blank timeout.
    """

    SPEECH_RMS_THRESHOLD: int = 350
    FAST_CLOSING_SILENCE_CHUNKS: int = 10   # ~1.0s pause triggers early close if 'Thanks'/'Thank you' is spoken
    FALLBACK_BLANK_SILENCE_CHUNKS: int = 30 # 3.0s blank silence timeout
    MIN_SPEECH_CHUNKS: int = 4              # At least ~0.4s of audio required to transcribe

    def __init__(
        self,
        on_speech_detected: Optional[Callable[[bool], None]] = None,
        on_wake_word: Optional[Callable[[str], None]] = None,
        is_busy_fn: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.on_speech_detected = on_speech_detected
        self.on_wake_word = on_wake_word
        self.is_busy_fn = is_busy_fn
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self) -> None:
        """Starts ambient voice monitoring in a background daemon thread."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._thread = threading.Thread(
                target=self._loop,
                daemon=True,
                name="VersoVoiceSensorThread",
            )
            self._thread.start()
            logger.info("VoiceSensor started.")

    def stop(self) -> None:
        """Stops ambient voice monitoring and releases the microphone."""
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False
            proc = self._proc
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
            self._proc = None

        if self._thread and self._thread.is_alive():
            if threading.current_thread() != self._thread:
                self._thread.join(timeout=1.0)
        logger.info("VoiceSensor stopped.")
        if self.on_speech_detected:
            try:
                self.on_speech_detected(False)
            except Exception:
                pass

    def _get_ffmpeg_cmd(self) -> List[str]:
        # Shared with STTService: on Windows this uses the first enumerated
        # DirectShow microphone instead of the nonexistent 'default' name.
        return build_microphone_command() + [
            "-ar", "16000",
            "-ac", "1",
            "-f", "s16le",
            "-y", "pipe:1",
        ]

    def _loop(self) -> None:
        chunk_size = 3200  # 0.1s at 16kHz mono (16-bit = 2 bytes/sample)
        cmd = self._get_ffmpeg_cmd()

        while self._is_running:
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                self._proc = proc
            except Exception as exc:
                logger.debug("Failed to spawn ffmpeg for VoiceSensor: %s", exc)
                time.sleep(2.0)
                continue

            accumulated_frames = bytearray()
            silence_chunks = 0
            is_speaking = False
            checked_fast_close = False

            try:
                while self._is_running and proc.poll() is None:
                    chunk = proc.stdout.read(chunk_size)
                    if not chunk:
                        break

                    # If assistant is actively speaking aloud or processing, ignore audio
                    # to prevent echo and self-listening loops.
                    if (self.is_busy_fn and self.is_busy_fn()) or TTSService.is_speaking():
                        if is_speaking:
                            is_speaking = False
                            if self.on_speech_detected:
                                self.on_speech_detected(False)
                        accumulated_frames.clear()
                        silence_chunks = 0
                        checked_fast_close = False
                        continue

                    energy = _calculate_rms(chunk)
                    if energy >= self.SPEECH_RMS_THRESHOLD:
                        if not is_speaking:
                            is_speaking = True
                            if self.on_speech_detected:
                                self.on_speech_detected(True)
                        accumulated_frames.extend(chunk)
                        silence_chunks = 0
                        checked_fast_close = False
                    else:
                        if accumulated_frames:
                            accumulated_frames.extend(chunk)
                            silence_chunks += 1

                            # Early closing check: if user said "Thanks" or "Thank you",
                            # trigger after ~1.0s pause without making them wait for the 3.0s blank.
                            if silence_chunks == self.FAST_CLOSING_SILENCE_CHUNKS and not checked_fast_close:
                                checked_fast_close = True
                                if len(accumulated_frames) >= self.MIN_SPEECH_CHUNKS * chunk_size:
                                    temp_audio = self._write_temp_wav(bytes(accumulated_frames))
                                    try:
                                        partial_text = STTService._transcribe(temp_audio)
                                        if has_closing_keyword(partial_text):
                                            prompt = extract_wake_prompt(partial_text)
                                            if prompt:
                                                is_speaking = False
                                                if self.on_speech_detected:
                                                    self.on_speech_detected(False)
                                                accumulated_frames.clear()
                                                silence_chunks = 0
                                                if self.on_wake_word:
                                                    logger.info("Wake command completed via 'Thanks' keyword: '%s'", prompt)
                                                    self.on_wake_word(prompt)
                                                continue
                                    finally:
                                        self._remove_temp_wav(temp_audio)

                            # Fallback closing check: 3-second blank reached
                            if silence_chunks >= self.FALLBACK_BLANK_SILENCE_CHUNKS:
                                is_speaking = False
                                if self.on_speech_detected:
                                    self.on_speech_detected(False)

                                frames_to_process = bytes(accumulated_frames)
                                accumulated_frames.clear()
                                silence_chunks = 0
                                checked_fast_close = False

                                if len(frames_to_process) >= self.MIN_SPEECH_CHUNKS * chunk_size:
                                    threading.Thread(
                                        target=self._process_utterance,
                                        args=(frames_to_process,),
                                        daemon=True,
                                        name="VersoUtteranceProcessor",
                                    ).start()
                        else:
                            silence_chunks = 0
            except Exception as exc:
                logger.debug("VoiceSensor read loop exception: %s", exc)
            finally:
                if proc.poll() is None:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                self._proc = None

            time.sleep(0.5)

    @staticmethod
    def _write_temp_wav(audio_data: bytes) -> str:
        temp_audio = os.path.join(
            tempfile.gettempdir(),
            f"verso_wake_{int(time.time() * 1000)}.wav",
        )
        with wave.open(temp_audio, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio_data)
        return temp_audio

    @staticmethod
    def _remove_temp_wav(temp_audio: str) -> None:
        if temp_audio and os.path.exists(temp_audio):
            try:
                os.remove(temp_audio)
            except Exception:
                pass

    def _process_utterance(self, audio_data: bytes) -> None:
        temp_audio = self._write_temp_wav(audio_data)
        try:
            text = STTService._transcribe(temp_audio)
            logger.debug("Ambient transcription (3s blank fallback): '%s'", text)
            prompt = extract_wake_prompt(text)
            if prompt and self.on_wake_word:
                logger.info("Wake command completed via 3s blank timeout: '%s'", prompt)
                self.on_wake_word(prompt)
        except Exception as exc:
            logger.debug("Error processing ambient utterance: %s", exc)
        finally:
            self._remove_temp_wav(temp_audio)
