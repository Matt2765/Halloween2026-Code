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
import random
from control.dimmer_controller import dim, start_glow

wallLanterns = False

# m1Digital_Write(33, 0)
# setDoorState(1, "OPEN")           # "CLOSED" / "CLOPEN" also supported
# play_audio("CabinRoom", "Hit.wav", gain=1)  # threaded=True / looping=True
# if BreakCheck(): return
# distance_mm = rsm.get_TOF_value("TOF2")  # Millimeters; None if unavailable/stale
# log_event("[CabinRoom] Effect...")
# toggleHouseLights(True)  # False = OFF
# threading.Thread(target=function_name, daemon=True, name="CabinRoom effect").start()

def run():
    global wallLanterns
    log_event("[CabinRoom] Starting...")
    effect_stop = threading.Event()
    effect_threads = []

    try:
        # Room startup here
        while house.HouseActive or house.Demo:
            if BreakCheck():
                break

            # Sequencing here
            house.CabinRoom_state = "ACTIVE"

            '''count = 0
            while not rsm.get_button_value("BTN2"):
                if count > 3:
                    continue
                count += 0.05
                t.sleep(.05)
                if BreakCheck():
                    return'''

            setDoorState(1, "CLOPEN")

            m1Digital_Write(26, 0) #wall lantern 1
            m1Digital_Write(24, 0) #wall lantern 2

            play_audio("CabinRoom_Wall", "cabinAmbienceShort.wav", gain=.3)
            play_audio("CabinRoom_PA", "cabinAmbienceShort.wav", gain=.3)

            wait(3)  # 3s elapsed; 43

            dim(60,channel=2)
            play_audio("CabinRoom_Wall", "cabinRoomIntrov10-NOTHUNDER.wav", gain=.4)
            play_audio("CabinRoom_PA", "cabinRoomIntrov10-NOTHUNDER.wav", gain=.4)
            setDoorState(2, "OPEN")
            setDoorState(4, "OPEN")

            wait(6)  # 9s elapsed

            effect_threads.append(dimFlickerOut(effect_stop))
            bulb_lightning(pin=28, flash_ms=200, delay_ms=80, flashes=range(2,5))
            play_audio("CabinRoom_Wall", "thunder1.wav", gain=.5)
            play_audio("CabinRoom_PA", "thunder1.wav", gain=.5)
            t.sleep(.5)
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=1)

            #start flickering wall lanterns here
            if not BreakCheck():
                wallLanterns = True
                wall_thread = threading.Thread(
                    target=wallLanternFlicker, args=(effect_stop,), daemon=True,
                    name="CabinRoom Wall Lantern Flicker")
                effect_threads.append(wall_thread)
                wall_thread.start()

            rsm.lantern(1, "intense_flickering_on")

            wait(2)  # 11s elapsed

            wait(3)  # 14s elapsed

            setDoorState(2, "CLOSED")
            setDoorState(4, "CLOSED")

            bulb_lightning(pin=28, flash_ms=200, delay_ms=80, flashes=range(2,5))
            play_audio("CabinRoom_Wall", "thunder2.wav", gain=.5)
            play_audio("CabinRoom_PA", "thunder2.wav", gain=.5)
            t.sleep(.5)
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=1)

            wait(10)  # 24s elapsed

            bulb_lightning(pin=28, flash_ms=200, delay_ms=80, flashes=range(2,5))
            play_audio("CabinRoom_Wall", "thunder3.wav", gain=.5)
            play_audio("CabinRoom_PA", "thunder3.wav", gain=.5)
            t.sleep(.5)
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=1)

            wait(11.5)  # 35.5s elapsed

            rsm.lantern(2, "intense_flicker_out")
            wallLanterns = False

            wait(5)  # 40.5s elapsed

            m1Digital_Write(22, 1) #strobe on

            wait(1)  # 41.5s elapsed

            bulb_lightning(pin=28, flash_ms=200, delay_ms=80, flashes=range(2,6))
            play_audio("CabinRoom_Wall", "ES_Lightning Bolt 7 - SFX Producer.wav", gain=.5)
            play_audio("CabinRoom_PA", "thunder4.wav", gain=.5)
            t.sleep(1.3)
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=1)

            wait(4)  # 45.5s elapsed

            bulb_lightning(pin=28, flash_ms=200, delay_ms=80, flashes=range(2,6))
            play_audio("CabinRoom_Wall", "ES_Lightning Bolt 4 - SFX Producer.wav", gain=.5)
            play_audio("CabinRoom_PA", "ES_Lightning Bolt 4 - SFX Producer.wav", gain=.5)
            t.sleep(.5)
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=1)

            setDoorState(2, "OPEN")
            setDoorState(3, "OPEN")
            wait(4.8)  # 50.3s elapsed

            bulb_lightning(pin=28, flash_ms=200, delay_ms=80, flashes=range(2,6))
            play_audio("CabinRoom_Wall", "thunder2.wav", gain=.5)
            play_audio("CabinRoom_PA", "thunder2.wav", gain=.5)
            t.sleep(.5)
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=.5)
            play_audio("primary_LFE", "thunder2.wav", gain=.5)

            setDoorState(2, "CLOPEN")

            rsm.lantern(3, "flickering_on")

            m1Digital_Write(23, 0) #dynamic hallway lanterns

            house.CabinRoom_state = "STANDBY"

            wait(5)  # 55.3s elapsed

            while not house.Basement_state == "ACTIVE":
                if house.DoorState[3] == "CLOSED":
                    break
                if not house.HouseActive or house.Demo:
                    break
                wait(1)  # 1s polling interval until Basement is ACTIVE

            m1Digital_Write(22, 0) #strobe off

            for thread in effect_threads:
                thread.join()
            effect_threads.clear()

            if BreakCheck() or house.Demo:
                if house.Demo:
                    house.Demo = False
                    house.HouseActive = False
                    toggleHouseLights(True)
                break

            t.sleep(0.1)
    finally:
        wallLanterns = False
        effect_stop.set()
        for thread in effect_threads:
            thread.join()
        dim(0, channel=2)
        m1Digital_Write(26, 1)
        m1Digital_Write(24, 1)
        house.CabinRoom_state = "INACTIVE"
        log_event("[CabinRoom] Exiting.")

