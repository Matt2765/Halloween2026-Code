# control/arduino.py
import time as t
from pymata4 import pymata4
from utils.tools import log_event
from context import house

M1PORT = "COM4"
M1 = None
M1_available = False


def m1Digital_Write(pin, value):
    """Write HIGH(1)/LOW(0) to a digital pin number (0–69 on Mega)."""
    if M1_available:
        try:
            M1.digital_write(pin, 1 if value else 0)
        except Exception as e:
            log_event(f"[Arduino] digital_write({pin},{value}) failed: [{e}]")
    else:
        log_event(f"[Arduino] (Simulated) m1Digital_Write(pin={pin}, value={value})")


def connectArduino():
    """Connect to Arduino Mega via Firmata and configure all pins 2–69 as digital outputs."""
    global M1, M1_available
    log_event("[Arduino] Attempting to establish connection with Arduino Mega...")

    try:
        # Ensure StandardFirmata or StandardFirmataPlus is flashed
        M1 = pymata4.Pymata4(com_port=M1PORT, baud_rate=57600, sleep_tune=0.3)
        log_event(f"[Arduino] Communication to board on {M1PORT} successfully started.")
        M1_available = True
    except Exception as e:
        log_event(f"[Arduino] Board not found on {M1PORT}. Error: [{e}]")
        M1_available = False
        return

    try:
        for i in range(1, 71):  # Sets all digital pins as outputs for M1
            #  if i == 14 or i == 15:      #Pins we do not want to edit
            #      pass
            # else:
            M1.set_pin_mode_digital_output(i)

        log_event("[Arduino] All pins 2–69 configured as digital outputs (A0–A15 included).")
    except Exception as e:
        log_event(f"[Arduino] Error during pin configuration: [{e}]")

    t.sleep(0.3)
