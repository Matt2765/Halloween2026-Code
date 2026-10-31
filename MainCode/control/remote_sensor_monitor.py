"""Latest device state and a single USB worker process for HauntProtocol v1.

See Esp32/PROTOCOL.md for wire/USB schemas and bench tests. Button polling is
intentionally latest-state: a complete tap between checks can still be missed.
None means unknown, never a synthetic release or a clear TOF measurement.
The bridge alone retries commands. Nothing is replayed after USB reconnect.
"""
from __future__ import annotations

import argparse
import atexit
import json
import multiprocessing as mp
import queue
import re
import threading
import time
import uuid

import serial
import serial.tools.list_ports

DEFAULT_BAUD = 921600
STALE_DEFAULT_MS = 350
HELD_FRESH_MS = 6000
DEVICE_FRESH_MS = 6000
SILENCE_RECONNECT_MS = 3500
CONNECTION_LOG_INTERVAL_MS = 10000
CONFLICT_QUIET_MS = 10000
DELIVERY_FRESH_MS = 400
PORT_HINTS = ("Silicon Labs", "CP210", "CH340", "USB-SERIAL", "ESP32", "WCH")
MAX_DEVICES = 64
MAX_COMMANDS = 128
LANTERN_STATES = ("off", "solid_on", "flickering_on", "intense_flickering_on",
                  "flicker_out", "intense_flicker_out", "strobe")
PEDRO_STATES = ("off", "standby", "active")
_manager = _proc = _shared = _txq = _commands = None
_started = _disabled = False
_tx_lock = threading.Lock()
_lantern_lock = threading.RLock()
_lantern_latches = {}  # device -> (boot session, sync generation, last house cue)


def _now_ms():
    return int(time.monotonic() * 1000)


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


def _record_rejection(shared, obj, reason, now, debug_info=False):
    sid = obj["id"]
    records = dict(shared.get("_rejections", {}))
    old = records.get(sid, {})
    detail = {key: obj.get(key) for key in ("mac", "observed_mac", "expected_mac", "session", "seq",
                                          "expected_session", "expected_seq") if key in obj}
    device = shared.get(sid)
    if device:
        for key, value in (("expected_mac", device["mac"]), ("expected_session", device["session"]),
                           ("expected_seq", device["seq"])):
            detail.setdefault(key, value)
    rec = dict(detail, reason=reason, t_host_ms=now, count=old.get("count", 0) + 1,
               logged_ms=old.get("logged_ms", -CONNECTION_LOG_INTERVAL_MS))
    logged_reasons = dict(old.get("logged_reasons", {}))
    if now - logged_reasons.get(reason, -CONNECTION_LOG_INTERVAL_MS) >= CONNECTION_LOG_INTERVAL_MS:
        if reason != "old_sequence" or debug_info:
            _log_event(f"{sid} report rejected: {reason}" + (f"; {detail}" if debug_info else ""))
        rec["logged_ms"] = now
        logged_reasons[reason] = now
    rec["logged_reasons"] = logged_reasons
    if sid in records or len(records) < MAX_DEVICES:
        records[sid] = rec
        shared["_rejections"] = records


