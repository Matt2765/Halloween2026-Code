import time as t
from context import house
from control.audio_manager import play_audio
from control.arduino import m1Digital_Write
from control.doors import setDoorState
from utils.tools import BreakCheck, log_event, wait
from control import remote_sensor_monitor as rsm
from control.houseLights import toggleHouseLights
from control import dimmer_controller as dim
import threading

# m1Digital_Write(33, 0)
# setDoorState(1, "OPEN")           # "CLOSED" / "CLOPEN" also supported
# play_audio("Basement", "Hit.wav", gain=1)  # threaded=True / looping=True
# if BreakCheck(): return
# while not rsm.obstructed("TOF2", block_mm=800, window_ms=250, min_consecutive=2):
#     if BreakCheck(): return
#     t.sleep(0.05)
# log_event("[Basement] Effect...")
# toggleHouseLights(True)  # False = OFF
# threading.Thread(target=function_name, daemon=True, name="Basement effect").start()

def run():
    log_event("[Basement] Starting...")

    try:
        # Room startup here
        house.Basement_state = "STANDBY"

        while house.HouseActive or house.Demo:
            if BreakCheck():
                break

            # Sequencing here
            while not house.Basement_state == "ACTIVE":
                if house.Demo or not house.HouseActive:
                    break
                wait(1)

            wait(15)

            setDoorState(5, "CLOSED")

            '''log_event("[Basement] Starting quick output test...")

            try:
                value=0
                for i in range(100):
                    value += 1
                    dim.dim(value, channel=7)
                for i in range(100):
                    value -= 1
                    dim.dim(value, channel=7)
            finally:
                dim.dim(0, channel=7)
                log_event("[Basement] Ambient Light 6 OFF (DIM7)")

            for pin, name in (
                (61, "Smoke Machine 3"),
                (49, "Laser Pneumatic 1"),
                (37, "Strobe 5"),
                (4, "Lightning Strip"),
                (3, "Spotlight"),
            ):
                if BreakCheck():
                    break
                try:
                    m1Digital_Write(pin, 0)
                    log_event(f"[Basement] {name} ON (D{pin})")
                    wait(1)
                finally:
                    m1Digital_Write(pin, 1)
                    log_event(f"[Basement] {name} OFF (D{pin})")
                wait(1)

            if not BreakCheck():
                try:
                    setDoorState(5, "CLOSED")
                    # Allow the 3-second PIR clear wait and 4-second travel.
                    wait(8)
                finally:
                    setDoorState(5, "OPEN")
                wait(1)

            log_event("[Basement] Quick output test finished.")'''

            dim.dim(30, channel=7)
            m1Digital_Write(3, 0) #spot

            wait(15)

            dim.dim(0, channel=7)
            m1Digital_Write(3, 1) #spot

            m1Digital_Write(4, 0) #lightning strip
            t.sleep(.7)
            m1Digital_Write(4, 1) #lightning strip
            t.sleep(.2)

            for i in range(2):
                m1Digital_Write(4, 0) #lightning strip
                t.sleep(.4)
                m1Digital_Write(4, 1) #lightning strip
                t.sleep(.2)

            wait(3)

            m1Digital_Write(37, 0) #strobe

            wait(5)

            setDoorState(6, "CLOPEN")

            wait(15)

            m1Digital_Write(37, 1) #strobe

            house.Basement_state = "STANDBY"

            if BreakCheck() or house.Demo:
                if house.Demo:
                    house.Demo = False
                    house.HouseActive = False
                    toggleHouseLights(True)
                break

            t.sleep(0.1)
    finally:
        house.Basement_state = "INACTIVE"
        log_event("[Basement] Exiting.")
