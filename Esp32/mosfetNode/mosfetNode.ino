#include <HauntProtocol.h>
using namespace haunt;
// ===== PER-FLASH DEVICE CONFIGURATION (original ESP32 Dev Module / WROOM) =====
const char* DEVICE_ID = "MOSFET1";
// All usable WROOM output GPIOs except UART0 (1,3), flash (6..11), input-only
// (34..39), and nonexistent pins. Remove entries to limit remotely usable pins.
// GPIO0,2,5,12,15 are boot-strapping pins: attached circuitry must preserve boot levels.
// GPIO16/17 are available on WROOM, but reserved for PSRAM on WROVER modules.
constexpr uint8_t OUTPUT_PINS[] = {0,2,4,5,12,13,14,15,16,17,18,19,21,22,23,25,26,27,32,33};
constexpr size_t OUTPUT_COUNT = sizeof(OUTPUT_PINS)/sizeof(OUTPUT_PINS[0]);
constexpr bool ACTIVE_HIGH = true;
constexpr uint32_t STATUS_MS = 1000;
constexpr bool SERIAL_DIAGNOSTICS = true; // Node-local USB debug output at 115200 baud.
// Outputs start OFF and latch until explicitly changed or the node restarts.
// Network, channel, retries and logical addressing: HauntConfig.h.
// ========================================================================
static_assert(OUTPUT_COUNT>0 && OUTPUT_COUNT<=20,"Configure 1..20 output pins");
constexpr bool usablePin(uint8_t pin) {
  return pin<=33 && pin!=1 && pin!=3 && !(pin>=6 && pin<=11) &&
         pin!=20 && pin!=24 && pin!=28 && pin!=29 && pin!=30 && pin!=31;
}
constexpr bool validPins() {
  for(size_t i=0;i<OUTPUT_COUNT;i++) {
    if(!usablePin(OUTPUT_PINS[i])) return false;
    for(size_t j=0;j<i;j++) if(OUTPUT_PINS[j]==OUTPUT_PINS[i]) return false;
  }
  return true;
}
static_assert(validPins(),"OUTPUT_PINS contains a duplicate or unavailable GPIO");
Radio radio;
uint64_t availablePins=0,onPins=0;
uint32_t lastStatus=0,lastDiagnostic=0,commandSession=0,commandSequence=0;
uint32_t reportsSent=0,reportSendFailures=0;
void report() {
  auto p=radio.make(MOSFET,BRIDGE_ID,24);
  put64(p.payload,availablePins); put64(p.payload+8,onPins);
  put32(p.payload+16,commandSession); put32(p.payload+20,commandSequence);
  if(radio.send(p)) reportsSent++; else reportSendFailures++;
  lastStatus=millis();
}
Code command(const Received& r) {
  const auto& p=r.packet;
  if(p.type!=COMMAND || p.length!=12 || p.payload[4]!=MOSFET_SET ||
     get16(p.payload+5)>1 || get32(p.payload+7)!=0 || p.payload[11]>=40) return INVALID;
  uint8_t pin=p.payload[11]; uint64_t bit=uint64_t(1)<<pin;
  if(!(availablePins&bit)) return INVALID;
  auto peer=radio.registry.find(p.src); if(peer&&peer->conflict) return CONFLICT;
  bool on=get16(p.payload+5)!=0;
  digitalWrite(pin,on==ACTIVE_HIGH?HIGH:LOW);
  if(on) onPins|=bit; else onPins&=~bit;
  commandSession=p.session; commandSequence=p.seq; report(); return ACCEPTED;
}
void setup() {
  if(SERIAL_DIAGNOSTICS) {
    Serial.begin(115200);
    delay(100);
    Serial.printf("[MOSFET] Boot id=%s network=0x%04X channel=%u outputs=%u\n",
                  DEVICE_ID,unsigned(NETWORK),unsigned(CHANNEL),unsigned(OUTPUT_COUNT));
  }
  for(auto pin:OUTPUT_PINS) {
    digitalWrite(pin,ACTIVE_HIGH?LOW:HIGH); // Set OFF before enabling output.
    pinMode(pin,OUTPUT); availablePins|=uint64_t(1)<<pin;
  }
  if(!radio.begin(DEVICE_ID,command)) {
    if(SERIAL_DIAGNOSTICS) Serial.println("[MOSFET] Radio initialization FAILED; restarting");
    delay(1000); ESP.restart(); return;
  }
  if(SERIAL_DIAGNOSTICS) Serial.printf("[MOSFET] Radio ready; session=%lu\n",(unsigned long)radio.session);
  report();
}
void loop() {
  radio.poll(); uint32_t now=millis();
  if(now-lastStatus>=STATUS_MS) report();
  if(now-lastDiagnostic>=10000) {
    lastDiagnostic=now; radio.diagnostic();
    if(SERIAL_DIAGNOSTICS) Serial.printf("[MOSFET] uptime_ms=%lu reports_sent=%lu send_failures=%lu last_command=%lu\n",
      (unsigned long)now,(unsigned long)reportsSent,(unsigned long)reportSendFailures,(unsigned long)commandSequence);
  }
  delay(2);
}