def _store_device(shared, obj, now, debug_info=False):
    """Validate before modifying state; ordering is per multi-button index."""
    queued = obj.get("queue_ms", 0)
    if not _uint32(queued):
        raise ValueError("Invalid bridge queue age")
    received_at = now
    now -= queued  # Both bridge queue timestamps use its own clock, not ESP uptime subtraction.
    sid, kind, vals = obj.get("id"), obj.get("kind"), obj.get("vals")
    session, seq = obj.get("session"), obj.get("seq")
    if not _valid_id(sid) or not _uint32(session) or not _uint32(seq) or not isinstance(vals, dict):
        raise ValueError("Invalid device identity or payload")
    if kind not in ("tof", "button", "pir", "servo", "sprite", "lantern", "pedro", "dropdown", "george", "mosfet"):
        raise ValueError("Unsupported device kind")
    if kind == "button" and (type(vals.get("btn")) is not int or not 1 <= vals["btn"] <= 8 or type(vals.get("pressed")) is not bool):
        raise ValueError("Invalid button state")
    if kind == "pir" and (type(vals.get("output")) is not bool or type(vals.get("ready")) is not bool):
        raise ValueError("Invalid PIR state")
    if kind == "tof" and (type(vals.get("valid")) is not bool or type(vals.get("status")) is not int):
        raise ValueError("Invalid TOF status")
    if kind == "tof" and vals["valid"] and (type(vals.get("dist_mm")) is not int or vals["dist_mm"] < 0 or vals["status"] != 0):
        raise ValueError("Invalid TOF measurement")
    if kind in ("servo", "dropdown") and (type(vals.get("output_angle")) is not int or not 0 <= vals["output_angle"] <= 180 or type(vals.get("moving")) is not bool):
        raise ValueError("Invalid servo output")
    if kind == "dropdown" and (type(vals.get("btn")) is not int or vals["btn"] != 1 or
                               type(vals.get("pressed")) is not bool or type(vals.get("led")) is not bool):
        raise ValueError("Invalid dropdown button/LED state")
    if kind == "lantern" and (vals.get("lantern_state") not in LANTERN_STATES or
                              type(vals.get("synced")) is not bool or
                              type(vals.get("brightness")) is not int or not 0 <= vals["brightness"] <= 255 or
                              not _uint32(vals.get("next_command_id")) or vals["next_command_id"] < 1 or
                              not _uint32(vals.get("sync_generation"))):
        raise ValueError("Invalid lantern state")
    if kind == "pedro" and (vals.get("pedro_state") not in PEDRO_STATES or
                            any(type(vals.get(key)) is not bool for key in ("controller_connected", "neck", "eyes", "moving")) or
                            any(type(vals.get(key)) is not int or not 0 <= vals[key] <= 180
                                for key in ("wings_angle", "wings_target", "beak_angle", "beak_target"))):
        raise ValueError("Invalid Pedro state")
    if kind == "george" and (vals.get("george_state") not in PEDRO_STATES or
                             any(type(vals.get(key)) is not bool for key in ("controller_connected", "eyes", "moving")) or
                             any(type(vals.get(key)) is not int or not 0 <= vals[key] <= 180
                                 for key in ("mouth_angle", "mouth_target", "neck_angle", "neck_target"))):
        raise ValueError("Invalid George state")
    if kind == "mosfet":
        pins, on_pins = vals.get("available_pins"), vals.get("on_pins")
        if (not isinstance(pins, list) or not pins or not isinstance(on_pins, list) or
                any(type(pin) is not int or not 0 <= pin < 40 for pin in pins + on_pins) or
                len(set(pins)) != len(pins) or len(set(on_pins)) != len(on_pins) or
                not set(on_pins).issubset(pins)):
            raise ValueError("Invalid MOSFET pin state")
    rec = shared.get(sid)
    mac = obj.get("mac")
    if not isinstance(mac, str) or not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", mac):
        raise ValueError("Invalid device MAC")
    if rec:
        if rec.get("mac") != mac:
            rec["conflict"] = True
            rec["last_conflict_ms"] = received_at
            shared[sid] = rec
            _record_rejection(shared, obj, "id_conflict", received_at, debug_info)
            return False
        if rec.get("conflict") and (received_at - rec.get("last_conflict_ms", received_at) < CONFLICT_QUIET_MS
                                    or queued >= DELIVERY_FRESH_MS):
            _record_rejection(shared, obj, "id_conflict", received_at, debug_info)
            return False
        if rec["session"] != session:
            if not _newer(session, rec["session"]):
                _record_rejection(shared, obj, "old_session", received_at, debug_info)
                return False
            if queued >= DELIVERY_FRESH_MS:
                return False
            if debug_info:
                _log_event(f"{sid} restarted: session {rec['session']} -> {session}")
            previous_identity = rec
            rec = None  # A reboot invalidates every previous button state.
        elif rec["kind"] != kind:
            raise ValueError("Device kind changed within session")
        else:
            previous_identity = rec
    else:
        previous_identity = None
    if rec is None and previous_identity is None and len([key for key in shared.keys() if not key.startswith("_")]) >= MAX_DEVICES:
        raise ValueError("Device table full")
    previous = rec
    if kind == "button" and rec:
        previous = rec.get("buttons", {}).get(str(vals["btn"]))
    if previous and not _newer(seq, previous["seq"]):
        _record_rejection(shared, obj, "old_sequence", received_at, debug_info)
        return False
    new = {"id": sid, "kind": kind, "session": session, "seq": seq,
           "mac": mac, "vals": vals, "t_host_ms": now, "fw": obj.get("fw"),
           "sequence_gaps": obj.get("sequence_gaps", 0)}
    if rec and "diagnostics" in rec:
        new["diagnostics"] = rec["diagnostics"]
    if kind in ("button", "dropdown"):
        buttons = dict(rec.get("buttons", {})) if rec else {}
        buttons[str(vals["btn"])] = {"seq": seq, "pressed": vals["pressed"], "t_host_ms": now}
        new["buttons"] = buttons
        if rec:
            new["t_host_ms"] = max(now, rec["t_host_ms"])
    shared[sid] = new
    if previous_identity is None and debug_info:
        _log_event(f"{sid} first report; mac={mac}; session={session}; seq={seq}")
    if previous_identity and previous_identity.get("conflict"):
        _log_event(f"{sid} identity conflict cleared; original board resumed")
        if shared.get("_error", {}).get("message") == f"ID conflict: {sid}":
            del shared["_error"]
    return True


