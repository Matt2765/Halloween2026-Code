"""Allowlisted manual test controls for the local web UI.

Relay polarity follows shutdown.py (Cabin strobe is active HIGH). Add wiring
assignments here only after confirming them; never expose arbitrary pin writes.
"""
import math
import threading
from context import house
from utils.tools import log_event

# key, room, label, Mega pin, ON level
RELAYS = [
    ("house_light", "House lights", "House light circuit", 2, 0),
    ("cabin_air1", "Cabin Room", "Air blast 1", 43, 0),
    ("cabin_air2", "Cabin Room", "Air blast 2", 47, 0),
    ("cabin_strobe", "Cabin Room", "Strobe", 22, 1),
    ("cabin_lantern1", "Cabin Room", "Wall lanterns 1", 26, 0),
    ("cabin_lantern2", "Cabin Room", "Wall lanterns 2", 24, 0),
    ("cabin_lightning", "Cabin Room", "Lightning", 28, 0),
    ("cabin_porch", "Cabin Room", "Porch lights", 5, 0),
    ("bath_strobe", "Bathroom", "Strobe", 35, 0),
    ("bath_mirror", "Bathroom", "Mirror light", 33, 0),
    ("bath_magic", "Bathroom", "Magic light", 31, 0),
    ("bath_smoke", "Bathroom", "Smoke machine 1", 60, 0),
    ("shower_ambient", "Shower Hallway", "Ambient light", 30, 0),
    ("shower_strobe", "Shower Hallway", "Strobe", 32, 0),
    ("shower_light", "Shower Hallway", "Shower light", 34, 0),
    ("shower_lanterns", "Shower Hallway", "Lanterns", 36, 0),
    ("basement_smoke", "Basement", "Smoke machine 3", 61, 0),
    ("basement_laser", "Basement", "Laser pneumatic", 49, 0),
    ("basement_strobe", "Basement", "Strobe", 37, 0),
    ("basement_strip", "Basement", "Lightning strip", 4, 0),
    ("basement_spot", "Basement", "Spotlight", 3, 0),
    ("pallet_strobe", "Pallet Hallway", "Strobe", 29, 0),
    ("pallet_backlight", "Pallet Hallway", "Pallet backlight", 27, 0),
    ("pallet_blacklight", "Pallet Hallway", "Blacklight", 25, 0),
    ("grave_smoke", "Graveyard", "Industrial smoke machine 5", 58, 0),
]
DIMMERS = [
    (1, "Cabin Room", "Ambient light"), (2, "Cabin Room", "Grandma light"),
    (3, "Cabin Room", "Fire light"), (4, "Dynamic Hallway", "Ambient light 1"),
    (5, "Dynamic Hallway", "Ambient light 2"), (6, "Bathroom", "Ambient light"),
    (7, "Basement", "Ambient light"), (8, "Pallet Hallway", "Ambient lights"),
]
UNMAPPED = ["Cabin chimney smoke machine: no pin assigned",
            "Dynamic Hallway blacklights, lanterns and smoke machine: no pins assigned",
            "Forest Hallway lasers, smoke, strobe and prop drop: no control mapping assigned"]
_lock = threading.RLock()


def catalog():
    from control.doors import DOOR_SOLENOID_PINS, DOOR_SENSOR_IDS
    from control.audio_manager import list_named_channels
    from control import remote_sensor_monitor as rsm
    return dict(
        relays=[dict(id=k, room=r, label=l, pin=p) for k, r, l, p, _ in RELAYS],
        dimmers=[dict(id=c, room=r, label=l) for c, r, l in DIMMERS],
        doors=[dict(id=i, sensor=DOOR_SENSOR_IDS[i]) for i in DOOR_SOLENOID_PINS],
        servos=["DROPDOWN1", "SERVO1", "SERVO2"],
        lanterns=[f"LANTERN{i}" for i in range(1, 7)],
        lantern_modes=list(rsm.LANTERN_STATES),
        speakers=list(list_named_channels()), unmapped=UNMAPPED,
        audio_disabled=house.DISABLE_AUDIO_MANAGER,
    )


def _number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"Value must be between {low} and {high}")
    return value


