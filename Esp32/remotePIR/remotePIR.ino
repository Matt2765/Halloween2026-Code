#include <HauntProtocol.h>
#include <esp_system.h>
using namespace haunt;
// ===== PER-FLASH DEVICE CONFIGURATION =====
const char* DEVICE_ID = "PIR4";
constexpr int PIR_PIN = 13; // HC-SR501 OUT; common ground, module VCC from 5V
constexpr uint32_t WARMUP_MS = 60000, STATUS_MS = 2000;
constexpr bool SERIAL_DEBUG = true; // USB diagnostics only; independent of Python DEBUG_INFO.
constexpr uint32_t DEBUG_BAUD = 115200;
// Network/retries: libraries/HauntProtocol/src/HauntConfig.h
// ========================================
Radio radio;
bool output=false,ready=false;
uint32_t bootMs=0,lastStatus=0,lastDiagnostic=0;
void delivery(const Packet& p,Code code,uint32_t elapsed) {
  if(!SERIAL_DEBUG) return;
  Serial.printf("[PIR] Delivery seq=%lu result=%u elapsed=%lu ms (0=bridge ACK, 1=invalid, 3=wrong session, 4=ID conflict, 6=unconfirmed)\n",
                (unsigned long)p.seq,unsigned(code),(unsigned long)elapsed);
}
void report(bool transition) {
  auto p=radio.make(PIR,BRIDGE_ID,2,transition);
  p.payload[0]=output; p.payload[1]=ready;
  bool submitted=radio.send(p);
  if(SERIAL_DEBUG) {
    uint32_t elapsed=millis()-bootMs;
    Serial.printf("[PIR] %s seq=%lu GPIO%d=%s %s warmup_left=%lu ms submit=%s (%s)\n",
                  transition?"transition":"status",(unsigned long)p.seq,PIR_PIN,
                  output?"HIGH":"LOW",ready?"ready":"warming",
                  (unsigned long)(elapsed>=WARMUP_MS?0:WARMUP_MS-elapsed),
                  submitted?"OK":"FAILED",transition?"queued; awaiting bridge ACK":"local send only; no ACK requested");
  }
  if(!submitted) radio.diagnostic();
}
void setup() {
  if(SERIAL_DEBUG) {
    Serial.begin(DEBUG_BAUD);
    Serial.printf("\n[PIR] Boot id=%s pin=%d reset_reason=%u fw=%s network=0x%04X channel=%u\n",
                  DEVICE_ID,PIR_PIN,unsigned(esp_reset_reason()),FIRMWARE,unsigned(NETWORK),unsigned(CHANNEL));
    Serial.println("[PIR] Initializing ESP-NOW radio...");
  }
  pinMode(PIR_PIN,INPUT);
  if(!radio.begin(DEVICE_ID,nullptr,delivery)) {
    if(SERIAL_DEBUG) { Serial.println("[PIR] ERROR: radio.begin failed; restarting in 1 second"); Serial.flush(); }
    delay(1000); ESP.restart();
  }
  if(SERIAL_DEBUG) {
    Serial.printf("[PIR] Radio ready MAC=%s session=%lu; warm-up=%lu ms\n",
                  WiFi.macAddress().c_str(),(unsigned long)radio.session,(unsigned long)WARMUP_MS);
    Serial.println("[PIR] Status every 2s. Local submit OK does not prove bridge reception.");
  }
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
  if(now-lastDiagnostic>=10000) {
    lastDiagnostic=now; radio.diagnostic();
    if(SERIAL_DEBUG) Serial.printf("[PIR] Counters send_errors=%lu retries=%lu unconfirmed=%lu drops=%lu malformed_rx=%lu conflicts=%lu\n",
                                  (unsigned long)radio.stats.sendErrors,(unsigned long)radio.stats.retries,
                                  (unsigned long)radio.stats.unconfirmed,(unsigned long)radio.stats.drops,
                                  (unsigned long)radio.stats.malformed,(unsigned long)radio.stats.conflicts);
  }
  delay(2);
}
