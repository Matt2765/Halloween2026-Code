# utils/debug.py
import time
from control.doors import setDoorState
from utils.tools import log_event


def debugDoors():
    log_event("[Debug] Toggling doors...")
    while True:
        setDoorState(1, "OPEN")
        time.sleep(1)
        setDoorState(1, "CLOSED")
        time.sleep(1)
