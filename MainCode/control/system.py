# control/system.py
import time as t
import threading
import multiprocessing

from rooms import Room_1, Room_2, Room_3, Room_4, Room_5
from context import house
from control.audio_manager import initialize_audio, play_audio
from control.arduino import connectArduino
from control.shutdown import shutdownDetector
from control.doors import setDoorState
from control.houseLights import toggleHouseLights
from control import remote_sensor_monitor
from ui.gui import MainGUI
from ui.http_server import HTTP_SERVER
from utils.tools import log_event, BreakCheck
from control.doors import spawn_doors
import control.dimmer_controller as dim
from control.shutdown import shutdown
import random

def initialize_system():
    while True:
        if house.Boot:
            log_event("[System] Initializing persistent services...")

            # Initialize hardware
            connectArduino()
            dim.init()

            # PortAudio/WASAPI streams must be created here on the main thread,
            # before GUI callbacks and room worker threads request playback.
            initialize_audio()
            
            t.sleep(1)

            shutdown()

            # Launch core services
            threading.Thread(target=HTTP_SERVER, daemon=True, name="HTTP SERVER").start()
            threading.Thread(target=MainGUI, daemon=True, name="GUI").start()
            
            remote_sensor_monitor.init(port="COM6", baud=921600)

            house.Boot = False
            
        log_event("[System] Initializing non-persistent services...")

        spawn_doors()

        t.sleep(0.2)
        house.systemState = "ONLINE"

        toggleHouseLights(True)
        
        log_event("[System] Initialization complete. System is ONLINE.")
            
        threading.Thread(target=shutdownDetector, daemon=True, name="Shutdown Detector").start()
        
        t.sleep(1)
        
        while house.systemState == "ONLINE":
            t.sleep(1)
        
        log_event("[System] All non-persistent services stopped. Most likely due to shutdown.")
            
        while house.systemState != "REBOOT":
            t.sleep(1) 

def StartHouse():
    if not house.HouseActive and house.systemState == "ONLINE":
        play_audio("starting house", gain=0.1)
        log_event("[System] Launching main sequence...")
        house.HouseActive = True

        setDoorState(1, "CLOSED")
        setDoorState(2, "CLOSED")
        t.sleep(1)
        toggleHouseLights(False)
        setDoorState(2, "OPEN")

        threading.Thread(
            target=Room_5.run, 
            args=(), 
            daemon=True,
            name=Room_5.__name__.split('.')[-1]
        ).start()

        threading.Thread(
            target=Room_1.run, 
            args=(), 
            daemon=True, 
            name=Room_1.__name__.split('.')[-1]
        ).start()
        
        threading.Thread(
            target=Room_2.run, 
            args=(), 
            daemon=True, 
            name=Room_2.__name__.split('.')[-1]
        ).start()
        
        threading.Thread(
            target=Room_3.run, 
            args=(), 
            daemon=True, 
            name=Room_3.__name__.split('.')[-1]
        ).start()
        
        threading.Thread(
            target=Room_4.run, 
            args=(), 
            daemon=True, 
            name=Room_4.__name__.split('.')[-1]
        ).start()

        noScareDetector(threaded=True)

        while house.HouseActive:
            if BreakCheck():
                break
            t.sleep(.1)

        log_event("[System] Main sequence ended.")
    else:
        if not house.HouseActive and house.systemState != "ONLINE":
            log_event("[System] Cannot start house while it is in a shutdown state.")
        else:
            log_event("[System] House is already active. Please stop the house before attemping to re-start it.")

def noScareDetector(threaded=False):
    no_scare_files = [
    "noScare1.wav",
    "noScare2.wav",
    "noScare3.wav",
    "noScare4.wav",
    "noScare5.wav",
    "noScare6.wav",
    "noScare7.wav",
    "noScare8.wav",
    "noScare9.wav",
    "noScare10.wav",
    "noScare11.wav"
    ]

    def main():
        while remote_sensor_monitor.get_button_value("BTN3") is not True:
            t.sleep(.05)
            if BreakCheck():
                return

        t.sleep(3)

        while remote_sensor_monitor.get_button_value("BTN3") is not True:
            audio = random.choice(no_scare_files)
            play_audio(audio, threaded=True, gain=1.5)

            for i in range(200): #15 secs
                if remote_sensor_monitor.get_button_value("BTN3") is True:
                    break
                t.sleep(.05)
                if BreakCheck():
                    return
                
        for i in range(5):
            t.sleep(1)
            if BreakCheck():
                return
            
    if threaded:
        threading.Thread(target=main, daemon=True, name="no scare detector").start()
    else:
        main()
        
