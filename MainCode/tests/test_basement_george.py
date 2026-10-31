"""George's awakening must release manual movement before speech starts."""
import ast
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class BasementGeorgeTests(unittest.TestCase):
    def load(self, *, cancelled=False, fail_wait=False):
        path = Path(__file__).resolve().parents[1] / "rooms/Basement.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == "awakenGeorge"]
        workers, events = [], {key:threading.Event() for key in ("neck", "eyes")}
        state = dict(cancelled=False)
        def worker_factory(**kwargs):
            worker = threading.Thread(**kwargs)
            workers.append(worker)
            return worker
        def neck(angle):
            self.assertTrue(type(angle) is int and 80 <= angle <= 180)
            events["neck"].set()
        george = SimpleNamespace(mouth=Mock(), neck=Mock(side_effect=neck),
                                  eyes=Mock(side_effect=lambda on: events["eyes"].set()))
        def wait(seconds):
            self.assertEqual(seconds, 15)
            if george.talk.called:
                # The second 15-second wait must follow speech completion.
                self.assertGreaterEqual(george.status.call_count, 2)
                self.assertTrue(all(not worker.is_alive() for worker in workers))
                george.stop.assert_not_called()
            self.assertTrue(all(event.wait(1) for event in events.values()))
            state["cancelled"] = cancelled
            if fail_wait:
                raise RuntimeError("Interrupted sequence")
        def talk(**kwargs):
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            return True
        george.talk = Mock(side_effect=talk, return_value=True)
        george.start_idle = Mock(return_value=True)
        george.stop = Mock()
        george.status = Mock(side_effect=[{"running":True}, {"running":False}])
        scope = dict(animatronic_service=SimpleNamespace(george=george),
                     threading=SimpleNamespace(Thread=worker_factory,Event=threading.Event),
                     BreakCheck=lambda: state["cancelled"], wait=Mock(side_effect=wait), log_event=Mock(),
                     t=SimpleNamespace(sleep=Mock()),
                     random=SimpleNamespace(randint=lambda low, high: high),
                     randMixedNum=lambda low, high: low)
        self.sequence_wait = scope["wait"]
        exec(compile(tree, str(path), "exec"), scope)
        return scope["awakenGeorge"], george, workers

    def test_manual_workers_finish_before_talk_takes_over(self):
        awaken, george, workers = self.load()
        awaken()
        self.assertEqual({worker.name for worker in workers}, {"George eyes", "George neck"})
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        george.mouth.assert_called_once_with(120)
        self.assertTrue(george.neck.called)
        self.assertTrue(george.eyes.called)
        george.start_idle.assert_called_once_with(neck_min=80, neck_max=180)
        george.talk.assert_called_once_with(channel="Basement")
        self.assertEqual(george.status.call_count, 2)
        self.assertEqual(self.sequence_wait.call_args_list, [unittest.mock.call(15), unittest.mock.call(15)])
        george.stop.assert_called_once_with()

    def test_cancelled_sequence_stops_workers_without_starting_speech(self):
        awaken, george, workers = self.load(cancelled=True)
        awaken()
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        george.talk.assert_not_called()

    def test_exception_still_stops_manual_workers(self):
        awaken, george, workers = self.load(fail_wait=True)
        with self.assertRaisesRegex(RuntimeError,"Interrupted sequence"):
            awaken()
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        george.talk.assert_not_called()

    def test_failed_talk_parks_without_waiting_for_speech(self):
        awaken, george, workers = self.load()
        george.talk.side_effect = None
        george.talk.return_value = False
        awaken()
        george.status.assert_not_called()
        george.stop.assert_called_once_with()

    def test_speech_wait_error_still_parks(self):
        awaken, george, workers = self.load()
        george.status.side_effect = RuntimeError("Playback status failed")
        with self.assertRaisesRegex(RuntimeError, "Playback status failed"):
            awaken()
        george.stop.assert_called_once_with()



if __name__ == "__main__":
    unittest.main()
