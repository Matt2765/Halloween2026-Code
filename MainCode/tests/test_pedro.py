import copy
from pathlib import Path
import queue
import random
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1]))
import pedro
from control import remote_sensor_monitor as rsm


def record():
    return {"v": 1, "type": "device", "id": "PEDRO1", "kind": "pedro", "session": 3,
            "seq": 10, "mac": "AA:BB:CC:DD:EE:FF", "queue_ms": 0,
            "vals": {"pedro_state": "standby", "controller_connected": True,
                     "wings_angle": 5, "wings_target": 115, "beak_angle": 55, "beak_target": 55,
                     "neck": False, "eyes": True, "moving": True, "ready": True}}


class PedroRsmTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(rsm, "_now_ms", return_value=10000)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        rsm._disabled = False
        rsm._shared = {"_connection": {"connected": True, "host": "a" * 32}}
        rsm._commands = {}
        rsm._txq = queue.Queue(32)
        rsm._store_device(rsm._shared, record(), 10000)

    def test_complete_pose_uses_existing_host_and_boot_session(self):
        cid = rsm.pedro(state="active", wings=115, beak=10, neck=True, eyes=False, ramp_ms=100)
        request = rsm._txq.get_nowait()
        self.assertEqual(request, {"v": 1, "type": "command", "host": "a" * 32, "command_id": cid,
                                  "id": "PEDRO1", "target_session": 3, "op": "pedro", "value": 2,
                                  "duration_ms": 100, "wings": 115, "beak": 10, "neck": True, "eyes": False})

    def test_invalid_pose_never_enters_queue(self):
        for values in ({"state": "talking"}, {"wings": True}, {"beak": 181}, {"neck": 1},
                       {"eyes": 0}, {"ramp_ms": -1}, {"ramp_ms": 30001}):
            with self.assertRaises(ValueError):
                rsm.pedro(**values)
        self.assertTrue(rsm._txq.empty())

    def test_wrong_kind_stale_conflicted_and_disconnected_reject(self):
        for change in ("kind", "stale", "conflict", "disconnected"):
            with self.subTest(change=change):
                rsm._shared["PEDRO1"] = dict(record(), t_host_ms=10000)
                rsm._shared["_connection"]["connected"] = True
                if change == "kind":
                    rsm._shared["PEDRO1"]["kind"] = "servo"
                elif change == "stale":
                    rsm._shared["PEDRO1"]["t_host_ms"] = 3000
                elif change == "conflict":
                    rsm._shared["PEDRO1"]["conflict"] = True
                else:
                    rsm._shared["_connection"]["connected"] = False
                cid = rsm.pedro()
                self.assertEqual(rsm.command_status(cid)["status"], "rejected")
                self.assertTrue(rsm._txq.empty())

    def test_telemetry_order_reboot_and_freshness(self):
        older = record()
        older["seq"] = 9
        older["vals"]["pedro_state"] = "active"
        self.assertFalse(rsm._store_device(rsm._shared, older, 10001))
        self.assertEqual(rsm.get_pedro_state()["pedro_state"], "standby")
        reboot = record()
        reboot.update(session=4, seq=1)
        reboot["vals"]["controller_connected"] = False
        self.assertTrue(rsm._store_device(rsm._shared, reboot, 10000))
        self.assertFalse(rsm.get_pedro_state()["controller_connected"])
        self.assertFalse(rsm._store_device(rsm._shared, record(), 10000))
        with patch.object(rsm, "_now_ms", return_value=16000):
            self.assertFalse(rsm.get_pedro_state()["available"])

    def test_invalid_telemetry_does_not_replace_last_good_state(self):
        for key, value in (("pedro_state", "unknown"), ("controller_connected", 1), ("moving", 1),
                           ("wings_target", 181), ("beak_angle", -1), ("neck", 0)):
            bad = record()
            bad["vals"][key] = value
            with self.assertRaises(ValueError):
                rsm._store_device(rsm._shared, bad, 10000)
        self.assertEqual(rsm.get_pedro_state()["wings_target"], 115)


