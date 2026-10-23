"""Exercise the real door loop with simulated time, PIR data, and outputs."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


def simulate(end=9, pir=lambda now: False, connected=lambda now: True,
             target=lambda now: "CLOSED", door=1, bypass=False, cancel_at=None):
    house = SimpleNamespace(systemState="ONLINE", DoorState={},
                            TargetDoorState={door: target(0)})
    writes, events, sensors = [], [], []

    class Clock:
        now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.now = round(self.now + seconds, 6)
            if cancel_at is not None and self.now >= cancel_at:
                scope["setDoorState"](door, "CLOSED")
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
    if bypass:
        scope["setDoorState"](door, "CLOSED", bypass_sensor=True)
    scope["door_process"](door)
    return writes, events, sensors


class DoorPirWaitTests(unittest.TestCase):
    def test_bypass_closes_with_blocked_sensor_without_clear_delay(self):
        writes, events, _ = simulate(bypass=True, pir=lambda now: True)
        self.assertIn((1.0, 39, 0), writes)
        self.assertIn((5.0, "[Doors] Door 1 closed"), events)

    def test_normal_command_cancels_bypass_during_motion(self):
        writes, _, _ = simulate(bypass=True, pir=lambda now: True, cancel_at=2)
        self.assertIn((1.0, 39, 0), writes)
        self.assertIn((2.0, 39, 1), writes)
        self.assertEqual([w for w in writes if w[2] == 0], [(1.0, 39, 0)])

    def test_bypass_does_not_carry_into_next_movement(self):
        writes, _, _ = simulate(end=10, bypass=True, pir=lambda now: True,
                                target=lambda now: "OPEN" if 6 <= now < 7 else "CLOSED")
        self.assertEqual([w for w in writes if w[2] == 0], [(1.0, 39, 0)])

    def test_initial_low_waits_three_seconds_for_each_mapped_door(self):
        for door, pin in ((1, 39), (2, 41), (3, 38), (4, 45), (5, 53), (6, 40)):
            with self.subTest(door=door):
                writes, events, sensors = simulate(door=door)
                self.assertEqual([w for w in writes if w[2] == 0 and w[0] < 9], [(4.0, pin, 0)])
                self.assertEqual(set(sensors), {{1:"PIR5",2:"PIR1",3:"PIR2",4:"PIR3",5:"PIR6",6:"PIR4"}[door]})
                self.assertIn((8.0, f"[Doors] Door {door} closed"), events)
                self.assertEqual(writes[-1], (9.0, pin, 0 if door in (3, 6) else 1))

    def test_close_after_long_clear_starts_immediately(self):
        writes, _, _ = simulate(end=10, target=lambda now: "OPEN" if now < 6 else "CLOSED")
        self.assertIn((6.0, 39, 0), writes)

    def test_close_after_recent_trip_waits_only_remaining_interval(self):
        writes, _, _ = simulate(end=10, pir=lambda now: now < 3,
                                target=lambda now: "OPEN" if now < 4 else "CLOSED")
        self.assertIn((6.0, 39, 0), writes)

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
                self.assertIn((5.0, 39, 1), writes)

    def test_cancelled_close_preserves_continuous_clear_time(self):
        writes, _, _ = simulate(target=lambda now: "OPEN" if 2 <= now < 3 else "CLOSED")
        self.assertEqual([w[0] for w in writes if w[2] == 0], [4.0])

    def test_clopen_does_not_add_wait_when_already_clear(self):
        # Apply CLOPEN once; let the real loop issue its CLOSED request.
        writes, _, _ = simulate(end=18, target=lambda now: "CLOPEN" if now == 0 else None)
        self.assertEqual([w[0] for w in writes if w[2] == 0], [13.05])


if __name__ == "__main__":
    unittest.main()
