"""Per-device stream options without opening PortAudio endpoints."""
import ast
import __future__
from pathlib import Path
import threading
import unittest
from types import SimpleNamespace
from typing import Any, Mapping, cast
from unittest.mock import Mock


class AudioStreamSettingsTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/"control/audio_manager.py"
        tree=ast.parse(path.read_text(encoding="utf-8-sig"))
        tree.body=[node for node in tree.body if getattr(node,"name",None)=="DeviceMixer"]
        self.opened=[]
        class Stream:
            active=False
            def start(self):self.active=True
            def close(self):self.active=False
        def open_stream(**kwargs):
            self.opened.append(kwargs)
            return Stream()
        self.scope=dict(threading=threading,sd=SimpleNamespace(OutputStream=open_stream,
            WasapiSettings=lambda **kwargs:kwargs),log_event=lambda *args:None,
            SECONDARY_WASAPI_EXCLUSIVE=False,SECONDARY_BLOCKSIZE=0,SECONDARY_LATENCY=.12,
            MIX_BLOCKSIZE=1024,MULTICH_MIN_CHANNELS=6,RESAMPLE_HEADROOM_DB=3)
        exec(compile(tree,str(path),'exec',flags=__future__.annotations.compiler_flag),self.scope)

    def mixer(self,kind,host='Windows WASAPI'):
        return self.scope['DeviceMixer'](kind,15,'test',8,48000,host)

    def test_secondary_uses_shared_mode_and_driver_selected_buffers(self):
        mixer=self.mixer('secondary');mixer.start()
        options=self.opened[0]
        self.assertEqual(options['extra_settings'],{'exclusive':False})
        self.assertEqual(options['blocksize'],0)
        self.assertEqual(options['latency'],.12)
        self.assertEqual(options['channels'],8)
        self.assertFalse(mixer.wasapi_exclusive)
        self.assertTrue(mixer.diagnostics()['stream_active'])

    def test_primary_retains_its_existing_exclusive_stream_options(self):
        mixer=self.mixer('primary');mixer.start()
        self.assertEqual(self.opened[0]['extra_settings'],{'exclusive':True})
        self.assertEqual(self.opened[0]['blocksize'],1024)
        self.assertEqual(self.opened[0]['latency'],.06)
        self.assertTrue(mixer.wasapi_exclusive)

    def test_non_wasapi_devices_use_the_existing_buffer_options(self):
        self.mixer('secondary','MME').start()
        self.assertIsNone(self.opened[0]['extra_settings'])
        self.assertEqual(self.opened[0]['blocksize'],1024)


class PartialChannelMapTests(unittest.TestCase):
    def test_six_channel_endpoint_keeps_valid_routes_without_stereo_fallback(self):
        path=Path(__file__).resolve().parents[1]/"control/audio_manager.py"
        tree=ast.parse(path.read_text(encoding="utf-8-sig"))
        tree.body=[node for node in tree.body if getattr(node,"name",None) in {"_fixed","_make_mixer"}]
        class Mixer:
            def __init__(self,kind,index,name,channels,rate,host,fallback=False):
                self.device_index,self.channels,self.fallback_to_all=index,channels,fallback
            def start(self):pass
        fallback=Mock(side_effect=AssertionError("Valid surround output must not enter fallback"))
        scope=dict(SECONDARY_DEVICE_INDEX=15,SECONDARY_DEVICE_NAME='CUBILUX',
            PRIMARY_DEVICE_INDEX=16,PRIMARY_DEVICE_NAME='DENON',
            sd=SimpleNamespace(query_devices=lambda index:dict(name='Speakers (CUBILUX CA7)',
                max_output_channels=6,default_samplerate=48000)),
            primary_channels={},secondary_channels={name:dict(index=index) for name,index in
                [('secondary_FR',1),('secondary_SL',4),('secondary_SR',5),('secondary_BL',6),('secondary_BR',7)]},
            _host=lambda index:'Windows WASAPI',log_event=Mock(),cast=cast,Mapping=Mapping,Any=Any,
            DeviceMixer=Mixer,FALLBACK_TO_SYSTEM_DEFAULT=True,_mixers={},
            _fallback_output_candidates=fallback)
        exec(compile(tree,str(path),'exec',flags=__future__.annotations.compiler_flag),scope)
        mixer=scope['_make_mixer']('secondary')
        self.assertEqual(mixer.device_index,15)
        self.assertEqual(mixer.channels,6)
        self.assertFalse(mixer.fallback_to_all)
        fallback.assert_not_called()
        warning=scope['log_event'].call_args[0][0]
        self.assertIn('secondary_BL, secondary_BR',warning)
        self.assertNotIn('secondary_SL',warning)


if __name__=='__main__':unittest.main()
