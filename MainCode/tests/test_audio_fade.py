"""Exercise playback fades through the real mixer callback without audio devices."""
import ast
import __future__
from dataclasses import dataclass, field
from pathlib import Path
import threading
import time
from typing import cast
import unittest

import numpy as np


class AudioFadeTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "control/audio_manager.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        tree.body = [n for n in tree.body
                     if getattr(n, "name", None) in {"PlaybackHandle", "_Voice", "DeviceMixer"}]
        self.scope = dict(threading=threading, time=time, np=np, dataclass=dataclass,
                          field=field, cast=cast, _mixers={}, _active_sessions=[],
                          _active_lock=threading.Lock(), log_event=lambda message: None)
        exec(compile(tree, str(path), "exec", flags=__future__.annotations.compiler_flag),
             self.scope)
        self.mixer = self.scope["DeviceMixer"]("primary", 0, "test", 1, 10, "test")
        self.scope["_mixers"]["primary"] = self.mixer

    def voice(self):
        class Source:
            closed = False

            def read(self, frames):
                return np.full((frames, 1), 0.2, dtype=np.float32), False

            def close(self):
                self.closed = True

        handle = self.scope["PlaybackHandle"](1, "music")
        voice = self.scope["_Voice"](Source(), "one", 0, 1.0, handle, True, True)
        self.mixer.voices.append(voice)
        self.scope["_active_sessions"].append(handle)
        return voice, handle

    def render(self, frames=4):
        output = np.zeros((frames, 1), dtype=np.float32)
        self.mixer._callback(output, frames, None, None)
        return output[:, 0]

    def test_fade_is_sample_continuous_and_only_affects_selected_playback(self):
        fading, music = self.voice()
        other, other_music = self.voice()
        np.testing.assert_allclose(self.render(), [0.4] * 4)
        music.fade_out(seconds=1)
        self.assertFalse(music.done.is_set())
        np.testing.assert_allclose(self.render(), [0.40, 0.38, 0.36, 0.34], atol=1e-7)
        np.testing.assert_allclose(self.render(), [0.32, 0.30, 0.28, 0.26], atol=1e-7)
        np.testing.assert_allclose(self.render(), [0.24, 0.22, 0.20, 0.20], atol=1e-7)
        self.assertTrue(music.done.is_set())
        self.assertTrue(music.cancelled)
        self.assertTrue(fading.source.closed)
        self.assertFalse(other_music.done.is_set())
        self.assertFalse(other.source.closed)
        np.testing.assert_allclose(self.render(), [0.2] * 4)

    def test_immediate_stop_interrupts_an_active_fade(self):
        voice, music = self.voice()
        music.fade_out(10)
        self.render()
        music.stop()
        np.testing.assert_array_equal(self.render(), [0] * 4)
        self.assertTrue(music.done.is_set())
        self.assertTrue(voice.source.closed)

    def test_zero_duration_stops_without_playing_another_block(self):
        _, music = self.voice()
        music.fade_out(0)
        np.testing.assert_array_equal(self.render(), [0] * 4)
        self.assertTrue(music.done.is_set())

    def test_repeated_request_does_not_restart_the_fade(self):
        _, music = self.voice()
        music.fade_out(1)
        self.render()
        music.fade_out(20)
        self.render()
        self.render()
        self.assertTrue(music.done.is_set())
        music.fade_out(1)  # A finished handle remains finished.
        self.assertTrue(music.done.is_set())

    def test_invalid_durations_do_not_change_playback(self):
        _, music = self.voice()
        for value in (-1, float("nan"), float("inf"), True):
            with self.subTest(seconds=value), self.assertRaises(ValueError):
                music.fade_out(value)
        np.testing.assert_allclose(self.render(), [0.2] * 4)
        self.assertFalse(music.done.is_set())


if __name__ == "__main__":
    unittest.main()
