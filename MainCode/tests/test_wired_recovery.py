"""Controller lifecycle checks with fake ports; never access installed hardware."""
import ast
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class Worker:
    def __init__(self, **kwargs):
        self.alive = False
        self.kwargs = kwargs
    def start(self): self.alive = True
    def is_alive(self): return self.alive
    def join(self, **kwargs): self.alive = False


class Port:
    is_open = True
    in_waiting = 0
    def close(self): self.is_open = False


class Board:
    def __init__(self):
        self.serial_port, self.pins, self.writes = Port(), [], []
    def set_pin_mode_digital_output(self, pin): self.pins.append(pin)
    def digital_write(self, *args): self.writes.append(args)
    def shutdown(self): pass


def load(name):
    tree = ast.parse((ROOT / 'control' / name).read_text(encoding='utf-8-sig'))
    tree.body = [n for n in tree.body
                 if not (isinstance(n, ast.ImportFrom) and n.module in ('pymata4', 'utils.tools', 'context'))
                 and not (isinstance(n, ast.Import) and any(a.name == 'serial' for a in n.names))
                 and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                          and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == 'register')]
    scope = dict(log_event=lambda *a: None, BreakCheck=lambda: False, house=types.SimpleNamespace(),
                 serial=types.SimpleNamespace(SerialException=OSError))
    exec(compile(tree, name, 'exec'), scope)
    scope['threading'] = types.SimpleNamespace(Thread=Worker, get_ident=threading.get_ident)
    return scope


class WiredRecoveryTests(unittest.TestCase):
    def test_mega_uses_previous_connection_path_and_valid_pin_range(self):
        s = load('arduino.py'); board = Board(); waits = []
        s['pymata4'] = types.SimpleNamespace(Pymata4=lambda **kwargs: board)
        s['t'] = types.SimpleNamespace(sleep=waits.append)
        s['connectArduino']()
        self.assertTrue(s['M1_available'])
        self.assertEqual(board.pins, list(range(2, 70)))
        self.assertEqual(waits, [0.3])
        self.assertFalse(hasattr(board.serial_port, 'write_timeout'))
        for pin in (39, 43, 22, 28, 5, 2):
            s['m1Digital_Write'](pin, 1)
            s['m1Digital_Write'](pin, 0)
        self.assertEqual(len(board.writes), 12)

    def test_mega_shutdown_relay_writes_all_reach_board(self):
        s = load('arduino.py'); board = Board()
        s.update(M1=board, M1_available=True)
        tree = ast.parse((ROOT / 'control/shutdown.py').read_text())
        tree.body = [n for n in tree.body if getattr(n, 'name', None) == 'shutdown']
        scope = dict(log_event=lambda *a: None, house=types.SimpleNamespace(),
                     DOOR_SOLENOID_PINS={1:39,2:41,3:38,4:45,5:53,6:40},
                     apply_door_shutdown_state=lambda door: s['m1Digital_Write']({1:39,2:41,3:38,4:45,5:53,6:40}[door],1),
                     stop_all=lambda: None, dim=lambda *a, **k: None,
                     m1Digital_Write=s['m1Digital_Write'],
                     t=types.SimpleNamespace(sleep=lambda seconds: None),
                     toggleHouseLights=lambda enabled: None)
        exec(compile(tree, 'shutdown.py', 'exec'), scope)
        scope['shutdown']()
        self.assertEqual(len(board.writes), 38)
        self.assertIn((43, 1), board.writes)
        self.assertIn((22, 0), board.writes)

    def test_dimmer_repeated_init_reuses_worker_and_explicit_close_disables_recovery(self):
        s = load('dimmer_controller.py')
        s['_initialize_once'] = lambda port=None: True
        self.assertTrue(s['init']()); worker = s['_recovery_thread']
        self.assertTrue(s['init']()); self.assertIs(worker, s['_recovery_thread'])
        self.assertTrue(s['_recovery_enabled'].is_set())
        s['close'](); self.assertFalse(s['_recovery_enabled'].is_set())

    def test_dimmer_reconnect_checks_version_and_off_without_restoring_old_level(self):
        s = load('dimmer_controller.py'); writes = []
        port = Port(); port.reset_input_buffer = lambda: None
        s['serial'].Serial = lambda *a, **k: port
        s['time'] = types.SimpleNamespace(sleep=lambda seconds: None, monotonic=lambda: 10)
        s['_command'] = lambda line, expected, **kwargs: writes.append(line) or True
        s['_last_sent_int'][0] = 80
        self.assertTrue(s['_initialize_once']())
        self.assertEqual(writes, ['VERSION', 'OFF'])
        self.assertEqual(s['_current_pct'], [0] * 8)
        self.assertIsNone(s['_initializing_thread'])
        s['close']()

    def test_dimmer_connection_failure_does_not_report_simulated_success(self):
        s = load('dimmer_controller.py')
        s['serial'].Serial = lambda *a, **k: (_ for _ in ()).throw(OSError('missing'))
        self.assertFalse(s['_initialize_once']())
        self.assertFalse(s['_command']('SET 1 80', 'ACK SET 1 80'))
        self.assertIsNone(s['_initializing_thread'])

    def test_dimmer_other_thread_cannot_send_during_initialization(self):
        s = load('dimmer_controller.py'); s['_initializing_thread'] = -1
        self.assertFalse(s['_command']('SET 1 80', 'ACK SET 1 80'))

    def test_dimmer_write_failure_marks_transport_for_recovery(self):
        s = load('dimmer_controller.py'); s['_simulated'] = False
        s['_ser'] = types.SimpleNamespace(write=lambda data: (_ for _ in ()).throw(OSError('unplugged')))
        self.assertFalse(s['_command']('SET 1 80', 'ACK SET 1 80'))
        self.assertTrue(s['_transport_failed'])

    def test_dimmer_supervisor_reconnects_failed_port_but_respects_disabled_recovery(self):
        for enabled in (True, False):
            s = load('dimmer_controller.py'); attempts = []
            if enabled: s['_recovery_enabled'].set()
            class Done(Exception): pass
            sleeps = []
            def sleep(seconds):
                sleeps.append(seconds)
                if len(sleeps) > 1: raise Done()
            s['time'] = types.SimpleNamespace(sleep=sleep)
            s['_initialize_once'] = lambda: attempts.append('connect')
            with self.assertRaises(Done): s['_recover_loop']()
            self.assertEqual(attempts, ['connect'] if enabled else [])


if __name__ == '__main__':
    unittest.main()
