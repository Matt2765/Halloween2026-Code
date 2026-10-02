"""KRIDA eight-channel UNO/Nano control. Existing calls default to channel 1."""
from __future__ import annotations
import math
import random
import threading
import time
from collections import deque
import serial
from utils.tools import BreakCheck, log_event

PORT = "COM7"
BAUD = 115200
TIMEOUT = 0.10
CHANNELS = 8
_BOOT_WAIT_S = 2.0
_WRITE_RATE_HZ = 30.0  # Total commands/second across all channels.
_MIN_WRITE_INTERVAL = 1.0 / _WRITE_RATE_HZ
_KEEPALIVE_S = 0.5
_ACK_TIMEOUT_S = 0.25
_ACK_PACING = True
_RAMP_HZ = 30.0
_RAMP_DT = 1.0 / _RAMP_HZ
_ser = None
_simulated = True
_transport_failed = False
_lock = threading.RLock()  # Serial transaction, rate limiting and cache updates.
_last_send_ts = 0.0
_current_pct = [0.0] * CHANNELS
_last_sent_int = [None] * CHANNELS
_last_send_ok_ts = [0.0] * CHANNELS
_rx_thread = None
_rx_stop_evt = threading.Event()
_board_reset = threading.Event()
_ack_cv = threading.Condition()
_expected_reply = None
_reply = None
_ack_lines = deque(maxlen=256)
_global_stop_evt = threading.Event()
_effects_lock = threading.Lock()
_effects = {}  # channel -> (stop event, thread)
_wire_debug = False


def _channel_index(channel):
    if isinstance(channel, bool) or not isinstance(channel, int) or not 1 <= channel <= CHANNELS:
        raise ValueError("channel must be an integer from 1 to 8")
    return channel - 1


