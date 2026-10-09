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
# play_audio("ForestHallway", "Hit.wav", gain=1)  # threaded=True / looping=True
# if BreakCheck(): return
# while not rsm.obstructed("TOF2", block_mm=800, window_ms=250, min_consecutive=2):
#     if BreakCheck(): return
#     t.sleep(0.05)
# log_event("[ForestHallway] Effect...")
# toggleHouseLights(True)  # False = OFF
# threading.Thread(target=function_name, daemon=True, name="ForestHallway effect").start()

def run():
    log_event("[ForestHallway] Starting...")
    house.ForestHallway_state = "ACTIVE"

    try:
        # Room startup here

        while house.HouseActive or house.Demo:
            if BreakCheck():
                break

            # Sequencing here

            if BreakCheck() or house.Demo:
                if house.Demo:
                    house.Demo = False
                    house.HouseActive = False
                    toggleHouseLights(True)
                break

            t.sleep(0.1)
    finally:
        house.ForestHallway_state = "INACTIVE"
        log_event("[ForestHallway] Exiting.")
