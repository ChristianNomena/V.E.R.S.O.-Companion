"""
V.E.R.S.O. - Audio Cue & Sound Notification Service
Plays instantaneous audible chimes when the assistant starts listening for user input
and when vocal capture finishes.
"""

import logging
import platform
import subprocess
import threading

logger = logging.getLogger(__name__)


class SoundService:
    """Manages system auditory cues for speech and listening states."""

    @classmethod
    def play_chime(cls) -> None:
        """Plays an instant gentle chime (inviting user to speak)."""
        threading.Thread(target=cls._play_sound_sync, args=("chime",), daemon=True).start()

    @classmethod
    def play_done(cls) -> None:
        """Plays an instant subtle pop sound (confirming speech was captured)."""
        threading.Thread(target=cls._play_sound_sync, args=("done",), daemon=True).start()

    @classmethod
    def _play_sound_sync(cls, sound_type: str) -> None:
        current_os = platform.system()
        try:
            if current_os == "Darwin":
                # High-fidelity native macOS system sound files
                sound_file = (
                    "/System/Library/Sounds/Tink.aiff"
                    if sound_type == "chime"
                    else "/System/Library/Sounds/Pop.aiff"
                )
                subprocess.run(
                    ["afplay", sound_file],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=2.0,
                )
            elif current_os == "Windows":
                # Native Windows sound cue
                ps_script = (
                    "[System.Media.SystemSounds]::Asterisk.Play();"
                    if sound_type == "chime"
                    else "[System.Media.SystemSounds]::Beep.Play();"
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=2.0,
                )
            else:
                # Linux fallback
                subprocess.run(
                    ["paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=2.0,
                )
        except Exception as exc:
            logger.debug("Sound playback skipped: %s", exc)
