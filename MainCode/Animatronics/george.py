"""George (formerly William Wallace): servo mouth/neck, digital eyes.

Angles are degrees, matching the old Firmata program and Haunt servo API.
No hardware or audio opens on import.
"""
import random
from pathlib import Path
if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Animatronics.core import AnimatronicController, AnimatronicShow
from Animatronics.pedro import ASSETS, BEAK_TIMES, EYES_ON_SECONDS, EYES_BLINK_SECONDS

MOUTH_OPEN, MOUTH_CLOSED = 120, 180
NECK_REST, NECK_LOW, NECK_HIGH = 80, 5, 180  # 80 degrees faces forward.


class Motion:
    def __init__(self, now, rng=None):
        self.rng = rng or random.Random()
        self.reset(now)

    def reset(self, now):
        self.neck, self.mouth, self.eyes = NECK_REST, MOUTH_CLOSED, True
        self.next_neck = now + self.rng.randint(1, 6)
        self.next_eyes = now + self.rng.uniform(*EYES_ON_SECONDS)
        self.next_mouth, self.mouth_step, self.was_active = now, 0, False

    def pose(self, state, now):
        if state == "off":
            self.reset(now)
            return dict(state=state, mouth=MOUTH_CLOSED, neck=NECK_REST, eyes=False)
        if now >= self.next_neck:
            self.neck = NECK_LOW if self.neck == NECK_HIGH else NECK_HIGH
            self.next_neck = now + self.rng.randint(1, 6)
        if now >= self.next_eyes:
            self.eyes = not self.eyes
            self.next_eyes = now + self.rng.uniform(*(EYES_ON_SECONDS if self.eyes else EYES_BLINK_SECONDS))
        active = state == "active"
        if active and not self.was_active:
            self.mouth_step, self.next_mouth = 0, now
        if active and now >= self.next_mouth:
            self.mouth = MOUTH_OPEN if self.mouth_step % 2 == 0 else MOUTH_CLOSED
            self.next_mouth = now + BEAK_TIMES[(self.mouth_step // 2) % len(BEAK_TIMES)]
            self.mouth_step += 1
        elif not active:
            self.mouth = MOUTH_CLOSED
        self.was_active = active
        return dict(state=state, mouth=self.mouth, neck=self.neck, eyes=self.eyes)


class GeorgeController(AnimatronicController):
    name, kind = "George", "george"
    finish_audio_on_link_loss = True
    motion_factory = Motion
    idle_neck_range = (NECK_LOW, NECK_HIGH)
    rest_pose = dict(mouth=MOUTH_CLOSED, neck=NECK_REST, eyes=False)
    output_limits = dict(mouth=(120, 180), neck=(0, 180), eyes=bool)

    def __init__(self, device_id="GEORGE1", **kwargs):
        super().__init__(device_id, **kwargs)


class GeorgeShow(AnimatronicShow):
    name, default_device_id = "George", "GEORGE1"
    controller_factory = GeorgeController

    def __init__(self, channel="George", *, quips=ASSETS / "SoundDir" / "Quips" / "George", **kwargs):
        super().__init__(channel, quips=quips, **kwargs)


def main(argv=None):
    from Animatronics.core import run_cli
    run_cli(GeorgeController, GeorgeShow, name="George", device_id="GEORGE1",
            quips=ASSETS / "SoundDir" / "Quips" / "George", argv=argv)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
