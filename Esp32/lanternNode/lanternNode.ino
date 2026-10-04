#include <HauntProtocol.h>
#include <driver/ledc.h>
using namespace haunt;
// ===== PER-FLASH DEVICE CONFIGURATION =====
const char* DEVICE_ID = "LANTERN1"; // Flash LANTERN1..LANTERN4 with unique IDs.
constexpr int LIGHT_PIN = 4;       // C3 Super Mini GPIO4: PWM to LED driver/MOSFET.
constexpr int SYNC_BUTTON_PIN = 5;  // C3 Super Mini GPIO5: button to GND; pull-up.
constexpr bool LIGHT_ACTIVE_HIGH = true;
constexpr uint8_t MAX_BRIGHTNESS = 255;
constexpr uint32_t DEBOUNCE_MS = 30, LONG_PRESS_MS = 3000;
constexpr uint32_t FLICKER_OUT_MS = 1800, INTENSE_FLICKER_OUT_MS = 2800;
constexpr uint32_t FLICKER_ON_RAMP_MS = 1500; // Ramp only when the light is dark.
constexpr uint8_t DARK_BRIGHTNESS_THRESHOLD = 0; // PWM 0..255; raise if lamp goes dark above zero.
constexpr uint32_t STROBE_ON_MIN_MS = 30, STROBE_ON_MAX_MS = 70;
constexpr uint32_t STROBE_OFF_MIN_MS = 50, STROBE_OFF_MAX_MS = 140;
constexpr uint32_t STATUS_MS = 500;
// Network, bridge, channel and retries: libraries/HauntProtocol/src/HauntConfig.h
// ========================================
enum LightState : uint8_t { OFF, SOLID_ON, FLICKERING_ON, INTENSE_FLICKERING_ON, FLICKER_OUT, INTENSE_FLICKER_OUT, STROBE };
static_assert(FLICKER_ON_RAMP_MS>0 && FLICKER_ON_RAMP_MS<=2000,"Flicker ramp must take 1..2000 ms");
static_assert(STROBE_ON_MIN_MS>0 && STROBE_ON_MIN_MS<=STROBE_ON_MAX_MS &&
              STROBE_OFF_MIN_MS>0 && STROBE_OFF_MIN_MS<=STROBE_OFF_MAX_MS,"Invalid strobe timing range");
Radio radio;
Debounced button;
LightState lightState=FLICKERING_ON;
bool synced=false, longHandled=false;
bool rampingOn=false, strobeLit=false;
uint8_t brightness=0, outputLevel=0, rampStartLevel=0, flicker=210;
uint32_t nextCommand=1, generation=0, commandSession=0, commandSequence=0;
uint32_t stateBegan=0, nextFlicker=0, pressedAt=0, lastStatus=0, lastDiagnostic=0;
uint32_t rampOnBegan=0;
uint32_t flashBegan=0, flashStep=0;
uint8_t flashSteps=0;
void lightTick(uint32_t now);

