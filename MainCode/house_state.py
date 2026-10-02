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
        self.FRthreadRunning = False
        self.remote_sensor_value = None

        self.Room_1_state = "INACTIVE"
        self.Room_2_state = "INACTIVE"
        self.Room_3_state = "INACTIVE"
        self.Room_4_state = "INACTIVE"
        self.Room_5_state = "INACTIVE"

        self.DoorState = {}
        self.TargetDoorState = {}

        self.smokeSequence = 1
        self.laserSequence = False

        self.DEBUG_INFO = False
        self.DEBUG_BREAKCHECK = True
        self.DISABLE_REMOTE_SENSOR_MONITOR = False # set to true if you want to avoid spam when esp32 disconnected