"""Exercise the real door loop with simulated time, PIR data, and outputs."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


def simulate(end=9, pir=lambda now: False, connected=lambda now: True,
             target=lambda now: "CLOSED", door=1):
    house = SimpleNamespace(systemState="ONLINE", DoorState={},
                            TargetDoorState={door: target(0)})
    writes, events, sensors = [], [], []

    class Clock:
        now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.now = round(self.now + seconds, 6)
            next_target = target(self.now)
            if next_target is not None:
                house.TargetDoorState[door] = next_target
            if self.now >= end:
                house.systemState = "OFFLINE"

    clock = Clock()

    def sensor(sid):
        sensors.append(sid)
        return {"triggered": pir(clock.now)}

    scope = dict(t=clock, house=house,
                 m1Digital_Write=lambda pin, value: writes.append((clock.now, pin, value)),
                 log_event=lambda text: events.append((clock.now, text)),
                 rsm=SimpleNamespace(healthy=lambda: {"connected": connected(clock.now)},
                                     get_pir_state=sensor))
    path = Path(__file__).resolve().parents[1] / "control/doors.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    tree.body = [node for node in tree.body
                 if not isinstance(node, (ast.Import, ast.ImportFrom))]
    exec(compile(tree, str(path), "exec"), scope)
    scope["door_process"](door)
    return writes, events, sensors


class DoorPirWaitTests(unittest.TestCase):
    def test_initial_low_waits_three_seconds_for_each_mapped_door(self):
        for door, pin in ((1, 47), (2, 38)):
            with self.subTest(door=door):
                writes, events, sensors = simulate(door=door)
                self.assertEqual([w for w in writes if w[2] == 0], [(4.0, pin, 0)])
                self.assertEqual(set(sensors), {f"PIR{door}"})
                self.assertIn((8.0, f"[Doors] Door {door} closed"), events)
                self.assertEqual(writes[-1], (9.0, pin, 1))

    def test_high_or_unknown_restarts_full_wait(self):
        # None covers unavailable, warming, and conflicting PIR data.
        for blocked in (True, None):
            with self.subTest(blocked=blocked):
                writes, _, _ = simulate(pir=lambda now: blocked if 2 <= now < 3 else False)
                self.assertEqual([w[0] for w in writes if w[2] == 0], [6.0])

    def test_bridge_loss_restarts_full_wait(self):
        writes, _, _ = simulate(connected=lambda now: not (2 <= now < 3))
        self.assertEqual([w[0] for w in writes if w[2] == 0], [6.0])

    def test_continuously_blocked_never_closes(self):
        for blocked in (True, None):
            writes, _, _ = simulate(pir=lambda now: blocked)
            self.assertFalse(any(w[2] == 0 for w in writes))

    def test_obstruction_while_closing_reopens_then_waits_before_retry(self):
        for blocked in (True, None):
            with self.subTest(blocked=blocked):
                writes, _, _ = simulate(end=13, pir=lambda now: blocked if 5 <= now < 6 else False)
                self.assertEqual([w[0] for w in writes if w[2] == 0], [4.0, 9.0])
                self.assertIn((5.0, 47, 1), writes)

    def test_cancelled_close_does_not_reuse_previous_clear_time(self):
        writes, _, _ = simulate(target=lambda now: "OPEN" if 2 <= now < 3 else "CLOSED")
        self.assertEqual([w[0] for w in writes if w[2] == 0], [6.0])

    def test_clopen_hold_is_followed_by_clear_wait(self):
        # Apply CLOPEN once; let the real loop issue its CLOSED request.
        writes, _, _ = simulate(end=18, target=lambda now: "CLOPEN" if now == 0 else None)
        self.assertEqual([w[0] for w in writes if w[2] == 0], [16.05])


if __name__ == "__main__":
    unittest.main()
