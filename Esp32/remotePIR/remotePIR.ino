#include <HauntProtocol.h>
using namespace haunt;
// ===== PER-FLASH DEVICE CONFIGURATION =====
const char* DEVICE_ID = "PIR1";
constexpr int PIR_PIN = 27; // HC-SR501 OUT; common ground, module VCC from 5V
constexpr uint32_t WARMUP_MS = 60000, STATUS_MS = 2000;
// Network/retries: libraries/HauntProtocol/src/HauntConfig.h
// ========================================
Radio radio;
bool output=false,ready=false;
uint32_t bootMs=0,lastStatus=0,lastDiagnostic=0;
void report(bool transition) {
  auto p=radio.make(PIR,BRIDGE_ID,2,transition);
  p.payload[0]=output; p.payload[1]=ready;
  if(!radio.send(p)) radio.diagnostic();
}
void setup() {
  pinMode(PIR_PIN,INPUT);
  if(!radio.begin(DEVICE_ID,nullptr)) { delay(1000); ESP.restart(); }
  bootMs=millis(); output=digitalRead(PIR_PIN)==HIGH; report(false);
}
void loop() {
  radio.poll(); uint32_t now=millis();
  bool newReady=ready || now-bootMs>=WARMUP_MS;
  bool value=digitalRead(PIR_PIN)==HIGH;
  if(value!=output || newReady!=ready) {
    output=value; ready=newReady; report(true); // Honest output even during warm-up.
  }
  if(now-lastStatus>=STATUS_MS) { lastStatus=now; report(false); }
  if(now-lastDiagnostic>=10000) { lastDiagnostic=now; radio.diagnostic(); }
  delay(2);
}
