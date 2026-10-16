import time as t
import threading
from control.arduino import m1Digital_Write
from utils.tools import log_event
from context import house
from control import remote_sensor_monitor as rsm

DOOR_SOLENOID_PINS = {1: 47, 2: 38}
DOOR_SENSOR_IDS = {1: "PIR1", 2: "PIR2"}
CLOSE_TRAVEL_S = 4
CLOPEN_HOLD_S = 12
SENSOR_POLL_S = 0.05
# Continuous ready LOW required before starting/retrying a close. Verify this
# against the installed HC-SR501's post-LOW blocking time; variants differ.
PIR_CLEAR_WAIT_S = 3.0


def setDoorState(id, state):
    if id in DOOR_SOLENOID_PINS and state in ("OPEN", "CLOPEN", "CLOSED"):
        house.TargetDoorState[id] = state
        log_event(f"[Doors] Set Door {id} to {state}")
    else:
        log_event(f"[Doors] Invalid door or state: id={id}, state={state}")


def pir_blocks_close(id):
    # Missing, warming, stale, or conflicted sensors also keep the door open.
    return (not rsm.healthy()["connected"] or
            rsm.get_pir_state(DOOR_SENSOR_IDS[id])["triggered"] is not False)


def door_process(id):
    pin = DOOR_SOLENOID_PINS[id]
    closing_since = reopen_until = previous_target = clear_since = None

    def open_door():
        if house.DoorState.get(id) != "OPEN":
            m1Digital_Write(pin, 1)
            house.DoorState[id] = "OPEN"
            log_event(f"[Doors] Door {id} opened")

    house.DoorState[id] = None  # Force the startup OPEN output.
    open_door()
    try:
        t.sleep(1)  # System initialization sets ONLINE after spawning doors.
        while house.systemState == "ONLINE":
            now = t.monotonic()
            target = house.TargetDoorState.get(id, "OPEN")
            if target != previous_target:
                clear_since = None
                reopen_until = now + CLOPEN_HOLD_S if target == "CLOPEN" else None
                previous_target = target

            if target != "CLOSED":
                open_door()
                closing_since = None
                clear_since = None
                if target == "CLOPEN" and now >= reopen_until:
                    if house.systemState == "ONLINE" and house.TargetDoorState.get(id) == "CLOPEN":
                        setDoorState(id, "CLOSED")
            elif house.DoorState[id] != "CLOSED":
                if pir_blocks_close(id):
                    open_door()
                    closing_since = None
                    clear_since = None
                elif closing_since is None:
                    if clear_since is None:
                        clear_since = now
                    if (now - clear_since >= PIR_CLEAR_WAIT_S and
                            house.systemState == "ONLINE" and house.TargetDoorState.get(id) == "CLOSED"):
                        m1Digital_Write(pin, 0)
                        house.DoorState[id] = "CLOSING"
                        closing_since = now
                        log_event(f"[Doors] Door {id} closing")
                elif now - closing_since >= CLOSE_TRAVEL_S:
                    house.DoorState[id] = "CLOSED"  # Timed estimate; no position feedback.
                    log_event(f"[Doors] Door {id} closed")
            t.sleep(SENSOR_POLL_S)
    finally:
        open_door()


def spawn_doors():
    for id in DOOR_SOLENOID_PINS:
        house.TargetDoorState[id] = "OPEN"
        threading.Thread(target=door_process, args=(id,), daemon=True,
                         name=f"Door {id} Process").start()
    log_event("[Doors] All door threads started.")
