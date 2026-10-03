"""Latest device state and a single USB worker process for HauntProtocol v1.

See Esp32/PROTOCOL.md for wire/USB schemas and bench tests. Button polling is
intentionally latest-state: a complete tap between checks can still be missed.
None means unknown, never a synthetic release or a clear TOF measurement.
The bridge alone retries commands. Nothing is replayed after USB reconnect.
"""
from __future__ import annotations

import argparse
import atexit
from collections import deque
import json
import multiprocessing as mp
import queue
import re
import threading
import time
import uuid
import warnings

import serial
import serial.tools.list_ports

DEFAULT_BAUD = 921600
STALE_DEFAULT_MS = 350
HELD_FRESH_MS = 6000
DEVICE_FRESH_MS = 6000
SILENCE_RECONNECT_MS = 3500
PORT_HINTS = ("Silicon Labs", "CP210", "CH340", "USB-SERIAL", "ESP32", "WCH")
MAX_DEVICES = 64
MAX_COMMANDS = 128
LANTERN_STATES = ("off", "solid_on", "flickering_on", "intense_flickering_on",
                  "flicker_out", "intense_flicker_out")
_manager = _proc = _shared = _txq = _commands = None
_started = _disabled = False
_hist = {}
_history_lock = threading.RLock()
_tx_lock = threading.Lock()


def _now_ms():
    return int(time.monotonic() * 1000)


_now_ms_local = _now_ms


def _newer(a, b):
    return 0 < ((a - b) & 0xffffffff) < 0x80000000


def _valid_id(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,15}", value) is not None


def _uint32(value):
    return type(value) is int and 0 <= value <= 0xffffffff


def _autodetect_port():
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        description = f"{port.device} {port.description} {port.manufacturer or ''}"
        if any(hint.lower() in description.lower() for hint in PORT_HINTS):
            return port.device
    return ports[0].device if ports else None


def _open_serial(port, baud):
    port = port or _autodetect_port()
    if not port:
        raise RuntimeError("No serial port found for ESP32 bridge")
    connection = serial.Serial(port, baud, timeout=0.02, write_timeout=0.2,
                               rtscts=False, dsrdtr=False)
    connection.setDTR(False)
    connection.setRTS(False)
    return connection


