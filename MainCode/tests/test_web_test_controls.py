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
            servo=Mock(return_value='cid'), led=Mock(return_value='cid'),
            command_status=Mock(return_value={'status': 'queued'}),
            LANTERN_STATES=('off','solid_on'),
            get_lantern_state=Mock(return_value={'available':True,'synced':True,'next_command_id':7}),
            lantern=Mock(return_value={'LANTERN1':'cid'}))
        control = ModuleType('control')
        control.arduino, control.dimmer_controller, control.remote_sensor_monitor = self.arduino, self.dim, self.rsm
        self.patch = patch.dict(sys.modules, {'control':control})
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


if __name__=='__main__': unittest.main()