def _ingest(shared, commands, obj, now, debug_info=False):
    if not isinstance(obj, dict) or obj.get("v") != 1:
        raise ValueError("Incompatible USB protocol")
    kind = obj.get("type")
    if kind == "device":
        return _store_device(shared, obj, now, debug_info)
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
                if obj.get("observed_mac") != rec["mac"] or "last_conflict_ms" not in rec:
                    rec["last_conflict_ms"] = now
                shared[sid] = rec
            shared["_error"] = {"message": f"ID conflict: {sid}", "t_host_ms": now}
            _record_rejection(shared, obj, "id_conflict", now, debug_info)
        elif obj.get("error") in ("old_session", "old_sequence"):
            _record_rejection(shared, obj, obj["error"], now, debug_info)
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


def _log_event(message):
    from utils.tools import log_event
    log_event(f"[RSM] {message}")


def _log_device_changes(previous, current, now, debug_info=False):
    """Log accepted, fresh telemetry transitions rather than every heartbeat."""
    sid, kind, vals = current["id"], current["kind"], current["vals"]
    if current.get("conflict"):
        return
    if previous and (previous["session"] != current["session"] or previous.get("conflict")):
        previous = None
    if kind in ("button", "dropdown"):
        index = str(vals["btn"])
        button = current["buttons"][index]
        if now - button["t_host_ms"] >= HELD_FRESH_MS:
            return
        old = previous.get("buttons", {}).get(index) if previous else None
        if old and old["pressed"] and now - old["t_host_ms"] >= HELD_FRESH_MS:
            old = None
        if (old and old["pressed"] != button["pressed"]) or (old is None and button["pressed"]):
            _log_event(f"{sid} button {index} {'pressed' if button['pressed'] else 'released'}")
    elif kind in ("pir", "lantern"):
        if now - current["t_host_ms"] >= DEVICE_FRESH_MS:
            return
        old = previous["vals"] if previous and now - previous["t_host_ms"] < DEVICE_FRESH_MS else {}
        if kind == "pir":
            if vals["ready"] and ((old.get("ready") and old.get("output") != vals["output"]) or
                                  (not old.get("ready") and vals["output"])):
                _log_event(f"{sid} {'tripped' if vals['output'] else 'cleared'}")
        elif old.get("lantern_state") != vals["lantern_state"]:
            _log_event(f"{sid} state: {vals['lantern_state']}")