def dimFlickerOut(stop_event=None):
    """Quickly flicker Grandma's DIM2 light out without delaying the sequence."""
    if stop_event is None:
        stop_event = threading.Event()

    def flicker():
        try:
            for step in range(10):
                if stop_event.is_set() or BreakCheck():
                    return
                dim(0, channel=2)
                if stop_event.wait(0.025) or BreakCheck():
                    return
                level = 60 * (1 - step / 10) * random.uniform(0.4, 1.0)
                dim(level, channel=2)
                if stop_event.wait(0.04):
                    return
        finally:
            dim(0, channel=2)

    thread = threading.Thread(target=flicker, daemon=True,
                              name="CabinRoom Grandma Flicker Out")
    thread.start()
    return thread


def wallLanternFlicker(stop_event=None):
    """Flicker D26/D24 until wallLanterns is False or the house stops."""
    if stop_event is None:
        stop_event = threading.Event()
    try:
        while wallLanterns and not stop_event.is_set() and not BreakCheck():
            for pin in (26, 24):
                if not wallLanterns or stop_event.is_set() or BreakCheck():
                    return
                m1Digital_Write(pin, random.choice((0, 0, 0, 1)))
            # Poll the flag and BreakCheck every 20 ms, including during holds.
            for _ in range(random.randint(4, 12)):
                if not wallLanterns or stop_event.is_set() or BreakCheck():
                    return
                if stop_event.wait(0.02):
                    return
    finally:
        m1Digital_Write(26, 1)
        m1Digital_Write(24, 1)
