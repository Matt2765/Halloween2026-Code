import time as t
from context import house
from control.audio_manager import play_audio
from control.arduino import m1Digital_Write
from control.doors import setDoorState
from utils.tools import BreakCheck, log_event, wait
from control import remote_sensor_monitor as rsm
from control.houseLights import toggleHouseLights
import threading
from control.dimmer_controller import dim
import random

# m1Digital_Write(33, 0)
# setDoorState(1, "OPEN")           # "CLOSED" / "CLOPEN" also supported
# play_audio("DynamicHallway", "Hit.wav", gain=1)  # threaded=True / looping=True
# if BreakCheck(): return
# distance_mm = rsm.get_TOF_value("TOF2")  # Millimeters; None if unavailable/stale
# log_event("[DynamicHallway] Effect...")
# toggleHouseLights(True)  # False = OFF
# threading.Thread(target=function_name, daemon=True, name="DynamicHallway effect").start()

def run():
    log_event("[DynamicHallway] Starting...")
    house.DynamicHallway_state = "ACTIVE"

    try:
        # Room startup here

        while house.HouseActive or house.Demo:
            if BreakCheck():
                break

            # Sequencing here
            if house.Demo:
                m1Digital_Write(23, 0)

            '''while not rsm.get_button_value("BTN2"):
                t.sleep(.1)
                if BreakCheck():
                    break'''
            
            while(
                rsm.get_pir_state("PIR3")["triggered"] is False
                or house.Bathroom_state == "ACTIVE"
            ):
                if BreakCheck():
                    break
                t.sleep(.5)

            lightning_bolt(threaded=True) 

            wait(3)

            dim(0, channel=4) #dynamic hallway green
            dim(0, channel=5) #dynamic hallway orange

            lightning_bolt(threaded=True)

            while not rsm.get_button_value("BTN4"):
                t.sleep(.1)
                if BreakCheck():
                    break

            m1Digital_Write(23, 1) #dynamic hallway lanterns

            m1Digital_Write(7, 0) #strobe

            t.sleep(.25)

            rsm.lantern(8, "strobe")

            play_audio("DynamicHallway", "PZ-jumpscare3.wav", gain=1)

            wait(2)

            rsm.lantern(9, "flickering_on")

            wait(8)

            m1Digital_Write(7, 1) #strobe

            if BreakCheck() or house.Demo:
                if house.Demo:
                    house.Demo = False
                    house.HouseActive = False
                    toggleHouseLights(True)
                break

            t.sleep(0.1)
    finally:
        house.DynamicHallway_state = "INACTIVE"
        log_event("[DynamicHallway] Exiting.")

def lightning_bolt(threaded=False):

    audioFiles = [
        "thunder1.wav",
        "thunder2.wav",
        "thunder3.wav",
        "thunder4.wav"
    ]

    def main():
        log_event("[Graveyard] Lightning Bolt Triggered")

        audio =  random.choice(audioFiles)

        play_audio("DynamicHallway", audio, gain=1)

        m1Digital_Write(4, 0)  # Deck lightning ON
        t.sleep(0.1)
        m1Digital_Write(4, 1)  # Deck lightning OFF
        t.sleep(1.1)
        m1Digital_Write(4, 0)  # Deck lightning ON
        t.sleep(0.07)
        m1Digital_Write(4, 1)  # Deck lightning OFF
        t.sleep(.5)
        m1Digital_Write(4, 0)  # Deck lightning ON
        t.sleep(0.07)
        m1Digital_Write(4, 1)  # Deck lightning OFF
        '''t.sleep(.5)
        m1Digital_Write(4, 0)  # Deck lightning ON
        t.sleep(0.07)
        m1Digital_Write(4, 1)  # Deck lightning OFF'''
    
    if threaded:
        threading.Thread(target=main, daemon=True, name="lightning bolt").start()
    else:
        main()
