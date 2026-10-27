import time as t
from context import house
from control.audio_manager import play_audio
from control.arduino import m1Digital_Write
from control.doors import setDoorState
from utils.tools import BreakCheck, log_event, wait
from control import remote_sensor_monitor as rsm
from control.houseLights import toggleHouseLights
import threading

# m1Digital_Write(33, 0)
# setDoorState(1, "OPEN")           # "CLOSED" / "CLOPEN" also supported
# play_audio("ShowerHallway", "Hit.wav", gain=1)  # threaded=True / looping=True
# if BreakCheck(): return
# distance_mm = rsm.get_TOF_value("TOF2")  # Millimeters; None if unavailable/stale
# log_event("[ShowerHallway] Effect...")
# toggleHouseLights(True)  # False = OFF
# threading.Thread(target=function_name, daemon=True, name="ShowerHallway effect").start()

def run():
    log_event("[ShowerHallway] Starting...")
    house.ShowerHallway_state = "ACTIVE"

    try:
        # Room startup here

        while house.HouseActive or house.Demo:
            if BreakCheck():
                break

            # Sequencing here

            while not rsm.get_button_value("BTN1"):
                if house.Demo:
                    break
                t.sleep(.1)
                if BreakCheck():
                    break

            play_audio("Shower_Hallway", "PZ-jumpscare2.wav", gain=1)

            wait(10)  # 10s elapsed

            if BreakCheck() or house.Demo:
                if house.Demo:
                    house.Demo = False
                    house.HouseActive = False
                    toggleHouseLights(True)
                break

            t.sleep(0.1)
    finally:
        house.ShowerHallway_state = "INACTIVE"
        log_event("[ShowerHallway] Exiting.")
