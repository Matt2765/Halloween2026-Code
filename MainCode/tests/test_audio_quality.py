"""Signal-level checks for fallback stereo, routing and rate conversion."""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control import audio_manager as audio


class AudioQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "stereo.wav"
        self.samples = np.tile(np.array([[0.2, 0.8], [0.4, -0.6]], np.float32), (100, 1))
        sf.write(self.path, self.samples, 48000, subtype="FLOAT")
        self.patches = [
            patch.object(audio.house, "HouseActive", True),
            patch.object(audio.house, "systemState", "ONLINE"),
            patch.dict(audio.primary_channels, {
                "quality_left": {"index": 3, "gain": 1.0},
                "quality_right": {"index": 5, "gain": 1.0},
                "stereo_quality_pair": {"index": [6, 2], "gain": 1.0},
            }, clear=True),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.mixers = []

    def tearDown(self):
        for mixer in self.mixers:
            mixer.stop_matching(lambda voice: True)
            self.render(mixer)

    def mixer(self, fallback=False):
        mixer = audio.DeviceMixer("primary", 3, "test output", 2 if fallback else 8,
                                  48000, "test", fallback)
        self.mixers.append(mixer)
        return mixer

    def render(self, mixer, frames=200):
        output = np.zeros((frames, mixer.channels), np.float32)
        mixer._callback(output, frames, None, None)
        return output

    def test_fallback_preserves_original_stereo_for_mono_and_all_requests(self):
        for route in ("quality_left", "all"):
            mixer = self.mixer(True)
            with patch.object(audio, "_mixer", return_value=mixer):
                audio.play_audio(route, str(self.path))
            np.testing.assert_array_equal(self.render(mixer), self.samples)
            self.assertEqual(mixer.clipped_samples, 0)

    def test_same_file_to_two_fallback_rooms_plays_one_aligned_copy(self):
        mixer = self.mixer(True)
        with patch.object(audio, "_mixer", return_value=mixer):
            audio.play_audio("quality_left", str(self.path))
            audio.play_audio("quality_right", str(self.path))
        self.assertEqual(len(mixer.voices), 1)
        np.testing.assert_array_equal(self.render(mixer), self.samples)
        self.assertEqual(mixer.clipped_samples, 0)

    def test_same_route_retrigger_is_not_deduplicated(self):
        mixer = self.mixer(True)
        with patch.object(audio, "_mixer", return_value=mixer):
            audio.play_audio("quality_left", str(self.path), gain=0.25)
            audio.play_audio("quality_left", str(self.path), gain=0.25)
        self.assertEqual(len(mixer.voices), 2)

    def test_configured_mono_routes_stay_independent_and_use_both_source_sides(self):
        mixer = self.mixer()
        with patch.object(audio, "_mixer", return_value=mixer):
            audio.play_audio("quality_left", str(self.path))
            audio.play_audio("quality_right", str(self.path))
        self.assertEqual(len(mixer.voices), 2)
        output = self.render(mixer)
        for channel in (3, 5):
            np.testing.assert_array_equal(output[:, channel], self.samples.mean(axis=1))
        np.testing.assert_array_equal(output[:, [0, 1, 2, 4, 6, 7]], 0)

    def test_configured_stereo_mapping_is_sample_exact(self):
        mixer = self.mixer()
        with patch.object(audio, "_mixer", return_value=mixer):
            audio.play_audio("quality_pair", str(self.path))
        output = self.render(mixer)
        np.testing.assert_array_equal(output[:, [6, 2]], self.samples)
        np.testing.assert_array_equal(output[:, [0, 1, 3, 4, 5, 7]], 0)

    def test_equal_sample_rates_are_unchanged(self):
        np.testing.assert_array_equal(audio._resample(self.samples, 48000, 48000), self.samples)

    def test_conversion_headroom_handles_full_scale_reconstructed_peaks(self):
        square = np.tile(np.repeat(np.array([1, -1], np.float32), 24), 1000)[:, None]
        output = audio._resample(square, 48000, 44100)
        self.assertLess(float(np.max(np.abs(output))), 1.0)

    def test_high_frequency_amplitude_survives_rate_conversion(self):
        t = np.arange(44100) / 44100
        tone = (0.5 * np.sin(2 * np.pi * 16000 * t)).astype(np.float32)[:, None]
        output = audio._resample(tone, 44100, 48000)[4096:-4096, 0]
        expected_rms = 0.5 / np.sqrt(2) * 10 ** (-audio.RESAMPLE_HEADROOM_DB / 20)
        level_db = 20 * np.log10(np.sqrt(np.mean(output ** 2)) / expected_rms)
        self.assertLess(abs(level_db), 0.05)

    def test_downsampling_rejects_out_of_band_aliasing(self):
        t = np.arange(48000) / 48000
        tone = (0.5 * np.sin(2 * np.pi * 20000 * t)).astype(np.float32)[:, None]
        output = audio._resample(tone, 48000, 32000)[4096:-4096, 0]
        alias_db = 20 * np.log10(max(float(np.sqrt(np.mean(output ** 2))), 1e-12) / 0.5)
        self.assertLess(alias_db, -80)

    def test_streamed_conversion_matches_whole_file_across_block_boundaries(self):
        rng = np.random.default_rng(42)
        samples = rng.uniform(-0.3, 0.3, (64001, 2)).astype(np.float32)
        path = Path(self.temp.name) / "stream.wav"
        sf.write(path, samples, 48000, subtype="FLOAT")
        expected = audio._resample(samples, 48000, 44100)
        source = audio._StreamedSource(path, 48000, 44100, 2, False)
        self.addCleanup(source.close)
        self.assertTrue(source.eof.wait(5))
        chunks = []
        while True:
            block, done = source.read(1024)
            chunks.append(block)
            if done:
                break
        output = np.concatenate(chunks)
        self.assertEqual(output.shape, expected.shape)
        np.testing.assert_allclose(output, expected, atol=2e-6, rtol=0)
        self.assertEqual(source.underruns, 0)


if __name__ == "__main__":
    unittest.main()