def _log_dropdown_commands(commands, logged, debug_info=False):
    """Persist lantern failures; include detailed dropdown outcomes in debug mode."""
    records = dict(commands.items())
    for cid in list(logged):
        if cid not in records:
            del logged[cid]
    for cid, rec in records.items():
        status = rec["status"]
        if rec.get("op") == "lantern" and status in ("rejected", "unconfirmed"):
            if logged.get(cid) != status:
                _log_event(f"{rec['id']} lantern cue {rec.get('duration_ms')} {status}: "
                           f"{rec.get('detail') or rec.get('reason', 'unknown')}")
                logged[cid] = status
            continue
        if not debug_info:
            continue
        if rec.get("kind") != "dropdown" and rec["id"] != "DROPDOWN1":
            continue
        if status in ("queued", "pending") or logged.get(cid) == status:
            continue
        _log_event(f"{rec['id']} {rec.get('op')}={rec.get('value')} {status}: "
                   f"{rec.get('detail') or rec.get('reason', '')}; command_id={cid}; "
                   f"bridge_connected={rec.get('bridge_connected')}; "
                   f"device_state={rec.get('device_state')}; age_ms={rec.get('device_age_ms')}; "
                   f"session={rec.get('device_session')}; diagnostics={rec.get('device_diagnostics', {})}")
        logged[cid] = status


def _log_device_health(shared, states, now, debug_info=False):
    for sid, rec in list(shared.items()):
        if sid.startswith("_"):
            continue
        age = max(0, now - rec["t_host_ms"])
        state = "conflict" if rec.get("conflict") else "silent" if age >= DEVICE_FRESH_MS else "reporting"
        previous = states.get(sid)
        if state != previous:
            if state == "silent":
                sleeping = rec["kind"] == "button" and not any(b["pressed"] for b in rec.get("buttons", {}).values())
                if sleeping:
                    if debug_info:
                        _log_event(f"{sid} has no recent reports; released battery buttons may be sleeping")
                else:
                    _log_event(f"{sid} telemetry unavailable")
            elif state == "reporting" and previous == "silent" and debug_info:
                _log_event(f"{sid} telemetry resumed; mac={rec['mac']}; session={rec['session']}; seq={rec['seq']}")
            states[sid] = state


def _monitor_main(shared, commands, txq, port, baud, debug_info=False):
    backoff = 0.25
    last_error_log = None
    logged_commands = {}
    device_health = {}
    last_health = 0
    _log_event(f"Starting monitor on {port or 'auto-detected port'} at {baud} baud")
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
                        received_at = _now_ms()
                        previous = shared.get(obj.get("id")) if isinstance(obj, dict) and obj.get("type") == "device" else None
                        accepted = _ingest(shared, commands, obj, received_at, debug_info)
                        if accepted and obj.get("type") == "device":
                            _log_device_changes(previous, shared[obj["id"]], received_at, debug_info)
                        last_valid = _now_ms()
                        if obj["type"] == "hello" and obj.get("host") == token:
                            if not handshake:
                                _log_event(f"Bridge connected on {connection.port}")
                                last_error_log = None
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
                _log_dropdown_commands(commands, logged_commands, debug_info)
                if now - last_health >= 500:
                    _log_device_health(shared, device_health, now, debug_info)
                    last_health = now
        except (OSError, serial.SerialException, RuntimeError) as error:
            shared["_connection"] = {"connected": False}
            shared["_error"] = {"message": str(error), "t_host_ms": _now_ms()}
            _finish_pending(commands, "usb_disconnected")
            _log_dropdown_commands(commands, logged_commands, debug_info)
            now = _now_ms()
            if last_error_log is None or now - last_error_log >= CONNECTION_LOG_INTERVAL_MS:
                _log_event(f"Bridge unavailable: {error}. Retrying connection...")
                last_error_log = now
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
    if _disabled:
        _log_event("Monitor disabled by house.DISABLE_REMOTE_SENSOR_MONITOR")
        return
    if _proc and _proc.is_alive():
        return
    with _lantern_lock:
        _lantern_latches.clear()
    if _manager is None:
        _manager = mp.Manager()
    _shared, _commands = _manager.dict(), _manager.dict()
    _txq = mp.Queue(maxsize=32)
    _proc = mp.Process(target=_monitor_main,
                       args=(_shared, _commands, _txq, port, baud, bool(house.DEBUG_INFO)), daemon=True)
    _proc.start()
    _started = True
    atexit.register(stop)


