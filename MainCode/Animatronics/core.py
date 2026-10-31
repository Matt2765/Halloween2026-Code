"""Shared show and atomic-pose worker for wireless animatronics.

Importing this module never opens hardware or audio.
"""
import argparse
from pathlib import Path
import random
import threading
import time
from control import remote_sensor_monitor as rsm

HEARTBEAT_SECONDS = 0.5
LINK_LOSS_GRACE_SECONDS = 2.0
HARD_COMMAND_FAILURES = frozenset({
    "invalid_command", "invalid_pedro_pose", "invalid_george_pose", "out_of_range", "not_pedro", "not_george",
    "id_conflict", "device_restarted", "unavailable_conflict_or_restarted",
    "invalid_request_or_host_session", "protocol_error",
})

class AnimatronicController:
    """Use with the application's existing RSM, or let the CLI initialize RSM.

    One worker sends atomic snapshots. It waits for each delivery result, so
    concurrent wing/eye/beak changes cannot supersede one another as partial poses.
    Missed ACKs and brief availability gaps preserve the current quip for up to
    two seconds since the last acceptance. Reconnect/reboot starts fresh in
    standby. `off` keeps the link alive while parked.
    """
    def __init__(self, device_id, *, simulate=False, off=False, transport=rsm):
        self.device_id, self.simulate, self.transport = device_id, simulate, transport
        self.stop_event, self.connected = threading.Event(), threading.Event()
        self.lock = threading.Lock()
        self.state = "off" if off else "standby"
        self.thread = None
        self.manual_pose = None
        self.idle_motion = True
        self.idle_ranges = {}
        self._speech_handle = None
        self._speech_peak = 0.03
        self._mouth_opening = 0.0
        self._mouth_changed_at = float("-inf")
        self.last_error = None
        self.link_epoch = 0

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name=f"{self.name} hardware", daemon=True)
        self.thread.start()

    def set_state(self, state):
        if state not in ("off", "standby", "active"):
            raise ValueError("State must be off, standby, or active")
        with self.lock:
            self.state = state
            self.manual_pose = None
            if state != "active":
                self._speech_handle = None
                self._mouth_opening = 0.0

    def set_speech_handle(self, handle):
        with self.lock:
            self._speech_handle = handle
            self._speech_peak = 0.03
            self._mouth_opening = 0.0
            self._mouth_changed_at = float("-inf")

    def _audio_mouth(self, now):
        level = self._speech_handle.audio_level(now)
        self._speech_peak = max(level, self._speech_peak * 0.995, 0.02)
        open_gate = max(0.006, self._speech_peak * self.speech_open_ratio)
        close_gate = max(0.004, self._speech_peak * self.speech_close_ratio)
        elapsed = now - self._mouth_changed_at
        was_open = bool(self._mouth_opening)
        is_open = was_open
        if level < 0.004:
            is_open = False  # Silence/end closes immediately, without a release tail.
        elif was_open:
            if elapsed >= self.speech_max_open or (elapsed >= self.speech_min_open and level < close_gate):
                is_open = False
        elif elapsed >= self.speech_min_closed and level >= open_gate:
            is_open = True
        if is_open != was_open:
            self._mouth_changed_at = now
        self._mouth_opening = float(is_open)
        mouth = "beak" if "beak" in self.rest_pose else "mouth"
        closed = self.rest_pose[mouth]
        low, high = self.output_limits[mouth]
        opened = low if closed == high else high
        return mouth, opened if is_open else closed

    def set_idle_motion(self, enabled, *, ranges=None):
        """Gate non-mouth animation without changing speech state or manual poses."""
        with self.lock:
            self.idle_motion = bool(enabled)
            if ranges is not None:
                self.idle_ranges = dict(ranges)

    def set_outputs(self, **outputs):
        """Hold a complete manual pose; callers validate character-specific limits."""
        with self.lock:
            pose = dict(self.manual_pose) if self.manual_pose is not None else dict(self.rest_pose)
            pose.update(outputs)
            pose["state"] = "standby"
            self.manual_pose = pose
            self.state = "standby"
        self.start()

    def _reset(self, motion, now):
        self.connected.clear()
        with self.lock:
            self.link_epoch += 1
            self._speech_handle = None
            if self.manual_pose is not None:
                self.state = "off"
            self.manual_pose = None
            if self.state == "active":
                self.state = "off" if getattr(self, "finish_audio_on_link_loss", False) else "standby"
        motion.reset(now)

    def _run(self):
        motion = self.motion_factory(time.monotonic())
        key, pending, sent_pose = None, None, None
        last_sent = last_accepted = 0.0
        try:
            while not self.stop_event.is_set():
                now = time.monotonic()
                if not self.simulate:
                    record = self.transport.get(self.device_id)
                    connection = self.transport.get("_connection") or {}
                    available = (self.transport.healthy()["connected"] and record and record["kind"] == self.kind
                                 and self.transport.device_status(self.device_id)["available"])
                    new_key = ((connection["host"], record["session"])
                               if connection.get("host") and record and record["kind"] == self.kind else None)
                    if not available:
                        fatal_device = record and (record.get("conflict") or record["kind"] != self.kind)
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
                            print(f"{self.name} command {status}: {self.last_error}")
                            if self.last_error in HARD_COMMAND_FAILURES:
                                self._reset(motion, now)
                            # Send a fresh current pose, never replay the failed one.
                            sent_pose = None
                            self.stop_event.wait(0.1)
                    if self.connected.is_set() and now - last_accepted >= LINK_LOSS_GRACE_SECONDS:
                        self._reset(motion, now)
                        sent_pose = None
                with self.lock:
                    if self.manual_pose is not None:
                        pose = dict(self.manual_pose)
                    else:
                        pose = motion.pose(self.state, now)
                        if self.state != "off":
                            for output, (low, high) in self.idle_ranges.items():
                                pose[output] = max(low, min(high, pose[output]))
                        if self.state == "active" and self._speech_handle is not None and callable(getattr(self._speech_handle, "audio_level", None)):
                            mouth, angle = self._audio_mouth(now)
                            pose[mouth] = angle
                        if not self.idle_motion:
                            mouth = "beak" if "beak" in self.rest_pose else "mouth"
                            pose.update({key: value for key, value in self.rest_pose.items() if key != mouth})
                if pose != sent_pose or now - last_sent >= HEARTBEAT_SECONDS:
                    if self.simulate:
                        print(f"[{self.name} simulation] {pose}")
                        self.connected.set()
                    else:
                        pending = getattr(self.transport, self.kind)(self.device_id, **pose)
                    sent_pose, last_sent = pose, now
                self.stop_event.wait(0.02)
        except Exception as error:
            self.last_error = str(error)
            print(f"{self.name} controller stopped: {error}")
        finally:
            self.connected.clear()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
        if not self.simulate and self.thread:
            # One final park, then let the ESP lease expire if the process exits.
            cid = getattr(self.transport, self.kind)(self.device_id, state="off")
            deadline = time.monotonic() + 0.8
            while time.monotonic() < deadline:
                result = self.transport.command_status(cid) or {}
                if result.get("status") not in ("queued", "pending"):
                    break
                time.sleep(0.02)


