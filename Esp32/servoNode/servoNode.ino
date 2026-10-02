#include <HauntProtocol.h>
#include <driver/ledc.h>
using namespace haunt;
// ===== PER-FLASH DEVICE CONFIGURATION =====
const char* DEVICE_ID = "SERVO1";
constexpr int SERVO_PIN = 18;
constexpr int DEFAULT_ANGLE = 90, MIN_ANGLE = 0, MAX_ANGLE = 180;
constexpr int SERVO_MIN_US = 500, SERVO_MAX_US = 2500;
constexpr uint32_t MOVING_REPORT_MS = 200, IDLE_REPORT_MS = 2000;
// Network/retries: libraries/HauntProtocol/src/HauntConfig.h
// ========================================
Radio radio;
Ramp ramp;
int bootAngle=DEFAULT_ANGLE;
uint32_t commandSession=0,commandSequence=0,lastStatus=0,lastDiagnostic=0;
int angleToUs(int angle) { return SERVO_MIN_US+(SERVO_MAX_US-SERVO_MIN_US)*angle/180; }
int usToAngle(int us) { return ((us-SERVO_MIN_US)*180+(SERVO_MAX_US-SERVO_MIN_US)/2)/(SERVO_MAX_US-SERVO_MIN_US); }
void output() {
  uint32_t duty=uint32_t((int64_t(ramp.current)*65535+10000)/20000);
  ledc_set_duty(LEDC_HIGH_SPEED_MODE,LEDC_CHANNEL_0,duty);
  ledc_update_duty(LEDC_HIGH_SPEED_MODE,LEDC_CHANNEL_0);
}
void report() {
  auto p=radio.make(SERVO,BRIDGE_ID,17);
  put16(p.payload,usToAngle(ramp.current)); put16(p.payload+2,usToAngle(ramp.target)); p.payload[4]=ramp.moving();
  put16(p.payload+5,ramp.current); put32(p.payload+7,commandSession); put32(p.payload+11,commandSequence);
  put16(p.payload+15,0xffff); // Reserved measured angle: unavailable, no shaft sensor.
  radio.send(p); lastStatus=millis();
}
Code command(const Received& r) {
  const auto& p=r.packet; if(p.type!=COMMAND) return INVALID;
  auto peer=radio.registry.find(p.src); if(peer&&peer->conflict) return CONFLICT;
  auto op=p.payload[4]; int angle=get16(p.payload+5); uint32_t ms=get32(p.payload+7);
  if((op!=MOVE&&op!=SET_DEFAULT)||angle<MIN_ANGLE||angle>MAX_ANGLE||ms>30000) return INVALID;
  if(op==SET_DEFAULT) {
    Preferences prefs;
    if(!prefs.begin("servo",false)) return INVALID;
    bool saved=prefs.putInt("boot_deg",angle)==4; prefs.end();
    if(!saved) return INVALID;
    bootAngle=angle; ms=300; // Preserve set_default's existing move-to-default behavior.
  }
  ramp.move(angleToUs(angle),ms,millis()); output();
  commandSession=p.session; commandSequence=p.seq; report(); return ACCEPTED;
}
void setup() {
  ledc_timer_config_t timer{};
  timer.speed_mode=LEDC_HIGH_SPEED_MODE; timer.timer_num=LEDC_TIMER_0;
  timer.duty_resolution=LEDC_TIMER_16_BIT; timer.freq_hz=50; timer.clk_cfg=LEDC_AUTO_CLK;
  ledc_timer_config(&timer);
  ledc_channel_config_t channel{};
  channel.gpio_num=SERVO_PIN; channel.speed_mode=LEDC_HIGH_SPEED_MODE; channel.channel=LEDC_CHANNEL_0;
  channel.timer_sel=LEDC_TIMER_0; channel.intr_type=LEDC_INTR_DISABLE; ledc_channel_config(&channel);
  Preferences prefs;
  if(prefs.begin("servo",true)) { bootAngle=prefs.getInt("boot_deg",DEFAULT_ANGLE); prefs.end(); }
  bootAngle=constrain(bootAngle,MIN_ANGLE,MAX_ANGLE);
  ramp.move(angleToUs(bootAngle),0,millis()); output();
  if(!radio.begin(DEVICE_ID,command)) { delay(1000); ESP.restart(); }
  report();
}
void loop() {
  bool completed=ramp.tick(millis()); output(); radio.poll();
  uint32_t now=millis();
  if(completed||now-lastStatus>=(ramp.moving()?MOVING_REPORT_MS:IDLE_REPORT_MS)) report();
  if(now-lastDiagnostic>=10000) { lastDiagnostic=now; radio.diagnostic(); }
  delay(2);
}
