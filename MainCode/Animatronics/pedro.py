"""Pedro-only replacement for PedroWallace v3; use the existing ESP-NOW bridge.

Run `python MainCode/Animatronics/pedro.py --help`. No serial, audio, or hardware opens on import.
Do not run a second standalone monitor on the same COM port as MainCode/main.py.
Inside the main app, use control.animatronic_service.pedro.start/stop; these
reuse its initialized RSM and audio mixers.
"""
from __future__ import annotations

import multiprocessing
from pathlib import Path
import random

# Support both package imports and the standalone CLI.
if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control import remote_sensor_monitor as rsm
from Animatronics.core import AnimatronicController, AnimatronicShow

ASSETS = Path(__file__).resolve().parents[3] / "Assets"
BEAK_TIMES = (0.2, 0.2, 0.1, 0.1, 0.4, 0.3)
WINGS_REST, WINGS_OPEN = 5, 115
BEAK_CLOSED, BEAK_OPEN = 55, 10
EYES_ON_SECONDS = (3.0, 7.0)
EYES_BLINK_SECONDS = (0.08, 0.16)


class Motion:
    """Python owns all random motion and mouth timing; ESP receives full poses."""
    def __init__(self, now, rng=None):
        self.rng = rng or random.Random()
        self.reset(now)

    def reset(self, now):
        self.wings, self.beak, self.neck, self.eyes = WINGS_REST, BEAK_CLOSED, False, True
        self.next_wings = now + self.rng.randint(1, 6)
        self.next_neck = now + self.rng.randint(1, 3)
        self.next_eyes = now + self.rng.uniform(*EYES_ON_SECONDS)
        self.next_beak, self.beak_step, self.was_active = now, 0, False

    def pose(self, state, now):
        if state == "off":
            self.reset(now)
            return dict(state=state, wings=WINGS_REST, beak=BEAK_CLOSED, neck=False, eyes=False)
        if now >= self.next_wings:
            self.wings = WINGS_OPEN if self.wings == WINGS_REST else WINGS_REST
            self.next_wings = now + self.rng.randint(1, 6)
        if now >= self.next_neck:
            self.neck = not self.neck
            self.next_neck = now + self.rng.randint(1, 3)
        if now >= self.next_eyes:
            self.eyes = not self.eyes
            self.next_eyes = now + self.rng.uniform(*(EYES_ON_SECONDS if self.eyes else EYES_BLINK_SECONDS))
        active = state == "active"
        if active and not self.was_active:
            self.beak_step, self.next_beak = 0, now
        if active and now >= self.next_beak:
            self.beak = BEAK_OPEN if self.beak_step % 2 == 0 else BEAK_CLOSED
            self.next_beak = now + BEAK_TIMES[(self.beak_step // 2) % len(BEAK_TIMES)]
            self.beak_step += 1
        elif not active:
            self.beak = BEAK_CLOSED
        self.was_active = active
        return dict(state=state, wings=self.wings, beak=self.beak, neck=self.neck, eyes=self.eyes)


class PedroController(AnimatronicController):
    name, kind = "Pedro", "pedro"
    audio_driven_mouth = True
    # Full beak strokes; leave enough time at each endpoint for servo travel.
    speech_min_open, speech_max_open, speech_min_closed = 0.08, 0.18, 0.09
    speech_open_ratio, speech_close_ratio = 0.24, 0.16
    motion_factory = Motion
    output_limits = dict(wings=(5, 115), beak=(10, 55), neck=bool, eyes=bool)
    rest_pose = dict(wings=WINGS_REST, beak=BEAK_CLOSED, neck=False, eyes=False)

    def __init__(self, device_id="PEDRO1", **kwargs):
        super().__init__(device_id, **kwargs)


class PedroShow(AnimatronicShow):
    name, default_device_id = "Pedro", "PEDRO1"
    controller_factory = PedroController

    def __init__(self, channel="Pedro", *, quips=ASSETS / "SoundDir" / "Quips" / "Pedro", **kwargs):
        super().__init__(channel, quips=quips, **kwargs)


def main(argv=None):
    from Animatronics.core import run_cli
    run_cli(PedroController, PedroShow, name="Pedro", device_id="PEDRO1",
            quips=ASSETS / "SoundDir" / "Quips" / "Pedro", argv=argv)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
