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
    ("cabin_fire", "Cabin Room", "Fire light", 6, 0),
    ("cabin_chimney_smoke", "Cabin Room", "Chimney smoke machine", 59, 0),
    ("cabin_rocking_chair", "Cabin Room", "Rocking chair", 51, 0),
    ("bath_strobe", "Bathroom", "Strobe", 35, 0),
    ("bath_mirror", "Bathroom", "Mirror light", 33, 0),
    ("bath_magic", "Bathroom", "Magic light", 31, 0),
    ("shower_ambient", "Shower Hallway", "Blacklight", 30, 0),
    ("shower_strobe", "Shower Hallway", "Strobe", 32, 0),
    ("shower_light", "Shower Hallway", "Shower light", 34, 0),
    ("shower_lanterns", "Shower Hallway", "Lanterns", 36, 0),
    ("basement_smoke", "Basement", "Smoke machine 3", 61, 0),
    ("basement_shrine", "Basement", "Shrine solenoid", 49, 0),
    ("basement_strobe", "Basement", "Strobe", 37, 0),
    ("dynamic_strip", "Dynamic Hallway", "Lightning strip", 4, 0),
    ("dynamic_strobe", "Dynamic Hallway", "Strobe", 7, 0),
    ("dynamic_lanterns", "Dynamic Hallway", "Lanterns", 23, 0),
    ("basement_spot", "Basement", "Spotlight", 3, 0),
    ("pallet_strobe", "Pallet Hallway", "Strobe", 29, 0),
    ("pallet_backlight", "Pallet Hallway", "Pallet backlight", 27, 0),
    ("pallet_blacklight", "Pallet Hallway", "Blacklight", 25, 0),
    ("grave_smoke", "Graveyard", "Industrial smoke machine 5", 58, 0),
    ("forest_smoke", "Forest Hallway", "Smoke machine 6", 57, 0),
    ("forest_strobe", "Forest Hallway", "Strobe", 8, 0),
    ("forest_prop_drop", "Forest Hallway", "Prop drop", 42, 0),
    ("forest_lasers", "Forest Hallway", "Lasers", 56, 0),
]
MOSFETS = []  # No wireless MOSFET outputs currently assigned in the wiring plan.
DIMMERS = [
    (1, "Cabin Room", "Ambient light 1"), (2, "Cabin Room", "Grandma light"),
    (3, "Basement", "Wall crack lights"), (4, "Dynamic Hallway", "Ambient light 3"),
    (5, "Dynamic Hallway", "Ambient light 4"), (6, "Bathroom", "Ambient light 2"),
    (7, "Basement", "Ambient light 6"), (8, "Pallet Hallway", "Ambient light 5"),
]
UNASSIGNED_CONTROLS = [
    ("Bathroom", "Mirror servo", "Servo device ID needs to be assigned"),
    ("Dynamic Hallway", "Blacklights", "Cable I, red; Arduino pin needed"),
    ("Dynamic Hallway", "Smoke machine 2", "Cable J, red/black; Arduino pin needed"),
    ("Graveyard", "Wendigo", "Device/pin and command mapping needed"),
]
UNMAPPED = [f"{room}: {label} - {detail}" for room, label, detail in UNASSIGNED_CONTROLS]
DOOR_ROOMS = {1: "Cabin Room", 2: "Cabin Room", 3: "Bathroom",
              4: "Cabin Room", 5: "Basement", 6: "Bathroom"}
_lock = threading.RLock()


