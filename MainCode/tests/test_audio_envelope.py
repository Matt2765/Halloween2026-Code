"""DAC-timed per-voice envelopes without opening an audio device."""
import ast
import __future__
from dataclasses import dataclass, field
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import cast
import unittest
import numpy as np


class AudioEnvelopeTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/"control/audio_manager.py"
        tree=ast.parse(path.read_text(encoding="utf-8-sig"))
        names={"PlaybackHandle","_Voice","DeviceMixer","_submit","play_audio"}
        tree.body=[n for n in tree.body if getattr(n,"name",None) in names]
        self.now=10.0
        self.scope=dict(threading=threading,time=SimpleNamespace(monotonic=lambda:self.now),np=np,
            dataclass=dataclass,field=field,cast=cast,_mixers={},_active_sessions=[],
            _active_lock=threading.Lock(),_epoch_lock=threading.Lock(),_cutoff_epoch=0,
            log_event=lambda *args:None,house=SimpleNamespace(DISABLE_AUDIO_MANAGER=False),
            _next_epoch=lambda:1,_resolve_named_target=lambda name:("primary","one",0,1),
            FALLBACK_DUPLICATE_WINDOW_SECONDS=0.5)
        exec(compile(tree,str(path),"exec",flags=__future__.annotations.compiler_flag),self.scope)
        self.mixer=self.scope['DeviceMixer']('primary',0,'test',1,1000,'test')
        self.scope['_mixers']['primary']=self.mixer
        self.scope['_Session']=self.scope['PlaybackHandle']
        self.scope['_mixer']=lambda kind:self.mixer

    def voice(self, samples, *, track=True, gain=1, finished=True):
        class Source:
            def read(self, frames):
                return np.array(samples,dtype=np.float32).reshape(-1,1),finished
            def close(self):pass
        handle=self.scope['PlaybackHandle'](1,'voice')
        handle.track_envelope=track
        voice=self.scope['_Voice'](Source(),'one',0,gain,handle,True,False)
        self.mixer.voices.append(voice)
        self.scope['_active_sessions'].append(handle)
        return handle

    def render(self, frames):
        output=np.zeros((frames,1),np.float32)
        self.mixer._callback(output,frames,SimpleNamespace(currentTime=100,outputBufferDacTime=100.06),None)
        return output

    def test_waits_for_dac_and_follows_leading_silence_speech_and_end(self):
        handle=self.voice([0]*20+[.2]*20)
        self.render(40)
        self.assertTrue(handle.done.is_set()) # Decoded, not yet audible.
        self.assertTrue(handle.audible_pending())
        self.assertEqual(handle.audio_level(),0)
        self.now=10.075
        self.assertEqual(handle.audio_level(),0)
        self.now=10.085
        self.assertAlmostEqual(handle.audio_level(),.2,places=6)
        self.now=10.101
        self.assertEqual(handle.audio_level(),0)
        self.assertFalse(handle.audible_pending())

    def test_internal_and_trailing_silence_close_the_envelope(self):
        handle=self.voice([.2]*10+[0]*20+[.1]*10+[0]*20)
        self.render(60)
        for when,expected in ((10.065,.2),(10.085,0),(10.095,.1),(10.105,0),(10.115,0)):
            self.now=when
            self.assertAlmostEqual(handle.audio_level(),expected,places=6)

    def test_background_voice_does_not_drive_silent_speech_handle(self):
        dialogue=self.voice([0]*20)
        background=self.voice([.8]*20,track=False)
        self.assertTrue(np.any(self.render(20)))
        self.now=10.065
        self.assertEqual(dialogue.audio_level(),0)
        self.assertEqual(background._audio_envelope,())

    def test_gain_and_cancellation_are_scoped_to_the_voice(self):
        handle=self.voice([.4]*20,gain=.5)
        self.render(20);self.now=10.065
        self.assertAlmostEqual(handle.audio_level(),.2,places=6)
        handle.stop()
        self.assertEqual(handle.audio_level(),0)
        self.assertFalse(handle.audible_pending())

    def test_submit_enables_tracking_before_first_callback(self):
        class Source:
            def read(self,frames):return np.ones((frames,1),np.float32),False
            def close(self):pass
        self.scope['_source']=lambda *args:Source()
        handle=self.scope['_submit'](Path('voice.wav'),'Pedro','one',0,1,False,True,False,True,
                                      track_envelope=True)
        self.assertTrue(handle.track_envelope)
        self.render(10);self.now=10.065
        self.assertEqual(handle.audio_level(),1)

    def test_six_channel_device_routes_surround_and_rejects_unavailable_back_output(self):
        class Source:
            def read(self,frames):return np.ones((frames,1),np.float32),False
            def close(self):pass
        self.scope['_source']=lambda *args:Source()
        self.mixer.channels=6
        self.scope['_resolve_named_target']=lambda name:('secondary','one',4 if name=='secondary_SL' else 6,1)
        self.scope['_submit'](Path('voice.wav'),'secondary_SL','one',0,1,False,True,False,True)
        output=np.zeros((10,6),np.float32)
        self.mixer._callback(output,10,None,None)
        np.testing.assert_array_equal(output[:,4],np.ones(10))
        np.testing.assert_array_equal(output[:,1],np.zeros(10))
        with self.assertRaisesRegex(ValueError,'6 output channels'):
            self.scope['_submit'](Path('voice.wav'),'secondary_BL','one',0,1,False,True,False,True)

    def test_play_audio_forwards_tracking_to_named_and_all_routes(self):
        for target,route in (('Pedro','play_to_named_channel'),('all','play_to_all_channels')):
            calls=[]
            self.scope[route]=lambda *args,**kwargs:calls.append(kwargs)
            self.scope['play_audio'](target,'voice.wav',track_envelope=True)
            self.assertTrue(calls[0]['track_envelope'])


if __name__=='__main__':unittest.main()
