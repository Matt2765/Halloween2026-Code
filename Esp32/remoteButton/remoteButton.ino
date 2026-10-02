#include <HauntButtons.h>
// ===== PER-FLASH DEVICE CONFIGURATION =====
const char* DEVICE_ID = "BTN2";
const int BUTTON_PINS[] = {32}; // Each button connects GPIO to GND.
const uint8_t BUTTON_IDS[] = {1}; // Python uses one-based numbering.
constexpr uint32_t DEBOUNCE_MS = 30, HELD_REPORT_MS = 2000;
constexpr bool IDLE_SLEEP = true;
// Network/retries: libraries/HauntProtocol/src/HauntConfig.h
// ========================================
haunt::Buttons buttons;
void setup() {
  if(!buttons.begin(DEVICE_ID,BUTTON_PINS,BUTTON_IDS,sizeof(BUTTON_IDS),DEBOUNCE_MS,HELD_REPORT_MS,IDLE_SLEEP)) { delay(1000); ESP.restart(); }
}
void loop() { buttons.tick(); }
