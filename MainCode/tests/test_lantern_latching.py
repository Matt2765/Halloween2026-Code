"""Lantern groups follow intended room cues despite stale/lost telemetry."""
import ast
from pathlib import Path
import re
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class LanternLatchingTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "control/remote_sensor_monitor.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        tree.body = [n for n in tree.body if getattr(n, "name", None) in ("lantern", "_valid_id")]
        self.records, self.sent, self.unavailable = {}, [], set()
        self.house = SimpleNamespace(Demo=False)
        self.context = patch.dict(sys.modules, {"context": SimpleNamespace(house=self.house)})
        self.context.start()
        self.addCleanup(self.context.stop)
        def send(sid, payload):
            self.sent.append((sid, payload))
            return str(len(self.sent))
        self.scope = dict(re=re, _lantern_lock=threading.RLock(), _lantern_latches={},
                          LANTERN_STATES=("off", "flickering_on", "strobe"),
                          snapshot=lambda: dict(self.records), get=self.records.get,
                          device_status=lambda sid: {"available": sid not in self.unavailable},
                          tx_to_id=send)
        exec(compile(tree, str(path), "exec"), self.scope)
        self.lantern = self.scope["lantern"]
        self.add("LANTERN1")

    def add(self, sid, *, next_cue=1, generation=1, session=10, synced=True):
        self.records[sid] = dict(kind="lantern", session=session,
            vals=dict(next_command_id=next_cue, sync_generation=generation, synced=synced))

    def test_two_lanterns_follow_group_even_when_one_never_acks_cue_one(self):
        self.add("LANTERN2")
        self.assertEqual(set(self.lantern(1, "flickering_on")), {"LANTERN1", "LANTERN2"})
        self.records["LANTERN2"]["vals"]["next_command_id"] = 2
        self.assertEqual(set(self.lantern(2, "strobe")), {"LANTERN1", "LANTERN2"})
        self.assertEqual([p["cue_id"] for _, p in self.sent], [1, 1, 2, 2])

    def test_stale_telemetry_does_not_strand_later_cues(self):
        for cue in range(1, 14):
            self.assertIn("LANTERN1", self.lantern(cue, "flickering_on"))
        self.assertEqual(self.records["LANTERN1"]["vals"]["next_command_id"], 1)
        self.assertEqual(len(self.sent), 13)

    def test_other_groups_and_repeated_room_cues_do_not_take_over(self):
        self.lantern(1, "flickering_on")
        self.lantern(2, "strobe")
        self.add("LANTERN2")
        self.assertEqual(set(self.lantern(1, "flickering_on")), {"LANTERN2"})
        self.assertEqual(set(self.lantern(3, "off")), {"LANTERN1"})
        self.assertEqual(set(self.lantern(2, "strobe")), {"LANTERN2"})
        self.assertEqual(self.lantern(2, "strobe"), {})

    def test_resync_detaches_old_group_and_can_join_again(self):
        self.lantern(1, "flickering_on")
        self.records["LANTERN1"]["vals"]["sync_generation"] = 2
        self.assertEqual(self.lantern(2, "strobe"), {})
        self.assertIn("LANTERN1", self.lantern(1, "flickering_on"))
        self.assertEqual(self.sent[-1][1]["sync_generation"], 2)

    def test_reboot_or_unsync_detaches(self):
        self.lantern(1, "flickering_on")
        self.add("LANTERN1", session=11, generation=0, synced=False)
        self.assertEqual(self.lantern(2, "strobe"), {})
        self.assertEqual(self.lantern(1, "flickering_on"), {})

    def test_late_joiner_and_unavailable_unsynced_or_conflicting_nodes_do_not_enroll(self):
        self.add("LANTERN2", synced=False)
        self.add("LANTERN3")
        self.unavailable.add("LANTERN3")
        self.add("LANTERN4")
        self.records["LANTERN4"]["conflict"] = True
        self.assertEqual(set(self.lantern(1, "flickering_on")), {"LANTERN1"})
        self.add("LANTERN5")
        self.assertEqual(set(self.lantern(2, "strobe")), {"LANTERN1"})

    def test_temporary_unavailability_keeps_group_but_never_replays_old_effects(self):
        self.lantern(1, "flickering_on")
        self.unavailable.add("LANTERN1")
        self.lantern(2, "strobe")
        self.unavailable.clear()
        self.assertIn("LANTERN1", self.lantern(3, "off"))
        self.assertEqual([p["cue_id"] for _, p in self.sent], [1, 2, 3])

    def test_demo_and_explicit_targets_do_not_require_enrollment(self):
        self.records["LANTERN1"]["vals"]["next_command_id"] = 8
        self.assertIn("LANTERN1", self.lantern(8, "strobe", "LANTERN1"))
        self.house.Demo = True
        self.assertIn("LANTERN1", self.lantern(1, "flickering_on"))
        self.assertEqual(self.sent[-1][1]["cue_id"], 8)
        self.assertEqual(self.scope["_lantern_latches"], {})


if __name__ == "__main__":
    unittest.main()
