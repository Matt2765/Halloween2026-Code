import time as t
from context import house
from control.audio_manager import play_audio
from control.arduino import m1Digital_Write
from control.doors import setDoorState
from utils.tools import BreakCheck, log_event, wait
from control import remote_sensor_monitor as rsm
from control.lightning import bulb_lightning
from control.houseLights import toggleHouseLights
import threading

# m1Digital_Write(33, 0)
# setDoorState(1, "OPEN")           # "CLOSED" / "CLOPEN" also supported
# play_audio("CabinRoom", "Hit.wav", gain=1)  # threaded=True / looping=True
# if BreakCheck(): return
# while not rsm.obstructed("TOF2", block_mm=800, window_ms=250, min_consecutive=2):
#     if BreakCheck(): return
#     t.sleep(0.05)
# log_event("[CabinRoom] Effect...")
# toggleHouseLights(True)  # False = OFF
# threading.Thread(target=function_name, daemon=True, name="CabinRoom effect").start()

def run():
    log_event("[CabinRoom] Starting...")
    house.CabinRoom_state = "ACTIVE"

    try:
        # Room startup here

        while house.HouseActive or house.Demo:
            if BreakCheck():
                break

            # Sequencing here

            '''count = 0
            while not rsm.get_button_value("BTN2"):
                if count > 3:
                    continue
                count += 0.05
                t.sleep(.05)
                if BreakCheck():
                    return'''

            setDoorState(1, "CLOPEN")

            play_audio("CabinRoom_Wall", "cabinRoomIntrov10-NOTHUNDER.wav", gain=.2)
            play_audio("CabinRoom_PA", "cabinRoomIntrov10-NOTHUNDER.wav", gain=.2)

            wait(6)
            bulb_lightning(pin=28, flash_ms=200, delay_ms=80, flashes=range(2,5))
            play_audio("CabinRoom_Wall", "thunder1.wav", gain=.5)
            play_audio("CabinRoom_PA", "thunder1.wav", gain=.5)
            t.sleep(.5)
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=1)

            rsm.lantern(1, "intense_flickering_on")

            wait(5)

            bulb_lightning(pin=28, flash_ms=200, delay_ms=80, flashes=range(2,5))
            play_audio("CabinRoom_Wall", "thunder2.wav", gain=.5)
            play_audio("CabinRoom_PA", "thunder2.wav", gain=.5)
            t.sleep(.5)
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=1)

            wait(10)

            bulb_lightning(pin=28, flash_ms=200, delay_ms=80, flashes=range(2,5))
            play_audio("CabinRoom_Wall", "thunder3.wav", gain=.5)
            play_audio("CabinRoom_PA", "thunder3.wav", gain=.5)
            t.sleep(.5)
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=1)

            wait(11.5)

            rsm.lantern(2, "intense_flicker_out")

            wait(6)

            bulb_lightning(pin=28, flash_ms=200, delay_ms=80, flashes=range(2,5))
            play_audio("CabinRoom_Wall", "ES_Lightning Bolt 7 - SFX Producer.wav", gain=.5)
            play_audio("CabinRoom_PA", "thunder4.wav", gain=.5)
            t.sleep(1.3)
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=1)

            wait(8.8)

            rsm.lantern(3, "flickering_on")

            wait(30)

            if BreakCheck() or house.Demo:
                if house.Demo:
                    house.Demo = False
                    house.HouseActive = False
                    toggleHouseLights(True)
                break

            t.sleep(0.1)
    finally:
        house.CabinRoom_state = "INACTIVE"
        log_event("[CabinRoom] Exiting.")
