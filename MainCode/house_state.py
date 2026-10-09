# house_state.py
class HouseState:
    def __init__(self):
        self.Boot = True
        self.HouseActive = False
        self.systemState = "OFFLINE"
        self.Demo = False
        self.SOUND = True
        self.testing = False
        self.houseLights = True
        self.remote_sensor_value = None

        self.CabinRoom_state = "INACTIVE"
        self.Bathroom_state = "INACTIVE"
        self.ShowerHallway_state = "INACTIVE"
        self.DynamicHallway_state = "INACTIVE"
        self.Basement_state = "INACTIVE"
        self.PalletHallway_state = "INACTIVE"
        self.ForestHallway_state = "INACTIVE"

        self.DoorState = {}
        self.TargetDoorState = {}

        self.smokeSequence = 1
        self.laserSequence = False

        self.DEBUG_INFO = True
        self.DEBUG_BREAKCHECK = True
        self.DISABLE_REMOTE_SENSOR_MONITOR = False # True disables ESP32 monitoring and its event logs