def stop_player(handle):
    if handle is not None and not handle.done.is_set():
        handle.stop()


def start_player(channel, path, *, background=False, gain=None, track_envelope=False):
    from control.audio_manager import play_audio
    # Independent manual control may run while HouseActive is False. System
    # shutdown still cancels these voices through honor_shutdown and the service.
    return play_audio(channel, str(path), gain=gain, looping=background,
                      threaded=True, honor_breakcheck=False, deduplicate=False, track_envelope=track_envelope)


def play_quip(controller, channel, path, *, gain=None, stop_event=None, enabled=lambda: True):
    handle = None
    epoch = controller.link_epoch
    keep_audio = getattr(controller, "finish_audio_on_link_loss", False)
    motion_interrupted = False

    def link_changed():
        return not controller.connected.is_set() or controller.link_epoch != epoch

    def park_motion():
        nonlocal motion_interrupted
        if not motion_interrupted:
            controller.set_state("off")
            motion_interrupted = True
            from utils.tools import log_event
            log_event(f"[{controller.name}] Wireless link changed; finishing current audio with motion parked")

    try:
        metered = getattr(controller, "audio_driven_mouth", False)
        handle = start_player(channel, path, gain=gain, track_envelope=metered)
        if handle is None:
            raise RuntimeError("Audio manager returned no playback handle")
        if handle.cancelled:
            return False
        if link_changed():
            if not keep_audio:
                return False
            park_motion()
        else:
            if metered:
                controller.set_speech_handle(handle)
            controller.set_state("active")
        while not handle.done.wait(0.01) or (metered and callable(getattr(handle, "audible_pending", None)) and handle.audible_pending()):
            if (controller.stop_event.is_set() or (stop_event and stop_event.is_set())
                    or not enabled() or handle.cancelled):
                return False
            if link_changed():
                if not keep_audio:
                    return False
                park_motion()
            if handle.done.is_set():
                time.sleep(0.01)  # Drain scheduled DAC tail without spinning.
        return not handle.cancelled
    finally:
        stop_player(handle)
        controller.set_state("standby")


