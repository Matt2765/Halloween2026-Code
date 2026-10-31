"""Exercise both hallway paths against strictly ordered lantern telemetry."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class DynamicLanternSequenceTests(unittest.TestCase):
    def run_room(self, pressed=False, cancelled=False, delivery=True):
        path = Path(__file__).resolve().parents[1] / "rooms/DynamicHallway.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in ("run", "_restore_lanterns_after_timeout")]
        now, expected, due = [0.0], [8], [None]
        calls, accepted = [], []
        def sleep(seconds):
            now[0] += seconds
        def refresh():
            if due[0] is not None and now[0] >= due[0]:
                expected[0] += 1
                due[0] = None
        def lantern(cue, state):
            refresh()
            calls.append((cue, state))
            if cue != expected[0]:
                return {}
            if delivery:
                accepted.append(cue)
                due[0] = now[0] + .04
            return {"LANTERN1": "command-id"}
        def get_state(device_id):
            refresh()
            return dict(available=True, synced=True, next_command_id=expected[0])
        house = SimpleNamespace(HouseActive=False, Demo=True,
                                Bathroom_state="STANDBY")
        log = Mock()
        scope = dict(house=house, t=SimpleNamespace(monotonic=lambda: now[0], sleep=sleep),
                     wait=sleep, sequence_wait=sleep, SequenceStopped=RuntimeError,
                     BreakCheck=lambda: cancelled, log_event=log,
                     rsm=SimpleNamespace(lantern=lantern, get_lantern_state=get_state,
                         get_button_value=lambda key: pressed,
                         get_pir_state=lambda key: {"triggered": True}),
                     play_audio=Mock(), blastLightning=Mock(), stopBlastLightning=Mock(),
                     m1Digital_Write=Mock(), dim=Mock(), toggleHouseLights=Mock())
        exec(compile(tree, str(path), "exec"), scope)
        scope["run"]()
        return calls, accepted, log

    def test_timeout_consumes_eight_without_strobe_then_nine(self):
        calls, accepted, _ = self.run_room()
        self.assertEqual(calls, [(8, "flickering_on"), (9, "flickering_on")])
        self.assertEqual(accepted, [8, 9])

    def test_button_keeps_strobe_and_sends_nine_once(self):
        calls, accepted, _ = self.run_room(pressed=True)
        self.assertEqual(calls, [(8, "strobe"), (9, "flickering_on")])
        self.assertEqual(accepted, [8, 9])

    def test_shutdown_does_not_send_cues(self):
        self.assertEqual(self.run_room(cancelled=True)[0], [])

    def test_failed_eight_is_not_retried_or_accepted_as_nine(self):
        calls, accepted, log = self.run_room(delivery=False)
        self.assertEqual(accepted, [])
        self.assertEqual([cue for cue, _ in calls], [8, 9])
        self.assertTrue(any("cue 8 not confirmed" in call.args[0] for call in log.call_args_list))


if __name__ == "__main__":
    unittest.main()
