import time as t
from context import house
from control.audio_manager import play_audio
from control.arduino import m1Digital_Write
from control.doors import setDoorState
from control.dimmer_controller import dim, start_glow
from utils.tools import BreakCheck, log_event, wait
from control import remote_sensor_monitor as rsm
from control.houseLights import toggleHouseLights
import threading
import random

# m1Digital_Write(33, 0)
# setDoorState(1, "OPEN")           # "CLOSED" / "CLOPEN" also supported
# play_audio("Bathroom", "Hit.wav", gain=1)  # threaded=True / looping=True
# if BreakCheck(): return
# while not rsm.obstructed("TOF2", block_mm=800, window_ms=250, min_consecutive=2):
#     if BreakCheck(): return
#     t.sleep(0.05)
# log_event("[Bathroom] Effect...")
# toggleHouseLights(True)  # False = OFF
# threading.Thread(target=function_name, daemon=True, name="Bathroom effect").start()

def run():
    global ambientLight
    log_event("[Bathroom] Starting...")
    house.Bathroom_state = "ACTIVE"

    try:
        # Room startup here
        rsm.servo("DROPDOWN1", '190') #frame in lowered position
        rsm.led("DROPDOWN1", False)
        threading.Thread(target=dropDownLatch, daemon=True).start()

        while house.HouseActive or house.Demo:
            if BreakCheck():
                break

            play_audio("Bathroom", "bathroomMusicPT1.wav", gain=.6)

            ambientLight = True
            threading.Thread(target=ambientGlow, daemon=True, name="Bathroom Ambient Glow").start()
            m1Digital_Write(31, 0) #magic light

            wait(67) #voice over time

            #mirror reveal
            ambientLight = False
            m1Digital_Write(31, 1) #magic light
            t.sleep(.08)
            m1Digital_Write(33, 0) #mirror light
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=1, threaded=True)

            wait(11.5) #bloody mary stare

            m1Digital_Write(35, 0) #strobe

            t.sleep(.5)

            ambientLight = True
            threading.Thread(target=ambientFlicker, daemon=True).start()

            #victim jumpscare
            play_audio("Bathroom", "victimJumpscare.wav", gain=1)
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=1)


            m1Digital_Write(33, 1) #mirror light

            wait(6.5) #victim performance

            m1Digital_Write(35, 1) #strobe

            wait(4.5) #victim performance

            m1Digital_Write(35, 0) #strobe

            t.sleep(.5)

            ambientLight = False

            play_audio("Bathroom", "bloodyMaryJumpscare.wav", gain=1)
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=1)

            rsm.servo("DROPDOWN1", '190') #frame down
            log_event("190 deg")
            rsm.led("DROPDOWN1", False)

            play_audio("Bathroom", "bathroomMusicPT2.wav", gain=.8)

            log_event("waiting...")

            wait(30)
            m1Digital_Write(35, 1) #strobe

            if BreakCheck() or house.Demo:
                if house.Demo:
                    house.Demo = False
                    house.HouseActive = False
                    toggleHouseLights(True)
                break

            t.sleep(0.1)
    finally:
        house.Bathroom_state = "INACTIVE"
        log_event("[Bathroom] Exiting.")

def ambientGlow():
    global ambientLight
    low, high = 15.0, 25.0
    ramp_seconds = 2.5  # Each direction; five seconds for a full cycle.
    update_seconds = 1.0 / 30.0
    start = t.monotonic()
    next_update = start
    try:
        if not ambientLight or BreakCheck():
            return
        if start_glow(low, high, ramp_seconds, channel=6):
            while ambientLight and not BreakCheck():
                t.sleep(0.02)
            return
        log_event("[Bathroom] Arduino GLOW unavailable; using Python ramp. "
                  "Upload the updated dimmer sketch for locally timed glow.")
        start = t.monotonic()
        next_update = start
        while ambientLight and not BreakCheck():
            elapsed = t.monotonic() - start
            phase = (elapsed / ramp_seconds) % 2.0
            fraction = phase if phase <= 1.0 else 2.0 - phase
            dim(low + (high - low) * fraction, channel=6, fine=True)
            # Skip missed updates instead of adding serial latency to the ramp
            # or sending a burst of old brightness values after a stall.
            now = t.monotonic()
            next_update += update_seconds
            if next_update <= now:
                next_update = start + (int((now - start) / update_seconds) + 1) * update_seconds
            t.sleep(max(0.0, next_update - now))
    finally:
        dim(0, channel=6)

def ambientFlicker():
    global ambientLight
    value = 20
    try:
        while not BreakCheck() and ambientLight == True:
            rand = random.randint(1, 5)
            for i in range(rand):
                value += 1
                dim(value, channel=6)
                t.sleep(.01)
                log_event(value)

            if BreakCheck():
                break
            
            for i in range(rand):
                value -= 1
                dim(value, channel=6)
                t.sleep(.01)
                log_event(value)

            if BreakCheck():
                break

            if value > 30:
                for i in range(10):
                    value -= 1
                    dim(value, channel=6)
                    t.sleep(.01)
                    log_event(value)
    finally:
        dim(0, channel=6)

def dropDownLatch():
    while house.HouseActive or house.Demo:
        while not rsm.get_button_value("DROPDOWN1"):
            #log_event("waiting for dropdown sens")
            t.sleep(.1)
            if BreakCheck():
                return
        rsm.led("DROPDOWN1", True)
        rsm.servo("DROPDOWN1", '90')
        log_event("90 deg")
        t.sleep(.5)