void output(uint8_t level) {
  outputLevel=level;
  brightness=uint16_t(level)*MAX_BRIGHTNESS/255;
  ledc_set_duty(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0,LIGHT_ACTIVE_HIGH?brightness:255-brightness);
  ledc_update_duty(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0);
}
void report() {
  auto p=radio.make(LANTERN,BRIDGE_ID,19);
  p.payload[0]=lightState; p.payload[1]=synced; p.payload[2]=brightness;
  put32(p.payload+3,nextCommand); put32(p.payload+7,generation);
  put32(p.payload+11,commandSession); put32(p.payload+15,commandSequence);
  radio.send(p); lastStatus=millis();
}
void setState(LightState value,uint32_t now) {
  bool flickeringOn=value==FLICKERING_ON || value==INTENSE_FLICKERING_ON;
  if(flickeringOn && !rampingOn && brightness<=DARK_BRIGHTNESS_THRESHOLD) {
    rampingOn=true; rampOnBegan=now;
    rampStartLevel=outputLevel;
  }
  else if(!flickeringOn) rampingOn=false;
  // Preserve an in-progress ramp when switching between the two flicker modes.
  // Output brightness also catches a dark fade/strobe without an OFF label.
  strobeLit=false;
  lightState=value; stateBegan=now; nextFlicker=now;
}
void resetSync(bool enable,uint32_t now) {
  // Generation is scoped to the persistent radio boot session. Never wrap.
  if(generation==0xffffffff) { ESP.restart(); return; }
  generation++; synced=enable; nextCommand=1;
  commandSession=commandSequence=0;
  setState(FLICKERING_ON,now); report();
}
void flashes(uint8_t count,uint32_t step,uint32_t now) {
  flashBegan=now; flashStep=step; flashSteps=count*2;
}
void buttonTick(uint32_t now) {
  if(button.sample(digitalRead(SYNC_BUTTON_PIN)==LOW,now,DEBOUNCE_MS)) {
    if(button.stable) {
      pressedAt=now; longHandled=false; flashSteps=0;
      resetSync(true,now); // Reset immediately on debounced press, even mid-effect.
    } else if(!longHandled) {
      if(now-pressedAt>=LONG_PRESS_MS) {
        longHandled=true; resetSync(false,now); flashes(2,400,now);
      } else flashes(3,100,now);
    }
  }
  if(button.stable && !longHandled && now-pressedAt>=LONG_PRESS_MS) {
    longHandled=true; resetSync(false,now); flashes(2,400,now);
  }
}
Code command(const Received& r) {
  const auto& p=r.packet;
  if(p.type!=COMMAND || p.length!=15 || p.payload[4]!=LANTERN_STATE) return INVALID;
  auto peer=radio.registry.find(p.src); if(peer&&peer->conflict) return CONFLICT;
  uint16_t value=get16(p.payload+5); uint32_t cue=get32(p.payload+7);
  if(!synced || get32(p.payload+11)!=generation || cue!=nextCommand || cue==0xffffffff || value>LANTERN_STATE_MAX) return INVALID;
  uint32_t now=millis();
  lightTick(now); // Refresh elapsed fades/output before deciding whether it is dark.
  nextCommand++; setState(LightState(value),now);
  commandSession=p.session; commandSequence=p.seq; report(); return ACCEPTED;
}
void lightTick(uint32_t now) {
  uint8_t level=0;
  bool completed=false;
  bool intense=lightState==INTENSE_FLICKERING_ON || lightState==INTENSE_FLICKER_OUT;
  bool fading=lightState==FLICKER_OUT || lightState==INTENSE_FLICKER_OUT;
  if(lightState==SOLID_ON) level=255;
  else if(lightState==STROBE) {
    if(due(now,nextFlicker)) {
      strobeLit=!strobeLit;
      flicker=strobeLit?random(200,256):0;
      nextFlicker=now+(strobeLit?random(STROBE_ON_MIN_MS,STROBE_ON_MAX_MS+1):
                                  random(STROBE_OFF_MIN_MS,STROBE_OFF_MAX_MS+1));
    }
    level=flicker;
  }
  else if(lightState!=OFF) {
    if(due(now,nextFlicker)) {
      // Normal flicker always remains visibly lit; intense has brief deep dips.
      flicker=intense?random(12,256):random(170,256);
      nextFlicker=now+(intense?random(20,85):random(55,160));
    }
    level=flicker;
    if(fading) {
      uint32_t duration=intense?INTENSE_FLICKER_OUT_MS:FLICKER_OUT_MS;
      uint32_t elapsed=now-stateBegan;
      if(elapsed>=duration) { setState(OFF,now); level=0; completed=true; }
      else level=uint32_t(level)*(duration-elapsed)/duration;
    }
  }
  if(rampingOn) {
    uint32_t elapsed=now-rampOnBegan;
    if(elapsed>=FLICKER_ON_RAMP_MS) rampingOn=false;
    else level=rampStartLevel+(int(level)-rampStartLevel)*int32_t(elapsed)/int32_t(FLICKER_ON_RAMP_MS);
  }
  // Feedback is an overlay: accepted commands still advance while flashes run.
  if(flashSteps) {
    uint32_t step=(now-flashBegan)/flashStep;
    if(step>=flashSteps) flashSteps=0;
    else level=(step%2==0)?255:0;
  }
  output(level);
  if(completed) report();
}
void setup() {
  pinMode(SYNC_BUTTON_PIN,INPUT_PULLUP);
  ledc_timer_config_t timer{};
  timer.speed_mode=LEDC_LOW_SPEED_MODE; timer.timer_num=LEDC_TIMER_0;
  timer.duty_resolution=LEDC_TIMER_8_BIT; timer.freq_hz=5000; timer.clk_cfg=LEDC_AUTO_CLK;
  ledc_timer_config(&timer);
  ledc_channel_config_t channel{};
  channel.gpio_num=LIGHT_PIN; channel.speed_mode=LEDC_LOW_SPEED_MODE; channel.channel=LEDC_CHANNEL_0;
  channel.timer_sel=LEDC_TIMER_0; channel.intr_type=LEDC_INTR_DISABLE; ledc_channel_config(&channel);
  randomSeed(esp_random()); output(210);
  if(!radio.begin(DEVICE_ID,command)) { delay(1000); ESP.restart(); }
  report();
}
void loop() {
  uint32_t now=millis(); buttonTick(now); radio.poll(); now=millis(); lightTick(now);
  if(now-lastStatus>=STATUS_MS) report();
  if(now-lastDiagnostic>=10000) { lastDiagnostic=now; radio.diagnostic(); }
  delay(2);
}
