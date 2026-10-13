#include <HauntProtocol.h>
#include <driver/ledc.h>
using namespace haunt;

// ===== PER-FLASH DEVICE CONFIGURATION =====
const char* DEVICE_ID = "DROPDOWN1"; // Unique on the network; used in RSM calls.
constexpr int SERVO_PIN = 4;
constexpr int BUTTON_PIN = 5; // Connect button between GPIO 5 and GPIO 6 (or GND).
constexpr int BUTTON_GND_PIN = 6; // Held LOW for button return only; not a power ground.
constexpr int LED_PIN = 8; // Blue onboard LED on ESP32-C3 Super Mini.
constexpr bool LED_ACTIVE_HIGH = false; // Super Mini's blue LED lights when LOW.
constexpr bool DEFAULT_LED_ON = false;
constexpr int DEFAULT_ANGLE = 90, MIN_ANGLE = 0, MAX_ANGLE = 180;
constexpr int SERVO_MIN_US = 500, SERVO_MAX_US = 2500;
constexpr uint32_t DEBOUNCE_MS = 30;
constexpr uint32_t MOVING_REPORT_MS = 200, IDLE_REPORT_MS = 2000;
constexpr uint32_t DIAGNOSTIC_MS = 10000;
constexpr const char* NODE_BUILD = "dropdown-2026-10-12-r2";
constexpr uint32_t USB_DIAGNOSTIC_MS = 1000;
// Network/retries: libraries/HauntProtocol/src/HauntConfig.h
// This powered actuator stays awake so it can always receive servo/LED commands.
// ========================================
static_assert(SERVO_PIN!=BUTTON_PIN && SERVO_PIN!=LED_PIN && BUTTON_PIN!=LED_PIN,"Pins must be distinct");
static_assert(BUTTON_GND_PIN!=SERVO_PIN && BUTTON_GND_PIN!=BUTTON_PIN && BUTTON_GND_PIN!=LED_PIN,"Button return pin must be distinct");
static_assert(0<=MIN_ANGLE && MIN_ANGLE<=DEFAULT_ANGLE && DEFAULT_ANGLE<=MAX_ANGLE && MAX_ANGLE<=180,"Invalid angle limits");
static_assert(0<SERVO_MIN_US && SERVO_MIN_US<SERVO_MAX_US && SERVO_MAX_US<20000,"Invalid PWM limits");

