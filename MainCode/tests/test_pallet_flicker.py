"""Pallet jumpscare flicker timing, target channel and cleanup without hardware."""
import ast
from pathlib import Path
import random
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class PalletFlickerTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/"rooms/PalletHallway.py"
        tree=ast.parse(path.read_text(encoding="utf-8-sig"))
        tree.body=[node for node in tree.body if not isinstance(node,(ast.Import,ast.ImportFrom))]
        self.now=0.0
        self.writes=[]
        def sleep(seconds):self.now+=seconds
        self.scope=dict(t=SimpleNamespace(monotonic=lambda:self.now,sleep=sleep),random=random.Random(1),
            dim=SimpleNamespace(stop_flicker=Mock(),dim=lambda level,**kwargs:self.writes.append((self.now,level,kwargs['channel']))),
            BreakCheck=lambda:False,log_event=Mock(),play_audio=Mock(),toggleHouseLights=Mock(),
            house=SimpleNamespace(HouseActive=True,Demo=True),rsm=SimpleNamespace(get_button_value=lambda sid:True))
        exec(compile(tree,str(path),'exec'),self.scope)

    def test_sharp_two_second_flicker_only_uses_requested_channel_and_ends_off(self):
        self.scope['jumpscareFlicker']()
        self.assertAlmostEqual(self.now,2.0)
        self.assertEqual({channel for _,_,channel in self.writes},{4})
        levels=[level for _,level,_ in self.writes]
        self.assertGreater(len(levels),10)
        self.assertTrue(all(80<=level<=100 for level in levels[:-1:2]))
        self.assertTrue(all(level in (0,5,10) for level in levels[1:-1:2]))
        self.assertEqual(levels[-1],0)
        self.scope['dim'].stop_flicker.assert_called_once_with(join=True,channel=4)

    def test_cancellation_turns_output_off_without_finishing_the_duration(self):
        self.scope['BreakCheck']=lambda:self.now>=.2
        self.scope['jumpscareFlicker']()
        self.assertLess(self.now,.23)
        self.assertEqual(self.writes[-1][1:],(0,4))

    def test_button_sequence_starts_audio_and_flicker_on_dim4(self):
        self.scope['run']()
        self.scope['play_audio'].assert_called_once_with('PalletHallway','PZ-jumpscare4.wav',gain=1)
        self.assertAlmostEqual(self.now,2.0)
        self.assertTrue(self.writes)
        self.assertEqual(self.scope['house'].PalletHallway_state,'INACTIVE')

    def test_cancelled_button_wait_does_not_fire_the_jumpscare(self):
        calls=[False,True,True]
        self.scope['BreakCheck']=lambda:calls.pop(0) if calls else True
        self.scope['rsm'].get_button_value=lambda sid:False
        self.scope['run']()
        self.scope['play_audio'].assert_not_called()
        self.assertFalse(self.writes)


if __name__=='__main__':unittest.main()
