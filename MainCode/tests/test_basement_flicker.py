"""Basement effect startup and cleanup without hardware."""
import ast
import inspect
from pathlib import Path
import random
import threading
from types import SimpleNamespace
import unittest


def load_room():
    path = Path(__file__).resolve().parents[1] / "rooms/Basement.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    scope = dict(house=SimpleNamespace(HouseActive=True, Demo=False),
                 threading=threading, random=random, BreakCheck=lambda: False,
                 log_event=lambda *args: None, randMixedNum=random.uniform)
    exec(compile(tree, str(path), "exec"), scope)
    return scope


class BasementFlickerTests(unittest.TestCase):
    def test_channels_stop_independently_and_can_restart(self):
        scope = load_room()
        changed = {7: threading.Event(), 3: threading.Event()}
        writes = {7: [], 3: []}
        def dim(value, *, channel):
            writes[channel].append(value)
            if value:
                changed[channel].set()
        scope.update(ambientLight=True, dim=SimpleNamespace(dim=dim))
        try:
            ambient = scope["startAmbientFlicker"](7)
            cracks = scope["startAmbientFlicker"](3)
            self.assertTrue(changed[7].wait(1))
            self.assertTrue(changed[3].wait(1))
            scope["stopAmbientFlicker"](7)
            self.assertFalse(ambient.is_alive())
            self.assertEqual(writes[7][-1], 0)
            self.assertTrue(cracks.is_alive())
            changed[3].clear()
            self.assertTrue(changed[3].wait(1))
            changed[7].clear()
            replacement = scope["startAmbientFlicker"](7)
            self.assertTrue(changed[7].wait(1))
            self.assertTrue(replacement.is_alive())
            # Starting the same channel again replaces, rather than duplicates it.
            newest = scope["startAmbientFlicker"](7)
            self.assertFalse(replacement.is_alive())
            self.assertTrue(newest.is_alive())
        finally:
            scope["stopAmbientFlicker"]()
        self.assertEqual(writes[3][-1], 0)
        self.assertEqual(writes[7][-1], 0)
        self.assertFalse(scope["_ambient_workers"])

    def test_both_ambient_channels_run_and_turn_off_on_stop(self):
        for channel in (7, 3):
            with self.subTest(channel=channel):
                scope = load_room()
                changed, stop = threading.Event(), threading.Event()
                writes, errors = [], []
                def dim(value, *, channel):
                    writes.append((value, channel))
                    if value:
                        changed.set()
                scope.update(ambientLight=True, dim=SimpleNamespace(dim=dim))
                def run():
                    try:
                        scope["ambientFlicker"](channel, stop)
                    except Exception as error:
                        errors.append(error)
                worker = threading.Thread(target=run, daemon=True)
                worker.start()
                try:
                    self.assertTrue(changed.wait(1))
                finally:
                    stop.set()
                    worker.join(1)
                self.assertFalse(worker.is_alive())
                self.assertFalse(errors)
                self.assertEqual(writes[-1], (0, channel))

    def test_sequence_starts_all_workers_with_valid_args_and_stops_them(self):
        scope = load_room()
        scope["house"].Demo = True
        workers = []
        class Worker:
            def __init__(self, target, args=(), **kwargs):
                inspect.signature(target).bind(*args)
                self.target, self.args, self.joined = target, args, False
                workers.append(self)
            def start(self): pass
            def join(self, **kwargs): self.joined = True
            def is_alive(self): return False
        scope.update(threading=SimpleNamespace(Thread=Worker, Event=threading.Event),
                     wait=lambda *args: None, play_audio=lambda *args, **kwargs: None,
                     setDoorState=lambda *args: None, m1Digital_Write=lambda *args: None,
                     toggleHouseLights=lambda *args: None)
        scope["run"]()
        self.assertEqual(len(workers), 3)
        self.assertEqual([w.args[0] for w in workers[1:]], [7, 3])
        self.assertTrue(all(w.joined for w in workers))
        self.assertTrue(workers[0].args[0].is_set())
        self.assertEqual(scope["house"].Basement_state, "INACTIVE")


if __name__ == "__main__":
    unittest.main()
