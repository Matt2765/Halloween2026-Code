# control/lights.py
from context import house
from control.arduino import m1Digital_Write
from utils.tools import log_event
from control import dimmer_controller as dim

# Define the pin numbers for the house lights followed by the digital value that determines their ON state.
house_light_pins = {
    2: 0,
    23: 0,
    22: 1
}

def toggleHouseLights(enable: bool = None):
    """
    Toggles or sets the house lights.
    - If 'enable' is True, turns lights ON.
    - If 'enable' is False, turns lights OFF.
    - If 'enable' is None (default), toggles the current state.
    """
    if enable is None:
        enable = not house.houseLights

    log_event(f"[Lights] House lights {'ON' if enable else 'OFF'}")
    house.houseLights = enable
    
    for pin, on_value in house_light_pins.items():
        m1Digital_Write(pin, on_value if enable else (1 - on_value))
        
    dim.dim(100 if enable else 0)