def stop():
    global _proc, _started, _txq
    with _lantern_lock:
        _lantern_latches.clear()
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
    elif kind in ("servo", "dropdown") and age > (1000 if vals.get("moving") else 6000):
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
    if not rec or rec.get("conflict") or rec.get("kind") not in ("button", "dropdown"):
        return None
    if rec["kind"] == "dropdown" and _now_ms() - rec["t_host_ms"] >= DEVICE_FRESH_MS:
        return None # Powered node: both pressed and released expire when disconnected.
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


def get_TOF_value(device_id):
    """Latest valid distance in millimeters, or None if unavailable or stale.

    Example: distance_mm = rsm.get_TOF_value("TOF2")
    Check for None before comparing the distance with a room's own threshold.
    """
    rec = get(device_id)
    if not rec or rec.get("kind") != "tof":
        return None
    return get_value(device_id, "dist_mm")


def get_pir_state(device_id):
    status = device_status(device_id)
    output = get_value(device_id, "output")
    return dict(status, output=output, triggered=(output if status["available"] and status["ready"] else None))


def get_servo_state(device_id):
    rec = get(device_id)
    return dict(device_status(device_id), **(rec["vals"] if rec and rec["kind"] in ("servo", "dropdown") else {}))


def get_lantern_state(device_id):
    rec = get(device_id)
    return dict(device_status(device_id), **(rec["vals"] if rec and rec["kind"] == "lantern" else {}))


def get_pedro_state(device_id="PEDRO1"):
    rec = get(device_id)
    return dict(device_status(device_id), **(rec["vals"] if rec and rec["kind"] == "pedro" else {}))


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
    recovered = {}
    for rec in records:
        if rec["status"] == "accepted":
            key = (rec["id"], rec.get("op"), rec.get("pin"))
            recovered[key] = max(recovered.get(key, -1), rec["created_ms"])
    failures = [rec for rec in records if rec["status"] in ("rejected", "unconfirmed") and
                recovered.get((rec["id"], rec.get("op"), rec.get("pin")), -1) <= rec["created_ms"]]
    if not failures:
        return None
    latest = max(failures, key=lambda rec: rec["t_host_ms"])
    return dict(latest, age_ms=max(0, _now_ms() - latest["t_host_ms"]))


