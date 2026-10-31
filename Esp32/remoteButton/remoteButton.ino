#include <HauntButtons.h>
// ===== PER-FLASH DEVICE CONFIGURATION =====
const char* DEVICE_ID = "BTN2";
constexpr int BUTTON_PINS[] = {32}; // Each button connects GPIO to GND.
const uint8_t BUTTON_IDS[] = {1}; // Python uses one-based numbering.
constexpr uint32_t DEBOUNCE_MS = 30, HELD_REPORT_MS = 2000;
constexpr bool IDLE_SLEEP = true;
constexpr bool ENABLE_LED_CONTROL = true; // Stays awake to receive rsm.led() commands.
constexpr int ONBOARD_LED_PIN = 2; // Original ESP32 onboard LED; change for your board.
constexpr int LED_PIN = 4; // External indicator output.
constexpr int LED_GND_PIN = 5; // External LED return, held LOW.
constexpr bool ONBOARD_LED_ACTIVE_HIGH = true;
constexpr bool LED_ACTIVE_HIGH = true;
constexpr bool DEFAULT_LED_ON = false;
// Network/retries: libraries/HauntProtocol/src/HauntConfig.h
// ========================================
haunt::Buttons buttons;
static_assert(!ENABLE_LED_CONTROL || (ONBOARD_LED_PIN!=LED_PIN &&
              ONBOARD_LED_PIN!=LED_GND_PIN && LED_PIN!=LED_GND_PIN &&
              ONBOARD_LED_PIN!=BUTTON_PINS[0] && LED_PIN!=BUTTON_PINS[0] &&
              LED_GND_PIN!=BUTTON_PINS[0]),"LED and button pins must be distinct");

void setLed(bool on) {
  digitalWrite(ONBOARD_LED_PIN,on==ONBOARD_LED_ACTIVE_HIGH?HIGH:LOW);
  digitalWrite(LED_PIN,on==LED_ACTIVE_HIGH?HIGH:LOW);
}

haunt::Code command(const haunt::Received& r) {
  const auto& p=r.packet;
  if(!ENABLE_LED_CONTROL || p.type!=haunt::COMMAND || p.length!=11 ||
     p.payload[4]!=haunt::LED || haunt::get16(p.payload+5)>1 ||
     haunt::get32(p.payload+7)!=0) return haunt::INVALID;
  setLed(haunt::get16(p.payload+5)!=0);
  return haunt::ACCEPTED;
}

void setup() {
  if(ENABLE_LED_CONTROL) {
    digitalWrite(LED_GND_PIN,LOW);
    pinMode(LED_GND_PIN,OUTPUT);
    pinMode(ONBOARD_LED_PIN,OUTPUT);
    pinMode(LED_PIN,OUTPUT);
    setLed(DEFAULT_LED_ON);
  }
  if(!buttons.begin(DEVICE_ID,BUTTON_PINS,BUTTON_IDS,sizeof(BUTTON_IDS),DEBOUNCE_MS,HELD_REPORT_MS,
                    IDLE_SLEEP,ENABLE_LED_CONTROL?command:nullptr)) { delay(1000); ESP.restart(); }
}
void loop() { buttons.tick(); }