def catalog():
    from control.doors import DOOR_SOLENOID_PINS, DOOR_SENSOR_IDS
    from control.audio_manager import list_named_channels
    from control import remote_sensor_monitor as rsm
    from control import animatronic_service as anim
    characters = {"pedro": anim.pedro, "george": anim.george}
    return dict(
        animatronics=[dict(id=key, name=character.name, outputs=[
            dict(id=output, label=output.capitalize(), type="digital", rest=character.controller_factory.rest_pose[output])
            if limit is bool else
            dict(id=output, label=output.capitalize(), type="angle", min=limit[0], max=limit[1],
                 rest=character.controller_factory.rest_pose[output])
            for output, limit in character.controller_factory.output_limits.items()])
            for key, character in characters.items()],
        relays=[dict(id=k, room=r, label=l, pin=p) for k, r, l, p, _ in RELAYS],
        mosfets=[dict(id=k, room=r, label=l, node=n, pin=p) for k, r, l, n, p in MOSFETS],
        dimmers=[dict(id=c, room=r, label=l) for c, r, l in DIMMERS],
        doors=[dict(id=i, sensor=DOOR_SENSOR_IDS[i], room=DOOR_ROOMS.get(i, "Doors"))
               for i in DOOR_SOLENOID_PINS],
        servos=["DROPDOWN1", "SERVO1", "SERVO2"],
        lanterns=[f"LANTERN{i}" for i in range(1, 7)],
        lantern_modes=list(rsm.LANTERN_STATES),
        speakers=list(list_named_channels()), unmapped=UNMAPPED,
        unassigned=[dict(room=r, label=l, detail=d) for r, l, d in UNASSIGNED_CONTROLS],
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
        elif kind == "mosfet":
            entry = next((row for row in MOSFETS if row[0] == key), None)
            if entry is None or type(value) is not bool:
                raise ValueError("Unknown MOSFET output or invalid ON/OFF value")
            if rsm.healthy()["disabled"]:
                raise RuntimeError("Sensor monitor disabled; command was not sent")
            cid = rsm.mosfet([entry[3]], entry[4], value)[entry[3]]
            result = _delivery(rsm, cid)
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
        elif kind == "animatronic":
            from control import animatronic_service as anim
            if key not in ("pedro", "george"):
                raise ValueError("Unknown animatronic")
            character = anim.pedro if key == "pedro" else anim.george
            if value not in ("start", "stop", "talk", "pose", "idle_start", "idle_stop"):
                raise ValueError("Unknown animatronic action")
            if value in ("stop", "idle_stop"):
                if value == "stop":
                    character.stop()
                    result["message"] = f"{character.name} stop/park requested"
                else:
                    character.stop_idle()
                    result["message"] = f"{character.name} idle movement stopped; current speech continues"
            else:
                if rsm.healthy()["disabled"]:
                    raise RuntimeError("Sensor monitor disabled; command was not sent")
                if value == "idle_start":
                    accepted = character.start_idle()
                    result["message"] = f"{character.name} idle movement enabled"
                elif value == "pose":
                    outputs = request.get("outputs")
                    limits = character.controller_factory.output_limits
                    if not isinstance(outputs, dict) or not outputs or any(output not in limits for output in outputs):
                        raise ValueError("Unknown or missing animatronic outputs")
                    for output, setting in outputs.items():
                        limit = limits[output]
                        if limit is bool:
                            if type(setting) is not bool:
                                raise ValueError(f"{output} requires ON/OFF")
                        elif type(setting) is not int or not limit[0] <= setting <= limit[1]:
                            raise ValueError(f"{output} requires a whole angle in {limit[0]}..{limit[1]}")
                    ramp = request.get("ramp_ms", 0)
                    if type(ramp) is not int or not 0 <= ramp <= 30000:
                        raise ValueError("Ramp must be a whole number in 0..30000 ms")
                    accepted = character.pose(ramp_ms=ramp, **outputs)
                    result["message"] = f"{character.name} manual pose requested; check live status"
                else:
                    from control.audio_manager import list_named_channels
                    if house.DISABLE_AUDIO_MANAGER:
                        raise RuntimeError("Audio manager is disabled in house_state.py")
                    channel = request.get("channel", character.name)
                    if channel not in list_named_channels():
                        raise ValueError("Unknown speaker route")
                    gain = _number(request.get("gain", 1), 0, 1)
                    action = character.start if value == "start" else character.talk
                    accepted = action(channel=channel, gain=gain)
                    result["message"] = (f"{character.name} " +
                        ("talking show requested" if value == "start" else "one quip requested") +
                        "; check live status")
                if not accepted:
                    raise RuntimeError(character.status().get("error") or f"{character.name} command could not start")
            result["animatronic"] = character.status()
        elif kind == "pedro":
            # Keep existing clients compatible; the current UI uses the shared API.
            from control.animatronic_service import start_pedro, stop_pedro
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
