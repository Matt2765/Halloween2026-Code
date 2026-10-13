from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
import pedro
from control import audio_manager as audio
from control import pedro_service as service


class FakeController:
    def __init__(self):
        self.connected, self.stop_event = threading.Event(), threading.Event()
        self.connected.set()
        self.state, self.thread, self.link_epoch, self.last_error = "off", None, 0, None
        self.starts = 0

    def start(self):
        self.starts += 1

    def set_state(self, state):
        self.state = state

    def close(self):
        self.state = "off"
        self.stop_event.set()


class FakeHandle:
    def __init__(self):
        self.done, self.cancelled = threading.Event(), False

    def stop(self):
        self.cancelled = True
        self.done.set()


def eventually(predicate):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class PedroServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.quips = Path(self.temp.name)
        (self.quips / "Quip01.mp3").touch()
        self.controller = FakeController()
        self.handles = []
        self.calls = []

        def play(*args, **kwargs):
            handle = FakeHandle()
            self.handles.append(handle)
            self.calls.append((args, kwargs))
            return handle

        self.patches = [patch.object(audio, "play_audio", side_effect=play),
                        patch.object(service.house, "systemState", "ONLINE"),
                        patch.object(service, "_show", None),
                        patch.object(pedro.rsm, "init")]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(service.stop_pedro)

    def test_shared_main_service_routes_and_restarts_without_opening_serial(self):
        real_show = pedro.PedroShow

        def create(*args, **kwargs):
            kwargs["controller"] = self.controller
            return real_show(*args, **kwargs)

        with patch.object(service, "PedroShow", side_effect=create):
            self.assertTrue(service.start_pedro(quips=self.quips, gain=0.7))
            self.assertTrue(eventually(lambda: self.controller.state == "active"))
            self.assertEqual(self.calls[0][0][0], "CabinRoom_Wall")
            self.assertEqual(self.calls[0][1]["gain"], 0.7)
            self.assertFalse(self.calls[0][1]["honor_breakcheck"])
            first_show = service._show
            self.assertTrue(service.start_pedro(quips=self.quips))
            self.assertIs(service._show, first_show)
            service.stop_pedro()
            self.assertTrue(self.handles[0].cancelled)
            self.assertEqual(self.controller.state, "off")
            self.assertFalse(first_show.thread.is_alive())
            self.assertTrue(service.start_pedro("Basement", quips=self.quips))
            self.assertTrue(eventually(lambda: len(self.calls) == 2))
            self.assertEqual(self.calls[-1][0][0], "Basement")
            self.assertTrue(service.pedro_status()["running"])
            pedro.rsm.init.assert_not_called()

    def test_online_state_change_stops_voice_and_parks(self):
        show = pedro.PedroShow(quips=self.quips, controller=self.controller,
                              enabled=lambda: service.house.systemState == "ONLINE")
        self.addCleanup(show.close)
        show.start()
        self.assertTrue(eventually(lambda: self.controller.state == "active"))
        service.house.systemState = "EmergencyShutoff"
        self.assertTrue(eventually(lambda: not show.thread.is_alive()))
        self.assertTrue(self.handles[0].cancelled)
        self.assertEqual(self.controller.state, "off")

    def test_stop_cancels_background_and_voice_only(self):
        show = pedro.PedroShow(quips=self.quips, background=self.quips / "ambient.mp3",
                              controller=self.controller)
        self.addCleanup(show.close)
        show.start()
        self.assertTrue(eventually(lambda: len(self.handles) == 2))
        show.stop()
        self.assertTrue(all(handle.cancelled for handle in self.handles))
        self.assertTrue(self.calls[0][1]["looping"])
        self.assertFalse(self.calls[1][1]["looping"])
        self.assertFalse(show.thread.is_alive())

    def test_invalid_channel_missing_assets_and_offline_start_are_rejected(self):
        with patch.object(pedro, "PedroController", return_value=self.controller):
            self.assertFalse(service.start_pedro("typo", quips=self.quips))
            self.assertFalse(service.start_pedro(quips=self.quips / "missing"))
            service.house.systemState = "SoftShutdown"
            self.assertFalse(service.start_pedro(quips=self.quips))
        self.assertFalse(self.handles)
        self.assertEqual(self.controller.starts, 0)


if __name__ == "__main__":
    unittest.main()
