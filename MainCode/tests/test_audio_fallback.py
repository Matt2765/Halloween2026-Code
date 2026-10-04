"""Regression tests for unplugged show hardware and physical-device logging."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control import audio_manager as audio


class FakeDevices:
    default = SimpleNamespace(device=[0, 3])
    devices = [
        {"name": "Input", "max_output_channels": 0, "default_samplerate": 48000},
        {"name": "Input", "max_output_channels": 0, "default_samplerate": 48000},
        {"name": "Other output", "max_output_channels": 2, "default_samplerate": 48000},
        {"name": "Laptop Speakers", "max_output_channels": 2, "default_samplerate": 44100},
    ]

    @classmethod
    def query_devices(cls, index=None):
        if index is None:
            return cls.devices
        if index == 13:
            return {"name": "Virtual output", "max_output_channels": 2, "default_samplerate": 48000}
        return cls.devices[index]

    @staticmethod
    def query_hostapis():
        return [{"name": "MME", "devices": [2, 3, 13]}]


class AudioFallbackTests(unittest.TestCase):
    def settings(self):
        return patch.multiple(audio, sd=FakeDevices, PRIMARY_DEVICE_INDEX=13,
                              SECONDARY_DEVICE_INDEX=30, PRIMARY_DEVICE_NAME=None,
                              SECONDARY_DEVICE_NAME=None, FALLBACK_TO_SYSTEM_DEFAULT=True)

    def test_reassigned_index_with_too_few_channels_uses_system_default(self):
        with self.settings(), patch.object(audio.DeviceMixer, "start"), \
             patch.dict(audio._mixers, {}, clear=True):
            mixer = audio._make_mixer("primary")
        self.assertEqual(mixer.device_index, 3)
        self.assertEqual(mixer.device_name, "Laptop Speakers")
        self.assertTrue(mixer.fallback_to_all)

    def test_expected_name_rejects_another_eight_channel_device(self):
        wrong = {"name": "Wrong eight-channel output", "max_output_channels": 8,
                 "default_samplerate": 48000}
        original = FakeDevices.query_devices
        def query(index=None):
            return wrong if index == 13 else original(index)
        with self.settings(), patch.object(audio, "PRIMARY_DEVICE_NAME", "RX-V673"), \
             patch.object(FakeDevices, "query_devices", side_effect=query), \
             patch.object(audio.DeviceMixer, "start"), patch.dict(audio._mixers, {}, clear=True):
            mixer = audio._make_mixer("primary")
        self.assertEqual(mixer.device_index, 3)

    def test_valid_show_device_keeps_discrete_routing(self):
        valid = {"name": "RX-V673", "max_output_channels": 8, "default_samplerate": 48000}
        with self.settings(), patch.object(audio, "PRIMARY_DEVICE_NAME", "RX-V673"), \
             patch.object(FakeDevices, "query_devices", return_value=valid), \
             patch.object(audio.DeviceMixer, "start"):
            mixer = audio._make_mixer("primary")
        self.assertEqual(mixer.device_index, 13)
        self.assertFalse(mixer.fallback_to_all)

    def test_secondary_prefers_default_over_unrelated_primary(self):
        primary = audio.DeviceMixer("primary", 77, "Connected show device", 8, 48000, "WASAPI")
        with self.settings(), patch.object(audio.DeviceMixer, "start"), \
             patch.dict(audio._mixers, {"primary": primary}, clear=True):
            mixer = audio._make_mixer("secondary")
        self.assertEqual(mixer.device_index, 3)
        self.assertEqual(mixer.device_name, "Laptop Speakers")

    def test_secondary_reuses_default_stream_without_opening_it_twice(self):
        primary = audio.DeviceMixer("primary", 3, "Laptop Speakers", 2, 44100, "MME", True)
        with self.settings(), patch.object(audio.DeviceMixer, "start") as start, \
             patch.dict(audio._mixers, {"primary": primary}, clear=True):
            mixer = audio._make_mixer("secondary")
        self.assertIs(mixer.backing, primary)
        start.assert_not_called()

    def test_disabled_fallback_reports_wrong_device(self):
        with self.settings(), patch.object(audio, "FALLBACK_TO_SYSTEM_DEFAULT", False):
            with self.assertRaisesRegex(RuntimeError, "channel table requires"):
                audio._make_mixer("primary")

    def test_failed_default_tries_another_output(self):
        def start(mixer):
            if mixer.device_index == 3:
                raise RuntimeError("Unavailable")
        with self.settings(), patch.object(audio.DeviceMixer, "start", start), \
             patch.dict(audio._mixers, {}, clear=True):
            mixer = audio._make_mixer("primary")
        self.assertEqual(mixer.device_index, 2)

    def test_playback_log_and_diagnostics_identify_physical_device(self):
        primary = audio.DeviceMixer("primary", 3, "Laptop Speakers", 2, 44100, "MME")
        secondary = audio._FallbackMixerView("secondary", primary)
        source = audio._CachedSource(np.zeros((1, 1), np.float32), False)
        voice = audio._Voice(source, "all", 0, 1, audio._Session(1, "clip.wav@room"),
                             False, False)
        with patch.object(audio, "log_event") as log:
            secondary.add(voice)
        message = log.call_args.args[0]
        for text in ("Laptop Speakers", "idx=3", "host=MME", "SECONDARY", "fallback=True"):
            self.assertIn(text, message)
        self.assertEqual(secondary.diagnostics()["device_name"], "Laptop Speakers")
        self.assertTrue(secondary.diagnostics()["fallback"])
        primary._callback(np.zeros((1, 2), np.float32), 1, None, None)


if __name__ == "__main__":
    unittest.main()

