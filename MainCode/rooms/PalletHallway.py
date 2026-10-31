import time as t
from context import house
from control.audio_manager import play_audio
from control.arduino import m1Digital_Write
from control.doors import setDoorState
from utils.tools import BreakCheck, log_event, wait
from control import remote_sensor_monitor as rsm
from control.houseLights import toggleHouseLights
import threading
import random
from control import dimmer_controller as dim

# m1Digital_Write(33, 0)
# setDoorState(1, "OPEN")           # "CLOSED" / "CLOPEN" also supported
# play_audio("PalletHallway", "Hit.wav", gain=1)  # threaded=True / looping=True
# if BreakCheck(): return
# distance_mm = rsm.get_TOF_value("TOF2")  # Millimeters; None if unavailable/stale
# log_event("[PalletHallway] Effect...")
# toggleHouseLights(True)  # False = OFF
# threading.Thread(target=function_name, daemon=True, name="PalletHallway effect").start()

def run():
    log_event("[PalletHallway] Starting...")
    house.PalletHallway_state = "ACTIVE"

    try:
        # Room startup here

        while house.HouseActive or house.Demo:
            if BreakCheck():
                break

            # Sequencing here

            while not rsm.get_button_value("BTN2"):
                if BreakCheck():
                    break
                t.sleep(.05)

            if BreakCheck():
                break

            val = random.randint(1,2)
            if val == 1:
                play_audio("secondary_SR", "PZ-jumpscare4.wav", gain=1)
            else:
                play_audio("secondary_SR", "PZ-jumpscare1.wav", gain=1)

            jumpscareFlicker(duration=2.0, channel=4)  # Dynamic Hallway green

            wait(1)

            if BreakCheck() or house.Demo:
                if house.Demo:
                    house.Demo = False
                    house.HouseActive = False
                    toggleHouseLights(True)
                break

            t.sleep(0.1)
    finally:
        house.PalletHallway_state = "INACTIVE"
        log_event("[PalletHallway] Exiting.")



def jumpscareFlicker(duration=2.0, *, channel=4):
    """Sharp, irregular flashes on the marked dimmer, ending OFF."""
    dim.stop_flicker(join=True, channel=channel)
    deadline = t.monotonic() + duration
    bright = True
    try:
        while t.monotonic() < deadline:
            if BreakCheck():
                return
            level = random.randint(80, 100) if bright else random.choice((0, 0, 5, 10))
            dim.dim(level, channel=channel)
            bright = not bright
            next_flash = min(deadline, t.monotonic() + random.uniform(.04, .12))
            while True:
                if BreakCheck():
                    return
                remaining = next_flash - t.monotonic()
                if remaining <= 0:
                    break
                t.sleep(min(.02, remaining))
    finally:
        dim.dim(0, channel=channel)
