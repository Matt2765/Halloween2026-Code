"""Pedro-only replacement for PedroWallace v3; use the existing ESP-NOW bridge.

Run `python MainCode/pedro.py --help`. No serial, audio, or hardware opens on import.
Do not run a second standalone monitor on the same COM port as MainCode/main.py.
Inside the main app, use control.pedro_service.start_pedro/stop_pedro; these
reuse its initialized RSM and audio mixers.
"""
from __future__ import annotations

import argparse
import multiprocessing
from pathlib import Path
import random
import threading
import time

from control import remote_sensor_monitor as rsm

ASSETS = Path(__file__).resolve().parents[2] / "Assets"
BEAK_TIMES = (0.2, 0.2, 0.1, 0.1, 0.4, 0.3)
WINGS_REST, WINGS_OPEN = 5, 115
BEAK_CLOSED, BEAK_OPEN = 55, 10
HEARTBEAT_SECONDS = 0.5
# Stay below the ESP's 2.5-second hardware lease, while tolerating missed ACKs.
LINK_LOSS_GRACE_SECONDS = 2.0
HARD_COMMAND_FAILURES = frozenset({
    "invalid_command", "invalid_pedro_pose", "out_of_range", "not_pedro",
    "id_conflict", "device_restarted", "unavailable_conflict_or_restarted",
    "invalid_request_or_host_session", "protocol_error",
})
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


class PedroController:
    """Use with the application's existing RSM, or let the CLI initialize RSM.

    One worker sends atomic snapshots. It waits for each delivery result, so
    concurrent wing/eye/beak changes cannot supersede one another as partial poses.
    Missed ACKs and brief availability gaps preserve the current quip for up to
    two seconds since the last acceptance. Reconnect/reboot starts fresh in
    standby. `off` keeps the link alive for a solid red indicator.
    """
    def __init__(self, device_id="PEDRO1", *, simulate=False, off=False, transport=rsm):
        self.device_id, self.simulate, self.transport = device_id, simulate, transport
        self.stop_event, self.connected = threading.Event(), threading.Event()
        self.lock = threading.Lock()
        self.state = "off" if off else "standby"
        self.thread = None
        self.last_error = None
        self.link_epoch = 0

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="Pedro hardware", daemon=True)
        self.thread.start()

    def set_state(self, state):
        if state not in rsm.PEDRO_STATES:
            raise ValueError("Pedro state must be off, standby, or active")
        with self.lock:
            self.state = state

    def _reset(self, motion, now):
        self.connected.clear()
        with self.lock:
            self.link_epoch += 1
            if self.state == "active":
                self.state = "standby"
        motion.reset(now)

    def _run(self):
        motion = Motion(time.monotonic())
        key, pending, sent_pose = None, None, None
        last_sent = last_accepted = 0.0
        try:
            while not self.stop_event.is_set():
                now = time.monotonic()
                if not self.simulate:
                    record = self.transport.get(self.device_id)
                    connection = self.transport.get("_connection") or {}
                    available = (self.transport.healthy()["connected"] and record and record["kind"] == "pedro"
                                 and self.transport.device_status(self.device_id)["available"])
                    new_key = ((connection["host"], record["session"])
                               if connection.get("host") and record and record["kind"] == "pedro" else None)
                    if not available:
                        fatal_device = record and (record.get("conflict") or record["kind"] != "pedro")
                        if key is not None and (fatal_device or (new_key is not None and new_key != key) or not self.connected.is_set()
                                                or now - last_accepted >= LINK_LOSS_GRACE_SECONDS):
                            self._reset(motion, now)
                            key, pending, sent_pose = None, None, None
                        self.stop_event.wait(0.05)
                        continue
                    if new_key != key:
                        self._reset(motion, now)
                        key, pending, sent_pose = new_key, None, None
                    if key is None:
                        self.stop_event.wait(0.05)
                        continue
                    if pending:
                        result = self.transport.command_status(pending) or {}
                        status = result.get("status")
                        if status in ("queued", "pending"):
                            if self.connected.is_set() and now - last_accepted >= LINK_LOSS_GRACE_SECONDS:
                                self._reset(motion, now)
                                sent_pose = None
                            self.stop_event.wait(0.02)
                            continue
                        pending = None
                        if status == "accepted":
                            last_accepted = now
                            self.connected.set()
                        else:
                            self.last_error = result.get("reason", "missing delivery result")
                            print(f"Pedro command {status}: {self.last_error}")
                            if self.last_error in HARD_COMMAND_FAILURES:
                                self._reset(motion, now)
                            # Send a fresh current pose, never replay the failed one.
                            sent_pose = None
                            self.stop_event.wait(0.1)
                    if self.connected.is_set() and now - last_accepted >= LINK_LOSS_GRACE_SECONDS:
                        self._reset(motion, now)
                        sent_pose = None
                with self.lock:
                    pose = motion.pose(self.state, now)
                if pose != sent_pose or now - last_sent >= HEARTBEAT_SECONDS:
                    if self.simulate:
                        print(f"[Pedro simulation] {pose}")
                        self.connected.set()
                    else:
                        pending = self.transport.pedro(self.device_id, **pose)
                    sent_pose, last_sent = pose, now
                self.stop_event.wait(0.02)
        except Exception as error:
            self.last_error = str(error)
            print(f"Pedro controller stopped: {error}")
        finally:
            self.connected.clear()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
        if not self.simulate and self.thread:
            # One final park, then let the ESP lease expire if the process exits.
            cid = self.transport.pedro(self.device_id, state="off")
            deadline = time.monotonic() + 0.8
            while time.monotonic() < deadline:
                result = self.transport.command_status(cid) or {}
                if result.get("status") not in ("queued", "pending"):
                    break
                time.sleep(0.02)


