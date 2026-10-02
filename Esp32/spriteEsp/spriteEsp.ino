#include <HauntProtocol.h>
using namespace haunt;
// ===== PER-FLASH DEVICE CONFIGURATION =====
const char* DEVICE_ID = "SPRITE1";
constexpr uint32_t SPR_BAUD = 9600;
constexpr int SPR_TX_PIN = 17, SPR_RX_PIN = 16;
constexpr uint8_t MAX_FILE_INDEX = 200, STARTUP_INDEX = 0;
constexpr uint32_t STATUS_MS = 2000;
// Network/retries: libraries/HauntProtocol/src/HauntConfig.h
// ========================================
Radio radio;
uint8_t currentIndex=STARTUP_INDEX;
uint32_t commandSession=0,commandSequence=0,lastStatus=0,lastDiagnostic=0;
void report() {
  auto p=radio.make(SPRITE,BRIDGE_ID,9); p.payload[0]=currentIndex;
  put32(p.payload+1,commandSession); put32(p.payload+5,commandSequence); radio.send(p);
  lastStatus=millis();
}
Code command(const Received& r) {
  const auto& p=r.packet;
  if(p.type!=COMMAND) return INVALID;
  auto peer=radio.registry.find(p.src); if(peer&&peer->conflict) return CONFLICT;
  uint8_t op=p.payload[4]; uint16_t index=get16(p.payload+5);
  if(op!=PLAY&&op!=NEXT) return INVALID;
  if(op==PLAY&&index>MAX_FILE_INDEX) return INVALID;
  if(Serial1.availableForWrite()<1) return QUEUE_FULL;
  uint8_t nextIndex=op==NEXT ? (currentIndex>=MAX_FILE_INDEX?0:currentIndex+1) : index;
  if(Serial1.write(nextIndex)!=1) return QUEUE_FULL;
  currentIndex=nextIndex; // Issued serial byte, not playback confirmation.
  commandSession=p.session; commandSequence=p.seq; report(); return ACCEPTED;
}
void setup() {
  Serial1.begin(SPR_BAUD,SERIAL_8N1,SPR_RX_PIN,SPR_TX_PIN);
  delay(100); Serial1.write(STARTUP_INDEX); // Preserve startup playback.
  if(!radio.begin(DEVICE_ID,command)) { delay(1000); ESP.restart(); }
  report();
}
void loop() {
  radio.poll();
  for(int i=0;i<32&&Serial1.available();i++) Serial1.read(); // No documented feedback decoder.
  uint32_t now=millis();
  if(now-lastStatus>=STATUS_MS) report();
  if(now-lastDiagnostic>=10000) { lastDiagnostic=now; radio.diagnostic(); }
  delay(1);
}