Radio radio;
Ramp ramp;
Debounced button;
bool ledOn=DEFAULT_LED_ON, initialButton=true;
int bootAngle=DEFAULT_ANGLE;
uint32_t commandSession=0,commandSequence=0,lastStatus=0,lastDiagnostic=0,buttonBegan=0;
uint32_t reportCount=0,commandCount=0,lastUsbDiagnostic=0,lastLoop=0,maxLoopGap=0;
int angleToUs(int angle) { return SERVO_MIN_US+(SERVO_MAX_US-SERVO_MIN_US)*angle/180; }
int usToAngle(int us) { return ((us-SERVO_MIN_US)*180+(SERVO_MAX_US-SERVO_MIN_US)/2)/(SERVO_MAX_US-SERVO_MIN_US); }
void output() {
  // C3 supports low-speed LEDC only, with a maximum 14-bit resolution.
  uint32_t duty=uint32_t((int64_t(ramp.current)*16383+10000)/20000);
  ledc_set_duty(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0,duty);
  ledc_update_duty(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0);
}
void setLed(bool on) {
  ledOn=on;
  digitalWrite(LED_PIN,(on==LED_ACTIVE_HIGH)?HIGH:LOW);
}
void report(bool edge=false) {
  // Idle availability must not depend on a single unacknowledged broadcast.
  // Moving snapshots remain replaceable; initial/button edges always retry.
  auto p=radio.make(DROPDOWN,BRIDGE_ID,19,edge || !ramp.moving());
  put16(p.payload,usToAngle(ramp.current)); put16(p.payload+2,usToAngle(ramp.target)); p.payload[4]=ramp.moving();
  put16(p.payload+5,ramp.current); put32(p.payload+7,commandSession); put32(p.payload+11,commandSequence);
  put16(p.payload+15,0xffff); // No shaft sensor: angles describe generated PWM.
  p.payload[17]=button.stable; p.payload[18]=ledOn;
  if(!radio.send(p)) radio.diagnostic();
  reportCount++;
  lastStatus=millis();
}
Code command(const Received& r) {
  const auto& p=r.packet; if(p.type!=COMMAND || p.length!=11) return INVALID;
  commandCount++;
  auto peer=radio.registry.find(p.src); if(peer&&peer->conflict) return CONFLICT;
  auto op=p.payload[4]; int value=get16(p.payload+5); uint32_t ms=get32(p.payload+7);
  if(op==LED) {
    if(value>1 || ms!=0) return INVALID;
    setLed(value);
  } else {
    if((op!=MOVE&&op!=SET_DEFAULT)||value<MIN_ANGLE||value>MAX_ANGLE||ms>30000) return INVALID;
    if(op==SET_DEFAULT) {
      Preferences prefs;
      if(!prefs.begin("servo",false)) return INVALID;
      bool saved=prefs.putInt("boot_deg",value)==4; prefs.end();
      if(!saved) return INVALID;
      bootAngle=value; ms=300;
    }
    ramp.move(angleToUs(value),ms,millis()); output();
    commandSession=p.session; commandSequence=p.seq; // Associated servo command, as on servoNode.
  }
  if(!initialButton) report();
  return ACCEPTED;
}
void setup() {
  Serial.begin(115200); // Optional native USB diagnostics; never wait for a host.
  digitalWrite(BUTTON_GND_PIN,LOW);
  pinMode(BUTTON_GND_PIN,OUTPUT);
  pinMode(BUTTON_PIN,INPUT_PULLUP);
  pinMode(LED_PIN,OUTPUT); setLed(DEFAULT_LED_ON);
  ledc_timer_config_t timer{};
  timer.speed_mode=LEDC_LOW_SPEED_MODE; timer.timer_num=LEDC_TIMER_0;
  timer.duty_resolution=LEDC_TIMER_14_BIT; timer.freq_hz=50; timer.clk_cfg=LEDC_AUTO_CLK;
  ledc_timer_config(&timer);
  ledc_channel_config_t channel{};
  channel.gpio_num=SERVO_PIN; channel.speed_mode=LEDC_LOW_SPEED_MODE; channel.channel=LEDC_CHANNEL_0;
  channel.timer_sel=LEDC_TIMER_0; channel.intr_type=LEDC_INTR_DISABLE; ledc_channel_config(&channel);
  Preferences prefs;
  if(prefs.begin("servo",true)) { bootAngle=prefs.getInt("boot_deg",DEFAULT_ANGLE); prefs.end(); }
  bootAngle=constrain(bootAngle,MIN_ANGLE,MAX_ANGLE);
  ramp.move(angleToUs(bootAngle),0,millis()); output();
  if(!radio.begin(DEVICE_ID,command)) { delay(1000); ESP.restart(); }
  buttonBegan=millis(); // Publish only after the initial input has settled.
}
void usbDiagnostic(uint32_t now) {
  if(now-lastUsbDiagnostic<USB_DIAGNOSTIC_MS) return;
  lastUsbDiagnostic=now;
  // Never let an absent/slow Serial Monitor stall the actuator or radio.
  if(!Serial) return;
  char line[256];
  int n=snprintf(line,sizeof(line),
    "%s id=%s uptime_ms=%lu session=%lu reports=%lu commands=%lu max_loop_gap_ms=%lu drops=%lu send_errors=%lu retries=%lu unconfirmed=%lu\n",
    NODE_BUILD,DEVICE_ID,(unsigned long)now,(unsigned long)radio.session,
    (unsigned long)reportCount,(unsigned long)commandCount,(unsigned long)maxLoopGap,
    (unsigned long)radio.stats.drops,(unsigned long)radio.stats.sendErrors,
    (unsigned long)radio.stats.retries,(unsigned long)radio.stats.unconfirmed);
  if(n>0 && n<int(sizeof(line)) && Serial.availableForWrite()>=n)
    Serial.write(reinterpret_cast<const uint8_t*>(line),size_t(n));
}
void loop() {
  uint32_t began=millis();
  if(lastLoop && began-lastLoop>maxLoopGap) maxLoopGap=began-lastLoop;
  lastLoop=began;
  bool completed=ramp.tick(millis()); output(); radio.poll();
  uint32_t now=millis();
  bool changed=button.sample(digitalRead(BUTTON_PIN)==LOW,now,DEBOUNCE_MS);
  if(initialButton) {
    if(now-buttonBegan>=DEBOUNCE_MS && button.raw==button.stable) {
      initialButton=false; report(true);
    }
  } else if(changed) report(true); // Same reliable press/release delivery as remote buttons.
  else if(completed||now-lastStatus>=(ramp.moving()?MOVING_REPORT_MS:IDLE_REPORT_MS)) report();
  if(now-lastDiagnostic>=DIAGNOSTIC_MS) { lastDiagnostic=now; radio.diagnostic(); }
  usbDiagnostic(now);
  delay(2);
}