def tx_to_id(device_id, payload):
    """Send once via logical addressing; return a command ID immediately."""
    if not _valid_id(device_id):
        raise ValueError("Device ID must contain 1..15 ASCII letters, digits, '_' or '-'")
    payload = json.loads(payload) if isinstance(payload, str) else dict(payload)
    if any(payload.get(key, device_id) != device_id for key in ("id", "to")):
        raise ValueError("Conflicting logical destination")
    if payload.get("cmd") == "mosfet":
        if type(payload.get("pin")) is not int or not 0 <= payload["pin"] < 40 or type(payload.get("on")) is not bool:
            raise ValueError("MOSFET requires a GPIO integer in 0..39 and True/False")
        op, value, duration = "mosfet", int(payload["on"]), 0
    elif payload.get("cmd") == "led":
        if type(payload.get("on")) is not bool:
            raise ValueError("LED on must be True or False")
        op, value, duration = "led", int(payload["on"]), 0
    elif payload.get("cmd") == "pedro":
        state = payload.get("state")
        if state not in PEDRO_STATES:
            raise ValueError(f"Pedro state must be one of {PEDRO_STATES}")
        if any(type(payload.get(key)) is not int or not 0 <= payload[key] <= 180 for key in ("wings", "beak")) or any(
                type(payload.get(key)) is not bool for key in ("neck", "eyes")):
            raise ValueError("Pedro requires wings/beak angles and boolean neck/eyes outputs")
        op, value, duration = "pedro", PEDRO_STATES.index(state), payload.get("ramp_ms", 0)
    elif payload.get("cmd") == "george":
        state = payload.get("state")
        if state not in PEDRO_STATES:
            raise ValueError(f"George state must be one of {PEDRO_STATES}")
        if any(type(payload.get(key)) is not int or not 0 <= payload[key] <= 180 for key in ("mouth", "neck")) or type(payload.get("eyes")) is not bool:
            raise ValueError("George requires mouth/neck angles and boolean eyes output")
        op, value, duration = "george", PEDRO_STATES.index(state), payload.get("ramp_ms", 0)
    elif payload.get("cmd") == "lantern":
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
        raise ValueError("Supported commands: angle, set_default, led, mosfet, pedro, george, lantern, play/index/file, next")
    maximum = 2 if op in ("pedro", "george") else 180 if op in ("move", "set_default") else len(LANTERN_STATES) - 1 if op == "lantern" else 200
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
        status = device_status(device_id)
        rec = {"command_id": cid, "id": device_id, "status": "queued", "created_ms": now, "t_host_ms": now,
               "op": op, "value": value, "duration_ms": duration, "kind": device.get("kind") if device else None,
               "bridge_connected": bool(connection.get("connected")), "device_state": status["state"],
               "device_age_ms": status["age_ms"], "device_session": device.get("session") if device else None,
               "device_diagnostics": device.get("diagnostics", {}) if device else {}}
        if op == "mosfet":
            rec["pin"] = payload["pin"]
        if not connection.get("connected") or not device or not status["available"]:
            detail = ("bridge_disconnected" if not connection.get("connected") else
                      "device_not_seen" if not device else
                      "device_id_conflict" if status["state"] == "conflict" else "device_telemetry_expired")
            _commands[cid] = dict(rec, status="rejected", reason="unavailable_or_disconnected", detail=detail)
            return cid
        request = {"v": 1, "type": "command", "host": connection["host"], "command_id": cid,
                   "id": device_id, "target_session": device["session"], "op": op, "value": value, "duration_ms": duration}
        if op == "mosfet":
            if device["kind"] != "mosfet":
                _commands[cid] = dict(rec, status="rejected", reason="not_a_mosfet")
                return cid
            if payload["pin"] not in device["vals"]["available_pins"]:
                _commands[cid] = dict(rec, status="rejected", reason="pin_not_configured")
                return cid
            request["pin"] = payload["pin"]
        if op == "led" and device["kind"] not in ("dropdown", "button"):
            _commands[cid] = dict(rec, status="rejected", reason="not_an_led_device")
            return cid
        if op == "pedro":
            if device["kind"] != "pedro":
                _commands[cid] = dict(rec, status="rejected", reason="not_pedro")
                return cid
            request.update({key: payload[key] for key in ("wings", "beak", "neck", "eyes")})
        if op == "george":
            if device["kind"] != "george":
                _commands[cid] = dict(rec, status="rejected", reason="not_george")
                return cid
            request.update({key: payload[key] for key in ("mouth", "neck", "eyes")})
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


def mosfet(node_ids, pin, on):
    """Set one configured GPIO on one or more nodes; return {node_id: command_id}.

    Example: mosfet(["MOSFET1"], 13, True). Outputs latch until changed or node
    reset; no keepalive is required. Check command_status() for each delivery.
    """
    targets = [node_ids] if isinstance(node_ids, str) else list(node_ids)
    if not targets or any(not _valid_id(sid) for sid in targets):
        raise ValueError("Provide one or more valid MOSFET node IDs")
    if type(pin) is not int or not 0 <= pin < 40 or type(on) is not bool:
        raise ValueError("MOSFET requires a GPIO integer in 0..39 and True/False")
    return {sid: tx_to_id(sid, {"cmd": "mosfet", "pin": pin, "on": on}) for sid in dict.fromkeys(targets)}


def get_mosfet_state(device_id):
    rec = get(device_id)
    return dict(device_status(device_id), **(rec["vals"] if rec and rec["kind"] == "mosfet" else {}))


def led(device_id, on):
    """Set a dropdown/button node's indicators; return an ID for command_status().

    Button nodes require LED-enabled firmware; both onboard and external LEDs
    follow the command. Unsupported button firmware rejects the command.
    """
    return tx_to_id(device_id, {"cmd": "led", "on": on})


def sprite_play(device_id, index):
    return tx_to_id(device_id, {"cmd": "play", "index": int(index)})


def pedro(device_id="PEDRO1", *, state="standby", wings=5, beak=55, neck=False, eyes=False, ramp_ms=0):
    """One atomic pose and controller keepalive. Refresh at least every 500 ms.

    Angles describe PWM output, not measured position. Off parks the hardware.
    Node calibration may reject angles inside 0..180 but outside Pedro's limits.
    """
    return tx_to_id(device_id, {"cmd": "pedro", "state": state, "wings": wings,
                               "beak": beak, "neck": neck, "eyes": eyes, "ramp_ms": ramp_ms})


