"""Shared main-system animatronic API; reuses the existing RSM and mixers.

pedro.start() / george.start(): generic quips, mouth motion, idle movement.
george.neck(90): switch to manual control and hold that servo angle.
"""
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

    def _online(self):
        if house.systemState != "ONLINE":
            log_event(f"[{self.name}] Cannot start while the main system is offline")
            return False
        return True

    def _hardware(self):
        if self._controller is None:
            self._controller = self.controller_factory(off=True)
        return self._controller

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
                if self._show and self._show.thread and self._show.thread.is_alive():
                    raise RuntimeError(f"{self.name} is still stopping")
                if len(interval) != 2 or interval[0] < 0 or interval[1] < interval[0]:
                    raise ValueError("Interval must be a nonnegative (minimum, maximum) pair")
                candidate = self.show_factory(channel or self.name, gain=gain,
                    quips=self.quips if quips is None else quips, background=background,
                    background_channel=background_channel, background_gain=background_gain,
                    interval=interval, once=once, enabled=lambda: house.systemState == "ONLINE",
                    controller=self._hardware())
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
            if self._show:
                self._show.stop()
            if self._controller:
                self._controller.set_state("off")
            self._mode = "off"

    def talk(self, quip=None, channel=None, **settings):
        """Play one quip with automatic motion, then park (nonblocking).

        quip=None chooses randomly; a filename resolves inside this character's
        Quips directory. An absolute audio path is also accepted.
        """
        with self._lock:
            self.stop()
            if quip is not None:
                settings["quips"] = self.quips / Path(quip)
            return self.start(channel, once=True, **settings)

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
        """George: servo degrees (0..115). Pedro: digital True/False."""
        return self.pose(neck=value, ramp_ms=ramp_ms)

    def eyes(self, on):
        return self.pose(eyes=on)

    def status(self):
        # UI polling never waits for a stop/join or asset validation.
        show, controller = self._show, self._controller
        running = bool(show and show.running)
        return {"running": running, "mode": "generic" if running else
                "manual" if controller and controller.manual_pose is not None else "off",
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
