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

_lightning_lock = threading.RLock()
_lightning_stop = threading.Event()
_lightning_done = threading.Event()
_lightning_done.set()
_lightning_worker = None
_lightning_audio = []


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

            while house.Bathroom_state != "ACTIVE":
                if BreakCheck():
                    break
                t.sleep(.5)

            while house.Bathroom_state != "STANDBY":
                if BreakCheck():
                    break
                t.sleep(.5)
            
            while(
                rsm.get_pir_state("PIR3")["triggered"] is False
            ):
                if BreakCheck():
                    break
                t.sleep(.5)

            if BreakCheck():
                break
            blastLightning(threaded=True)

            wait(3)

            dim(0, channel=4) #dynamic hallway green
            dim(0, channel=5) #dynamic hallway orange

            for i in range(150): #15 sec
                if rsm.get_button_value("BTN4"):
                    stopBlastLightning()
                    '''for i in range(10):
                        if not rsm.get_button_value("BTN4"):
                            break
                        t.sleep(.1)'''

                    stopBlastLightning()
                    
                    m1Digital_Write(23, 1) #dynamic hallway lanterns

                    m1Digital_Write(7, 0) #strobe

                    t.sleep(.25)

                    rsm.lantern(8, "strobe")

                    play_audio("DynamicHallway", "PZ-jumpscare3.wav", gain=1)

                    wait(2)

                    rsm.lantern(9, "flickering_on")

                    wait(8)

                    m1Digital_Write(7, 1) #strobe
                    break
                t.sleep(.1)
                if BreakCheck():
                    break

            if BreakCheck() or house.Demo:
                if house.Demo:
                    house.Demo = False
                    house.HouseActive = False
                    toggleHouseLights(True)
                break

            t.sleep(0.1)
    finally:
        stopBlastLightning()
        house.DynamicHallway_state = "INACTIVE"
        log_event("[DynamicHallway] Exiting.")

def _lightning_wait(stop_event, seconds):
    """Explicit stops wake immediately; house cancellation is checked every 20 ms."""
    deadline = t.monotonic() + seconds
    while not stop_event.is_set() and not BreakCheck():
        remaining = deadline - t.monotonic()
        if remaining <= 0:
            return True
        stop_event.wait(min(remaining, 0.02))
    return False


def _stop_lightning_audio(handles):
    for handle in handles:
        if handle is not None and not handle.done.is_set():
            handle.stop()


def _run_lightning(count, stop_event, done, handles):
    try:
        for _ in range(count):
            if not _lightning_wait(stop_event, 0):
                return
            began = t.monotonic()
            log_event("[DynamicHallway] Lightning bolt triggered")
            audio = random.choice(("thunder1.wav", "thunder2.wav", "thunder3.wav", "thunder4.wav"))
            handles.append(play_audio("DynamicHallway", audio, gain=1, threaded=True, deduplicate=False))
            for level, seconds in ((0, .1), (1, 1.1), (0, .07), (1, .5), (0, .07), (1, 0)):
                if not _lightning_wait(stop_event, 0):
                    return
                m1Digital_Write(4, level)  # Active LOW lightning relay.
                if not _lightning_wait(stop_event, seconds):
                    return
            # Preserve three seconds between bolt starts without detached children.
            if count > 1 and not _lightning_wait(stop_event, max(0, 3 - (t.monotonic() - began))):
                return
    except Exception:
        stop_event.set()
        raise
    finally:
        try:
            m1Digital_Write(4, 1)
        finally:
            try:
                if stop_event.is_set() or BreakCheck():
                    _stop_lightning_audio(handles)
            finally:
                done.set()


def stopBlastLightning():
    """Cancel flashes and their thunder, wait for cleanup, and leave lightning OFF."""
    with _lightning_lock:
        _lightning_stop.set()
        if _lightning_worker is not threading.current_thread():
            if not _lightning_done.wait(timeout=2):
                raise RuntimeError("Dynamic Hallway lightning has not stopped yet")
        _stop_lightning_audio(_lightning_audio)


def _start_lightning(count, threaded):
    global _lightning_stop, _lightning_done, _lightning_worker, _lightning_audio
    with _lightning_lock:
        stopBlastLightning()
        stop_event, done, handles = threading.Event(), threading.Event(), []
        _lightning_stop, _lightning_done, _lightning_audio = stop_event, done, handles
        if threaded:
            worker = threading.Thread(target=_run_lightning, args=(count, stop_event, done, handles),
                                      daemon=True, name="DynamicHallway lightning")
            _lightning_worker = worker
            try:
                worker.start()
            except Exception:
                done.set()
                raise
            return worker
        _lightning_worker = threading.current_thread()
    _run_lightning(count, stop_event, done, handles)


def lightning_bolt(threaded=False):
    """One stoppable bolt; stopBlastLightning() also cancels this entry point."""
    return _start_lightning(1, threaded)


def blastLightning(threaded=False):
    """Seven bolts, three seconds apart. Use threaded=True for background playback.

    stopBlastLightning() interrupts flashes, gaps and this effect's own audio.
    Starting again replaces any previous lightning worker.
    """
    return _start_lightning(7, threaded)
