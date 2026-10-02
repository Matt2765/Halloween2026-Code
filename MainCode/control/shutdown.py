# control/shutdown.py
import time as t
from utils.tools import log_event
from context import house
from control.houseLights import toggleHouseLights
from control.audio_manager import play_audio, stop_all_audio
from control.arduino import m1Digital_Write
from utils.thread_diagnostics import dump_threads

def shutdown():
    log_event("[Shutdown] Executing shutdown routine...")

    house.HouseActive = False
    house.testing = False

    def _dim_off(ch: int):
        for fn_name in ("dim_set", "setDimLevel", "set_dimmer_level",
                        "dimmer_set", "set_dimmer", "setDimmer"):
            fn = globals().get(fn_name)
            if callable(fn):
                try:
                    fn(ch, 0)
                    return True
                except Exception:
                    pass
        return False

    # ---------------- Room_1 ----------------
    log_event("SHUTDOWN - Room_1:")
    m1Digital_Write(47, 1); log_event("+12v Door, Solenoid A OFF")

    # ---------------- Room_2 ----------------
    log_event("SHUTDOWN - Room_2:")
    m1Digital_Write(3, 1);  log_event("+120v Ambient Light 4 (G) OFF")

    # ---------------- Room_3 ----------------
    log_event("SHUTDOWN - Room_3:")
    m1Digital_Write(9,  1); log_event("+120v Strobe 2 (F) OFF")

    # ---------------- Room_4 ----------------
    log_event("SHUTDOWN - Room_4:")
    m1Digital_Write(45, 1); log_event("+12v Enemy Cannon Solenoid (L) OFF")

    # ---------------- Room_5 ----------------
    log_event("SHUTDOWN - Room_5:")
    m1Digital_Write(49, 1); log_event("+12v Barrel Solenoid (D) OFF")

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
