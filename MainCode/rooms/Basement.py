import time as t
from context import house
from control.audio_manager import play_audio
from control.arduino import m1Digital_Write
from control.doors import setDoorState
from utils.tools import BreakCheck, log_event, wait, randMixedNum
from control import remote_sensor_monitor as rsm
from control.houseLights import toggleHouseLights
from control import dimmer_controller as dim
import threading
import random

_ambient_workers = {}
_ambient_lock = threading.RLock()


def stopAmbientFlicker(channel=None):
    """Stop one channel (or all with no argument), wait, and leave it OFF."""
    with _ambient_lock:
        channels = list(_ambient_workers) if channel is None else [channel]
        for ch in channels:
            entry = _ambient_workers.get(ch)
            if entry is not None:
                entry[0].set()
        for ch in channels:
            entry = _ambient_workers.get(ch)
            if entry is not None:
                entry[1].join(timeout=2)
                if entry[1].is_alive():
                    raise RuntimeError(f"Basement DIM{ch} flicker has not stopped yet")
                del _ambient_workers[ch]


def startAmbientFlicker(channel, ramp_seconds=0.0):
    """Start a stoppable worker; channel 7 can ramp its flicker up from OFF."""
    if type(channel) is not int or not 1 <= channel <= 8:
        raise ValueError("Dimmer channel must be 1..8")
    with _ambient_lock:
        stopAmbientFlicker(channel)
        stop_event = threading.Event()
        worker = threading.Thread(target=ambientFlicker,
                                  args=(channel, stop_event, ramp_seconds),
                                  daemon=True, name=f"Basement flicker DIM{channel}")
        _ambient_workers[channel] = (stop_event, worker)
        worker.start()
        return worker

# m1Digital_Write(33, 0)
# setDoorState(1, "OPEN")           # "CLOSED" / "CLOPEN" also supported
# play_audio("Basement", "Hit.wav", gain=1)  # threaded=True / looping=True
# if BreakCheck(): return
# distance_mm = rsm.get_TOF_value("TOF2")  # Millimeters; None if unavailable/stale
# log_event("[Basement] Effect...")
# toggleHouseLights(True)  # False = OFF
# threading.Thread(target=function_name, daemon=True, name="Basement effect").start()

def run():
    log_event("[Basement] Starting...")

    effect_stop = threading.Event()
    effect_threads = []
    try:
        # Room startup here
        house.Basement_state = "STANDBY"
        global spotThread
        global spotState
        global ambientLight

        while house.HouseActive or house.Demo:
            if BreakCheck():
                break

            # Sequencing here
            while not house.Basement_state == "ACTIVE":
                if house.Demo or not house.HouseActive:
                    break
                wait(1)  # 1 second polling interval until ACTIVE

            m1Digital_Write(3, 0)

            while rsm.get_TOF_value("TOF1") > 100:
                wait(1)

            play_audio("Basement", "basementExamplev3.wav", gain=1)
            play_audio("primary_LFE", "basementExamplev3.wav", gain=1)

            spotThread = True
            spotState = "FLICKERING"
            effect_stop = threading.Event()
            spot_worker = threading.Thread(target=flickeringSpot, args=(effect_stop,),
                                           daemon=True, name="Basement spotlight")
            effect_threads.append(spot_worker)
            spot_worker.start()

            ambientLight = True
            # stopAmbientFlicker(7) stops ambient; (3) stops wall cracks;
            # stopAmbientFlicker() stops both. Each call leaves that channel OFF.
            ambient_worker = startAmbientFlicker(7, ramp_seconds=7.0)
            effect_threads.append(ambient_worker)

            wait(9.5)  # 9.5s elapsed

            m1Digital_Write(49, 0) #shrine

            wait(2.5)  # 12s elapsed

            spotState = "OUT"

            wait(3)  # 15s elapsed

            setDoorState(5, "CLOSED")

            crack_worker = startAmbientFlicker(3)
            effect_threads.append(crack_worker)

            wait(3)

            m1Digital_Write(61, 0) #smoke machine

            wait(2.5)

            stopAmbientFlicker(7)

            wait(10)  # 30.5s elapsed

            m1Digital_Write(61, 1) #smoke machine

            wait(3)

            stopAmbientFlicker(3)

            wait(2.1)  # 35.1s elapsed

            wait(5)  # 40.1s elapsed

            m1Digital_Write(37, 0) #strobe

            setDoorState(6, "CLOPEN")

            wait(15)  # 55.1s elapsed

            m1Digital_Write(37, 1) #strobe

            effect_stop.set()
            stopAmbientFlicker()
            for worker in effect_threads:
                worker.join(timeout=2)
            effect_threads.clear()
            house.Basement_state = "STANDBY"

            m1Digital_Write(49, 1)

            if BreakCheck() or house.Demo:
                if house.Demo:
                    house.Demo = False
                    house.HouseActive = False
                    toggleHouseLights(True)
                break

            t.sleep(0.1)
    finally:
        spotThread = False
        ambientLight = False
        effect_stop.set()
        stopAmbientFlicker()
        for worker in effect_threads:
            worker.join(timeout=2)
        house.Basement_state = "INACTIVE"
        log_event("[Basement] Exiting.")

def flickeringSpot(stop_event=None):
    global spotThread, spotState
    stop_event = stop_event or threading.Event()
    try:
        while house.HouseActive or house.Demo:
            if not spotThread or stop_event.is_set() or BreakCheck():
                return
            for _ in range(random.randint(1, 5)):
                m1Digital_Write(3, 1)
                if stop_event.wait(randMixedNum(.05, .15)):
                    return
                m1Digital_Write(3, 0)
                if stop_event.wait(randMixedNum(.05, .15)):
                    return
            if spotState == "OUT":
                for _ in range(5):
                    m1Digital_Write(3, 0)
                    if stop_event.wait(randMixedNum(.05, .15)):
                        return
                    m1Digital_Write(3, 1)
                    if stop_event.wait(randMixedNum(.05, .2)):
                        return
                return
            if stop_event.wait(randMixedNum(.2, .8)):
                return
    finally:
        m1Digital_Write(3, 1)


def ambientFlicker(channel, stop_event=None, ramp_seconds=0.0):
    global ambientLight
    stop_event = stop_event or threading.Event()
    value = 20
    started = t.monotonic()

    def write_level(level):
        if channel == 7 and ramp_seconds > 0:
            progress = min(1.0, (t.monotonic() - started) / ramp_seconds)
            if progress < 1.0:
                # Build both brightness and flicker strength from near OFF.
                dim.dim(level * progress, channel=channel, fine=True)
                return
        dim.dim(level, channel=channel)

    try:
        if channel in (3, 7):
            # Intense flicker: wall cracks stay at least 20%; ambient can go OFF.
            floor = 20 if channel == 3 else 0
            while not stop_event.is_set() and not BreakCheck() and ambientLight:
                write_level(random.randint(floor, 65))
                if stop_event.wait(random.uniform(0.04, 0.12)):
                    return
            return

        while not stop_event.is_set() and not BreakCheck() and ambientLight:
            rand = random.randint(1, 5)
            for i in range(rand):
                value += 1
                write_level(value)
                if stop_event.wait(.01):
                    return
                #log_event(value)

            if BreakCheck():
                break

            for i in range(rand):
                value -= 1
                write_level(value)
                if stop_event.wait(.01):
                    return
                #log_event(value)

            if BreakCheck():
                break

            if value > 30:
                for i in range(10):
                    value -= 1
                    write_level(value)
                    if stop_event.wait(.01):
                        return
                    #log_event(value)
    finally:
        dim.dim(0, channel=channel)
