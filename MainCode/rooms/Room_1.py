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
    log_event("[Room_1] Starting...")
    house.Room_1_state = "ACTIVE"

    while house.HouseActive or house.Demo:

        #m1Digital_Write(33, 0) #torch lights
        #log_event("[Room_1] +120v Torch Lights ON")

        setDoorState(1, "CLOPEN")

        play_audio("CabinRoom_Wall", "cabinRoomIntrov10.wav", gain=1)
        play_audio("CabinRoom_PA", "cabinRoomIntrov10.wav", gain=1)

        wait(6)

        rsm.lantern(1, "intense_flickering_on")

        wait(28)

        rsm.lantern(2, "intense_flicker_out")

        wait(16)

        rsm.lantern(3, "flickering_on")

        #play_audio("Room_1", "splash1.wav", gain=1)

        m1Digital_Write(33, 1) #torch lights
        log_event("[Room_1] +120v Torch Lights OFF")

        wait(2)

        if BreakCheck() or house.Demo: # end on breakCheck or if demo'ing
            if house.Demo:
                house.Demo = False
                house.HouseActive = False
            toggleHouseLights(True)
            return

        t.sleep(0.1)

    house.Room_1_state = "INACTIVE"
    log_event("[Room_1] Exiting.")
