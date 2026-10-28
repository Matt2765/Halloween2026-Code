"""LED commands must reach button/dropdown nodes without opening serial ports."""
import ast
from pathlib import Path
import queue
import threading
import unittest
import uuid


class ButtonLedTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "control/remote_sensor_monitor.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        tree.body = [n for n in tree.body if getattr(n, "name", None) in {"tx_to_id", "led"}]
        self.device = {"kind": "button", "session": 123}
        self.scope = dict(
            uuid=uuid, queue=queue, _valid_id=lambda sid: sid == "BTN4",
            _now_ms=lambda: 100, _disabled=False, _commands={},
            _txq=queue.Queue(), _tx_lock=threading.Lock(), MAX_COMMANDS=128,
            get=lambda sid: {"connected": True, "host": "test"} if sid == "_connection" else self.device,
            device_status=lambda sid: {"available": True, "state": "valid", "age_ms": 0},
        )
        exec(compile(tree, str(path), "exec"), self.scope)

    def test_button_and_dropdown_on_off_use_existing_led_operation(self):
        for kind in ("button", "dropdown"):
            self.device["kind"] = kind
            for on in (True, False):
                cid = self.scope["led"]("BTN4", on)
                request = self.scope["_txq"].get_nowait()
                self.assertEqual(request["op"], "led")
                self.assertEqual(request["value"], int(on))
                self.assertEqual(request["target_session"], 123)
                self.assertEqual(request["duration_ms"], 0)
                self.assertEqual(self.scope["_commands"][cid]["status"], "queued")

    def test_other_device_kinds_are_rejected_without_queueing(self):
        self.device["kind"] = "pir"
        cid = self.scope["led"]("BTN4", True)
        self.assertEqual(self.scope["_commands"][cid]["status"], "rejected")
        self.assertTrue(self.scope["_txq"].empty())

    def test_only_boolean_led_values_are_allowed(self):
        for value in (1, 0, "on", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.scope["led"]("BTN4", value)
        self.assertTrue(self.scope["_txq"].empty())


if __name__ == "__main__":
    unittest.main()
