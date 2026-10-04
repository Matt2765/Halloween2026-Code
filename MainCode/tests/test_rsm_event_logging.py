import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "rsm_logging_tests", Path(__file__).parents[1] / "control" / "remote_sensor_monitor.py")
rsm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rsm)


class EventLoggingTests(unittest.TestCase):
    def setUp(self):
        self.shared = {}
        self.tof_events = {}
        self.seq = 0
        self.logger = patch.object(rsm, "_log_event")
        self.log = self.logger.start()
        self.addCleanup(self.logger.stop)

    def update(self, kind, vals, sid=None, queue_ms=0):
        self.seq += 1
        sid = sid or kind.upper() + "1"
        previous = self.shared.get(sid)
        obj = dict(v=1, type="device", id=sid, kind=kind, vals=vals,
                   session=1, seq=self.seq, mac="AA:BB:CC:DD:EE:FF", queue_ms=queue_ms)
        if rsm._ingest(self.shared, {}, obj, 10000):
            rsm._log_device_changes(previous, self.shared[sid], 10000, self.tof_events)

    def test_tof_logs_two_sample_trip_and_clear_without_heartbeat_spam(self):
        for distance in (1000, 700):
            self.update("tof", dict(valid=True, status=0, dist_mm=distance))
        self.log.assert_not_called()
        for distance in (600, 650, 825, 900, 1000):
            self.update("tof", dict(valid=True, status=0, dist_mm=distance))
        self.assertEqual(self.log.call_count, 2)
        self.assertIn("tripped", self.log.call_args_list[0].args[0])
        self.assertIn("cleared", self.log.call_args_list[1].args[0])

    def test_invalid_or_stale_tof_never_trips_or_fakes_a_clear(self):
        for _ in range(2):
            self.update("tof", dict(valid=True, status=0, dist_mm=500))
        self.log.reset_mock()
        self.update("tof", dict(valid=False, status=1))
        for _ in range(2):
            self.update("tof", dict(valid=True, status=0, dist_mm=500), queue_ms=1000)
        self.log.assert_not_called()

    def test_pir_ignores_warmup_and_logs_edges_only(self):
        for ready, output in ((False, True), (True, False), (True, True),
                              (True, True), (True, False)):
            self.update("pir", dict(ready=ready, output=output))
        self.assertEqual([call.args[0] for call in self.log.call_args_list],
                         ["PIR1 tripped", "PIR1 cleared"])

    def test_panel_buttons_keep_independent_edges_and_capture_short_taps(self):
        for index, pressed in ((1, False), (2, True), (1, True), (2, True),
                               (2, False), (1, False)):
            self.update("button", dict(btn=index, pressed=pressed), sid="Multi_BTN1")
        self.assertEqual([call.args[0] for call in self.log.call_args_list], [
            "Multi_BTN1 button 2 pressed", "Multi_BTN1 button 1 pressed",
            "Multi_BTN1 button 2 released", "Multi_BTN1 button 1 released"])

    def test_lantern_logs_mode_changes_only_and_servo_stays_silent(self):
        for mode, brightness in (("off", 0), ("flickering_on", 100), ("flickering_on", 200)):
            self.update("lantern", dict(lantern_state=mode, brightness=brightness,
                                        synced=True, next_command_id=1, sync_generation=0))
        self.assertEqual([call.args[0] for call in self.log.call_args_list],
                         ["LANTERN1 state: off", "LANTERN1 state: flickering_on"])
        self.log.reset_mock()
        self.update("servo", dict(output_angle=20, moving=True))
        self.update("servo", dict(output_angle=90, moving=False))
        self.log.assert_not_called()

    def test_disconnected_bridge_logs_immediately_then_at_ten_second_intervals(self):
        clock = [0]
        waits = iter((1000, 10000))

        def advance(_):
            clock[0] += next(waits)  # StopIteration ends the otherwise persistent worker.

        with patch.object(rsm, "_open_serial", side_effect=OSError("not connected")), \
                patch.object(rsm, "_now_ms", side_effect=lambda: clock[0]), \
                patch.object(rsm.time, "sleep", side_effect=advance):
            with self.assertRaises(StopIteration):
                rsm._monitor_main({}, {}, None, "COM6", rsm.DEFAULT_BAUD)
        self.assertEqual(self.log.call_count, 3)  # Startup plus two unavailable messages.
        self.assertIn("Starting monitor", self.log.call_args_list[0].args[0])
        self.assertIn("Bridge unavailable", self.log.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()