def _delivery(rsm, cid):
    record = rsm.command_status(cid) or {}
    if record.get("status") in ("rejected", "failed", "timeout"):
        raise RuntimeError(record.get("detail") or record.get("reason") or record["status"])
    return dict(message="Command queued; check device telemetry for result", command_id=cid)


def execute(request):
    """Set a single named output. Does not launch room sequences or retry commands."""
    if not isinstance(request, dict):
        raise ValueError("Expected a JSON object")
    with _lock:
        if house.systemState != "ONLINE":
            raise RuntimeError("Tests require the system to be ONLINE")
        if house.HouseActive or house.Demo:
            raise RuntimeError("Stop the house or room demo before testing individual outputs")
        kind, key, value = request.get("kind"), request.get("id"), request.get("value")
        from control import arduino, dimmer_controller as dim, remote_sensor_monitor as rsm
        result = {"message": "Command sent (not measured feedback)"}
        if kind == "relay":
            entry = next((row for row in RELAYS if row[0] == key), None)
            if entry is None or type(value) is not bool:
                raise ValueError("Unknown relay or invalid ON/OFF value")
            if not arduino.M1_available:
                raise RuntimeError("Arduino unavailable; no physical output was changed")
            arduino.M1.digital_write(entry[3], entry[4] if value else 1 - entry[4])
        elif kind == "dimmer":
            if type(key) is not int or key not in [row[0] for row in DIMMERS]:
                raise ValueError("Unknown dimmer channel")
            value = _number(value, 0, 100)
            if dim._simulated:
                raise RuntimeError("Dimmer unavailable; controller is in simulation mode")
            if not dim.dim(value, channel=key, force=True):
                raise RuntimeError("Dimmer did not acknowledge the command")
        elif kind == "door":
            from control.doors import DOOR_SOLENOID_PINS, setDoorState
            if type(key) is not int or key not in DOOR_SOLENOID_PINS or value not in ("OPEN", "CLOSED"):
                raise ValueError("Unknown door or state")
            setDoorState(key, value, bypass_sensor=request.get("force") is True)
            result["message"] = "Door target updated; see Mains for position and PIR readings"
        elif kind in ("servo", "led", "lantern"):
            if rsm.healthy()["disabled"]:
                raise RuntimeError("Sensor monitor disabled; command was not sent")
            if kind == "servo":
                if key not in ("DROPDOWN1", "SERVO1", "SERVO2"):
                    raise ValueError("Unknown servo")
                angle = _number(value, 0, 180)
                if int(angle) != angle:
                    raise ValueError("Servo angle must be a whole number")
                cid = rsm.servo(key, int(angle))
            elif kind == "led":
                if key != "DROPDOWN1" or type(value) is not bool:
                    raise ValueError("Unknown indicator or ON/OFF value")
                cid = rsm.led(key, value)
            else:
                if key not in [f"LANTERN{i}" for i in range(1, 7)] or value not in rsm.LANTERN_STATES:
                    raise ValueError("Unknown lantern or mode")
                state = rsm.get_lantern_state(key)
                if not state.get("available") or not state.get("synced"):
                    raise RuntimeError("Lantern must be available and synced before sending a cue")
                cid = rsm.lantern(state["next_command_id"], value, [key])[key]
            result = _delivery(rsm, cid)
        elif kind == "audio":
            from control import audio_manager as audio
            if value == "stop":
                audio.stop_all_audio()
            else:
                if value != "speak":
                    raise ValueError("Unknown speaker test action")
                if house.DISABLE_AUDIO_MANAGER:
                    raise RuntimeError("Audio manager is disabled in house_state.py")
                if key not in audio.list_named_channels():
                    raise ValueError("Unknown speaker route")
                gain = _number(request.get("gain", 0.2), 0, 1)
                audio.play_audio(f"{key}: Speaker test. {key}", gain=gain)
                result["message"] = "Speaker test requested"
        elif kind == "pedro":
            from control.pedro_service import start_pedro, stop_pedro
            if value == "start":
                if not start_pedro():
                    raise RuntimeError("Pedro could not start; check the system log")
            elif value == "stop":
                stop_pedro()
            else:
                raise ValueError("Unknown Pedro action")
        else:
            raise ValueError("Unknown test control")
        log_event(f"[Test] {kind} {key}: {value}")
        return result
