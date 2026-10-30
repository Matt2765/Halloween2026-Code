"""Hardware-free checks of manual output routing and input validation."""
import ast
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


def load_controls():
    path = Path(__file__).resolve().parents[1] / 'control/web_tests.py'
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    tree.body = [n for n in tree.body if not isinstance(n, ast.ImportFrom)]
    scope = dict(house=SimpleNamespace(systemState='ONLINE', HouseActive=False,
                 Demo=False, DISABLE_AUDIO_MANAGER=False), log_event=Mock())
    exec(compile(tree, str(path), 'exec'), scope)
    return scope


class WebTestControlsTests(unittest.TestCase):
    def setUp(self):
        self.scope = load_controls()
        self.arduino = SimpleNamespace(M1_available=True, M1=SimpleNamespace(digital_write=Mock()))
        self.dim = SimpleNamespace(_simulated=False, dim=Mock(return_value=True))
        self.rsm = SimpleNamespace(healthy=lambda: {'disabled': False},
            mosfet=Mock(return_value={'MOSFET1':'cid'}),
            servo=Mock(return_value='cid'), led=Mock(return_value='cid'),
            command_status=Mock(return_value={'status': 'queued'}),
            LANTERN_STATES=('off','solid_on'),
            get_lantern_state=Mock(return_value={'available':True,'synced':True,'next_command_id':7}),
            lantern=Mock(return_value={'LANTERN1':'cid'}))
        control = ModuleType('control')
        control.arduino, control.dimmer_controller, control.remote_sensor_monitor = self.arduino, self.dim, self.rsm
        self.characters = {}
        for key, limits, rest in (
            ('pedro', dict(wings=(5,115),beak=(10,55),neck=bool,eyes=bool),
             dict(wings=5,beak=55,neck=False,eyes=False)),
            ('george', dict(mouth=(120,180),neck=(0,115),eyes=bool),
             dict(mouth=180,neck=80,eyes=False))):
            self.characters[key] = SimpleNamespace(name=key.capitalize(),
                controller_factory=SimpleNamespace(output_limits=limits,rest_pose=rest),
                start=Mock(return_value=True), talk=Mock(return_value=True), stop=Mock(),
                start_idle=Mock(return_value=True), stop_idle=Mock(),
                pose=Mock(return_value=True), status=Mock(return_value=dict(mode='off',error=None)))
        control.animatronic_service = SimpleNamespace(**self.characters)
        self.audio = SimpleNamespace(list_named_channels=lambda: ['Pedro','George','Basement'])
        self.patch = patch.dict(sys.modules, {'control':control, 'control.audio_manager':self.audio})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def execute(self, kind, id=None, value=None, **kw):
        return self.scope['execute'](dict(kind=kind,id=id,value=value,**kw))

    def test_every_relay_uses_its_configured_polarity(self):
        for key, room, label, pin, on in self.scope['RELAYS']:
            for value in (True,False):
                self.execute('relay',key,value)
                self.arduino.M1.digital_write.assert_called_with(pin,on if value else 1-on)
        self.assertEqual(next(r[4] for r in self.scope['RELAYS'] if r[0]=='cabin_strobe'),1)

    def test_relay_pins_and_off_levels_match_shutdown(self):
        path = Path(__file__).resolve().parents[1] / 'control/shutdown.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        shutdown = next(n for n in tree.body
                        if isinstance(n, ast.FunctionDef) and n.name == 'shutdown')
        shutdown_outputs = {
            ast.literal_eval(node.args[0]): ast.literal_eval(node.args[1])
            for node in ast.walk(shutdown)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == 'm1Digital_Write'
        }
        test_outputs = {pin: 1 - on for key, room, label, pin, on in self.scope['RELAYS']
                        if key != 'house_light'}
        self.assertEqual(test_outputs, shutdown_outputs)

    def test_forest_lasers_use_the_assigned_wired_pin(self):
        for value in (True, False):
            self.execute('relay', 'forest_lasers', value)
            self.arduino.M1.digital_write.assert_called_with(56, 0 if value else 1)
        self.rsm.mosfet.assert_not_called()
        for key, value in [('arbitrary', True), ('forest_lasers', 1)]:
            with self.assertRaises(ValueError):
                self.execute('relay', key, value)
        with self.assertRaises(ValueError):
            self.execute('mosfet', 'forest_lasers', True)
        self.rsm.mosfet.assert_not_called()

    def test_shutdown_turns_lasers_off_without_wireless_monitor(self):
        path = Path(__file__).resolve().parents[1] / 'control/shutdown.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        tree.body = [n for n in tree.body if getattr(n, 'name', None) == 'shutdown']
        lights = Mock()
        scope = dict(house=SimpleNamespace(), rsm=self.rsm, log_event=Mock(),
                     DOOR_SOLENOID_PINS={}, apply_door_shutdown_state=Mock(),
                     stop_all=Mock(), dim=Mock(), m1Digital_Write=Mock(),
                     t=SimpleNamespace(sleep=Mock()), toggleHouseLights=lights)
        exec(compile(tree, str(path), 'exec'), scope)
        self.rsm.mosfet.side_effect = RuntimeError('Call init() first')
        scope['shutdown']()
        scope['m1Digital_Write'].assert_any_call(56, 1)
        self.rsm.mosfet.assert_not_called()
        lights.assert_called_with(True)

    def test_numeric_validation_and_dimmer_channel(self):
        self.execute('dimmer',6,37.5)
        self.dim.dim.assert_called_with(37.5,channel=6,force=True)
        for value in (-1,101,True,float('nan'),float('inf'),'50',None):
            with self.assertRaises(ValueError): self.execute('dimmer',1,value)
        with self.assertRaises(ValueError): self.execute('dimmer',99,50)
        with self.assertRaises(ValueError): self.execute('relay','arbitrary_pin',True)

    def test_no_success_when_hardware_is_unavailable(self):
        self.arduino.M1_available=False
        with self.assertRaises(RuntimeError): self.execute('relay','cabin_air1',True)
        self.arduino.M1.digital_write.assert_not_called()
        self.dim._simulated=True
        with self.assertRaises(RuntimeError): self.execute('dimmer',1,20)
        self.dim.dim.assert_not_called()

    def test_tests_require_online_house(self):
        self.scope['house'].systemState = 'EmergencyShutoff'
        with self.assertRaises(RuntimeError):
            self.execute('relay', 'cabin_air1', True)
        self.arduino.M1.digital_write.assert_not_called()

    def test_tests_allow_running_house_and_demo(self):
        house = self.scope['house']
        for active, demo in [(True, False), (False, True), (True, True)]:
            with self.subTest(active=active, demo=demo):
                house.HouseActive, house.Demo = active, demo
                for value in (True, False):
                    self.execute('relay', 'cabin_air1', value)
                    self.arduino.M1.digital_write.assert_called_with(43, 0 if value else 1)
                self.execute('dimmer', 7, 40)
                self.dim.dim.assert_called_with(40, channel=7, force=True)
                self.assertEqual((house.HouseActive, house.Demo), (active, demo))

    def test_servo_limits_and_remote_rejection(self):
        self.execute('servo','DROPDOWN1',90)
        self.rsm.servo.assert_called_with('DROPDOWN1',90)
        for angle in (181,-1,2.5):
            with self.assertRaises(ValueError): self.execute('servo','DROPDOWN1',angle)
        self.rsm.command_status.return_value={'status':'rejected','detail':'device_not_seen'}
        with self.assertRaisesRegex(RuntimeError,'device_not_seen'): self.execute('led','DROPDOWN1',True)

    def test_lantern_uses_reported_next_cue(self):
        self.execute('lantern','LANTERN1','solid_on')
        self.rsm.lantern.assert_called_with(7,'solid_on',['LANTERN1'])
        self.rsm.get_lantern_state.return_value={'available':False}
        with self.assertRaises(RuntimeError): self.execute('lantern','LANTERN1','off')

    def test_catalog_contains_both_characters_and_their_actual_output_limits(self):
        doors = SimpleNamespace(DOOR_SOLENOID_PINS={},DOOR_SENSOR_IDS={})
        with patch.dict(sys.modules, {'control.doors':doors}):
            entries = self.scope['catalog']()['animatronics']
        self.assertEqual([entry['id'] for entry in entries], ['pedro','george'])
        outputs = {entry['id']:{output['id']:output for output in entry['outputs']} for entry in entries}
        self.assertEqual(outputs['george']['neck']['max'], 115)
        self.assertEqual(outputs['george']['mouth']['min'], 120)
        self.assertEqual(outputs['george']['mouth']['rest'], 180)
        self.assertEqual(outputs['pedro']['neck']['type'], 'digital')
        self.assertNotIn('led', outputs['george'])

    def test_animatronic_show_talk_and_park_use_shared_service(self):
        for key, character in self.characters.items():
            for value, method in [('start',character.start), ('talk',character.talk)]:
                result = self.execute('animatronic',key,value,channel='Basement',gain=0.4)
                method.assert_called_once_with(channel='Basement',gain=0.4)
                self.assertIn('requested',result['message'])
            self.execute('animatronic',key,'stop')
            character.stop.assert_called_once_with()

    def test_manual_controls_route_angles_and_booleans_without_starting_a_show(self):
        for key, outputs in [('george',dict(mouth=120,neck=90,eyes=True)),
                             ('pedro',dict(wings=115,beak=10,neck=True,eyes=False))]:
            self.execute('animatronic',key,'pose',outputs=outputs,ramp_ms=500)
            character=self.characters[key]
            character.pose.assert_called_once_with(ramp_ms=500,**outputs)
            character.start.assert_not_called()
            character.talk.assert_not_called()

    def test_idle_buttons_work_without_audio_and_do_not_stop_speech(self):
        self.scope['house'].DISABLE_AUDIO_MANAGER=True
        for key, character in self.characters.items():
            self.execute('animatronic',key,'idle_start')
            character.start_idle.assert_called_once_with()
            self.execute('animatronic',key,'idle_stop')
            character.stop_idle.assert_called_once_with()
            character.stop.assert_not_called()
            character.talk.assert_not_called()

    def test_invalid_animatronic_requests_never_reach_service(self):
        for outputs in [dict(neck=116), dict(mouth=119), dict(eyes=1), dict(neck=5.5),
                        dict(neck=True), dict(wings=5), {}, None, ['neck']]:
            with self.subTest(outputs=outputs), self.assertRaises(ValueError):
                self.execute('animatronic','george','pose',outputs=outputs)
        for ramp in [-1,30001,True,1.5]:
            with self.subTest(ramp=ramp), self.assertRaises(ValueError):
                self.execute('animatronic','george','pose',outputs={'neck':5},ramp_ms=ramp)
        for key, action in [('unknown','start'),('george','__dict__')]:
            with self.assertRaises(ValueError):
                self.execute('animatronic',key,action)
        self.characters['george'].pose.assert_not_called()

    def test_talking_validates_routes_gain_and_disabled_audio(self):
        for settings in [dict(channel='unknown'),dict(gain=-1),dict(gain=float('nan'))]:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.execute('animatronic','george','start',**settings)
        self.scope['house'].DISABLE_AUDIO_MANAGER=True
        with self.assertRaisesRegex(RuntimeError,'Audio manager'):
            self.execute('animatronic','george','talk')
        self.characters['george'].talk.assert_not_called()
        self.execute('animatronic','george','pose',outputs={'eyes':True})

    def test_disabled_monitor_rejects_motion_but_allows_park(self):
        self.rsm.healthy=lambda: {'disabled':True}
        with self.assertRaisesRegex(RuntimeError,'Sensor monitor disabled'):
            self.execute('animatronic','george','pose',outputs={'neck':90})
        self.characters['george'].pose.assert_not_called()
        self.execute('animatronic','george','stop')
        self.characters['george'].stop.assert_called_once()

    def test_service_failures_surface_instead_of_claiming_success(self):
        character=self.characters['george']
        character.pose.return_value=False
        character.status.return_value={'error':'Hardware link unavailable'}
        with self.assertRaisesRegex(RuntimeError,'Hardware link unavailable'):
            self.execute('animatronic','george','pose',outputs={'neck':90})
        character.start.return_value=False
        character.status.return_value={'error':'No audio files in George'}
        with self.assertRaisesRegex(RuntimeError,'No audio files'):
            self.execute('animatronic','george','start')



if __name__=='__main__': unittest.main()
