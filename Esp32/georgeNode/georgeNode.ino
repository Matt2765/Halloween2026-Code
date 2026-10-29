#include <HauntProtocol.h>
#include <driver/ledc.h>
using namespace haunt;
// ===== PER-FLASH DEVICE CONFIGURATION =====
const char* DEVICE_ID = "GEORGE1";
constexpr int NECK_PIN=26, MOUTH_PIN=14, EYES_PIN=13;
constexpr bool EYES_ACTIVE_HIGH=true;
// George was William Wallace: mouth/neck are servos; eyes are digital.
constexpr int NECK_REST=80, NECK_MIN=0, NECK_MAX=115; // Head faces forward at 80 degrees.
constexpr int MOUTH_REST=180, MOUTH_MIN=120, MOUTH_MAX=180;
constexpr int SERVO_MIN_US=500, SERVO_MAX_US=2500;
constexpr uint32_t CONTROLLER_TIMEOUT_MS=2500, STATUS_MS=500;
// Shared network/channel/retries: HauntConfig.h. Original ESP32 target.
// ========================================
enum GeorgeState : uint8_t { OFF=0, STANDBY=1, ACTIVE=2 };
Radio radio;
Ramp neck,mouth;
GeorgeState state=OFF;
bool controllerConnected=false,eyes=false;
uint32_t lastController=0,lastStatus=0,lastDiagnostic=0,commandSession=0,commandSequence=0;
int angleToUs(int angle) { return SERVO_MIN_US+(SERVO_MAX_US-SERVO_MIN_US)*angle/180; }
int usToAngle(int us) { return ((us-SERVO_MIN_US)*180+(SERVO_MAX_US-SERVO_MIN_US)/2)/(SERVO_MAX_US-SERVO_MIN_US); }
void digitalOutput(int pin,bool on,bool activeHigh) { digitalWrite(pin,on==activeHigh?HIGH:LOW); }
void servoOutput(ledc_channel_t channel,const Ramp& ramp) {
  uint32_t duty=uint32_t((int64_t(ramp.current)*65535+10000)/20000);
  ledc_set_duty(LEDC_HIGH_SPEED_MODE,channel,duty);
  ledc_update_duty(LEDC_HIGH_SPEED_MODE,channel);
}
void output() {
  servoOutput(LEDC_CHANNEL_0,neck); servoOutput(LEDC_CHANNEL_1,mouth);
  digitalOutput(EYES_PIN,eyes,EYES_ACTIVE_HIGH);
}
void park(uint32_t now) {
  neck.move(angleToUs(NECK_REST),0,now); mouth.move(angleToUs(MOUTH_REST),0,now);
  eyes=false; output();
}
void report() {
  auto p=radio.make(GEORGE,BRIDGE_ID,20);
  p.payload[0]=state; p.payload[1]=controllerConnected;
  put16(p.payload+2,usToAngle(mouth.current)); put16(p.payload+4,usToAngle(mouth.target));
  put16(p.payload+6,usToAngle(neck.current)); put16(p.payload+8,usToAngle(neck.target));
  p.payload[10]=eyes; p.payload[11]=mouth.moving()||neck.moving();
  put32(p.payload+12,commandSession); put32(p.payload+16,commandSequence);
  radio.send(p); lastStatus=millis();
}
Code command(const Received& r) {
  const auto& p=r.packet;
  if(p.type!=COMMAND || p.length!=16 || p.payload[4]!=GEORGE_POSE) return INVALID;
  auto peer=radio.registry.find(p.src); if(peer&&peer->conflict) return CONFLICT;
  int requestedState=get16(p.payload+5),mouthAngle=get16(p.payload+11),neckAngle=get16(p.payload+13);
  uint32_t duration=get32(p.payload+7),now=millis();
  if(requestedState>ACTIVE || mouthAngle<MOUTH_MIN || mouthAngle>MOUTH_MAX ||
     neckAngle<NECK_MIN || neckAngle>NECK_MAX || duration>30000 || p.payload[15]>1) return INVALID;
  state=GeorgeState(requestedState); controllerConnected=true; lastController=now;
  if(state==OFF) park(now);
  else {
    if(mouth.target!=angleToUs(mouthAngle) || !mouth.moving()) mouth.move(angleToUs(mouthAngle),duration,now); if(neck.target!=angleToUs(neckAngle) || !neck.moving()) neck.move(angleToUs(neckAngle),duration,now);
    eyes=p.payload[15]; output();
  }
  commandSession=p.session; commandSequence=p.seq; report(); return ACCEPTED;
}
bool setupServo(int pin,ledc_channel_t channelNumber) {
  ledc_channel_config_t channel{};
  channel.gpio_num=pin; channel.speed_mode=LEDC_HIGH_SPEED_MODE; channel.channel=channelNumber;
  channel.timer_sel=LEDC_TIMER_0; channel.intr_type=LEDC_INTR_DISABLE;
  return ledc_channel_config(&channel)==ESP_OK;
}
void setup() {
  pinMode(EYES_PIN,OUTPUT);
  eyes=false;
  digitalOutput(EYES_PIN,false,EYES_ACTIVE_HIGH);
  ledc_timer_config_t timer{};
  timer.speed_mode=LEDC_HIGH_SPEED_MODE; timer.timer_num=LEDC_TIMER_0;
  timer.duty_resolution=LEDC_TIMER_16_BIT; timer.freq_hz=50; timer.clk_cfg=LEDC_AUTO_CLK;
  if(ledc_timer_config(&timer)!=ESP_OK || !setupServo(NECK_PIN,LEDC_CHANNEL_0) || !setupServo(MOUTH_PIN,LEDC_CHANNEL_1)) {
    delay(1000); ESP.restart(); return;
  }
  park(millis());
  if(!radio.begin(DEVICE_ID,command)) { delay(1000); ESP.restart(); return; }
  report();
}
void controllerTick(uint32_t now) {
  auto bridge=radio.registry.find(BRIDGE_ID);
  if(controllerConnected && (now-lastController>=CONTROLLER_TIMEOUT_MS || (bridge&&bridge->conflict))) {
    controllerConnected=false; state=OFF; park(now); report();
  }
}
void loop() {
  uint32_t now=millis();
  bool completed=neck.tick(now); completed=mouth.tick(now)||completed; output();
  radio.poll(); now=millis(); controllerTick(now);
  if(completed || now-lastStatus>=STATUS_MS) report();
  if(now-lastDiagnostic>=10000) { lastDiagnostic=now; radio.diagnostic(); }
  delay(2);
}
