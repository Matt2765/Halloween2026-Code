"""Shared main-system animatronic API; reuses the existing RSM and mixers.

pedro.start() / george.start(): generic quips, mouth motion, idle movement.
start_idle() keeps body animation running across talk(..., gain=...) calls.
george.neck(90): switch to manual control and hold that servo angle.
"""
import math
import threading
from pathlib import Path

from context import house
from Animatronics.pedro import PedroShow, PedroController, ASSETS
from Animatronics.george import GeorgeShow, GeorgeController
from utils.tools import log_event


class Animatronic:
    def __init__(self, name, show_factory, controller_factory):
        self.name = name
        self.show_factory, self.controller_factory = show_factory, controller_factory
        self.quips = ASSETS / "SoundDir" / "Quips" / name
        self._lock = threading.RLock()
        self._show = self._controller = None
        self._error = None
        self._mode = "off"
        self._idle_enabled = False

    def _online(self):
        if house.systemState != "ONLINE":
            log_event(f"[{self.name}] Cannot start while the main system is offline")
            return False
        return True

    def _hardware(self):
        if self._controller is None:
            self._controller = self.controller_factory(off=True)
        return self._controller

    def _finish_state(self):
        # Show workers must not acquire the service lock: stop() joins them.
        return "standby" if self._idle_enabled and house.systemState == "ONLINE" else "off"

    @staticmethod
    def _validate_gain(gain):
        if gain is not None and (type(gain) not in (int, float) or not math.isfinite(gain) or gain < 0):
            raise ValueError("gain must be a finite nonnegative number or None")

    def start(self, channel=None, *, gain=None, quips=None, background=None,
              background_channel=None, background_gain=0.89, interval=(10, 15), once=False):
        """Start the generic talking show. Returns False if offline/invalid.

        Stop before changing an already-running show's settings. Audio routes
        have the same meaning as play_audio; no second RSM is initialized.
        """
        with self._lock:
            if not self._online():
                return False
            if self._show and self._show.running:
                return True
            try:
                self._validate_gain(gain)
                if self._show and self._show.thread and self._show.thread.is_alive():
                    raise RuntimeError(f"{self.name} is still stopping")
                if len(interval) != 2 or interval[0] < 0 or interval[1] < interval[0]:
                    raise ValueError("Interval must be a nonnegative (minimum, maximum) pair")
                candidate = self.show_factory(channel or self.name, gain=gain,
                    quips=self.quips if quips is None else quips, background=background,
                    background_channel=background_channel, background_gain=background_gain,
                    interval=interval, once=once, enabled=lambda: house.systemState == "ONLINE",
                    controller=self._hardware(), finish_state=self._finish_state)
                candidate.start()
                self._show, self._mode, self._error = candidate, "generic", None
                log_event(f"[{self.name}] Started on {candidate.channel}")
                return True
            except Exception as error:
                self._error = str(error)
                log_event(f"[{self.name}] Start failed: {error}")
                return False

    def stop(self):
        """Stop audio/motion and park; retain off heartbeats."""
        with self._lock:
            self._idle_enabled = False
            if self._show:
                self._show.stop()
            if self._controller:
                self._controller.set_state("off")
            self._mode = "off"

    def stop_talking(self):
        """Cancel this character's speech and close its mouth, preserving idle."""
        with self._lock:
            if self._show:
                self._show.stop(park=False)
                if self._show.thread and self._show.thread.is_alive():
                    self._error = "Speech is still stopping"
                    return False
            if self._controller:
                self._controller.set_state(self._finish_state())
            self._mode = "idle" if self._idle_enabled else "off"
            return True

    def start_idle(self, *, neck_min=None, neck_max=None):
        """Enable persistent idle motion without starting audio or needing quips.

        During a quip only the body's idle setting changes; the mouth/audio
        continue uninterrupted. Optional neck_min/neck_max are servo degrees;
        omitted endpoints use the character's normal idle range. Calling with
        no limits restores that range. Limits also apply while talking.
        """
        ranges = {}
        if neck_min is not None or neck_max is not None:
            defaults = getattr(self.controller_factory, "idle_neck_range", None)
            if defaults is None:
                raise ValueError(f"{self.name} does not have a servo neck idle range")
            low = defaults[0] if neck_min is None else neck_min
            high = defaults[1] if neck_max is None else neck_max
            limit = self.controller_factory.output_limits["neck"]
            if (type(low) is not int or type(high) is not int
                    or not limit[0] <= low <= high <= limit[1]):
                raise ValueError(f"Neck idle limits must be integer degrees with {limit[0]} <= neck_min <= neck_max <= {limit[1]}")
            ranges["neck"] = (low, high)
        with self._lock:
            if not self._online():
                return False
            controller = self._hardware()
            self._idle_enabled = True
            controller.set_idle_motion(True, ranges=ranges)
            if not (self._show and self._show.running):
                if self._show and self._show.thread and self._show.thread.is_alive():
                    self._error = "Show is still stopping"
                    self._idle_enabled = False
                    return False
                controller.set_state("standby")
                self._mode = "idle"
            controller.start()
            self._error = None
            return True

    def stop_idle(self):
        """Disable idle movement without cancelling an in-progress quip."""
        with self._lock:
            self._idle_enabled = False
            if self._controller:
                self._controller.set_idle_motion(False)
                if not (self._show and self._show.running):
                    self._controller.set_state("off")
                    self._mode = "off"

    def idle(self, enabled=True):
        """Convenience alias: idle() enables; idle(False) disables."""
        if type(enabled) is not bool:
            raise ValueError("Idle enabled must be True or False")
        if enabled:
            return self.start_idle()
        self.stop_idle()
        return True

    def talk(self, quip=None, channel=None, *, gain=None, **settings):
        """Play one quip, returning to idle if enabled, otherwise parking.

        gain uses play_audio semantics (None = configured route gain; values
        above 1 amplify). This call is nonblocking. quip=None picks randomly;
        filenames resolve inside this character's Quips directory.
        """
        self._validate_gain(gain)
        with self._lock:
            if not self._online():
                return False
            if self._show:
                # Preserve idle ownership while replacing only this character's audio.
                self._show.stop(park=False)
            if quip is not None:
                settings["quips"] = self.quips / Path(quip)
            return self.start(channel, gain=gain, once=True, **settings)

    def pose(self, *, ramp_ms=0, **outputs):
        """Switch to manual mode, holding outputs without random movement.

        Returns True when the pose is handed to the shared worker; this does
        not promise delivery. status() reports link/errors. A lost connection
        parks the node; old manual poses are discarded on reconnect.
        """
        limits = self.controller_factory.output_limits
        if type(ramp_ms) is not int or not 0 <= ramp_ms <= 30000:
            raise ValueError("ramp_ms must be an integer in 0..30000")
        for key, value in outputs.items():
            if key not in limits:
                raise ValueError(f"{self.name} has no {key} output")
            limit = limits[key]
            if limit is bool:
                if type(value) is not bool:
                    raise ValueError(f"{key} requires True or False")
            elif type(value) is not int or not limit[0] <= value <= limit[1]:
                raise ValueError(f"{key} requires an integer angle in {limit[0]}..{limit[1]}")
        with self._lock:
            if not self._online():
                return False
            if self._mode != "manual":
                self.stop()
            if self._show and self._show.thread and self._show.thread.is_alive():
                self._error = "Show is still stopping"
                return False
            controller = self._hardware()
            controller.start()  # Parked until the first pose is accepted.
            if not controller.connected.wait(2.0) or house.systemState != "ONLINE":
                self._error = "Hardware link unavailable"
                controller.set_state("off")
                return False
            controller.set_outputs(ramp_ms=ramp_ms, **outputs)
            self._mode, self._error = "manual", None
            return True

    def neck(self, value, *, ramp_ms=0):
        """George: servo degrees (0..180). Pedro: digital True/False."""
        return self.pose(neck=value, ramp_ms=ramp_ms)

    def eyes(self, on):
        return self.pose(eyes=on)

    def status(self):
        # UI polling never waits for a stop/join or asset validation.
        show, controller = self._show, self._controller
        running = bool(show and show.running)
        idle_enabled = self._idle_enabled and house.systemState == "ONLINE"
        return {"running": running, "idle_enabled": idle_enabled,
                "mode": "generic" if running else
                "manual" if controller and controller.manual_pose is not None else
                "idle" if idle_enabled else "off",
                "channel": show.channel if show else self.name,
                "connected": bool(controller and controller.connected.is_set()),
                "error": self._error or (show.last_error if show else None) or
                         (controller.last_error if controller else None)}


class Pedro(Animatronic):
    def wings(self, angle, *, ramp_ms=0):
        return self.pose(wings=angle, ramp_ms=ramp_ms)

    def beak(self, angle, *, ramp_ms=0):
        return self.pose(beak=angle, ramp_ms=ramp_ms)

    mouth = beak


class George(Animatronic):
    def mouth(self, angle, *, ramp_ms=0):
        return self.pose(mouth=angle, ramp_ms=ramp_ms)


pedro = Pedro("Pedro", PedroShow, PedroController)
george = George("George", GeorgeShow, GeorgeController)


def stop_all():
    pedro.stop()
    george.stop()


# Named functions keep the current UI/house controls simple.
start_pedro, stop_pedro, pedro_status = pedro.start, pedro.stop, pedro.status
start_george, stop_george, george_status = george.start, george.stop, george.status
