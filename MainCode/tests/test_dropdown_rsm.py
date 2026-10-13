import importlib.util
from pathlib import Path
import queue
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "dropdown_rsm_test_module", Path(__file__).parents[1] / "control" / "remote_sensor_monitor.py")
rsm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rsm)


def device(seq=10, session=3, pressed=False):
    return {"v": 1, "type": "device", "id": "DROPDOWN1", "kind": "dropdown",
            "session": session, "seq": seq, "mac": "AA:BB:CC:DD:EE:FF",
            "vals": {"output_angle": 90, "target": 120, "moving": False,
                     "btn": 1, "pressed": pressed, "led": False, "ready": True}}


class DropdownRsmTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(rsm, "_now_ms", return_value=10000)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        rsm._disabled = False
        rsm._shared = {"_connection": {"connected": True, "host": "a" * 32}}
        rsm._commands = {}
        rsm._txq = queue.Queue(32)

    def add(self, **kwargs):
        return rsm._store_device(rsm._shared, device(**kwargs), 10000)

    def test_servo_led_and_button_share_one_device(self):
        self.add(pressed=True)
        self.assertIs(rsm.get_button_value("DROPDOWN1"), True)
        self.assertIs(rsm.get_button_value("DROPDOWN1", 1), True)
        self.assertIsNone(rsm.get_button_value("DROPDOWN1", 2))
        self.assertEqual(rsm.get_servo_state("DROPDOWN1")["output_angle"], 90)
        self.assertIs(rsm.get_value("DROPDOWN1", "led"), False)
        for cid, op, value, duration in [
            (rsm.servo("DROPDOWN1", 120, 800), "move", 120, 800),
            (rsm.led("DROPDOWN1", True), "led", 1, 0),
            (rsm.led("DROPDOWN1", False), "led", 0, 0),
            (rsm.tx_to_id("DROPDOWN1", {"set_default": 45}), "set_default", 45, 300),
        ]:
            request = rsm._txq.get_nowait()
            self.assertEqual((request["op"], request["value"], request["duration_ms"]), (op, value, duration))
            self.assertEqual(request["target_session"], 3)
            self.assertEqual(request["command_id"], cid)

    def test_held_and_released_states_expire_on_powered_node(self):
        for pressed in (False, True):
            rsm._shared.pop("DROPDOWN1", None)
            self.add(pressed=pressed)
            with patch.object(rsm, "_now_ms", return_value=15999):
                self.assertIs(rsm.get_button_value("DROPDOWN1"), pressed)
            with patch.object(rsm, "_now_ms", return_value=16000):
                self.assertIsNone(rsm.get_button_value("DROPDOWN1"))
                self.assertIsNone(rsm.get_value("DROPDOWN1", "pressed"))
                cid = rsm.led("DROPDOWN1", True)
                self.assertEqual(rsm.command_status(cid)["status"], "rejected")

    def test_old_snapshot_cannot_undo_button_or_led_and_reboot_resets(self):
        self.add(pressed=True)
        old = device(seq=9)
        self.assertFalse(rsm._store_device(rsm._shared, old, 10001))
        self.assertIs(rsm.get_button_value("DROPDOWN1"), True)
        self.add(seq=1, session=4, pressed=False)
        self.assertIs(rsm.get_button_value("DROPDOWN1"), False)
        self.assertFalse(self.add(seq=100, session=3, pressed=True))

    def test_invalid_telemetry_preserves_good_state(self):
        self.add()
        for key, value in [("pressed", 1), ("led", 1), ("btn", 2), ("btn", True),
                           ("output_angle", 181), ("moving", 0)]:
            record = device(seq=11)
            record["vals"][key] = value
            with self.assertRaises(ValueError):
                rsm._store_device(rsm._shared, record, 10001)
        self.assertEqual(rsm.get("DROPDOWN1")["seq"], 10)

    def test_invalid_led_values_and_wrong_device_do_not_enqueue(self):
        for value in (1, 0, "on", None):
            with self.assertRaises(ValueError):
                rsm.led("DROPDOWN1", value)
        record = device()
        record["kind"] = "servo"
        rsm._store_device(rsm._shared, record, 10000)
        cid = rsm.led("DROPDOWN1", True)
        self.assertEqual(rsm.command_status(cid)["reason"], "not_a_dropdown")
        self.assertTrue(rsm._txq.empty())

    def test_button_logging_ignores_servo_and_led_snapshots(self):
        self.add()
        previous = rsm.get("DROPDOWN1")
        self.add(seq=11, pressed=True)
        with patch.object(rsm, "_log_event") as log:
            rsm._log_device_changes(previous, rsm.get("DROPDOWN1"), 10000, {})
            previous = rsm.get("DROPDOWN1")
            self.add(seq=12, pressed=True)
            rsm._log_device_changes(previous, rsm.get("DROPDOWN1"), 10000, {})
            log.assert_called_once_with("DROPDOWN1 button 1 pressed")


if __name__ == "__main__":
    unittest.main()