def _percentage(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("brightness must be finite")
    return max(0.0, min(100.0, value))


def set_write_rate_hz(hz):
    global _WRITE_RATE_HZ, _MIN_WRITE_INTERVAL
    _WRITE_RATE_HZ = max(1.0, float(hz))
    _MIN_WRITE_INTERVAL = 1.0 / _WRITE_RATE_HZ


def set_keepalive(seconds):
    global _KEEPALIVE_S
    _KEEPALIVE_S = max(0.05, float(seconds))


def set_ack_timeout(seconds):
    global _ACK_TIMEOUT_S
    _ACK_TIMEOUT_S = max(0.05, float(seconds))


def set_ack_pacing(on=True):
    global _ACK_PACING
    _ACK_PACING = bool(on)


def set_ramp_hz(hz):
    global _RAMP_HZ, _RAMP_DT
    _RAMP_HZ = max(5.0, float(hz))
    _RAMP_DT = 1.0 / _RAMP_HZ


def enable_wire_debug(on=True):
    global _wire_debug
    _wire_debug = bool(on)


def _rx_loop():
    global _reply, _transport_failed
    while not _rx_stop_evt.is_set():
        try:
            line = _ser.readline().decode("ascii", "replace").strip()
        except Exception:
            if not _rx_stop_evt.is_set():
                _transport_failed = True
                with _ack_cv:
                    _reply = "ERR serial read failed"
                    _ack_cv.notify_all()
            return
        if not line:
            continue
        _ack_lines.append(line)
        if line.startswith("KRIDA 8CH TEST READY"):
            _board_reset.set()
        with _ack_cv:
            if line == _expected_reply or line.startswith("ERR"):
                _reply = line
                _ack_cv.notify_all()


def _command(line, expected, *, wait=None, timeout=None):
    """One complete transaction; the RX thread never takes _lock."""
    global _last_send_ts, _expected_reply, _reply, _transport_failed
    wait = _ACK_PACING if wait is None else wait
    timeout = _ACK_TIMEOUT_S if timeout is None else timeout
    with _lock:
        if _transport_failed:
            return False
        remaining = _MIN_WRITE_INTERVAL - (time.monotonic() - _last_send_ts)
        if remaining > 0:
            time.sleep(remaining)
        _last_send_ts = time.monotonic()
        if _simulated:
            if _wire_debug:
                log_event(f"[dimmer_controller] (Simulated) {line}")
            return True
        if _ser is None:
            return False
        with _ack_cv:
            _expected_reply, _reply = expected, None
        data = (line + "\n").encode("ascii")
        started = time.monotonic()
        try:
            if _ser.write(data) != len(data):
                raise IOError("incomplete serial command")
        except Exception as exc:
            # Don't append another command to a potentially truncated line.
            _transport_failed = True
            log_event(f"[dimmer_controller] Serial write failed; reinitialize: {exc}")
            return False
        ok = True
        if wait:
            with _ack_cv:
                received = _ack_cv.wait_for(lambda: _reply is not None, timeout)
                ok = received and _reply == expected
        if _wire_debug:
            log_event(f"[dimmer_controller] {line}: {'OK' if ok else 'NO ACK'} "
                      f"{(time.monotonic() - started) * 1000:.1f} ms")
        return ok


def init(port: str | None = None):
    """Verify updated firmware and leave all channels OFF. True=hardware, False=simulation."""
    global _ser, _simulated, PORT, _rx_thread, _transport_failed, _last_send_ts
    close()
    if port:
        PORT = port
    _transport_failed = False
    _last_send_ts = 0.0
    _last_sent_int[:] = [None] * CHANNELS
    _current_pct[:] = [0.0] * CHANNELS
    _last_send_ok_ts[:] = [0.0] * CHANNELS
    _board_reset.clear()
    _global_stop_evt.clear()
    try:
        _ser = serial.Serial(PORT, BAUD, timeout=TIMEOUT,
                             write_timeout=_ACK_TIMEOUT_S, inter_byte_timeout=0)
        _simulated = False
        time.sleep(_BOOT_WAIT_S)  # Opening serial usually resets UNO/Nano.
        _ser.reset_input_buffer()
        _rx_stop_evt.clear()
        _rx_thread = threading.Thread(target=_rx_loop, name="dimmer-rx", daemon=True)
        _rx_thread.start()
        if not _command("VERSION", "KRIDA8 V1", wait=True, timeout=1.0):
            raise RuntimeError("KRIDA8 V1 not detected; upload the updated UNO/Nano sketch")
        if not all_off():
            raise RuntimeError("firmware did not acknowledge OFF")
        log_event(f"[dimmer_controller] KRIDA 8CH connected on {PORT}; all OFF")
        return True
    except Exception as exc:
        close()
        _transport_failed = False
        log_event(f"[dimmer_controller] Connection failed: {exc}")
        log_event("[dimmer_controller] Running in simulated mode.")
        return False


def close():
    """Stop workers, request all OFF, then release the port."""
    global _ser, _simulated, _rx_thread
    stop_flicker(join=True)
    if _ser is not None and _rx_thread is not None and _rx_thread.is_alive():
        if not _command("OFF", "OK OFF", wait=True):
            log_event("[dimmer_controller] OFF was not acknowledged during close")
        else:
            _current_pct[:] = [0.0] * CHANNELS
    _rx_stop_evt.set()
    if _rx_thread is not None:
        _rx_thread.join(timeout=TIMEOUT + 0.5)
    if _ser is not None:
        _ser.close()
    _ser = None
    _rx_thread = None
    _simulated = True
    _last_sent_int[:] = [None] * CHANNELS


def request_stop():
    _global_stop_evt.set()


def clear_stop():
    _global_stop_evt.clear()


def dim(value: float, *, channel: int = 1, force: bool = False) -> bool:
    """Set one channel; False means duplicate or failed command.

    ACK pacing confirms the matching channel/value before caching it. Keepalive
    resends happen on calls to dim(), not in a background heartbeat.
    """
    index = _channel_index(channel)
    pct = _percentage(value)
    value_int = int(round(pct))
    with _lock:
        if _board_reset.is_set():
            _last_sent_int[:] = [None] * CHANNELS
            _board_reset.clear()
        stale = time.monotonic() - _last_send_ok_ts[index] >= _KEEPALIVE_S
        if not force and not stale and _last_sent_int[index] == value_int:
            _current_pct[index] = pct
            return False
        if not _command(f"SET {channel} {value_int}", f"ACK SET {channel} {value_int}"):
            return False
        _current_pct[index] = pct
        _last_sent_int[index] = value_int
        _last_send_ok_ts[index] = time.monotonic()
        return True


def get_current_pct(channel: int = 1) -> float:
    """Last commanded percentage, not measured bulb output."""
    with _lock:
        return _current_pct[_channel_index(channel)]


def all_off() -> bool:
    """Stop all Python effects and Arduino demos, then clear all eight outputs."""
    stop_flicker(join=True)
    with _lock:
        if not _command("OFF", "OK OFF", wait=True):
            return False
        _current_pct[:] = [0.0] * CHANNELS
        _last_sent_int[:] = [0] * CHANNELS
        _last_send_ok_ts[:] = [time.monotonic()] * CHANNELS
        return True


def stop_flicker(join: bool = False, timeout: float = 0.5, *, channel: int | None = None):
    """Stop one effect, or all when channel is omitted; hold the current levels."""
    if channel is not None:
        _channel_index(channel)
    with _effects_lock:
        selected = [(ch, item) for ch, item in _effects.items()
                    if channel is None or ch == channel]
        for _, (stop, _) in selected:
            stop.set()
    if join:
        for _, (_, worker) in selected:
            if worker is not threading.current_thread():
                worker.join(timeout=timeout)


def _should_stop_effect(local_stop):
    return local_stop.is_set() or _global_stop_evt.is_set() or BreakCheck()


def _ramp(from_val, to_val, duration, local_stop, ease=True, *, channel=1):
    start = time.monotonic()
    while not _should_stop_effect(local_stop):
        fraction = min(1.0, (time.monotonic() - start) / duration) if duration > 0 else 1.0
        weight = 0.5 - 0.5 * math.cos(math.pi * fraction) if ease else fraction
        # Recheck after acquiring the serial lock so stopped workers cannot
        # send another level after all_off() clears the outputs.
        with _lock:
            if _should_stop_effect(local_stop):
                return
            dim(from_val + (to_val - from_val) * weight, channel=channel)
        if fraction >= 1:
            return
        local_stop.wait(_RAMP_DT)


def dimmer_flicker(duration: float, min_intensity: float, max_intensity: float,
                   flicker_length_min: float, flicker_length_max: float,
                   threaded: bool = False, ease: bool = True, *, channel: int = 1):
    """Smooth randomized flicker; separate channels can run concurrently."""
    _channel_index(channel)
    low, high = sorted((_percentage(min_intensity), _percentage(max_intensity)))
    seg_min, seg_max = sorted((max(0.03, float(flicker_length_min)),
                               max(0.03, float(flicker_length_max))))
    stop_flicker(join=True, channel=channel)
    local_stop = threading.Event()

    def run():
        deadline = time.monotonic() + max(0.0, duration)
        try:
            while not _should_stop_effect(local_stop):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                _ramp(get_current_pct(channel), random.uniform(low, high),
                      min(remaining, random.uniform(seg_min, seg_max)),
                      local_stop, ease, channel=channel)
        finally:
            with _effects_lock:
                if _effects.get(channel, (None,))[0] is local_stop:
                    _effects.pop(channel, None)

    worker = threading.Thread(target=run, name=f"dimmer-flicker-{channel}", daemon=True) if threaded else threading.current_thread()
    with _effects_lock:
        _effects[channel] = (local_stop, worker)
        if threaded:
            worker.start()
    if threaded:
        return worker
    run()


def ack_latency_test(set_value: int = 50, n: int = 30,
                     ack_timeout_s: float | None = None, *, channel: int = 1):
    _channel_index(channel)
    value = int(round(_percentage(set_value)))
    if _simulated or _ser is None:
        log_event("[dimmer_controller] ACK test skipped; no dimmer connected")
        return
    samples = []
    for _ in range(n):
        start = time.monotonic()
        with _lock:
            ok = _command(f"SET {channel} {value}", f"ACK SET {channel} {value}",
                          wait=True, timeout=ack_timeout_s)
            if ok:
                index = channel - 1
                _current_pct[index] = value
                _last_sent_int[index] = value
                _last_send_ok_ts[index] = time.monotonic()
        if ok:
            samples.append(time.monotonic() - start)
    if samples:
        print(f"[ACKTEST] ch={channel} n={n} ok={len(samples)} lost={n-len(samples)} "
              f"mean={sum(samples)/len(samples)*1000:.1f}ms max={max(samples)*1000:.1f}ms (includes rate limit)")
    else:
        print(f"[ACKTEST] ch={channel} no ACKs, lost={n}")
