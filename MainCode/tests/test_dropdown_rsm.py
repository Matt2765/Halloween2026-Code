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

    def test_rejection_captures_exact_cause_without_sending(self):
        for cause in ("bridge_disconnected", "device_not_seen", "device_id_conflict", "device_telemetry_expired"):
            with self.subTest(cause=cause):
                rsm._shared = {"_connection": {"connected": True, "host": "a" * 32}}
                self.add()
                if cause == "bridge_disconnected":
                    rsm._shared["_connection"]["connected"] = False
                elif cause == "device_not_seen":
                    del rsm._shared["DROPDOWN1"]
                elif cause == "device_id_conflict":
                    rsm._shared["DROPDOWN1"]["conflict"] = True
                else:
                    rsm._shared["DROPDOWN1"]["t_host_ms"] = 4000
                cid = rsm.servo("DROPDOWN1", 120)
                result = rsm.command_status(cid)
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["detail"], cause)
                self.assertEqual((result["op"], result["value"]), ("move", 120))
                self.assertEqual(result["device_age_ms"], None if cause == "device_not_seen" else
                                 6000 if cause == "device_telemetry_expired" else 0)
                self.assertTrue(rsm._txq.empty())

    def test_led_success_does_not_hide_failed_move_but_later_move_does(self):
        failed = rsm.servo("DROPDOWN1", 120)
        self.add()
        with patch.object(rsm, "_now_ms", return_value=10100):
            led = rsm.led("DROPDOWN1", True)
            rsm._ingest(rsm._shared, rsm._commands,
                        dict(v=1, type="command_result", command_id=led, status="accepted"), 10100)
            self.assertEqual(rsm.command_failure()["command_id"], failed)
            self.assertEqual(rsm.command_failure()["age_ms"], 100)
            move = rsm.servo("DROPDOWN1", 120)
            self.assertEqual(rsm.command_failure()["command_id"], failed)  # Queued isn't success.
            rsm._ingest(rsm._shared, rsm._commands,
                        dict(v=1, type="command_result", command_id=move, status="accepted"), 10100)
            self.assertIsNone(rsm.command_failure())
            self.assertEqual(rsm.command_status(failed)["status"], "rejected")  # History retained.

    def test_newer_rejection_remains_visible_after_earlier_success(self):
        self.add()
        accepted = rsm.servo("DROPDOWN1", 120)
        rsm._commands[accepted]["status"] = "accepted"
        with patch.object(rsm, "_now_ms", return_value=16000):
            rejected = rsm.servo("DROPDOWN1", 90)
            self.assertEqual(rsm.command_failure()["command_id"], rejected)

    def test_worker_logs_failed_and_accepted_commands_once_with_context(self):
        failed = rsm.servo("DROPDOWN1", 120)
        logged = {}
        with patch.object(rsm, "_log_event") as log:
            rsm._log_dropdown_commands(rsm._commands, logged, debug_info=True)
            rsm._log_dropdown_commands(rsm._commands, logged, debug_info=True)
            self.assertEqual(log.call_count, 1)
            self.assertIn("device_not_seen", log.call_args.args[0])
            self.assertIn("bridge_connected=True", log.call_args.args[0])
            self.add()
            move = rsm.servo("DROPDOWN1", 120)
            rsm._log_dropdown_commands(rsm._commands, logged, debug_info=True)
            self.assertEqual(log.call_count, 1)
            rsm._ingest(rsm._shared, rsm._commands,
                        dict(v=1, type="command_result", command_id=move, status="accepted"), 10001)
            rsm._log_dropdown_commands(rsm._commands, logged, debug_info=True)
            rsm._log_dropdown_commands(rsm._commands, logged, debug_info=True)
            self.assertEqual(log.call_count, 2)
            self.assertIn("move=120 accepted", log.call_args.args[0])
            self.assertIn("age_ms=0; session=3", log.call_args.args[0])
            del rsm._commands[failed]
            rsm._log_dropdown_commands(rsm._commands, logged, debug_info=True)
            self.assertNotIn(failed, logged)

    def test_telemetry_recovery_and_restart_logged_without_heartbeat_spam(self):
        self.add()
        previous = rsm.get("DROPDOWN1")
        rsm._store_device(rsm._shared, device(seq=11), 17000)
        with patch.object(rsm, "_log_event") as log:
            rsm._log_device_changes(previous, rsm.get("DROPDOWN1"), 17000, {}, debug_info=True)
            self.assertIn("telemetry resumed after 7000 ms", log.call_args.args[0])
            previous = rsm.get("DROPDOWN1")
            rsm._store_device(rsm._shared, device(seq=12), 19000)
            rsm._log_device_changes(previous, rsm.get("DROPDOWN1"), 19000, {}, debug_info=True)
            self.assertEqual(log.call_count, 1)
            previous = rsm.get("DROPDOWN1")
            rsm._store_device(rsm._shared, device(seq=1, session=4), 20000)
            rsm._log_device_changes(previous, rsm.get("DROPDOWN1"), 20000, {}, debug_info=True)
            self.assertEqual(log.call_count, 2)
            self.assertIn("restarted: session 3 -> 4", log.call_args.args[0])

    def test_radio_diagnostics_survive_heartbeat_but_not_node_reboot(self):
        self.add()
        rsm._ingest(rsm._shared, rsm._commands,
                    dict(v=1, type="diagnostic", id="DROPDOWN1", vals={"send_errors": 7}), 10000)
        self.add(seq=11)
        self.assertEqual(rsm.get("DROPDOWN1")["diagnostics"], {"send_errors": 7})
        self.add(seq=1, session=4)
        self.assertNotIn("diagnostics", rsm.get("DROPDOWN1"))

    def test_debug_off_suppresses_details_but_keeps_button_events(self):
        rsm.servo("DROPDOWN1", 120)
        self.add()
        previous = rsm.get("DROPDOWN1")
        rsm._store_device(rsm._shared, device(seq=11, pressed=True), 17000)
        with patch.object(rsm, "_log_event") as log:
            rsm._log_dropdown_commands(rsm._commands, {}, debug_info=False)
            rsm._log_device_changes(previous, rsm.get("DROPDOWN1"), 17000, {}, debug_info=False)
            log.assert_called_once_with("DROPDOWN1 button 1 pressed")
            log.reset_mock()
            previous = rsm.get("DROPDOWN1")
            rsm._store_device(rsm._shared, device(seq=1, session=4), 18000)
            rsm._log_device_changes(previous, rsm.get("DROPDOWN1"), 18000, {}, debug_info=False)
            log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