def _write_json(connection, obj):
    line = (json.dumps(obj, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
    if connection.write(line) != len(line):
        raise OSError("Incomplete serial write; command outcome unknown")


class SerialLines:
    """Bound fragments; discard an oversized line through its next newline."""
    def __init__(self):
        self.buffer = bytearray()
        self.discard = False
        self.errors = 0

    def feed(self, chunk):
        lines = []
        for byte in chunk:
            if byte == 10:
                if not self.discard and self.buffer:
                    lines.append(bytes(self.buffer))
                self.buffer.clear()
                self.discard = False
            elif not self.discard:
                if len(self.buffer) >= 1024:
                    self.buffer.clear()
                    self.discard = True
                    self.errors += 1
                else:
                    self.buffer.append(byte)
        return lines


def _store_device(shared, obj, now):
    """Validate before modifying state; ordering is per multi-button index."""
    queued = obj.get("queue_ms", 0)
    if not _uint32(queued):
        raise ValueError("Invalid bridge queue age")
    now -= queued  # Both bridge queue timestamps use its own clock, not ESP uptime subtraction.
    sid, kind, vals = obj.get("id"), obj.get("kind"), obj.get("vals")
    session, seq = obj.get("session"), obj.get("seq")
    if not _valid_id(sid) or not _uint32(session) or not _uint32(seq) or not isinstance(vals, dict):
        raise ValueError("Invalid device identity or payload")
    if kind not in ("tof", "button", "pir", "servo", "sprite", "lantern"):
        raise ValueError("Unsupported device kind")
    if kind == "button" and (type(vals.get("btn")) is not int or not 1 <= vals["btn"] <= 8 or type(vals.get("pressed")) is not bool):
        raise ValueError("Invalid button state")
    if kind == "pir" and (type(vals.get("output")) is not bool or type(vals.get("ready")) is not bool):
        raise ValueError("Invalid PIR state")
    if kind == "tof" and (type(vals.get("valid")) is not bool or type(vals.get("status")) is not int):
        raise ValueError("Invalid TOF status")
    if kind == "tof" and vals["valid"] and (type(vals.get("dist_mm")) is not int or vals["dist_mm"] < 0 or vals["status"] != 0):
        raise ValueError("Invalid TOF measurement")
    if kind == "servo" and (type(vals.get("output_angle")) is not int or not 0 <= vals["output_angle"] <= 180 or type(vals.get("moving")) is not bool):
        raise ValueError("Invalid servo output")
    if kind == "lantern" and (vals.get("lantern_state") not in LANTERN_STATES or
                              type(vals.get("synced")) is not bool or
                              type(vals.get("brightness")) is not int or not 0 <= vals["brightness"] <= 255 or
                              not _uint32(vals.get("next_command_id")) or vals["next_command_id"] < 1 or
                              not _uint32(vals.get("sync_generation"))):
        raise ValueError("Invalid lantern state")
    rec = shared.get(sid)
    mac = obj.get("mac")
    if not isinstance(mac, str) or not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", mac):
        raise ValueError("Invalid device MAC")
    if rec:
        if rec.get("conflict") or rec.get("mac") != mac:
            rec["conflict"] = True
            shared[sid] = rec
            return False
        if rec["session"] != session:
            if not _newer(session, rec["session"]):
                return False
            rec = None  # A reboot invalidates every previous button state.
        elif rec["kind"] != kind:
            raise ValueError("Device kind changed within session")
    elif len([key for key in shared.keys() if not key.startswith("_")]) >= MAX_DEVICES:
        raise ValueError("Device table full")
    previous = rec
    if kind == "button" and rec:
        previous = rec.get("buttons", {}).get(str(vals["btn"]))
    if previous and not _newer(seq, previous["seq"]):
        return False
    new = {"id": sid, "kind": kind, "session": session, "seq": seq,
           "mac": mac, "vals": vals, "t_host_ms": now, "fw": obj.get("fw"),
           "sequence_gaps": obj.get("sequence_gaps", 0)}
    if kind == "button":
        buttons = dict(rec.get("buttons", {})) if rec else {}
        buttons[str(vals["btn"])] = {"seq": seq, "pressed": vals["pressed"], "t_host_ms": now}
        new["buttons"] = buttons
        if rec:
            new["t_host_ms"] = max(now, rec["t_host_ms"])
    shared[sid] = new
    return True


def _ingest(shared, commands, obj, now):
    if not isinstance(obj, dict) or obj.get("v") != 1:
        raise ValueError("Incompatible USB protocol")
    kind = obj.get("type")
    if kind == "device":
        return _store_device(shared, obj, now)
    if kind == "bridge":
        if not _uint32(obj.get("session")):
            raise ValueError("Invalid bridge session")
        shared["_bridge"] = dict(obj, t_host_ms=now)
    elif kind == "command_result":
        cid = obj.get("command_id")
        if cid in commands:
            old = commands[cid]
            if obj.get("status") not in ("pending", "accepted", "rejected", "unconfirmed", "superseded"):
                raise ValueError("Invalid command result")
            # A local timeout/disconnect is terminal; late lines cannot replay work.
            if old.get("status") in ("queued", "pending"):
                commands[cid] = dict(old, **obj, t_host_ms=now)
        elif obj.get("status") == "rejected":
            shared["_error"] = {"message": obj.get("reason"), "t_host_ms": now}
    elif kind == "diagnostic":
        sid = obj.get("id")
        if not _valid_id(sid):
            raise ValueError("Invalid diagnostic ID")
        rec = shared.get(sid)
        if obj.get("error") == "id_conflict":
            if rec:
                rec["conflict"] = True
                shared[sid] = rec
            shared["_error"] = {"message": f"ID conflict: {sid}", "t_host_ms": now}
        elif rec:
            rec["diagnostics"] = obj.get("vals", {})
            shared[sid] = rec  # Diagnostics do not refresh measurement/state age.
    elif kind != "hello":
        raise ValueError("Unsupported USB record")
    return True


def _finish_pending(commands, reason):
    for cid, rec in list(commands.items()):
        if rec["status"] in ("queued", "pending"):
            commands[cid] = dict(rec, status="unconfirmed", reason=reason, t_host_ms=_now_ms())


def _monitor_main(shared, commands, txq, port, baud):
    backoff = 0.25
    while True:
        connection = None
        try:
            connection = _open_serial(port, baud)
            connection.reset_input_buffer()
            token = uuid.uuid4().hex
            shared["_connection"] = {"connected": False, "host": token}
            _finish_pending(commands, "usb_reconnect_no_replay")
            lines = SerialLines()
            handshake = False
            bridge_session = None
            last_valid = _now_ms()
            last_host = 0
            while True:
                now = _now_ms()
                if now - last_host >= 500:
                    _write_json(connection, {"v": 1, "type": "host_heartbeat" if handshake else "hello", "host": token})
                    last_host = now
                for line in lines.feed(connection.read(4096)):
                    try:
                        obj = json.loads(line)
                        if not handshake and isinstance(obj, dict) and obj.get("type") not in ("hello", "bridge"):
                            continue  # Drain pre-handshake USB records without refreshing state.
                        _ingest(shared, commands, obj, _now_ms())
                        last_valid = _now_ms()
                        if obj["type"] == "hello" and obj.get("host") == token:
                            handshake = True
                            bridge_session = obj["session"]
                            shared["_connection"] = {"connected": True, "host": token, "t_host_ms": last_valid}
                            backoff = 0.25
                        elif obj["type"] == "bridge" and handshake and obj["session"] != bridge_session:
                            raise OSError("Bridge restarted")
                    except (ValueError, TypeError, KeyError) as error:
                        shared["_error"] = {"message": str(error), "t_host_ms": _now_ms()}
                if lines.errors:
                    shared["_error"] = {"message": "Oversized USB line", "t_host_ms": now}
                    lines.errors = 0
                if now - last_valid > SILENCE_RECONNECT_MS:
                    raise OSError("Bridge heartbeat missing")
                if handshake:
                    for _ in range(8):
                        try:
                            request = txq.get_nowait()
                        except queue.Empty:
                            break
                        cid = request["command_id"]
                        rec = commands.get(cid)
                        if not rec or rec["status"] != "queued":
                            continue
                        if request["host"] != token or now - rec["created_ms"] > 500:
                            commands[cid] = dict(rec, status="unconfirmed", reason="expired_before_send", t_host_ms=now)
                            continue
                        commands[cid] = dict(rec, status="pending", t_host_ms=now)
                        _write_json(connection, request)  # Exactly one host send, no retry loop.
                for cid, rec in list(commands.items()):
                    if rec["status"] in ("queued", "pending") and now - rec["created_ms"] > 2000:
                        commands[cid] = dict(rec, status="unconfirmed", reason="result_timeout", t_host_ms=now)
        except (OSError, serial.SerialException, RuntimeError) as error:
            shared["_connection"] = {"connected": False}
            shared["_error"] = {"message": str(error), "t_host_ms": _now_ms()}
            _finish_pending(commands, "usb_disconnected")
            if connection:
                connection.close()
            time.sleep(backoff)
            backoff = min(backoff * 2, 3.0)


def set_disabled(disabled=True):
    global _disabled
    _disabled = bool(disabled)
    if _disabled:
        stop()


def init(port=None, baud=DEFAULT_BAUD):
    global _manager, _proc, _shared, _commands, _started, _txq
    from context import house
    set_disabled(house.DISABLE_REMOTE_SENSOR_MONITOR)
    if _disabled or (_proc and _proc.is_alive()):
        return
    if _manager is None:
        _manager = mp.Manager()
    _shared, _commands = _manager.dict(), _manager.dict()
    _txq = mp.Queue(maxsize=32)
    _proc = mp.Process(target=_monitor_main, args=(_shared, _commands, _txq, port, baud), daemon=True)
    _proc.start()
    _started = True
    atexit.register(stop)


def stop():
    global _proc, _started, _txq
    if _proc and _proc.is_alive():
        _proc.terminate()
        _proc.join(timeout=1)
    if _shared is not None:
        _shared["_connection"] = {"connected": False}
    if _commands is not None:
        _finish_pending(_commands, "monitor_stopped")
    if _txq is not None:
        _txq.cancel_join_thread()
        _txq.close()
        _txq = None
    _proc, _started = None, False


def get(sensor_id):
    return _shared.get(sensor_id) if not _disabled and _shared is not None else None


def snapshot():
    return {key: value for key, value in dict(_shared).items() if not key.startswith("_")} if not _disabled and _shared is not None else {}


def device_status(sensor_id):
    rec = get(sensor_id)
    if not rec:
        return {"state": "unavailable", "age_ms": None, "available": False, "ready": False}
    age = max(0, _now_ms() - rec["t_host_ms"])
    kind, vals = rec["kind"], rec["vals"]
    state = "valid"
    if rec.get("conflict"):
        state = "conflict"
    elif kind == "button":
        buttons = list(rec.get("buttons", {}).values())
        held = any(button["pressed"] for button in buttons)
        state = "held" if held else "sleeping"
        if any(button["pressed"] and _now_ms() - button["t_host_ms"] >= HELD_FRESH_MS for button in buttons):
            state = "unknown"
    elif age >= DEVICE_FRESH_MS:
        state = "unavailable"
    elif kind == "tof":
        state = "stale" if age > STALE_DEFAULT_MS else "valid" if vals.get("valid") else "invalid"
    elif kind == "servo" and age > (1000 if vals.get("moving") else 6000):
        state = "stale"
    elif not vals.get("ready", True):
        state = "warming"
    return {"state": state, "age_ms": age, "available": state not in ("unavailable", "conflict", "unknown"),
            "ready": bool(vals.get("ready", True)), "kind": kind}


def get_button_value(device_id, btn_num=None):
    """True/False latest state, or None for missing/conflicted/expired held state."""
    if _disabled:
        return False
    rec = get(device_id)
    if not rec or rec.get("conflict") or rec.get("kind") != "button":
        return None
    index = btn_num if btn_num is not None else rec["vals"]["btn"]
    button = rec.get("buttons", {}).get(str(index))
    if not button:
        return None
    if button["pressed"] and _now_ms() - button["t_host_ms"] >= HELD_FRESH_MS:
        return None
    return button["pressed"]


def get_value(sensor_id, key, default=None, max_age_ms=None):
    rec = get(sensor_id)
    if not rec or rec.get("conflict"):
        return default
    if key == "pressed":
        value = get_button_value(sensor_id)
        return default if value is None else value
    age = _now_ms() - rec["t_host_ms"]
    limit = STALE_DEFAULT_MS if rec["kind"] == "tof" else DEVICE_FRESH_MS
    if max_age_ms is not None:
        limit = min(limit, max_age_ms)
    if age > limit:
        return default
    vals = rec["vals"]
    if key == "dist_mm" and (not vals.get("valid") or vals.get("status") != 0):
        return default
    return vals.get(key, default)


def get_pir_state(device_id):
    status = device_status(device_id)
    output = get_value(device_id, "output")
    return dict(status, output=output, triggered=(output if status["available"] and status["ready"] else None))


def get_servo_state(device_id):
    rec = get(device_id)
    return dict(device_status(device_id), **(rec["vals"] if rec and rec["kind"] == "servo" else {}))


def get_lantern_state(device_id):
    rec = get(device_id)
    return dict(device_status(device_id), **(rec["vals"] if rec and rec["kind"] == "lantern" else {}))


def get_latency_ms(sensor_id):
    """Independent ESP uptime clocks cannot establish one-way latency."""
    return None


def healthy():
    bridge = get("_bridge") or {}
    connection = get("_connection") or {}
    return {"started": _started, "disabled": _disabled, "sensors": len(snapshot()),
            "connected": bool(connection.get("connected")) and _now_ms() - bridge.get("t_host_ms", 0) < SILENCE_RECONNECT_MS,
            "diagnostics": bridge.get("diagnostics", {}), "error": get("_error")}


def command_status(command_id):
    return _commands.get(command_id) if _commands is not None else None


def command_failure():
    records = list(_commands.values()) if _commands is not None else []
    failures = [rec for rec in records if rec["status"] in ("rejected", "unconfirmed")]
    return max(failures, key=lambda rec: rec["t_host_ms"]) if failures else None


def tx_to_id(device_id, payload):
    """Send once via logical addressing; return a command ID immediately."""
    if not _valid_id(device_id):
        raise ValueError("Device ID must contain 1..15 ASCII letters, digits, '_' or '-'")
    payload = json.loads(payload) if isinstance(payload, str) else dict(payload)
    if any(payload.get(key, device_id) != device_id for key in ("id", "to")):
        raise ValueError("Conflicting logical destination")
    if payload.get("cmd") == "lantern":
        state = payload.get("state")
        if state not in LANTERN_STATES:
            raise ValueError(f"Lantern state must be one of {LANTERN_STATES}")
        op, value, duration = "lantern", LANTERN_STATES.index(state), payload.get("cue_id")
        if type(duration) is not int or not 1 <= duration < 0xffffffff or not _uint32(payload.get("sync_generation")):
            raise ValueError("Lantern cue ID must be 1..4294967294 and sync generation must be uint32")
    elif "set_default" in payload:
        op, value, duration = "set_default", payload["set_default"], 300
    elif "angle" in payload:
        op, value, duration = "move", payload["angle"], payload.get("ramp_ms", 300)
    elif payload.get("cmd") == "next" or not any(key in payload for key in ("cmd", "index", "file")):
        op, value, duration = "next", 0, 0
    elif payload.get("cmd", "play") == "play":
        op, value, duration = "play", payload.get("index", payload.get("file")), 0
    else:
        raise ValueError("Supported commands: angle, set_default, play/index/file, next")
    maximum = 180 if op in ("move", "set_default") else 5 if op == "lantern" else 200
    duration_maximum = 0xfffffffe if op == "lantern" else 30000
    if type(value) is not int or not 0 <= value <= maximum or type(duration) is not int or not 0 <= duration <= duration_maximum:
        raise ValueError("Command value or duration out of range")
    cid, now = uuid.uuid4().hex, _now_ms()
    if _disabled:
        return cid  # Dry-run mode never touches serial or actuators.
    if _txq is None or _commands is None:
        raise RuntimeError("Call init() first")
    with _tx_lock:
        if len(_commands) >= MAX_COMMANDS:
            completed = [(key, rec) for key, rec in _commands.items() if rec["status"] not in ("queued", "pending")]
            if not completed:
                raise RuntimeError("Command history full")
            del _commands[min(completed, key=lambda pair: pair[1]["created_ms"])[0]]
        connection, device = get("_connection") or {}, get(device_id)
        rec = {"command_id": cid, "id": device_id, "status": "queued", "created_ms": now, "t_host_ms": now}
        if not connection.get("connected") or not device or not device_status(device_id)["available"]:
            _commands[cid] = dict(rec, status="rejected", reason="unavailable_or_disconnected")
            return cid
        request = {"v": 1, "type": "command", "host": connection["host"], "command_id": cid,
                   "id": device_id, "target_session": device["session"], "op": op, "value": value, "duration_ms": duration}
        if op == "lantern":
            if device["kind"] != "lantern":
                _commands[cid] = dict(rec, status="rejected", reason="not_a_lantern")
                return cid
            request["sync_generation"] = payload["sync_generation"]
        _commands[cid] = rec
        try:
            _txq.put_nowait(request)
        except queue.Full:
            _commands[cid] = dict(rec, status="rejected", reason="host_queue_full")
    return cid


def tx_broadcast(payload):
    payload = json.loads(payload) if isinstance(payload, str) else dict(payload)
    destination = payload.get("id") or payload.get("to")
    if not destination:
        raise ValueError("Broadcast transport still requires an explicit logical recipient")
    return tx_to_id(destination, payload)


def tx_to_mac(mac, payload):
    raise NotImplementedError("MAC TX removed; use tx_to_id(). All radio traffic is broadcast.")


def servo(device_id, angle, ramp_ms=None):
    return tx_to_id(device_id, {"angle": max(0, min(180, int(angle))), "ramp_ms": 0 if ramp_ms is None else int(ramp_ms)})


def sprite_play(device_id, index):
    return tx_to_id(device_id, {"cmd": "play", "index": int(index)})


def lantern(command_id, state, lantern_ids=None):
    """Issue a numbered cue; return {device_id: delivery UUID} for status checks.

    lantern_ids: one ID, an iterable of IDs, or None for all fresh lanterns
    synced and waiting for this cue. Explicit targets still obey local sync and
    sequence gates. Call the next cue after telemetry confirms next_command_id.
    No replay or automatic catch-up occurs for absent lanterns.
    """
    if type(command_id) is not int or not 1 <= command_id < 0xffffffff:
        raise ValueError("Lantern command ID must be 1..4294967294")
    if state not in LANTERN_STATES:
        raise ValueError(f"Lantern state must be one of {LANTERN_STATES}")
    if lantern_ids is None:
        targets = [sid for sid, rec in snapshot().items() if rec["kind"] == "lantern" and
                   rec["vals"].get("synced") and rec["vals"].get("next_command_id") == command_id and
                   device_status(sid)["available"]]
    else:
        targets = [lantern_ids] if isinstance(lantern_ids, str) else list(lantern_ids)
    if any(not _valid_id(sid) for sid in targets):
        raise ValueError("Invalid lantern device ID")
    results = {}
    for sid in dict.fromkeys(targets):
        rec = get(sid)
        generation = rec["vals"].get("sync_generation", 0) if rec else 0
        results[sid] = tx_to_id(sid, {"cmd": "lantern", "state": state, "cue_id": command_id,
                                     "sync_generation": generation})
    return results


def button_pop(timeout=0.0):
    raise NotImplementedError("Button event consumption is postponed; use get_button_value().")


def set_far_distance_mm(value):
    warnings.warn("Synthetic far distances are removed; invalid TOF remains unknown", DeprecationWarning, stacklevel=2)


def _get_dist_sample(sid, **kwargs):
    distance = get_value(sid, "dist_mm")
    rec = get(sid)
    return (rec["t_host_ms"], distance) if distance is not None and rec else None

def _hist_update(sid: str, window_ms: int, **kw):
    now = _now_ms_local()
    sample = _get_dist_sample(sid, **kw)

    # keep a per-sensor deque of (timestamp_ms, distance_mm)
    if sid not in _hist and len(_hist) >= MAX_DEVICES:
        _hist.pop(next(iter(_hist)))
    h = _hist.setdefault(sid, {'q': deque(maxlen=256), 'last': False, 'last_ts': -1})
    if sample:
        t_ms, d = sample
        # avoid duplicating the same timestamp
        if t_ms != h['last_ts']:
            h['q'].append((t_ms, d))
            h['last_ts'] = t_ms

    q = h['q']
    if sample is None:
        q.clear()
        h['last'] = False
    # evict old samples from the *left* (oldest first)
    while q and (now - q[0][0]) > window_ms:
        q.popleft()

    return h

def _distance_filtered(sid: str, window_ms: int=250, min_samples: int=3,
                          ignore_neg1: bool=True, require_status_zero: bool=False,
                          method: str="median"):
    h = _hist_update(sid, window_ms, ignore_neg1=ignore_neg1, require_status_zero=require_status_zero)
    q = list(h['q'])
    if len(q) < max(1, min_samples):
        return None
    vals = [d for (_, d) in q]
    if not vals:
        return None
    if method == "mean":
        return sum(vals) / len(vals)
    vals.sort()
    n = len(vals); mid = n // 2
    return vals[mid] if n % 2 else (vals[mid-1] + vals[mid]) / 2

def _obstructed(sid: str, block_mm: int,
               clear_mm: int|None=None,
               window_ms: int=250,
               min_consecutive: int=2,
               ignore_neg1: bool=True,
               require_status_zero: bool=False) -> bool:
    if _disabled:
        return False
    h = _hist_update(sid, window_ms, ignore_neg1=ignore_neg1, require_status_zero=require_status_zero)
    q = h['q']
    if clear_mm is None:
        clear_mm = block_mm + 50
    consec = 0
    for (_, d) in reversed(q):
        if d < block_mm:
            consec += 1
            if consec >= max(1, min_consecutive):
                h['last'] = True
                return True
        else:
            break
    if h['last']:
        if q:
            _, latest = q[-1]
            if latest > clear_mm:
                h['last'] = False
    return h['last']



def get_distance_filtered(*args, **kwargs):
    with _history_lock:
        return _distance_filtered(*args, **kwargs)


def obstructed(*args, **kwargs):
    # Room triggers require positive valid evidence. Doors separately require clear evidence.
    with _history_lock:
        return _obstructed(*args, **kwargs)


def format_table():
    rows = ["ID               state        age_ms  values"]
    for sid, rec in sorted(snapshot().items()):
        status = device_status(sid)
        rows.append(f"{sid:16} {status['state']:12} {status['age_ms']:7}  {rec['vals']}")
    return "\n".join(rows)


def print_table():
    print(format_table())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument("--watch", type=float, nargs="?", const=2, default=2)
    args = parser.parse_args()
    init(args.port, args.baud)
    try:
        while True:
            print_table()
            time.sleep(1 / max(0.1, args.watch))
    except KeyboardInterrupt:
        stop()