class FakeTransport:
    def __init__(self):
        self.available, self.host, self.session, self.status = True, "a" * 32, 3, "accepted"
        self.poses = []

    def get(self, sid):
        return {"host": self.host} if sid == "_connection" else {"kind": "pedro", "session": self.session}

    def healthy(self):
        return {"connected": self.available}

    def device_status(self, sid):
        return {"available": self.available}

    def pedro(self, sid, **pose):
        self.poses.append(copy.copy(pose))
        return str(len(self.poses))

    def command_status(self, cid):
        return {"status": self.status, "reason": "fake_result"}


def eventually(predicate):
    deadline = time.monotonic() + 1.2
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class PedroControllerTests(unittest.TestCase):
    def controller(self, transport=None):
        transport = transport or FakeTransport()
        controller = pedro.PedroController(transport=transport)
        controller.start()
        self.addCleanup(controller.close)
        return controller, transport

    def test_digital_neck_and_beak_only_talk_during_active(self):
        motion = pedro.Motion(0, random.Random(1))
        self.assertEqual(motion.pose("standby", 0)["beak"], 55)
        self.assertEqual(motion.pose("active", 0)["beak"], 10)
        self.assertEqual(motion.pose("active", 0.2)["beak"], 55)
        pose = motion.pose("standby", 3)
        self.assertEqual(pose["beak"], 55)
        self.assertIs(type(pose["neck"]), bool)
        self.assertEqual(motion.pose("off", 4), dict(state="off", wings=5, beak=55, neck=False, eyes=False))

    def test_waits_for_ack_and_keeps_bounded_outstanding_work(self):
        transport = FakeTransport()
        transport.status = "pending"
        controller, _ = self.controller(transport)
        self.assertTrue(eventually(lambda: len(transport.poses) == 1))
        controller.set_state("active")
        time.sleep(0.1)
        self.assertFalse(controller.connected.is_set())
        self.assertEqual(len(transport.poses), 1)
        transport.status = "accepted"
        self.assertTrue(controller.connected.wait(1))
        self.assertTrue(eventually(lambda: transport.poses[-1]["state"] == "active"))

    def test_unchanged_pose_still_refreshes_controller_lease(self):
        controller, transport = self.controller()
        controller.set_state("off")
        self.assertTrue(controller.connected.wait(1))
        self.assertTrue(eventually(lambda: len([p for p in transport.poses if p["state"] == "off"]) >= 2))

    def test_disconnect_and_reboot_do_not_resume_talking(self):
        controller, transport = self.controller()
        self.assertTrue(controller.connected.wait(1))
        controller.set_state("active")
        self.assertTrue(eventually(lambda: transport.poses[-1]["state"] == "active"))
        epoch = controller.link_epoch
        transport.available = False
        time.sleep(0.1)
        self.assertEqual(controller.link_epoch, epoch)
        self.assertTrue(controller.connected.is_set())
        # A known reboot still invalidates the quip immediately, even in grace.
        transport.session += 1
        self.assertTrue(eventually(lambda: controller.link_epoch > epoch))
        self.assertFalse(controller.connected.is_set())
        transport.available = True
        self.assertTrue(controller.connected.wait(1))
        self.assertEqual(transport.poses[-1]["state"], "standby")
        self.assertEqual(transport.poses[-1]["beak"], 55)
        controller.set_state("active")
        self.assertTrue(eventually(lambda: transport.poses[-1]["state"] == "active"))
        transport.session += 1
        self.assertTrue(eventually(lambda: transport.poses[-1]["state"] == "standby"))

    def test_missed_ack_burst_does_not_interrupt_playing_quip(self):
        controller, transport = self.controller()
        self.assertTrue(controller.connected.wait(1))
        finished = threading.Event()
        process = Mock(done=finished, cancelled=False)
        outcome = []
        with patch.object(pedro, "start_player", return_value=process), patch.object(pedro, "stop_player"):
            player = threading.Thread(target=lambda: outcome.append(
                pedro.play_quip(controller, "CabinRoom_Wall", Path("Quip01.mp3"))))
            player.start()
            try:
                self.assertTrue(eventually(lambda: transport.poses[-1]["state"] == "active"))
                epoch = controller.link_epoch
                before = len(transport.poses)
                transport.status = "unconfirmed"
                self.assertTrue(eventually(lambda: len(transport.poses) >= before + 3))
                self.assertTrue(player.is_alive())
                self.assertTrue(controller.connected.is_set())
                self.assertEqual(controller.link_epoch, epoch)
                self.assertEqual(controller.state, "active")
                transport.status = "accepted"
                self.assertTrue(eventually(lambda: len(transport.poses) >= before + 4))
            finally:
                finished.set()
                player.join(timeout=1)
        self.assertEqual(outcome, [True])

    def test_sustained_ack_loss_expires_grace_and_clears_talking(self):
        with patch.object(pedro, "LINK_LOSS_GRACE_SECONDS", 0.3):
            controller, transport = self.controller()
            self.assertTrue(controller.connected.wait(1))
            controller.set_state("active")
            self.assertTrue(eventually(lambda: transport.poses[-1]["state"] == "active"))
            epoch = controller.link_epoch
            transport.status = "unconfirmed"
            self.assertTrue(eventually(lambda: controller.link_epoch > epoch))
            self.assertFalse(controller.connected.is_set())
            self.assertEqual(controller.state, "standby")

    def test_brief_availability_gap_preserves_quip_but_sustained_gap_drops_it(self):
        with patch.object(pedro, "LINK_LOSS_GRACE_SECONDS", 0.35):
            controller, transport = self.controller()
            self.assertTrue(controller.connected.wait(1))
            controller.set_state("active")
            epoch = controller.link_epoch
            transport.available = False
            time.sleep(0.1)
            self.assertTrue(controller.connected.is_set())
            self.assertEqual(controller.link_epoch, epoch)
            transport.available = True
            self.assertTrue(eventually(lambda: transport.poses[-1]["state"] == "active"))
            self.assertEqual(controller.link_epoch, epoch)
            transport.available = False
            self.assertTrue(eventually(lambda: controller.link_epoch > epoch))
            self.assertFalse(controller.connected.is_set())

    def test_invalid_command_is_not_hidden_by_loss_filter(self):
        controller, transport = self.controller()
        self.assertTrue(controller.connected.wait(1))
        controller.set_state("active")
        self.assertTrue(eventually(lambda: transport.poses[-1]["state"] == "active"))
        epoch = controller.link_epoch
        transport.command_status = lambda cid: {"status": "rejected", "reason": "invalid_pedro_pose"}
        self.assertTrue(eventually(lambda: controller.link_epoch > epoch))
        self.assertFalse(controller.connected.is_set())
        self.assertEqual(controller.state, "standby")

    def test_audio_launch_error_and_cancelled_playback_clear_active(self):
        controller = pedro.PedroController(simulate=True)
        controller.connected.set()
        with patch.object(pedro, "start_player", side_effect=OSError("missing player")):
            with self.assertRaises(OSError):
                pedro.play_quip(controller, "CabinRoom_Wall", Path("Quip01.mp3"))
        self.assertEqual(controller.state, "standby")
        process = Mock(done=threading.Event(), cancelled=True)
        process.done.set()
        with patch.object(pedro, "start_player", return_value=process):
            self.assertFalse(pedro.play_quip(controller, "CabinRoom_Wall", Path("Quip01.mp3")))
        self.assertEqual(controller.state, "standby")

    def test_brief_disconnect_stops_audio_even_if_already_reconnected(self):
        controller = pedro.PedroController(simulate=True)
        controller.connected.set()
        process = Mock(cancelled=False)

        def wait(timeout):
            controller.link_epoch += 1
            return False

        process.done.wait.side_effect = wait
        with patch.object(pedro, "start_player", return_value=process), patch.object(pedro, "stop_player") as stop:
            self.assertFalse(pedro.play_quip(controller, "CabinRoom_Wall", Path("Quip01.mp3")))
            stop.assert_called_with(process)
        self.assertEqual(controller.state, "standby")

    def test_no_repeat_and_single_file_does_not_hang(self):
        self.assertEqual(pedro.choose_quip(["a", "b"], "a"), "b")
        self.assertEqual(pedro.choose_quip(["a"], "a"), "a")


if __name__ == "__main__":
    unittest.main()
