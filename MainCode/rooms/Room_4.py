import time as t
from context import house
from control.audio_manager import play_audio
from control.arduino import m1Digital_Write
from control.doors import setDoorState
from utils.tools import BreakCheck, log_event, wait
from control import remote_sensor_monitor as rsm
from control.houseLights import toggleHouseLights
import threading


def run():
    log_event("[Room_4] Starting...")
    house.Room_4_state = "ACTIVE"

    while house.HouseActive or house.Demo:

        m1Digital_Write(33, 0) #torch lights
        log_event("[Room_4] +120v Torch Lights ON")

        setDoorState(1, "CLOPEN")

        while not rsm.obstructed("TOF2", block_mm=800, window_ms=250, min_consecutive=2):
            if BreakCheck():
                return
            t.sleep(0.05)

        play_audio("Room_4", "Hit.wav", gain=1)

        m1Digital_Write(33, 1) #torch lights
        log_event("[Room_4] +120v Torch Lights OFF")

        wait(10)
        
        play_audio("Room_4", "test", gain=1)

        if BreakCheck() or house.Demo: # end on breakCheck or if demo'ing
            if house.Demo:
                house.Demo = False
                house.HouseActive = False
            toggleHouseLights(True)
            return

        t.sleep(0.1)

    house.Room_4_state = "INACTIVE"
    log_event("[Room_4] Exiting.")