def choose_quip(files, previous, rng=random):
    choices = [path for path in files if path != previous] or files
    return rng.choice(choices)


class AnimatronicShow:
    """Restartable show using the shared RSM and audio manager in this process."""
    def __init__(self, channel, *, gain=None,
                 quips, background=None,
                 background_channel=None, background_gain=0.89, interval=(10, 15),
                 device_id=None, simulate=False, once=False,
                 enabled=lambda: True, controller=None, finish_state=lambda: "off"):
        self.channel, self.gain = channel, gain
        self.quips = Path(quips)
        self.background_path = Path(background) if background else None
        self.background_channel = background_channel or channel
        self.background_gain, self.interval = background_gain, interval
        self.controller = controller or self.controller_factory(device_id or self.default_device_id, simulate=simulate, off=True)
        self.once, self.enabled = once, enabled
        self.finish_state = finish_state
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
                raise RuntimeError(f"{self.name} is still stopping; wait before restarting")
            paths = [self.quips] if self.quips.is_file() else self.quips.iterdir()
            files = sorted(path for path in paths
                           if path.is_file() and path.suffix.lower() in (".mp3", ".wav", ".ogg", ".flac"))
            if not files:
                raise FileNotFoundError(f"No audio files in {self.quips}")
            from control.audio_manager import _resolve_named_target
            for channel in (self.channel, self.background_channel):
                if channel.lower() != "all":
                    _resolve_named_target(channel)  # Fail before starting hardware/audio.
            self.stop_event.clear()
            self.last_error = None
            self.controller.set_state("standby")
            self.controller.start()
            self.thread = threading.Thread(target=self._run, args=(files,), name=f"{self.name} show", daemon=True)
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
                        raise RuntimeError(self.controller.last_error or f"{self.name} hardware worker exited")
                    continue
                if self.stop_event.is_set() or not self.enabled():
                    break
                if self.background_path and self.background is None:
                    self.background = start_player(self.background_channel, self.background_path,
                                                   background=True, gain=self.background_gain)
                path = choose_quip(files, previous)
                log_event(f"[{self.name}] Playing {path.name} on {self.channel}")
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
            log_event(f"[{self.name}] Show stopped: {error}")
        finally:
            stop_player(self.background)
            self.background = None
            final_state = self.finish_state() if self.enabled() else "off"
            self.controller.set_state(final_state)
            log_event(f"[{self.name}] " + ("Returned to idle" if final_state == "standby" else "Stopped and parked"))

    def stop(self, *, park=True):
        with self.lock:
            self.stop_event.set()
            if park:
                self.controller.set_state("off")
            stop_player(self.background)
            if self.thread and self.thread is not threading.current_thread():
                self.thread.join(timeout=3)
            if park:
                self.controller.set_state("off")

    def close(self):
        self.stop()
        self.controller.close()



def run_cli(controller_factory, show_factory, *, name, device_id, quips, argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", default="COM6", help="Existing USB transceiver, NOT the animatronic node USB port")
    parser.add_argument("--device-id", default=device_id)
    parser.add_argument("--quips", type=Path, default=quips)
    parser.add_argument("--channel", default=name, help="Named audio-manager route, as in play_audio")
    parser.add_argument("--gain", type=float, default=None, help="Defaults to the named channel's configured gain")
    parser.add_argument("--background", type=Path, default=None, help="Optional ambience file")
    parser.add_argument("--background-channel", default=None, help="Defaults to the voice channel")
    parser.add_argument("--no-background", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--off", action="store_true", help="Keep connected and parked")
    mode.add_argument("--standby", action="store_true", help="Idle movements, no quips")
    parser.add_argument("--simulate", action="store_true", help="Print poses without opening serial")
    parser.add_argument("--once", action="store_true", help="Play one random quip, then park and exit")
    args = parser.parse_args(argv)
    if not rsm._valid_id(args.device_id):
        parser.error("Invalid device ID; use 1..15 ASCII letters, digits, '_' or '-'")
    controller = controller_factory(args.device_id, simulate=args.simulate, off=args.off)
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
            show = show_factory(args.channel, gain=args.gain, quips=args.quips,
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

