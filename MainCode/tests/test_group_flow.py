"""Reservations, exit evidence, and real room-script handoff regressions."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tested_group_flow", ROOT / "control/group_flow.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Stopped(Exception):
    pass


def load_run(name, scope):
    path = ROOT / "rooms" / (name + ".py")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run"]
    exec(compile(tree, str(path), "exec"), scope)
    return scope["run"]


class GroupFlowTests(unittest.TestCase):
    def setUp(self):
        self.flow = module.GroupFlow()

    def test_reservation_prevents_lost_or_overwritten_arrivals(self):
        f = self.flow
        self.assertFalse(f.reserve_basement())
        f.basement_ready()
        self.assertTrue(f.reserve_basement())
        self.assertFalse(f.reserve_basement())
        self.assertTrue(f.arrive())
        self.assertFalse(f.reserve_basement())
        self.assertEqual(f.take_basement_arrival(), 1)
        self.assertEqual(f.take_hallway_arrival(), 1)
        self.assertIsNone(f.take_basement_arrival())
        f.basement_ready()
        self.assertTrue(f.reserve_basement())
        self.assertTrue(f.arrive())
        self.assertEqual(f.take_basement_arrival(), 2)

    def test_exit_requires_crossing_then_ten_clear_seconds_not_pir7(self):
        f = self.flow
        f.start_exit()
        self.assertFalse(f.update_exit(0, False, True))
        self.assertFalse(f.update_exit(30, False, False))
        self.assertFalse(f.update_exit(31, True, False))
        self.assertFalse(f.update_exit(32, False, False))
        self.assertFalse(f.update_exit(41.99, False, False))
        self.assertTrue(f.update_exit(42, False, False))
        self.assertTrue(f.status()["forest_seen"])

    def test_straggler_unknown_or_disconnection_restarts_clear_countdown(self):
        f = self.flow
        f.start_exit()
        f.update_exit(0, True, False)
        f.update_exit(1, False, False)
        self.assertFalse(f.update_exit(9, True, True))
        f.update_exit(10, False, False)
        self.assertFalse(f.update_exit(19, None, True))
        f.update_exit(20, False, False)
        self.assertFalse(f.update_exit(29.9, False, False))
        self.assertTrue(f.update_exit(30, False, False))

    def test_pir7_is_optional_and_shutdown_cannot_be_reactivated(self):
        f = self.flow
        f.update_exit(0, True, False)
        f.update_exit(1, False, False)
        self.assertTrue(f.update_exit(11, False, False))
        f.basement_ready()
        f.reserve_basement()
        f.stop()
        f.basement_ready()
        self.assertFalse(f.arrive())
        self.assertFalse(f.basement_available())
        self.assertIsNone(f.take_basement_arrival())

    def test_only_basement_room_writes_its_active_state(self):
        for name in ("Bathroom", "CabinRoom", "DynamicHallway"):
            tree = ast.parse((ROOT / "rooms" / (name + ".py")).read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    self.assertFalse(any(isinstance(n, ast.Attribute) and n.attr == "Basement_state"
                                         for target in node.targets for n in ast.walk(target)))

    def test_hallway_cannot_start_behind_closed_door_four(self):
        house = SimpleNamespace(HouseActive=True, Demo=False, DoorState={4:"CLOSED"})
        now, starts = [0.0], []
        def wait(seconds):
            now[0] += seconds
            if now[0] >= .2:
                house.DoorState[4] = "OPEN"
        def take():
            self.assertEqual(house.DoorState[4], "OPEN")
            return 1
        def audio(*args, **kwargs):
            self.assertEqual(house.DoorState[4], "OPEN")
            self.assertGreaterEqual(now[0], .2)
            starts.append(args)
            raise Stopped()
        scope = dict(house=house, sequence_wait=wait, SequenceStopped=Stopped,
                     BreakCheck=lambda:False, flow=SimpleNamespace(take_hallway_arrival=take),
                     log_event=Mock(), play_audio=audio, stopBlastLightning=Mock())
        load_run("DynamicHallway", scope)()
        self.assertEqual(len(starts), 1)

    def test_cabin_preserves_grandmas_door_four_actor_window(self):
        house = SimpleNamespace(HouseActive=True, Demo=False, Bathroom_state="STANDBY",
                                DoorState={3:"CLOSED",4:"CLOSED"})
        now, actor_window = [0.0], []
        worker = Mock()
        pedro = SimpleNamespace(start_idle=Mock(),talk=Mock(),
                                status=lambda:{"running":False},stop_talking=lambda:True)
        def door(door_id, state):
            if door_id == 4:
                self.assertEqual(house.Bathroom_state, "STANDBY")
                actor_window.append((state, now[0]))
                if state == "CLOSED":
                    raise Stopped()
        scope = dict(house=house, sequence_wait=lambda seconds:now.__setitem__(0,now[0]+seconds),
                     SequenceStopped=Stopped, t=SimpleNamespace(monotonic=lambda:now[0]),
                     BreakCheck=lambda:False, animatronic_service=SimpleNamespace(pedro=pedro),
                     rsm=SimpleNamespace(led=Mock(),lantern=Mock(),get_button_value=lambda key:True),
                     threading=SimpleNamespace(Event=Mock,Thread=Mock(return_value=worker)),
                     dim=Mock(), dimmer_flicker=Mock(return_value=worker),stop_flicker=Mock(),
                     setDoorState=door,m1Digital_Write=Mock(),log_event=Mock(),play_audio=Mock(return_value=None),
                     dimFlickerOut=Mock(return_value=worker),wallLanternFlicker=Mock(),bulb_lightning=Mock())
        load_run("CabinRoom", scope)()
        self.assertEqual([state for state,_ in actor_window], ["OPEN","CLOSED"])
        self.assertAlmostEqual(actor_window[1][1]-actor_window[0][1],11.5)

    def test_cabin_readiness_reacts_without_twenty_second_wait_and_cancels_voice_first(self):
        house = SimpleNamespace(HouseActive=True, Demo=False, Bathroom_state="ACTIVE",
                                DoorState={3:"CLOSED",4:"CLOSED"})
        now, events = [0.0], []
        pedro = SimpleNamespace(start_idle=Mock(), talk=Mock(), status=lambda:{"running":True},
                                stop_talking=lambda:events.append("cancel speech") or True)
        def wait(seconds):
            now[0] += seconds
            if now[0] >= 20.2:
                house.Bathroom_state = "STANDBY"
        def audio(channel, filename, **kwargs):
            if "cabinRoomIntro" in filename:
                events.append("scare audio")
                self.assertLess(now[0], 20.4)
                raise Stopped()
            return None
        scope = dict(house=house, sequence_wait=wait, SequenceStopped=Stopped,
                     t=SimpleNamespace(monotonic=lambda:now[0]), BreakCheck=lambda:False,
                     animatronic_service=SimpleNamespace(pedro=pedro),
                     rsm=SimpleNamespace(led=Mock(),get_button_value=lambda key:True),
                     threading=SimpleNamespace(Event=Mock),
                     dim=Mock(), dimmer_flicker=Mock(return_value=SimpleNamespace(join=Mock())),
                     stop_flicker=Mock(), setDoorState=Mock(), m1Digital_Write=Mock(),
                     log_event=Mock(),play_audio=audio)
        load_run("CabinRoom", scope)()
        self.assertEqual(events, ["cancel speech", "scare audio"])
        self.assertFalse(house.CabinReady)


if __name__ == "__main__":
    unittest.main()