def stop_player(handle):
    if handle is not None and not handle.done.is_set():
        handle.stop()


def start_player(channel, path, *, background=False, gain=None):
    from control.audio_manager import play_audio
    # Independent manual control may run while HouseActive is False. System
    # shutdown still cancels these voices through honor_shutdown and the service.
    return play_audio(channel, str(path), gain=gain, looping=background,
                      threaded=True, honor_breakcheck=False, deduplicate=False)


def play_quip(controller, channel, path, *, gain=None, stop_event=None, enabled=lambda: True):
    handle = None
    epoch = controller.link_epoch
    try:
        handle = start_player(channel, path, gain=gain)
        if handle is None:
            raise RuntimeError("Audio manager returned no playback handle")
        if handle.cancelled:
            return False
        controller.set_state("active")
        while not handle.done.wait(0.02):
            if (controller.stop_event.is_set() or (stop_event and stop_event.is_set())
                    or not enabled() or not controller.connected.is_set()
                    or controller.link_epoch != epoch):
                return False
        return not handle.cancelled
    finally:
        stop_player(handle)
        controller.set_state("standby")


def choose_quip(files, previous, rng=random):
    choices = [path for path in files if path != previous] or files
    return rng.choice(choices)


class PedroShow:
    """Restartable show using the shared RSM and audio manager in this process."""
    def __init__(self, channel="Pedro", *, gain=None,
                 quips=ASSETS / "SoundDir" / "Quips", background=None,
                 background_channel=None, background_gain=0.89, interval=(10, 15),
                 device_id="PEDRO1", simulate=False, once=False,
                 enabled=lambda: True, controller=None):
        self.channel, self.gain = channel, gain
        self.quips = Path(quips)
        self.background_path = Path(background) if background else None
        self.background_channel = background_channel or channel
        self.background_gain, self.interval = background_gain, interval
        self.controller = controller or PedroController(device_id, simulate=simulate, off=True)
        self.once, self.enabled = once, enabled
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.thread = None
        self.background = None
        self.last_error = None

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive() and not self.stop_event.is_set())

    def start(self):
        with self.lock:
            if self.running:
                return False
            if self.thread and self.thread.is_alive():
                raise RuntimeError("Pedro is still stopping; wait before restarting")
            files = sorted(path for path in self.quips.glob("Quip*")
                           if path.suffix.lower() in (".mp3", ".wav", ".ogg", ".flac"))
            if not files:
                raise FileNotFoundError(f"No Quip audio files in {self.quips}")
            from control.audio_manager import _resolve_named_target
            for channel in (self.channel, self.background_channel):
                if channel.lower() != "all":
                    _resolve_named_target(channel)  # Fail before starting hardware/audio.
            self.stop_event.clear()
            self.last_error = None
            self.controller.set_state("standby")
            self.controller.start()
            self.thread = threading.Thread(target=self._run, args=(files,), name="Pedro show", daemon=True)
            self.thread.start()
            return True

    def _run(self, files):
        from utils.tools import log_event
        previous = None
        try:
            while not self.stop_event.is_set() and self.enabled():
                if not self.controller.connected.wait(0.1):
                    stop_player(self.background)
                    self.background = None
                    if self.controller.thread and not self.controller.thread.is_alive():
                        raise RuntimeError(self.controller.last_error or "Pedro hardware worker exited")
                    continue
                if self.stop_event.is_set() or not self.enabled():
                    break
                if self.background_path and self.background is None:
                    self.background = start_player(self.background_channel, self.background_path,
                                                   background=True, gain=self.background_gain)
                path = choose_quip(files, previous)
                log_event(f"[Pedro] Playing {path.name} on {self.channel}")
                completed = play_quip(self.controller, self.channel, path, gain=self.gain,
                                      stop_event=self.stop_event, enabled=self.enabled)
                previous = path
                if not completed:
                    stop_player(self.background)
                    self.background = None
                if self.once:
                    break
                # Keep a gap after interruptions too, preventing a new-line storm.
                deadline = time.monotonic() + random.uniform(*self.interval)
                while time.monotonic() < deadline and self.enabled():
                    if self.stop_event.wait(0.05):
                        break
        except Exception as error:
            self.last_error = str(error)
            log_event(f"[Pedro] Show stopped: {error}")
        finally:
            stop_player(self.background)
            self.background = None
            self.controller.set_state("off")
            log_event("[Pedro] Stopped and parked")

    def stop(self):
        with self.lock:
            self.stop_event.set()
            self.controller.set_state("off")
            stop_player(self.background)
            if self.thread and self.thread is not threading.current_thread():
                self.thread.join(timeout=3)
            self.controller.set_state("off")

    def close(self):
        self.stop()
        self.controller.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", default="COM6", help="Existing USB transceiver, NOT Pedro's USB port")
    parser.add_argument("--device-id", default="PEDRO1")
    parser.add_argument("--quips", type=Path, default=ASSETS / "SoundDir" / "Quips")
    parser.add_argument("--channel", default="Pedro", help="Named audio-manager route, as in play_audio")
    parser.add_argument("--gain", type=float, default=None, help="Defaults to the named channel's configured gain")
    parser.add_argument("--background", type=Path, default=None, help="Optional ambience file")
    parser.add_argument("--background-channel", default=None, help="Defaults to the voice channel")
    parser.add_argument("--no-background", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--off", action="store_true", help="Keep connected and parked: solid red")
    mode.add_argument("--standby", action="store_true", help="Idle movements, no quips: solid green")
    parser.add_argument("--simulate", action="store_true", help="Print poses without opening serial")
    parser.add_argument("--once", action="store_true", help="Play one random quip, then park and exit")
    args = parser.parse_args(argv)
    if not rsm._valid_id(args.device_id):
        parser.error("Invalid device ID; use 1..15 ASCII letters, digits, '_' or '-'")
    controller = PedroController(args.device_id, simulate=args.simulate, off=args.off)
    show = None
    try:
        if not args.simulate:
            rsm.init(port=args.port, baud=rsm.DEFAULT_BAUD)
        if args.off or args.standby:
            controller.start()
            while controller.thread.is_alive():
                time.sleep(0.1)
        else:
            from control.audio_manager import initialize_audio
            initialize_audio()
            show = PedroShow(args.channel, gain=args.gain, quips=args.quips,
                             background=None if args.no_background else args.background,
                             background_channel=args.background_channel,
                             once=args.once, controller=controller)
            show.start()
            while show.thread.is_alive():
                time.sleep(0.1)
            if show.last_error:
                raise RuntimeError(show.last_error)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if show:
                show.close()
            else:
                controller.close()
        finally:
            if not args.simulate:
                rsm.stop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
