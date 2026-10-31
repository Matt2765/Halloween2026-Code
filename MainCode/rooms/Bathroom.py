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
from control.group_flow import flow
from control.room_sequence import sequence_wait, SequenceStopped

# m1Digital_Write(33, 0)
# setDoorState(1, "OPEN")           # "CLOSED" / "CLOPEN" also supported
# play_audio("Bathroom", "Hit.wav", gain=1)  # threaded=True / looping=True
# if BreakCheck(): return
# distance_mm = rsm.get_TOF_value("TOF2")  # Millimeters; None if unavailable/stale
# log_event("[Bathroom] Effect...")
# toggleHouseLights(True)  # False = OFF
# threading.Thread(target=function_name, daemon=True, name="Bathroom effect").start()

def run():
    wait = sequence_wait
    global ambientLight
    log_event("[Bathroom] Starting...")

    try:
        # Room startup here
        rsm.servo("DROPDOWN1", '190') #frame in lowered position
        rsm.led("DROPDOWN1", False)
        threading.Thread(target=dropDownLatch, daemon=True).start()
        house.Bathroom_state = "STANDBY"

        while house.HouseActive or house.Demo:
            if BreakCheck():
                break

            while not house.CabinRoom_state == "STANDBY":
                if house.Demo:
                    break

                if house.HouseActive:
                    wait(1)  # 1 second polling interval until Cabin Room is STANDBY
                else:
                    return

            if BreakCheck():
                return

            house.Bathroom_state = "ACTIVE"
            house.BathroomExitReady = False
            basement_reserved = False
            setDoorState(4, "CLOSED")

            m1Digital_Write(34, 1) #blacklight
            
            play_audio("Bathroom", "bathroomMusicPT1.wav", gain=.6)

            ambientLight = True
            threading.Thread(target=ambientGlow, daemon=True, name="Bathroom Ambient Glow").start()
            m1Digital_Write(31, 0) #magic light

            wait(23)  # 20s elapsed
            
            #dim(0, channel=5) #dynamic hallway orange

            setDoorState(3, "CLOSED")
            basement_reserved = house.Demo or flow.reserve_basement()
            if basement_reserved:
                setDoorState(4, "OPEN")
            else:
                setDoorState(4, "CLOSED")
                log_event("[Bathroom] Holding Door 4: previous group is still in Basement")

            wait(23)  # 62s elapsed; voice over time

            rsm.lantern(4, "intense_flickering_on")

            wait(2)  # 64s elapsed

            rsm.lantern(5, "intense_flicker_out")

            wait(3)  # 67s elapsed

            #mirror reveal
            ambientLight = False
            m1Digital_Write(31, 1) #magic light
            wait(.08)
            m1Digital_Write(33, 0) #mirror light
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=1, threaded=True)

            wait(8.5)  # 78.5s elapsed; bloody mary stare

            m1Digital_Write(35, 0) #strobe

            wait(.5)

            ambientLight = True
            threading.Thread(target=ambientFlicker, daemon=True).start()

            #victim jumpscare
            play_audio("Bathroom", "victimJumpscare.wav", gain=1)
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=1)


            m1Digital_Write(33, 1) #mirror light

            wait(3)  # 85s elapsed

            m1Digital_Write(35, 1) #strobe

            wait(6)  # 89.5s elapsed; victim performance

            m1Digital_Write(35, 0) #strobe

            wait(.5)

            ambientLight = False

            play_audio("Bathroom", "bloodyMaryJumpscare.wav", gain=1)
            play_audio("primary_LFE", "SUB-Lightning3.wav", gain=1)

            rsm.servo("DROPDOWN1", '190') #frame down
            log_event("190 deg")
            rsm.led("DROPDOWN1", False)

            play_audio("Bathroom", "bathroomMusicPT2.wav", gain=.8)

            m1Digital_Write(34, 0) #blacklight

            log_event("waiting...")

            wait(2)  
            rsm.lantern(6, "intense_flickering_on")

            setDoorState(5, "OPEN")

            dim(19, channel=5) #dynamic hallway orange

            # Finish the scene, then hold here until Basement can take this group.
            while not basement_reserved:
                if BreakCheck():
                    return
                basement_reserved = flow.reserve_basement()
                wait(.05)

            setDoorState(4, "OPEN")
            while house.DoorState.get(4) != "OPEN":
                wait(.05)
            log_event("[Bathroom] Door 4 released for the next group")
            house.BathroomExitReady = True

            # Unknown sensor data must not count as a group crossing.
            while rsm.get_pir_state("PIR3")["triggered"] is not True:
                wait(.05)

            if BreakCheck():
                return
            if not house.Demo and not flow.arrive():
                return
            house.BathroomExitReady = False

            house.Bathroom_state = "STANDBY"
            setDoorState(4, "CLOPEN")
            rsm.lantern(7, "flicker_out")

            log_event("[Bathroom] Group handed to Dynamic Hallway / Basement")

            m1Digital_Write(35, 1) #strobe

            if BreakCheck() or house.Demo:
                if house.Demo:
                    house.Demo = False
                    house.HouseActive = False
                    toggleHouseLights(True)
                break

            wait(0.1)

            while not house.CabinRoom_state == "ACTIVE":
                wait(.05)
    except SequenceStopped:
        pass
    finally:
        house.BathroomExitReady = False
        ambientLight = False
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
                #log_event(value)

            if BreakCheck():
                break
            
            for i in range(rand):
                value -= 1
                dim(value, channel=6)
                t.sleep(.01)
                #log_event(value)

            if BreakCheck():
                break

            if value > 30:
                for i in range(10):
                    value -= 1
                    dim(value, channel=6)
                    t.sleep(.01)
                    #log_event(value)
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
