# control/shutdown.py
import time as t
from utils.tools import log_event
from context import house
from control.houseLights import toggleHouseLights
from control.audio_manager import play_audio, stop_all_audio
from control.arduino import m1Digital_Write
from utils.thread_diagnostics import dump_threads
from control.animatronic_service import stop_all
from control.doors import DOOR_SOLENOID_PINS, apply_door_shutdown_state
from control.dimmer_controller import dim
from control.group_flow import flow

def shutdown():
    log_event("[Shutdown] Executing shutdown routine...")

    house.HouseActive = False
    flow.stop()
    house.testing = False
    for door in DOOR_SOLENOID_PINS:
        apply_door_shutdown_state(door)
    stop_all()

    # DIM1 Cabin ambient, DIM2 Grandma, DIM3 Basement wall cracks,
    # DIM4/5 Dynamic Hallway ambient, DIM6 Bathroom ambient,
    # DIM7 Basement ambient, DIM8 Pallet Hallway ambient.
    for i in range(1, 9):
        dim(0, channel=i)

    # ---------------- Cabin Room ----------------
    log_event("SHUTDOWN - Cabin Room:")
    m1Digital_Write(43, 1); log_event("+12v Air Blast 1 (E) OFF")
    m1Digital_Write(47, 1); log_event("+12v Air Blast 2 (B) OFF")
    m1Digital_Write(22, 0); log_event("+120v Strobe 1 (B) OFF")
    m1Digital_Write(26, 1); log_event("+120v Lanterns 1 (B) OFF")
    m1Digital_Write(24, 1); log_event("+120v Lanterns 2 (B) OFF")
    m1Digital_Write(28, 1); log_event("+120v Lightning (C) OFF")
    m1Digital_Write(5, 1); log_event("+120v Porch Lights (G) OFF")
    m1Digital_Write(6, 1); log_event("+120v Fire Light (C) OFF")
    m1Digital_Write(59, 1); log_event("Chimney Smoke Machine (G) OFF")
    m1Digital_Write(51, 1); log_event("+12v Rocking Chair (A) OFF")

    # ---------------- Shower Hallway ----------------
    log_event("SHUTDOWN - Shower Hallway:")
    m1Digital_Write(32, 1); log_event("+120v Strobe 4 (M) OFF")
    m1Digital_Write(34, 1); log_event("+120v Shower Light (M) OFF")
    m1Digital_Write(36, 1); log_event("+120v Lanterns (M) OFF")

    # ---------------- Basement ----------------
    log_event("SHUTDOWN - Basement:")
    m1Digital_Write(61, 1); log_event("Smoke Machine 3 (N) OFF")
    m1Digital_Write(49, 1); log_event("+12v Shrine Solenoid (D) OFF")
    m1Digital_Write(37, 1); log_event("+120v Strobe 5 (N) OFF")
    m1Digital_Write(3, 1); log_event("+120v Spotlight (D) OFF")

    # ---------------- Bathroom ----------------
    log_event("SHUTDOWN - Bathroom:")
    m1Digital_Write(35, 1); log_event("+120v Strobe 2 (F) OFF")
    m1Digital_Write(33, 1); log_event("+120v Mirror Light (F) OFF")
    m1Digital_Write(31, 1); log_event("+120v Magic Light (F) OFF")

    # ---------------- Dynamic Hallway ----------------
    log_event("SHUTDOWN - Dynamic Hallway:")
    m1Digital_Write(9, 1); log_event("+120v Blacklights (I) OFF")
    m1Digital_Write(4, 1); log_event("+120v Lightning Strip (D) OFF")
    m1Digital_Write(7, 1); log_event("+120v Strobe (J) OFF")
    m1Digital_Write(23, 1); log_event("+120v Lanterns (I) OFF")
    # Pending pin assignment: smoke machine 2 (J).

    # ---------------- Pallet Hallway ----------------
    log_event("SHUTDOWN - Pallet Hallway:")
    m1Digital_Write(29, 1); log_event("+120v Strobe 3 (K) OFF")
    m1Digital_Write(27, 1); log_event("+120v Pallet Backlight (K) OFF")
    m1Digital_Write(25, 1); log_event("+120v Blacklight (K) OFF")

    # ---------------- Forest Hallway ----------------
    log_event("SHUTDOWN - Forest Hallway:")
    m1Digital_Write(57, 1); log_event("Smoke Machine 6 (P) OFF")
    m1Digital_Write(8, 1); log_event("+120v Strobe (P) OFF")
    m1Digital_Write(42, 1); log_event("+12v Prop Drop (P) OFF")
    m1Digital_Write(56, 1); log_event("+5v Lasers (Q) OFF")

    # ---------------- Graveyard ----------------
    log_event("SHUTDOWN - Graveyard:")
    m1Digital_Write(58, 1); log_event("Industrial Smoke Machine 5 (L) OFF")

    t.sleep(1)
    toggleHouseLights(True)

def shutdownDetector():
    while house.systemState == "ONLINE":
        t.sleep(1)

    t.sleep(1)

    if house.systemState == "EmergencyShutoff":
        log_event("EMERGENCY SHUTDOWN DETECTED - Please type keyword 'SAFE' into terminal to return to standby mode.")
        stop_all_audio()
        #t.sleep(.1)
        play_audio("emergency shutdown activated", gain=.7)
        shutdown()
        for _ in range(3):
            toggleHouseLights(False)
            t.sleep(0.25)
            toggleHouseLights(True)
            t.sleep(0.25)
        while True:
            input1 = input().upper()
            if input1 == "SAFE":
                play_audio(f"returning to standby in 5 seconds", gain=0.7)
                for a in range(5, 0, -1):
                    log_event(f"Returning to standby in {a} seconds.")
                    t.sleep(1)
                house.systemState = "REBOOT"
                play_audio("system rebooting", gain=0.1)
                break
            else:
                log_event("Invalid command. Please type keyword 'SAFE' into terminal to return to standby mode.")

    elif house.systemState == "SoftShutdown":
        log_event("SOFT SHUTDOWN DETECTED - Systems will be restarted to standby.")
        stop_all_audio()
        #t.sleep(1)
        play_audio("soft shutdown activated", gain=.3)
        shutdown()
        for _ in range(3):
            toggleHouseLights(False)
            t.sleep(0.25)
            toggleHouseLights(True)
            t.sleep(0.25)
        play_audio(f"returning to standby in 5 seconds", gain=.3)
        for a in range(5, 0, -1):
            log_event(f"Returning to standby in {a} seconds.")
            t.sleep(1)
        #dump_threads()
        house.systemState = "REBOOT"
        play_audio("system rebooting", gain=0.3)

    else:
        log_event("Shutdown ID unknown - Please type keyword 'SAFE' into terminal to return to standby mode.")
        stop_all_audio()
        #t.sleep(.2)
        play_audio("unknown shutdown detected", gain=0.7)
        shutdown()
        while True:
            input1 = input().upper()
            if input1 == "SAFE":
                house.systemState = "REBOOT"
                break
            else:
                log_event("Invalid command. Please type keyword 'SAFE' into terminal to return to standby mode.")
