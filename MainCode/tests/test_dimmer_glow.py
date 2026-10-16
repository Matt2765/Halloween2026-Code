"""Hardware-free checks for Arduino glow commands and Bathroom integration."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_controller():
    tree = ast.parse((ROOT / "control/dimmer_controller.py").read_text(encoding="utf-8-sig"))
    tree.body = [node for node in tree.body
                 if not (isinstance(node, ast.Import) and any(a.name == "serial" for a in node.names))
                 and not (isinstance(node, ast.ImportFrom) and node.module == "utils.tools")]
    scope = {"BreakCheck": lambda: False, "log_event": lambda *args: None}
    exec(compile(tree, "dimmer_controller.py", "exec"), scope)
    return scope


class GlowTests(unittest.TestCase):
    def test_start_and_stop_even_after_missing_ack(self):
        for acknowledged in (True, False):
            controller = load_controller()
            calls = []
            def command(line, expected, **kwargs):
                calls.append((line, expected, kwargs))
                return acknowledged if line.startswith("GLOW") else True
            controller["_command"] = command
            # Simulate a recent OFF cached before starting the glow.
            controller["_last_sent_int"][5] = 0
            controller["_last_send_ok_ts"][5] = controller["time"].monotonic()
            self.assertEqual(controller["start_glow"](15, 25, 2.5, channel=6), acknowledged)
            self.assertEqual(calls[0], ("GLOW 6 6871 6148 2500", "ACK GLOW 6 6871 6148 2500", {"wait": True}))
            self.assertTrue(controller["dim"](0, channel=6))
            self.assertEqual(calls[-1][0], "SET 6 0")

    def test_invalid_parameters_do_not_send(self):
        controller = load_controller()
        controller["_command"] = lambda *args, **kwargs: self.fail("unexpected command")
        for low, high, duration in ((0, 25, 2.5), (15, 25, 0), (15, 25, float("nan")), (15, 25, 66)):
            with self.assertRaises(ValueError):
                controller["start_glow"](low, high, duration, channel=6)

    def test_room_uses_one_start_then_off_or_falls_back(self):
        tree = ast.parse((ROOT / "rooms/Bathroom.py").read_text(encoding="utf-8-sig"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "ambientGlow")
        for supported in (True, False):
            class Clock:
                now = 0.0
                def monotonic(self): return self.now
                def sleep(self, seconds): self.now += seconds
            clock = Clock()
            levels, starts = [], []
            scope = {"t": clock, "ambientLight": True,
                     "BreakCheck": lambda: clock.now >= 0.15,
                     "log_event": lambda *args: None,
                     "dim": lambda value, **kwargs: levels.append(value)}
            def start(*args, **kwargs):
                starts.append((args, kwargs))
                return supported
            scope["start_glow"] = start
            exec(compile(ast.Module(body=[function], type_ignores=[]), "Bathroom.py", "exec"), scope)
            scope["ambientGlow"]()
            self.assertEqual(starts, [((15.0, 25.0, 2.5), {"channel": 6})])
            self.assertEqual(levels[-1], 0)
            if supported:
                self.assertEqual(levels, [0])  # No brightness streaming while glowing.
            else:
                self.assertGreater(len(levels), 1)


if __name__ == "__main__":
    unittest.main()
