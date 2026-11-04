"""Headless tests for TTSService (no audio hardware).

Covers the Piper neural voice primary path (with a fake ``piper`` module),
the automatic fallback to native OS voices, WAV player selection, speech-rate
mapping, and playback controls (stop/is_speaking).
"""

import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from verso.services import tts_service
from verso.services.tts_service import TTSService

PIPER_VOICE = "en_US-amy-medium"


def _install_fake_piper():
    """Installs a fake ``piper`` module tree into sys.modules.

    Returns (fake_piper_module, FakeVoice class, download_voice mock).
    The fake voice writes 0.1s of silence into the provided WAV writer.
    """
    fake_piper = types.ModuleType("piper")

    class FakeSynthesisConfig:
        def __init__(self, length_scale=None, **kwargs):
            self.length_scale = length_scale

    fake_config_mod = types.ModuleType("piper.config")
    fake_config_mod.SynthesisConfig = FakeSynthesisConfig

    fake_download_mod = types.ModuleType("piper.download_voices")
    fake_download_mod.download_voice = MagicMock()

    class FakeVoice:
        loaded = []

        @classmethod
        def load(cls, model_path, use_cuda=False):
            voice = FakeVoice()
            voice.model_path = model_path
            voice.use_cuda = use_cuda
            cls.loaded.append(voice)
            return voice

        def synthesize_wav(self, text, wav_file, syn_config=None):
            wav_file.setframerate(22050)
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.writeframes(b"\x00\x00" * 2205)

    fake_piper.PiperVoice = FakeVoice

    modules = {
        "piper": fake_piper,
        "piper.config": fake_config_mod,
        "piper.download_voices": fake_download_mod,
    }
    patcher = patch.dict(sys.modules, modules)
    patcher.start()
    return patcher, FakeVoice, fake_download_mod.download_voice


class TTSServiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(setattr, TTSService, "_piper_voice", None)
        self.addCleanup(setattr, TTSService, "_piper_unavailable", False)
        self.addCleanup(setattr, TTSService, "_current_process", None)
        self.addCleanup(setattr, TTSService, "_cached_english_voice", None)
        TTSService._piper_voice = None
        TTSService._piper_unavailable = False
        TTSService._current_process = None
        TTSService._cached_english_voice = None
        self._patchers = []
        self.addCleanup(self._stop_patchers)

    def _stop_patchers(self):
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._patchers.clear()

    def _patch(self, *args, **kwargs):
        patcher = patch(*args, **kwargs)
        self._patchers.append(patcher)
        return patcher.start()

    def _patch_object(self, target, *args, **kwargs):
        patcher = patch.object(target, *args, **kwargs)
        self._patchers.append(patcher)
        return patcher.start()

    def _voice_dir(self, with_model=False):
        voice_dir = Path(self._tmp.name) / "piper-voices"
        voice_dir.mkdir(parents=True, exist_ok=True)
        if with_model:
            (voice_dir / f"{PIPER_VOICE}.onnx").touch()
        return voice_dir

    def test_system_provider_uses_native_say_on_macos(self):
        self._patch_object(tts_service, "TTS_PROVIDER", "system")
        self._patch("platform.system", return_value="Darwin")
        self._patch_object(TTSService, "get_best_macos_voice", return_value="Samantha")
        popen = self._patch("subprocess.Popen")
        started = threading.Event()
        done = threading.Event()

        TTSService._speak_sync("hello", on_started=started.set, on_complete=done.set)

        popen.assert_called_once()
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[:4], ["say", "-v", "Samantha", "-r"])
        self.assertEqual(cmd[5], "hello")
        self.assertTrue(started.is_set())
        self.assertTrue(done.is_set())

    def test_piper_path_synthesizes_and_plays_wav(self):
        patcher, fake_voice_cls, download_mock = _install_fake_piper()
        self._patchers.append(patcher)
        fake_voice_cls.loaded.clear()
        voice_dir = self._voice_dir(with_model=True)
        self._patch_object(tts_service, "TTS_PROVIDER", "piper")
        self._patch_object(tts_service, "PIPER_VOICE", PIPER_VOICE)
        self._patch_object(TTSService, "_piper_data_dir", return_value=voice_dir)
        self._patch("platform.system", return_value="Darwin")
        popen = self._patch("subprocess.Popen")
        done = threading.Event()

        TTSService._speak_sync("hello there", on_complete=done.set)

        download_mock.assert_not_called()  # model already on disk
        self.assertEqual(len(fake_voice_cls.loaded), 1)
        popen.assert_called_once()
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[0], "afplay")
        wav_path = Path(cmd[1])
        self.assertEqual(wav_path.suffix, ".wav")
        self.assertFalse(wav_path.exists())  # temp WAV cleaned up
        self.assertTrue(done.is_set())

    def test_piper_downloads_voice_once_when_missing(self):
        patcher, fake_voice_cls, download_mock = _install_fake_piper()
        self._patchers.append(patcher)
        fake_voice_cls.loaded.clear()
        voice_dir = self._voice_dir(with_model=False)
        self._patch_object(tts_service, "TTS_PROVIDER", "piper")
        self._patch_object(tts_service, "PIPER_VOICE", PIPER_VOICE)
        self._patch_object(TTSService, "_piper_data_dir", return_value=voice_dir)
        self._patch("platform.system", return_value="Darwin")
        self._patch("subprocess.Popen")

        TTSService._speak_sync("hello")

        download_mock.assert_called_once_with(PIPER_VOICE, voice_dir)
        self.assertEqual(len(fake_voice_cls.loaded), 1)

    def test_piper_failure_falls_back_to_system_voice(self):
        self._patch_object(tts_service, "TTS_PROVIDER", "piper")
        self._patch_object(TTSService, "_get_piper_voice", return_value=None)
        self._patch("platform.system", return_value="Darwin")
        self._patch_object(TTSService, "get_best_macos_voice", return_value="Samantha")
        popen = self._patch("subprocess.Popen")
        done = threading.Event()

        TTSService._speak_sync("hello", on_complete=done.set)

        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0][:3], ["say", "-v", "Samantha"])
        self.assertTrue(done.is_set())

    def test_piper_not_installed_falls_back_and_stays_disabled(self):
        with patch.dict(sys.modules, {"piper": None, "piper.download_voices": None}):
            self._patch_object(tts_service, "TTS_PROVIDER", "piper")
            self._patch("platform.system", return_value="Darwin")
            self._patch_object(TTSService, "get_best_macos_voice", return_value="Samantha")
            popen = self._patch("subprocess.Popen")

            TTSService._speak_sync("hello")

            popen.assert_called_once()
            self.assertEqual(popen.call_args.args[0][:3], ["say", "-v", "Samantha"])
            self.assertTrue(TTSService._piper_unavailable)
            # Second call must not retry the failed import.
            TTSService._get_piper_voice()
            self.assertTrue(TTSService._piper_unavailable)

    def test_windows_playback_uses_sound_player(self):
        with patch("platform.system", return_value="Windows"):
            cmd = TTSService._playback_command("C:\\Temp\\sample.wav")
        self.assertEqual(cmd[0], "powershell")
        self.assertIn("SoundPlayer", cmd[-1])
        self.assertIn("C:\\Temp\\sample.wav", cmd[-1])

    def test_linux_playback_prefers_aplay_then_paplay(self):
        with (
            patch("platform.system", return_value="Linux"),
            patch("shutil.which", side_effect=lambda name: f"/usr/bin/{name}"),
        ):
            self.assertEqual(
                TTSService._playback_command("/tmp/s.wav"),
                ["/usr/bin/aplay", "-q", "/tmp/s.wav"],
            )
        with (
            patch("platform.system", return_value="Linux"),
            patch("shutil.which", side_effect=lambda name: None if name == "aplay" else "/usr/bin/paplay"),
        ):
            self.assertEqual(
                TTSService._playback_command("/tmp/s.wav"),
                ["/usr/bin/paplay", "/tmp/s.wav"],
            )
        with (
            patch("platform.system", return_value="Linux"),
            patch("shutil.which", return_value=None),
        ):
            with self.assertRaises(RuntimeError):
                TTSService._playback_command("/tmp/s.wav")

    def test_linux_without_player_falls_back_to_system_voice(self):
        patcher, _, _ = _install_fake_piper()
        self._patchers.append(patcher)
        voice_dir = self._voice_dir(with_model=True)
        self._patch_object(tts_service, "TTS_PROVIDER", "piper")
        self._patch_object(tts_service, "PIPER_VOICE", PIPER_VOICE)
        self._patch_object(TTSService, "_piper_data_dir", return_value=voice_dir)
        self._patch("platform.system", return_value="Linux")
        self._patch("shutil.which", return_value=None)
        popen = self._patch("subprocess.Popen")

        TTSService._speak_sync("hello")

        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0][:3], ["spd-say", "-l", "en"])

    def test_length_scale_maps_speech_rate(self):
        with patch.object(tts_service, "TTS_SPEECH_RATE", 175):
            self.assertAlmostEqual(TTSService._piper_length_scale(), 1.0)
        with patch.object(tts_service, "TTS_SPEECH_RATE", 350):
            self.assertAlmostEqual(TTSService._piper_length_scale(), 0.5)
        with patch.object(tts_service, "TTS_SPEECH_RATE", 50):
            self.assertAlmostEqual(TTSService._piper_length_scale(), 2.0)
        with patch.object(tts_service, "TTS_SPEECH_RATE", "invalid"):
            self.assertAlmostEqual(TTSService._piper_length_scale(), 1.0)

    def test_stop_and_is_speaking(self):
        self.assertFalse(TTSService.is_speaking())
        proc = MagicMock()
        proc.poll.return_value = None
        TTSService._current_process = proc
        self.assertTrue(TTSService.is_speaking())
        TTSService.stop()
        proc.kill.assert_called_once()
        self.assertIsNone(TTSService._current_process)
        self.assertFalse(TTSService.is_speaking())

    def test_speech_text_strips_markdown(self):
        cleaned = TTSService.clean_for_speech(
            "**Bold** move: run `git status` and see [the docs](https://example.com/x)\n"
            "- first *step*\n"
            "- second _step_"
        )
        self.assertNotIn("*", cleaned)
        self.assertNotIn("`", cleaned)
        self.assertNotIn("https://", cleaned)
        self.assertIn("Bold move: run git status", cleaned)
        self.assertIn("the docs", cleaned)
        self.assertIn("first step", cleaned)
        self.assertIn("second step", cleaned)

    def test_speak_sync_speaks_cleaned_text(self):
        self._patch_object(tts_service, "TTS_PROVIDER", "system")
        self._patch("platform.system", return_value="Darwin")
        self._patch_object(TTSService, "get_best_macos_voice", return_value="Samantha")
        popen = self._patch("subprocess.Popen")

        TTSService._speak_sync("**Hello** `world`")

        self.assertEqual(popen.call_args.args[0][-1], "Hello world")

    def test_speech_chunks_split_long_text_by_sentence(self):
        chunks = TTSService._speech_chunks("A" * 150 + ". " + "B" * 150 + ".")
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].startswith("A"))
        self.assertTrue(chunks[1].startswith("B"))
        # Short text stays a single chunk.
        self.assertEqual(TTSService._speech_chunks("One. Two!"), ["One. Two!"])

    def test_stop_prevents_queued_speech_from_starting(self):
        popen = self._patch("subprocess.Popen")
        self._patch_object(tts_service, "TTS_PROVIDER", "system")
        done = threading.Event()
        TTSService._speech_lock.acquire()
        try:
            TTSService.speak("queued hello", on_complete=done.set)
            TTSService.stop()
        finally:
            TTSService._speech_lock.release()
        self.assertTrue(done.wait(timeout=3.0))
        popen.assert_not_called()

    def test_stt_stop_kills_recording_process(self):
        from verso.services.stt_service import STTService

        proc = MagicMock()
        proc.poll.return_value = None
        STTService._record_process = proc
        STTService._is_recording = True
        try:
            STTService.stop()
        finally:
            STTService._record_process = None
            STTService._is_recording = False
        proc.kill.assert_called_once()
        self.assertFalse(STTService._is_recording)

    def test_empty_text_completes_without_speaking(self):
        popen = self._patch("subprocess.Popen")
        done = threading.Event()
        TTSService.speak("   ", on_complete=done.set)
        self.assertTrue(done.wait(timeout=2.0))
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
