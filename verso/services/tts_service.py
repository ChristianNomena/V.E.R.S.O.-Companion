"""
V.E.R.S.O. - Text-to-Speech (TTS) Service
Cross-platform neural vocal output (Piper, offline after the one-time voice
download) with automatic fallback to the native OS voices when Piper, its
voice model, or a WAV player is unavailable.
"""

import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from verso.config import (
    PIPER_DATA_DIR,
    PIPER_USE_CUDA,
    PIPER_VOICE,
    TTS_PROVIDER,
    TTS_SPEECH_RATE,
    TTS_VOICE_NAME,
)

logger = logging.getLogger(__name__)


class TTSService:
    """Handles vocal synthesis output for the companion assistant."""

    _current_process: Optional[subprocess.Popen] = None
    _process_lock = threading.Lock()
    _speech_lock = threading.Lock()
    _speech_epoch = 0
    _cached_english_voice: Optional[str] = None
    _piper_voice: Any = None
    _piper_lock = threading.Lock()
    _piper_unavailable: bool = False

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

    @staticmethod
    def clean_for_speech(text: str) -> str:
        """Strips Markdown/formatting so speech reads words, not symbols.

        Removes bold/italic/code markers, headings, quotes, list bullets,
        link/image syntax (keeping the visible label), bare URLs, and table
        pipes. The displayed text is untouched; this is speech-only.
        """
        cleaned = text or ""
        cleaned = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", cleaned)  # image -> alt
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cleaned)  # link -> label
        cleaned = re.sub(r"https?://\S+", "", cleaned)  # bare URLs are unreadable
        cleaned = re.sub(r"<[^>]+>", "", cleaned)  # HTML tags
        cleaned = cleaned.replace("**", "").replace("__", "")
        cleaned = cleaned.replace("*", "").replace("`", "").replace("~", "")
        cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", cleaned)  # headings
        cleaned = re.sub(r"(?m)^\s*>\s?", "", cleaned)  # blockquotes
        cleaned = re.sub(r"(?m)^\s*[-+]\s+", "", cleaned)  # bullet markers
        cleaned = cleaned.replace("|", ", ")
        cleaned = cleaned.replace("_", " ")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    @classmethod
    def _speech_chunks(cls, text: str, max_chars: int = 220) -> List[str]:
        """Groups sentences into speakable chunks (bounded length each).

        Speaking sentence-sized chunks lets playback start after the first
        sentence is synthesized instead of waiting for the whole answer.
        """
        sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+", (text or "").strip())
            if s.strip()
        ]
        chunks: List[str] = []
        current = ""
        for sentence in sentences:
            while len(sentence) > max_chars:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(sentence[:max_chars].rstrip())
                sentence = sentence[max_chars:].lstrip()
            if not current:
                current = sentence
            elif len(current) + 1 + len(sentence) <= max_chars:
                current = f"{current} {sentence}"
            else:
                chunks.append(current)
                current = sentence
        if current:
            chunks.append(current)
        return chunks

    @classmethod
    def _kill_current_process(cls) -> None:
        """Kills the active playback process without invalidating queued speech."""
        with cls._process_lock:
            if cls._current_process and cls._current_process.poll() is None:
                try:
                    cls._current_process.kill()
                    cls._current_process.wait(timeout=0.5)
                except Exception:
                    pass
            cls._current_process = None

    @classmethod
    def stop(cls) -> None:
        """Stops everything spoken: current playback, remaining chunks, and
        any queued speech that has not started yet."""
        cls._speech_epoch += 1
        cls._kill_current_process()

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
        A later stop() invalidates this request, even if it is still queued.
        """
        if not text or not text.strip():
            if on_complete:
                on_complete()
            return

        cls._speech_epoch += 1
        token = cls._speech_epoch
        thread = threading.Thread(
            target=cls._speak_sync,
            args=(text, on_started, on_complete, token),
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
        token: Optional[int] = None,
    ) -> None:
        # Halt any active speech process immediately before acquiring the lock
        cls._kill_current_process()
        if token is None:
            token = cls._speech_epoch

        # Speak cleaned text, sentence chunk by sentence chunk, so playback
        # starts early and never reads Markdown symbols aloud.
        chunks = cls._speech_chunks(cls.clean_for_speech(text))
        if not chunks:
            if on_complete:
                on_complete()
            return

        # Guarantee serialized single speech execution across the application
        with cls._speech_lock:
            if cls._speech_epoch != token:
                # stop() (or a newer speak) superseded this queued request.
                if on_complete:
                    try:
                        on_complete()
                    except Exception:
                        pass
                return
            if on_started:
                try:
                    on_started()
                except Exception as exc:
                    logger.error("Error in on_started callback: %s", exc)

            try:
                for chunk in chunks:
                    if cls._speech_epoch != token:
                        break  # stop() was requested between chunks
                    if not cls._try_speak_piper(chunk):
                        cls._speak_system(chunk)
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

    @classmethod
    def _piper_data_dir(cls) -> Path:
        """Voice model storage (same default layout on all platforms)."""
        if PIPER_DATA_DIR:
            return Path(PIPER_DATA_DIR).expanduser()
        return Path.home() / ".cache" / "verso" / "piper-voices"

    @classmethod
    def _get_piper_voice(cls) -> Optional[Any]:
        """Loads (downloading once if needed) and caches the Piper voice.

        Returns None when Piper is unusable (package missing, voice download
        failed, model unloadable). A failure disables Piper for the rest of
        the session so every utterance does not pay a slow retry.
        """
        with cls._piper_lock:
            if cls._piper_unavailable:
                return None
            if cls._piper_voice is not None:
                return cls._piper_voice
            try:
                from piper import PiperVoice
                from piper.download_voices import download_voice
            except ImportError as exc:
                logger.warning(
                    "Piper TTS unavailable (piper-tts not installed): %s", exc
                )
                cls._piper_unavailable = True
                return None
            try:
                data_dir = cls._piper_data_dir()
                data_dir.mkdir(parents=True, exist_ok=True)
                model_path = data_dir / f"{PIPER_VOICE}.onnx"
                if not model_path.exists():
                    logger.info(
                        "Downloading Piper voice '%s' (one-time, ~60 MB)...",
                        PIPER_VOICE,
                    )
                    download_voice(PIPER_VOICE, data_dir)
                cls._piper_voice = PiperVoice.load(
                    str(model_path), use_cuda=PIPER_USE_CUDA
                )
                logger.info("Piper voice '%s' ready", PIPER_VOICE)
                return cls._piper_voice
            except Exception as exc:
                logger.warning(
                    "Piper TTS failed, falling back to system voices: %s", exc
                )
                cls._piper_unavailable = True
                return None

    @classmethod
    def _piper_length_scale(cls) -> float:
        """Approximates TTS_SPEECH_RATE (words/min) as a Piper length scale."""
        try:
            rate = float(TTS_SPEECH_RATE)
        except (TypeError, ValueError):
            rate = 175.0
        if rate <= 0:
            rate = 175.0
        return min(2.0, max(0.5, 175.0 / rate))

    @classmethod
    def _playback_command(cls, wav_path: str) -> List[str]:
        """Native per-OS command line playing a WAV file to completion."""
        current_os = platform.system()
        if current_os == "Darwin":
            return ["afplay", wav_path]
        if current_os == "Windows":
            escaped = wav_path.replace('"', '""')
            return [
                "powershell",
                "-NoProfile",
                "-Command",
                f'(New-Object System.Media.SoundPlayer("{escaped}")).PlaySync()',
            ]
        player = (
            shutil.which("aplay") or shutil.which("paplay") or shutil.which("play")
        )
        if player is None:
            raise RuntimeError("no WAV player found (aplay/paplay/play)")
        if Path(player).name == "aplay":
            return [player, "-q", wav_path]
        return [player, wav_path]

    @classmethod
    def _try_speak_piper(cls, text: str) -> bool:
        """Synthesizes with Piper and plays the result.

        Returns True when Piper spoke, False when the caller must fall back
        to the system voices (provider disabled, voice unavailable, or no
        WAV player installed).
        """
        if TTS_PROVIDER != "piper":
            return False
        voice = cls._get_piper_voice()
        if voice is None:
            return False
        try:
            from piper.config import SynthesisConfig

            syn_config = SynthesisConfig(length_scale=cls._piper_length_scale())
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                wav_path = tmp.name
            try:
                with wave.open(wav_path, "wb") as wav_file:
                    voice.synthesize_wav(text, wav_file, syn_config=syn_config)
                cmd = cls._playback_command(wav_path)
                with cls._process_lock:
                    cls._current_process = subprocess.Popen(
                        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                cls._current_process.wait()
            finally:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass
            return True
        except Exception as exc:
            logger.warning(
                "Piper synthesis/playback failed, falling back to system: %s", exc
            )
            return False

    @classmethod
    def _speak_system(cls, text: str) -> None:
        """Speaks with the native OS voices (say / SAPI / spd-say)."""
        current_os = platform.system()
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