def george(device_id="GEORGE1", *, state="standby", mouth=180, neck=80, eyes=False, ramp_ms=0):
    """Atomic pose/keepalive; mouth and neck are servo angles in degrees.

    Refresh at least every 500 ms. Off parks mouth=180, neck=80 (head forward), eyes=False.
    Firmware enforces calibrated mouth 120..180 and neck 0..115 limits.
    """
    return tx_to_id(device_id, {"cmd": "george", "state": state, "mouth": mouth,
                               "neck": neck, "eyes": eyes, "ramp_ms": ramp_ms})


def get_george_state(device_id="GEORGE1"):
    rec = get(device_id)
    return dict(device_status(device_id), **(rec["vals"] if rec and rec["kind"] == "george" else {}))


def lantern(command_id, state, lantern_ids=None):
    """Issue a numbered cue; return {device_id: delivery UUID} for status checks.

    Untargeted house cue 1 enrolls fresh, synced lanterns waiting for 1.
    Later house cues follow that group's intended progress even after a lost
    delivery. Updated node firmware accepts forward jumps within the same
    sync generation; missed effects are never replayed. Telemetry remains the
    actual confirmed state, not an assumed success. Re-sync/reboot detaches a
    lantern until a new cue 1. Multiple groups can occupy different rooms.
    Demo mode and explicit targets use telemetry/manual addressing as before.
    """
    if type(command_id) is not int or not 1 <= command_id < 0xffffffff:
        raise ValueError("Lantern command ID must be 1..4294967294")
    if state not in LANTERN_STATES:
        raise ValueError(f"Lantern state must be one of {LANTERN_STATES}")
    with _lantern_lock:
        demo_mode = False
        records = {}
        if lantern_ids is None:
            from context import house
            demo_mode = bool(house.Demo)
            records = snapshot()
            # A button press changes generation, including a quick re-sync
            # back to cue 1 before the old group's next room cue arrives.
            for sid, latch in list(_lantern_latches.items()):
                rec = records.get(sid)
                if (not rec or rec["kind"] != "lantern" or not rec["vals"].get("synced")
                        or rec.get("conflict")
                        or (rec["session"], rec["vals"].get("sync_generation")) != latch[:2]):
                    del _lantern_latches[sid]
            targets = []
            for sid, rec in records.items():
                if rec["kind"] != "lantern" or not rec["vals"].get("synced") or rec.get("conflict"):
                    continue
                next_cue = rec["vals"].get("next_command_id")
                if type(next_cue) is not int or not 1 <= next_cue < 0xffffffff:
                    continue
                if demo_mode:
                    if device_status(sid)["available"]:
                        targets.append(sid)
                    continue
                if (command_id == 1 and next_cue == 1 and sid not in _lantern_latches
                        and device_status(sid)["available"]):
                    _lantern_latches[sid] = (rec["session"], rec["vals"]["sync_generation"], 0)
                latch = _lantern_latches.get(sid)
                if latch is not None and latch[2] + 1 == command_id:
                    targets.append(sid)
        else:
            targets = [lantern_ids] if isinstance(lantern_ids, str) else list(lantern_ids)
        if any(not _valid_id(sid) for sid in targets):
            raise ValueError("Invalid lantern device ID")
        results = {}
        for sid in dict.fromkeys(targets):
            rec = records.get(sid) if lantern_ids is None else get(sid)
            generation = rec["vals"].get("sync_generation", 0) if rec else 0
            cue_id = rec["vals"]["next_command_id"] if demo_mode else command_id
            results[sid] = tx_to_id(sid, {"cmd": "lantern", "state": state, "cue_id": cue_id,
                                         "sync_generation": generation})
            if lantern_ids is None and not demo_mode:
                # An unconfirmed/rejected send must not strand this group's
                # future cues. No claim is made that hardware accepted it.
                _lantern_latches[sid] = (rec["session"], generation, command_id)
        return results


def button_pop(timeout=0.0):
    raise NotImplementedError("Button event consumption is postponed; use get_button_value().")


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
