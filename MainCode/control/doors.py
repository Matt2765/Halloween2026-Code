import time as t
import threading
from control.arduino import m1Digital_Write
from utils.tools import log_event
from context import house
from control import remote_sensor_monitor as rsm

DOOR_SOLENOID_PINS = {1: 39, 2: 41, 3: 38, 4: 45, 5: 53, 6: 40}
# Shutdown output for each door: "OPEN" or "CLOSED".
# Applies on startup, soft/emergency shutdown and door-worker exit. These are direct
# output defaults, not normal movement requests through the ONLINE PIR loop.
DOOR_SHUTDOWN_STATES = {
    1: "OPEN",
    2: "OPEN",
    3: "CLOSED",
    4: "OPEN",
    5: "OPEN",
    6: "CLOSED",
}
# Door number -> installed sensor ID. Edit each entry to match the wiring;
# sensor numbering does not have to match door numbering.
DOOR_SENSOR_IDS = {
    1: "PIR5",
    2: "PIR1",
    3: "PIR2",
    4: "PIR3",
    5: "PIR6",
    6: "PIR4",
}
# Per-door timing in seconds.
CLOSE_TRAVEL_S = {
    1: 9,
    2: 6,
    3: 7,
    4: 4,
    5: 4,
    6: 7,
}
CLOPEN_HOLD_S = {
    1: 12,
    2: 12,
    3: 12,
    4: 12,
    5: 12,
    6: 12,
}
SENSOR_POLL_S = 0.05
# Continuous ready LOW required before starting/retrying a close. Verify this
# against the installed HC-SR501's post-LOW blocking time; variants differ.
PIR_CLEAR_WAIT_S = 3.0
DOOR_SENSOR_BYPASS = {}  # One movement only; never a persistent configuration.
_DOOR_STARTUP_PENDING = set()  # Preserve defaults until the first valid PIR reading.


def setDoorState(id, state, *, bypass_sensor=False):
    if id in DOOR_SOLENOID_PINS and state in ("OPEN", "CLOPEN", "CLOSED"):
        _DOOR_STARTUP_PENDING.discard(id)
        DOOR_SENSOR_BYPASS[id] = bool(bypass_sensor and state == "CLOSED")
        house.TargetDoorState[id] = state
        log_event(f"[Doors] Set Door {id} to {state}" +
                  (" (sensor bypass for this movement)" if bypass_sensor else ""))
    else:
        log_event(f"[Doors] Invalid door or state: id={id}, state={state}")


def pir_blocks_close(id):
    # Missing, warming, stale, or conflicted sensors also keep the door open.
    return (not rsm.healthy()["connected"] or
            rsm.get_pir_state(DOOR_SENSOR_IDS[id])["triggered"] is not False)


def apply_door_shutdown_state(id):
    _DOOR_STARTUP_PENDING.discard(id)
    DOOR_SENSOR_BYPASS.pop(id, None)
    state = DOOR_SHUTDOWN_STATES.get(id, "OPEN")
    if state not in ("OPEN", "CLOSED"):
        log_event(f"[Doors] Invalid shutdown state for Door {id}: {state!r}; using OPEN")
        state = "OPEN"
    m1Digital_Write(DOOR_SOLENOID_PINS[id], 1 if state == "OPEN" else 0)
    house.TargetDoorState[id] = state
    # No position feedback: do not claim CLOSED before the travel completes.
    house.DoorState[id] = "OPEN" if state == "OPEN" else "CLOSING"
    log_event(f"[Doors] Door {id} shutdown output: {state}")


def door_process(id):
    pin = DOOR_SOLENOID_PINS[id]
    closing_since = reopen_until = previous_target = clear_since = None

    def open_door():
        if house.DoorState.get(id) != "OPEN":
            m1Digital_Write(pin, 1)
            house.DoorState[id] = "OPEN"
            log_event(f"[Doors] Door {id} opened")

    # spawn_doors has already applied the configured default output. Preserve
    # it here instead of briefly opening every door when its worker starts.
    if id not in house.DoorState:
        apply_door_shutdown_state(id)
        _DOOR_STARTUP_PENDING.add(id)
    if house.DoorState[id] == "CLOSING":
        closing_since = t.monotonic()
    try:
        t.sleep(1)  # System initialization sets ONLINE after spawning doors.
        while house.systemState == "ONLINE":
            now = t.monotonic()
            # Track observed clear time even while OPEN; a close request must
            # not restart an already satisfied sensor recovery interval.
            triggered = (rsm.get_pir_state(DOOR_SENSOR_IDS[id])["triggered"]
                         if rsm.healthy()["connected"] else None)
            if triggered is not None:
                _DOOR_STARTUP_PENDING.discard(id)
            blocked = triggered is not False
            if blocked:
                clear_since = None
            elif clear_since is None:
                clear_since = now
            target = house.TargetDoorState.get(id, "OPEN")
            if target != previous_target:
                reopen_until = now + CLOPEN_HOLD_S[id] if target == "CLOPEN" else None
                previous_target = target

            if target != "CLOSED":
                DOOR_SENSOR_BYPASS.pop(id, None)
                open_door()
                closing_since = None
                if target == "CLOPEN" and now >= reopen_until:
                    if house.systemState == "ONLINE" and house.TargetDoorState.get(id) == "CLOPEN":
                        setDoorState(id, "CLOSED")
            elif house.DoorState[id] != "CLOSED":
                if (not DOOR_SENSOR_BYPASS.get(id, False) and blocked
                        and id not in _DOOR_STARTUP_PENDING):
                    open_door()
                    closing_since = None
                    clear_since = None
                elif closing_since is None:
                    if ((DOOR_SENSOR_BYPASS.get(id, False) or (clear_since is not None and now - clear_since >= PIR_CLEAR_WAIT_S)) and
                            house.systemState == "ONLINE" and house.TargetDoorState.get(id) == "CLOSED"):
                        m1Digital_Write(pin, 0)
                        house.DoorState[id] = "CLOSING"
                        closing_since = now
                        log_event(f"[Doors] Door {id} closing")
                elif now - closing_since >= CLOSE_TRAVEL_S[id]:
                    house.DoorState[id] = "CLOSED"  # Timed estimate; no position feedback.
                    DOOR_SENSOR_BYPASS.pop(id, None)
                    log_event(f"[Doors] Door {id} closed")
            else:
                DOOR_SENSOR_BYPASS.pop(id, None)
            t.sleep(SENSOR_POLL_S)
    finally:
        apply_door_shutdown_state(id)


def spawn_doors():
    for id in DOOR_SOLENOID_PINS:
        apply_door_shutdown_state(id)
        _DOOR_STARTUP_PENDING.add(id)
        threading.Thread(target=door_process, args=(id,), daemon=True,
                         name=f"Door {id} Process").start()
    log_event("[Doors] All door threads started.")
