"""Disabled playback must never open a device, read a file, or start speech."""
import ast
import __future__
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest


class AudioDisabledTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "control/audio_manager.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        names = {"PlaybackHandle", "_disabled_playback", "initialize_audio",
                 "play_audio", "play_to_named_channel", "play_to_all_channels",
                 "_submit", "_speak"}
        tree.body = [node for node in tree.body if getattr(node, "name", None) in names]
        self.scope = dict(house=SimpleNamespace(DISABLE_AUDIO_MANAGER=True),
                          threading=threading, time=time, _mixers={},
                          log_event=lambda message: None)
        # Unprovided dependencies fail if playback gets past the disabled guard.
        exec(compile(tree, str(path), "exec", flags=__future__.annotations.compiler_flag), self.scope)

    def test_disabled_initialization_and_speech_do_not_open_devices(self):
        self.scope["initialize_audio"]()
        self.scope["_speak"]("hello", None, 1, 0)
        self.assertEqual(self.scope["_mixers"], {})

    def test_disabled_playback_returns_completed_handles_without_file_access(self):
        calls = [
            ("play_audio", ("hello",)),
            ("play_audio", ("CabinRoom", "missing.wav")),
            ("play_to_named_channel", ("missing.wav", "CabinRoom")),
            ("play_to_all_channels", ("missing.wav",)),
            ("_submit", (Path("missing.wav"), None, "all", 0, 1, False, True, True, False)),
        ]
        for name, args in calls:
            with self.subTest(name=name, args=args):
                handle = self.scope[name](*args)
                self.assertTrue(handle.done.wait(0))
                self.assertTrue(handle.cancelled)
                handle.stop()


if __name__ == "__main__":
    unittest.main()
