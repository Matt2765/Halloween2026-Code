"""Exercise real ingestion and recovery without serial, workers, or actuators."""
import ast
from pathlib import Path
import re
import unittest


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "control/remote_sensor_monitor.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        names = {"_newer", "_valid_id", "_uint32", "_record_rejection", "_store_device", "_ingest",
                 "_log_device_health", "get_button_value"}
        tree.body = [n for n in tree.body if getattr(n, "name", None) in names]
        self.shared, self.logs, self.now = {}, [], 0
        self.scope = dict(re=re, MAX_DEVICES=64, CONNECTION_LOG_INTERVAL_MS=10000,
                          CONFLICT_QUIET_MS=10000, DELIVERY_FRESH_MS=400,
                          DEVICE_FRESH_MS=6000, HELD_FRESH_MS=6000, _disabled=False,
                          _log_event=self.logs.append, _now_ms=lambda: self.now,
                          get=self.shared.get)
        exec(compile(tree, str(path), "exec"), self.scope)

    def frame(self, mac="AA:BB:CC:DD:EE:01", session=10, seq=1, pressed=False, **extra):
        return dict(v=1, type="device", id="BTN4", kind="button", mac=mac,
                    session=session, seq=seq, vals=dict(btn=1, pressed=pressed), **extra)

    def ingest(self, obj, now=0, debug=False):
        self.now = now
        return self.scope["_ingest"](self.shared, {}, obj, now, debug)

    def conflict(self, now=100):
        return self.ingest(self.frame(mac="AA:BB:CC:DD:EE:02"), now)

    def test_original_board_recovers_without_reset_and_other_devices_survive(self):
        self.ingest(self.frame())
        self.shared["OTHER"] = {"sentinel": True}
        self.assertFalse(self.conflict())
        self.assertIsNone(self.scope["get_button_value"]("BTN4"))
        self.assertFalse(self.ingest(self.frame(seq=2, pressed=True), 10099))
        self.assertTrue(self.ingest(self.frame(seq=3, pressed=True), 10100))
        self.assertTrue(self.scope["get_button_value"]("BTN4"))
        self.assertEqual(self.shared["OTHER"], {"sentinel": True})
        self.assertIn("conflict cleared", self.logs[-1])

    def test_active_duplicate_keeps_original_blocked_and_never_takes_ownership(self):
        self.ingest(self.frame())
        for now in (100, 9000, 18000, 27000):
            self.assertFalse(self.conflict(now))
            self.assertFalse(self.ingest(self.frame(seq=now), now+9000))
        self.assertEqual(self.shared["BTN4"]["mac"], "AA:BB:CC:DD:EE:01")

    def test_old_sequence_session_and_queued_frames_cannot_unlock_conflict(self):
        self.ingest(self.frame(seq=100))
        self.conflict()
        for obj in (self.frame(seq=99), self.frame(session=9, seq=1000),
                    self.frame(seq=101, queue_ms=400), self.frame(session=11, queue_ms=500)):
            self.assertFalse(self.ingest(obj, 20000, True))
            self.assertTrue(self.shared["BTN4"]["conflict"])
        self.assertTrue(self.ingest(self.frame(session=11), 20001))

    def test_battery_reboot_clears_all_old_multibutton_states(self):
        self.ingest(self.frame(pressed=True))
        second = self.frame(seq=2, pressed=True)
        second["vals"]["btn"] = 2
        self.ingest(second)
        self.assertTrue(self.ingest(self.frame(session=11), 1000, True))
        self.assertEqual(set(self.shared["BTN4"]["buttons"]), {"1"})
        self.assertIsNone(self.scope["get_button_value"]("BTN4", 2))
        self.assertTrue(any("restarted" in log for log in self.logs))

    def test_usb_reconnect_does_not_erase_identity_or_ordering(self):
        self.ingest(self.frame(seq=100))
        self.shared["_connection"] = {"connected": False}
        self.shared["_connection"] = {"connected": True, "host": "new"}
        self.assertFalse(self.ingest(self.frame(seq=99), 10000))
        self.assertTrue(self.ingest(self.frame(seq=101), 10001))
        self.assertFalse(self.conflict(10002))

    def test_bridge_conflict_diagnostics_quarantine_original_and_recover(self):
        self.ingest(self.frame())
        diagnostic = dict(v=1, type="diagnostic", id="BTN4", error="id_conflict",
                          observed_mac="AA:BB:CC:DD:EE:02", expected_mac="AA:BB:CC:DD:EE:01")
        self.ingest(diagnostic, 100)
        self.ingest(diagnostic, 10000)
        self.assertFalse(self.ingest(self.frame(seq=2), 19999))
        self.assertTrue(self.ingest(self.frame(seq=3), 20000))

    def test_rejections_are_throttled_and_debug_details_are_gated(self):
        self.ingest(self.frame(seq=100))
        self.ingest(self.frame(seq=99), 100)
        self.assertEqual(self.logs, [])  # Out-of-order telemetry is debug detail.
        self.ingest(self.frame(session=9), 200)
        self.ingest(self.frame(session=9), 201)
        self.assertEqual(len(self.logs), 1)
        self.assertNotIn("AA:BB", self.logs[0])
        self.ingest(self.frame(session=9), 10200, True)
        self.assertIn("expected_session", self.logs[-1])
        self.assertEqual(self.shared["_rejections"]["BTN4"]["count"], 4)

    def test_loss_and_return_logging_and_expected_battery_sleep(self):
        self.ingest(self.frame())
        states = {}
        health = self.scope["_log_device_health"]
        health(self.shared, states, 0, False)
        health(self.shared, states, 6000, False)
        self.assertEqual(self.logs, [])
        self.ingest(self.frame(seq=2), 7000)
        health(self.shared, states, 7000, True)
        self.assertIn("telemetry resumed", self.logs[-1])
        self.ingest(self.frame(seq=3, pressed=True), 8000)
        health(self.shared, states, 14000, False)
        health(self.shared, states, 15000, False)
        self.assertEqual(sum("telemetry unavailable" in log for log in self.logs), 1)

    def test_old_session_bridge_rejection_does_not_refresh_device_age(self):
        self.ingest(self.frame())
        self.ingest(dict(v=1, type="diagnostic", id="BTN4", error="old_session",
                         session=9, expected_session=10), 10000, True)
        self.assertEqual(self.shared["BTN4"]["t_host_ms"], 0)
        self.assertIn("old_session", self.logs[-1])


if __name__ == "__main__":
    unittest.main()
