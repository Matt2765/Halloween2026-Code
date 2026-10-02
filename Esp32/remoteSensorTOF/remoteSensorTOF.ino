#include <HauntProtocol.h>
#include <Wire.h>
#include <Adafruit_VL53L1X.h>
using namespace haunt;
// ===== PER-FLASH DEVICE CONFIGURATION =====
const char* DEVICE_ID = "TOF1";
constexpr int I2C_SDA = 21, I2C_SCL = 22;
constexpr uint32_t REPORT_MS = 100;
constexpr uint16_t TIMING_BUDGET_MS = 100;
constexpr uint16_t DISTANCE_MODE = 1; // 1 = short, 2 = long.
// Network/retries: libraries/HauntProtocol/src/HauntConfig.h
// ========================================
Radio radio;
Adafruit_VL53L1X vl;
bool sensorReady=false;
uint32_t lastReport=0,lastDiagnostic=0;
void setup() {
  Serial.begin(115200);
  if(!radio.begin(DEVICE_ID,nullptr)) { delay(1000); ESP.restart(); }
  Wire.begin(I2C_SDA,I2C_SCL); Wire.setTimeOut(20);
  sensorReady=vl.begin(0x29,&Wire);
  if(sensorReady) {
    // Make the ranging profile explicit. A 100 ms timing budget is the
    // longest budget that can sustain the installation's 10 Hz update rate.
    sensorReady=vl.VL53L1X_SetDistanceMode(DISTANCE_MODE)==0 &&
                vl.VL53L1X_SetTimingBudgetInMs(TIMING_BUDGET_MS)==0 &&
                vl.startRanging();
  }
}
void loop() {
  radio.poll(); uint32_t now=millis();
  if(now-lastReport>=REPORT_MS) {
    lastReport=now;
    int16_t distance=-1,status=-3; bool valid=false;
    if(sensorReady) {
      status=-2; // No new measurement. Never reuse an old distance as clear.
      if(vl.dataReady()) {
        uint8_t rangeStatus=255;
        uint16_t rawDistance=0;
        auto rangeError=vl.VL53L1X_GetRangeStatus(&rangeStatus);
        auto distanceError=vl.VL53L1X_GetDistance(&rawDistance);
        status=rangeError ? -4 : distanceError ? -5 : rangeStatus;
        if(!distanceError && rawDistance<=INT16_MAX) distance=int16_t(rawDistance);
        valid=!rangeError && !distanceError && distance>=0 && status==0;
        vl.clearInterrupt();
      }
    }
    // Retry only the current snapshot; the radio replaces it at the next report
    // and expires it after 100 ms even if the sensor loop stalls.
    auto p=radio.make(TOF,BRIDGE_ID,5,true);
    p.payload[0]=valid; put16(p.payload+1,uint16_t(distance)); put16(p.payload+3,uint16_t(status)); radio.send(p);
  }
  if(now-lastDiagnostic>=10000) { lastDiagnostic=now; radio.diagnostic(); }
  delay(1);
}
