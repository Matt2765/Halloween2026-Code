import importlib.util
from pathlib import Path
import queue
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "lantern_rsm_test_module", Path(__file__).parents[1] / "control" / "remote_sensor_monitor.py")
rsm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rsm)


def device(sid, *, cue=1, generation=4, synced=True, now=10000):
    return {"v": 1, "type": "device", "id": sid, "kind": "lantern", "session": 3,
            "seq": 10, "mac": "AA:BB:CC:DD:EE:FF", "queue_ms": 0,
            "vals": {"lantern_state": "flickering_on", "synced": synced, "brightness": 200,
                     "next_command_id": cue, "sync_generation": generation}, "t_host_ms": now}


class LanternRsmTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(rsm, "_now_ms", return_value=10000)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        rsm._disabled = False
        rsm._shared = {"_connection": {"connected": True, "host": "a" * 32}}
        rsm._commands = {}
        rsm._txq = queue.Queue(32)

    def add(self, sid, **kwargs):
        record = device(sid, **kwargs)
        rsm._store_device(rsm._shared, record, record["t_host_ms"])

    def test_group_selects_only_fresh_synced_matching_cue(self):
        self.add("LANTERN1")
        self.add("LANTERN2", cue=2)
        self.add("LANTERN3", synced=False)
        self.add("LANTERN4", now=3000)
        results = rsm.lantern(1, "solid_on")
        self.assertEqual(list(results), ["LANTERN1"])
        request = rsm._txq.get_nowait()
        self.assertEqual((request["op"], request["value"], request["duration_ms"]), ("lantern", 1, 1))
        self.assertEqual((request["target_session"], request["sync_generation"]), (3, 4))
        self.assertEqual(request["command_id"], results["LANTERN1"])

    def test_explicit_targets_and_deduplication(self):
        self.add("LANTERN1", cue=2, generation=8)
        self.add("LANTERN2", cue=2, generation=15)
        results = rsm.lantern(2, "intense_flicker_out", ["LANTERN1", "LANTERN2", "LANTERN1"])
        self.assertEqual(len(results), 2)
        self.assertEqual([rsm._txq.get_nowait()["sync_generation"] for _ in range(2)], [8, 15])

    def test_old_telemetry_cannot_undo_sync_generation(self):
        self.add("LANTERN1", generation=8)
        old = device("LANTERN1", generation=7)
        old["seq"] = 9
        self.assertFalse(rsm._store_device(rsm._shared, old, 10000))
        self.assertEqual(rsm.get_lantern_state("LANTERN1")["sync_generation"], 8)

    def test_invalid_input_does_not_enqueue_any_command(self):
        for cue, state, ids in [(True, "off", None), (0, "off", None),
                                (0xffffffff, "off", None), (1, "typo", None),
                                (1, "off", ["LANTERN1", "bad id"])]:
            with self.assertRaises(ValueError):
                rsm.lantern(cue, state, ids)
        self.assertTrue(rsm._txq.empty())

    def test_missing_explicit_target_reports_rejected_and_empty_group_is_empty(self):
        self.assertEqual(rsm.lantern(1, "off"), {})
        cid = rsm.lantern(1, "off", "LANTERN1")["LANTERN1"]
        self.assertEqual(rsm.command_status(cid)["status"], "rejected")
        self.assertTrue(rsm._txq.empty())

    def test_bad_telemetry_is_rejected(self):
        for key, value in [("synced", 1), ("brightness", 256), ("next_command_id", 0),
                           ("sync_generation", -1), ("lantern_state", "unknown")]:
            record = device("LANTERN1")
            record["vals"][key] = value
            with self.assertRaises(ValueError):
                rsm._store_device(rsm._shared, record, 10000)
        self.assertNotIn("LANTERN1", rsm._shared)


if __name__ == "__main__":
    unittest.main()
