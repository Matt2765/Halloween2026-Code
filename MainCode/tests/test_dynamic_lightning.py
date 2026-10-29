"""Cancellation checks for the real lightning worker with fake GPIO/audio."""
import ast
from pathlib import Path
import random
import threading
import time
from types import SimpleNamespace
import unittest


class DynamicLightningTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "rooms/DynamicHallway.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
        self.writes, self.handles = [], []
        self.on, self.first_off = threading.Event(), threading.Event()
        self.cancelled = False
        def write(pin, value):
            self.writes.append((pin, value))
            if value == 0:
                self.on.set()
            elif self.on.is_set():
                self.first_off.set()
        class Handle:
            def __init__(self):
                self.done, self.cancelled = threading.Event(), False
            def stop(self):
                self.cancelled = True
                self.done.set()
        def play(*args, **kwargs):
            handle = Handle()
            self.handles.append(handle)
            return handle
        self.scope = dict(threading=threading,t=time,random=random,
            house=SimpleNamespace(),BreakCheck=lambda: self.cancelled,
            log_event=lambda *args: None,m1Digital_Write=write,play_audio=play)
        exec(compile(tree, str(path), "exec"), self.scope)
        self.addCleanup(self.scope['stopBlastLightning'])

    def stop_and_check(self, worker):
        began = time.monotonic()
        self.scope['stopBlastLightning']()
        self.assertLess(time.monotonic()-began, 0.3)
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.writes[-1], (4,1))
        self.assertTrue(self.handles)
        self.assertTrue(all(handle.cancelled for handle in self.handles))

    def test_stop_during_on_pulse_cancels_light_and_own_audio(self):
        worker=self.scope['blastLightning'](threaded=True)
        self.assertTrue(self.on.wait(1))
        self.stop_and_check(worker)

    def test_stop_during_long_dark_pause_does_not_wait_for_next_flash(self):
        worker=self.scope['blastLightning'](threaded=True)
        self.assertTrue(self.first_off.wait(1))
        self.stop_and_check(worker)
        self.assertEqual(sum(value==0 for _,value in self.writes),1)

    def test_stop_during_gap_prevents_the_next_bolt(self):
        gap=threading.Event()
        original=self.scope['_lightning_wait']
        def wait(stop, seconds):
            if seconds>2:
                gap.set()
                return original(stop,30)
            return original(stop,0)
        self.scope['_lightning_wait']=wait
        worker=self.scope['blastLightning'](threaded=True)
        self.assertTrue(gap.wait(1))
        self.stop_and_check(worker)
        self.assertEqual(len(self.handles),1)

    def test_restart_replaces_old_worker_and_audio(self):
        first=self.scope['blastLightning'](threaded=True)
        self.assertTrue(self.on.wait(1))
        second=self.scope['blastLightning'](threaded=True)
        first.join(1)
        self.assertFalse(first.is_alive())
        self.assertTrue(self.handles[0].cancelled)
        self.stop_and_check(second)

    def test_house_cancellation_interrupts_flash_waits(self):
        worker=self.scope['blastLightning'](threaded=True)
        self.assertTrue(self.on.wait(1))
        self.cancelled=True
        worker.join(0.3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.writes[-1],(4,1))
        self.assertTrue(self.handles[0].cancelled)

    def test_single_bolt_can_be_stopped_through_the_same_api(self):
        worker=self.scope['lightning_bolt'](threaded=True)
        self.assertTrue(self.on.wait(1))
        self.stop_and_check(worker)

    def test_completed_sequence_keeps_original_seven_bolts_and_flash_pattern(self):
        self.scope['_lightning_wait']=lambda stop, seconds: not stop.is_set()
        self.scope['blastLightning']()
        self.assertEqual(len(self.handles),7)
        self.assertEqual([value for _,value in self.writes], [0,1,0,1,0,1]*7+[1])
        self.assertFalse(any(handle.cancelled for handle in self.handles))
        self.scope['stopBlastLightning']()
        self.assertTrue(all(handle.cancelled for handle in self.handles))


if __name__ == '__main__':
    unittest.main()
