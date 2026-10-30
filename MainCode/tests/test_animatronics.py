"""Exercise the real pose worker/service with fake radio and audio endpoints."""
import ast
import importlib
from pathlib import Path
import queue
import random
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]


class Transport:
    def __init__(self, kind="george"):
        self.kind, self.session, self.available = kind, 1, True
        self.calls = []
        self.results = {}
        self.lock = threading.Lock()

    def get(self, key):
        if key == "_connection":
            return dict(host="host", connected=True)
        return dict(kind=self.kind, session=self.session)

    def healthy(self):
        return dict(connected=self.available)

    def device_status(self, key):
        return dict(available=self.available)

    def _send(self, device, **pose):
        with self.lock:
            cid = str(len(self.calls))
            self.calls.append(dict(pose))
            self.results[cid] = dict(status="accepted")
            return cid

    george = pedro = _send

    def command_status(self, cid):
        return self.results.get(cid)


class Handle:
    def __init__(self):
        self.done = threading.Event()
        self.cancelled = False

    def stop(self):
        self.cancelled = True
        self.done.set()


class AnimatronicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before_modules = set(sys.modules)
        cls.house = SimpleNamespace(systemState="ONLINE")
        cls.modules = patch.dict(sys.modules, {
            "context": SimpleNamespace(house=cls.house),
            "utils.tools": SimpleNamespace(log_event=lambda *args: None),
            "control.audio_manager": SimpleNamespace(_resolve_named_target=lambda channel: None),
        })
        cls.modules.start()
        sys.path.insert(0, str(ROOT))
        cls.service = importlib.import_module("control.animatronic_service")
        cls.core = importlib.import_module("Animatronics.core")
        cls.george = importlib.import_module("Animatronics.george")
        cls.pedro = importlib.import_module("Animatronics.pedro")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(ROOT))
        for name in set(sys.modules) - cls.before_modules:
            if name.startswith(("Animatronics", "control", "serial")):
                sys.modules.pop(name, None)
        cls.modules.stop()

    def setUp(self):
        self.house.systemState = "ONLINE"
        self.transport = Transport()
        transport = self.transport
        class Controller(self.george.GeorgeController):
            def __init__(self, **kwargs):
                super().__init__(transport=transport, **kwargs)
        self.character = self.service.George("George", self.george.GeorgeShow, Controller)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.character.quips = Path(self.directory.name)
        self.addCleanup(self.close)

    def close(self):
        self.character.stop()
        if self.character._controller:
            self.character._controller.close()

    def until(self, predicate, seconds=1):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Timed out waiting for worker")

    def test_character_calibration_and_separate_asset_paths(self):
        self.assertEqual(self.george.GeorgeController.rest_pose, dict(mouth=180, neck=80, eyes=False))
        self.assertEqual(self.pedro.PedroController.rest_pose, dict(wings=5, beak=55, neck=False, eyes=False))
        self.assertEqual(self.service.pedro.quips.name, "Pedro")
        self.assertEqual(self.service.george.quips.name, "George")
        self.assertEqual(self.service.pedro.quips.parent, self.service.george.quips.parent)
        self.assertTrue(self.service.pedro.quips.is_relative_to(ROOT.parent.parent / "Assets"))

    def test_talking_uses_old_angles_and_standby_closes_mouth(self):
        motion = self.george.Motion(0, random.Random(1))
        self.assertEqual(motion.pose("active", 0)["mouth"], 120)
        self.assertEqual(motion.pose("active", .21)["mouth"], 180)
        self.assertEqual(motion.pose("standby", 1)["mouth"], 180)
        self.assertEqual(motion.pose("off", 2), dict(state="off", mouth=180, neck=80, eyes=False))
        self.assertEqual(motion.pose("standby", 100)["neck"], 115)

    def test_manual_outputs_merge_and_heartbeat_without_random_motion(self):
        self.assertTrue(self.character.neck(90))
        self.assertTrue(self.character.mouth(120))
        self.assertTrue(self.character.eyes(True))
        self.until(lambda: self.transport.calls[-1].get("eyes") is True)
        previous = len(self.transport.calls)
        self.until(lambda: len(self.transport.calls) > previous, seconds=1)
        self.assertEqual(self.transport.calls[-1], dict(state="standby", mouth=120, neck=90, eyes=True, ramp_ms=0))
        self.assertEqual(self.character.status()["mode"], "manual")
        self.character.stop()
        self.until(lambda: self.transport.calls[-1]["state"] == "off")

    def test_pedro_manual_outputs_keep_existing_digital_neck(self):
        transport = Transport("pedro")
        base = self.pedro.PedroController
        class Controller(base):
            def __init__(self, **kwargs):
                super().__init__(transport=transport, **kwargs)
        character = self.service.Pedro("Pedro", self.pedro.PedroShow, Controller)
        try:
            self.assertTrue(character.wings(115))
            self.assertTrue(character.beak(10))
            self.assertTrue(character.neck(True))
            self.until(lambda: transport.calls[-1].get("neck") is True)
            self.assertEqual(transport.calls[-1]["wings"], 115)
            self.assertEqual(transport.calls[-1]["beak"], 10)
            with self.assertRaises(ValueError):
                character.neck(90)
        finally:
            character.stop()
            if character._controller:
                character._controller.close()

    def test_session_restart_discards_manual_pose_and_parks(self):
        self.assertTrue(self.character.neck(90))
        self.until(lambda: self.transport.calls[-1].get("neck") == 90)
        self.transport.session += 1
        self.until(lambda: self.character._controller.manual_pose is None)
        self.until(lambda: self.transport.calls[-1]["state"] == "off")
        self.assertEqual(self.character.status()["mode"], "off")

    def test_invalid_manual_outputs_never_start_hardware(self):
        for outputs in (dict(neck=116), dict(neck=True), dict(mouth=119), dict(eyes=1), dict(wings=5), dict(ramp_ms=-1)):
            with self.subTest(outputs=outputs), self.assertRaises(ValueError):
                self.character.pose(**outputs)
        self.assertIsNone(self.character._controller)

    def test_offline_never_starts_show_or_manual_hardware(self):
        self.house.systemState = "SoftShutdown"
        self.assertFalse(self.character.start())
        self.assertFalse(self.character.neck(90))
        self.assertIsNone(self.character._controller)

    def test_empty_quips_fail_before_hardware_starts(self):
        self.assertFalse(self.character.start())
        self.assertIsNone(self.character._controller.thread)
        self.assertIn("No audio files", self.character.status()["error"])

    def test_one_quip_uses_playback_completion_and_parks(self):
        (self.character.quips / "hello.wav").touch()
        handles = []
        def play(*args, **kwargs):
            handle = Handle()
            handles.append(handle)
            return handle
        with patch.object(self.core, "start_player", side_effect=play):
            self.assertTrue(self.character.talk("hello.wav"))
            self.until(lambda: bool(handles) and self.transport.calls[-1]["state"] == "active")
            handles[0].done.set()
            self.until(lambda: not self.character.status()["running"])
            self.until(lambda: self.transport.calls[-1]["state"] == "off")

    def test_manual_takeover_cancels_show_audio_and_generic_can_resume(self):
        (self.character.quips / "hello.mp3").touch()
        handles = []
        def play(*args, **kwargs):
            handle = Handle()
            handles.append(handle)
            return handle
        with patch.object(self.core, "start_player", side_effect=play):
            self.assertTrue(self.character.start())
            self.until(lambda: bool(handles))
            self.assertTrue(self.character.neck(5))
            self.assertTrue(handles[0].cancelled)
            self.assertFalse(self.character.status()["running"])
            self.assertTrue(self.character.start())
            self.until(lambda: len(handles) == 2)
            self.assertIsNone(self.character._controller.manual_pose)

    def make_character(self, kind):
        module = self.pedro if kind == "pedro" else self.george
        base = module.PedroController if kind == "pedro" else module.GeorgeController
        show = module.PedroShow if kind == "pedro" else module.GeorgeShow
        service = self.service.Pedro if kind == "pedro" else self.service.George
        transport = Transport(kind)
        class Controller(base):
            def __init__(self, **kwargs):
                super().__init__(transport=transport, **kwargs)
        character = service(kind.capitalize(), show, Controller)
        character.quips = self.character.quips
        def close():
            character.stop()
            if character._controller:
                character._controller.close()
        self.addCleanup(close)
        return character, transport

    def test_pedro_beak_follows_speech_level_without_interrupting_idle(self):
        (self.character.quips / "hello.wav").touch()
        character, transport = self.make_character("pedro")
        handle = Handle()
        level = [0.0]
        pending = [False]
        handle.audio_level = lambda now: level[0]
        handle.audible_pending = lambda: pending[0]
        with patch.object(self.core, "start_player", return_value=handle) as player:
            self.assertTrue(character.start_idle())
            self.assertTrue(character.talk("hello.wav"))
            self.until(lambda: transport.calls and transport.calls[-1]["state"] == "active")
            self.assertTrue(player.call_args.kwargs["track_envelope"])
            self.assertEqual(transport.calls[-1]["beak"],55)
            level[0]=.15
            self.until(lambda: transport.calls[-1]["beak"]==10)
            level[0]=0
            self.until(lambda: transport.calls[-1]["beak"]==55)
            self.assertFalse(handle.cancelled)
            self.assertTrue(character.status()["idle_enabled"])
            # Done can precede the last audible samples queued by PortAudio.
            pending[0]=True
            handle.done.set()
            self.assertTrue(character.status()["running"])
            pending[0]=False
            self.until(lambda: not character.status()["running"])
            self.until(lambda: transport.calls[-1]["state"]=="standby")
            self.assertEqual(transport.calls[-1]["beak"],55)
            self.assertEqual(character.status()["mode"],"idle")

    def test_pedro_audio_strokes_reach_both_endpoints_and_dwell_closed(self):
        character, transport = self.make_character("pedro")
        controller = character._hardware()
        level = [0.0]
        controller.set_speech_handle(SimpleNamespace(audio_level=lambda now: level[0]))
        self.assertEqual(controller._audio_mouth(0), ("beak",55))
        level[0]=.2
        self.assertEqual(controller._audio_mouth(.02), ("beak",10))
        self.assertEqual(controller._audio_mouth(.12), ("beak",10))
        # Even sustained speech gets a full closing stroke, not a hovering jaw.
        self.assertEqual(controller._audio_mouth(.22), ("beak",55))
        self.assertEqual(controller._audio_mouth(.26), ("beak",55))
        self.assertEqual(controller._audio_mouth(.33), ("beak",10))
        level[0]=0
        self.assertEqual(controller._audio_mouth(.34), ("beak",55))
        self.assertEqual(controller._audio_mouth(.8), ("beak",55))

    def test_idle_survives_multiple_quips_and_forwards_gain_for_both_characters(self):
        (self.character.quips / "hello.wav").touch()
        for kind in ("pedro", "george"):
            with self.subTest(kind=kind):
                character, transport = self.make_character(kind)
                handles, gains = [], []
                def play(*args, **kwargs):
                    handle = Handle()
                    handles.append(handle)
                    gains.append(kwargs["gain"])
                    return handle
                with patch.object(self.core, "start_player", side_effect=play):
                    self.assertTrue(character.start_idle())
                    self.until(lambda: transport.calls and transport.calls[-1]["state"] == "standby")
                    self.assertFalse(handles)
                    for gain in (0.35, 1.25):
                        self.assertTrue(character.talk("hello.wav", channel="Basement", gain=gain))
                        self.until(lambda: len(handles) == len(gains) and gains and gains[-1] == gain
                                   and transport.calls[-1]["state"] == "active")
                        handle = handles[-1]
                        self.assertFalse(handle.cancelled)
                        self.assertTrue(character.status()["idle_enabled"])
                        handle.done.set()
                        self.until(lambda: not character.status()["running"])
                        self.until(lambda: transport.calls[-1]["state"] == "standby")
                        self.assertEqual(character.status()["mode"], "idle")
                        self.assertTrue(character._controller.thread.is_alive())
                    self.assertEqual(gains, [0.35, 1.25])
                    character.stop_idle()
                    self.until(lambda: transport.calls[-1]["state"] == "off")
                    self.assertFalse(character.status()["idle_enabled"])

    def test_idle_toggle_during_speech_does_not_cancel_mouth_or_audio(self):
        (self.character.quips / "hello.wav").touch()
        for kind in ("pedro", "george"):
            with self.subTest(kind=kind):
                character, transport = self.make_character(kind)
                handle = Handle()
                with patch.object(self.core, "start_player", return_value=handle):
                    self.assertTrue(character.start_idle())
                    self.assertTrue(character.talk("hello.wav", gain=0.5))
                    self.until(lambda: transport.calls and transport.calls[-1]["state"] == "active")
                    character.stop_idle()
                    mouth = "beak" if kind == "pedro" else "mouth"
                    body = {key:value for key,value in character.controller_factory.rest_pose.items() if key != mouth}
                    self.until(lambda: all(transport.calls[-1].get(key) == value for key,value in body.items()))
                    self.assertEqual(character._controller.state, "active")
                    self.assertFalse(handle.cancelled)
                    began = len(transport.calls)
                    self.until(lambda: len({pose[mouth] for pose in transport.calls[began:] if pose["state"] == "active"}) >= 2)
                    self.assertTrue(all(all(pose.get(key) == value for key,value in body.items())
                                        for pose in transport.calls[began:] if pose["state"] == "active"))
                    self.assertTrue(character.start_idle())
                    self.assertEqual(character._controller.state, "active")
                    self.assertFalse(handle.cancelled)
                    character.stop()
                    self.assertTrue(handle.cancelled)
                    self.until(lambda: transport.calls[-1]["state"] == "off")
                    self.assertFalse(character.status()["idle_enabled"])

    def test_idle_requires_online_but_no_quip_files(self):
        self.assertTrue(self.character.start_idle())
        self.assertEqual(self.character.status()["mode"], "idle")
        self.assertFalse(self.character.status()["running"])
        self.character.stop()
        self.house.systemState = "SoftShutdown"
        self.assertFalse(self.character.start_idle())
        self.assertFalse(self.character.status()["idle_enabled"])

    def test_invalid_talk_gain_does_not_cancel_existing_speech(self):
        (self.character.quips / "hello.wav").touch()
        handle = Handle()
        with patch.object(self.core, "start_player", return_value=handle):
            self.assertTrue(self.character.talk("hello.wav", gain=0.5))
            self.until(lambda: self.transport.calls and self.transport.calls[-1]["state"] == "active")
            for gain in (-1, float("nan"), float("inf"), True, "0.5"):
                with self.subTest(gain=gain), self.assertRaises(ValueError):
                    self.character.talk(gain=gain)
            self.assertFalse(handle.cancelled)
            self.assertTrue(self.character.status()["running"])

    def test_stop_all_parks_both_characters(self):
        pedro, george = SimpleNamespace(stop=unittest.mock.Mock()), SimpleNamespace(stop=unittest.mock.Mock())
        with patch.object(self.service, "pedro", pedro), patch.object(self.service, "george", george):
            self.service.stop_all()
        pedro.stop.assert_called_once()
        george.stop.assert_called_once()


class GeorgeTransportTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "control/remote_sensor_monitor.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        names = {"tx_to_id", "george", "_store_device", "_valid_id", "_uint32", "_newer"}
        tree.body = [node for node in tree.body if getattr(node, "name", None) in names]
        self.device = dict(kind="george", session=12)
        self.scope = dict(uuid=uuid, queue=queue, re=__import__("re"), _now_ms=lambda: 100,
            _disabled=False, _commands={}, _txq=queue.Queue(), _tx_lock=threading.Lock(), MAX_COMMANDS=128,
            PEDRO_STATES=("off", "standby", "active"), DEVICE_FRESH_MS=6000, MAX_DEVICES=64,
            get=lambda sid: dict(connected=True, host="host") if sid == "_connection" else self.device,
            device_status=lambda sid: dict(available=True, state="valid", age_ms=0))
        exec(compile(tree, str(path), "exec"), self.scope)

    def test_atomic_pose_preserves_boot_fence_and_outputs(self):
        cid = self.scope["george"](neck=90, mouth=120, eyes=True)
        request = self.scope["_txq"].get_nowait()
        self.assertEqual((request["op"], request["target_session"], request["value"]), ("george", 12, 1))
        self.assertEqual((request["neck"], request["mouth"], request["eyes"]), (90, 120, True))
        self.assertEqual(self.scope["_commands"][cid]["status"], "queued")

    def test_wrong_device_kind_is_rejected_without_radio_queue(self):
        self.device["kind"] = "pedro"
        cid = self.scope["george"]()
        self.assertEqual(self.scope["_commands"][cid]["reason"], "not_george")
        self.assertTrue(self.scope["_txq"].empty())

    def test_malformed_outputs_are_rejected(self):
        for kwargs in (dict(neck=True), dict(mouth=-1), dict(eyes=1), dict(state="bad"), dict(ramp_ms=30001)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.scope["george"](**kwargs)

    def test_telemetry_validation_does_not_accept_partial_or_malformed_pose(self):
        vals = dict(george_state="standby", controller_connected=True, mouth_angle=180,
                    mouth_target=180, neck_angle=0, neck_target=0, eyes=False, moving=False, ready=True)
        obj = dict(id="GEORGE1", kind="george", vals=vals, session=1, seq=1, mac="00:11:22:33:44:55")
        shared = {}
        self.scope["_store_device"](shared, obj, 100)
        self.assertIn("GEORGE1", shared)
        for key, value in (("eyes", 1), ("neck_angle", 181), ("mouth_target", None)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.scope["_store_device"]({}, dict(obj, vals=dict(vals, **{key: value})), 101)


if __name__ == "__main__":
    unittest.main()
