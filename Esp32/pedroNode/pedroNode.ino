#include <HauntProtocol.h>
#include <driver/ledc.h>
using namespace haunt;
// ===== PER-FLASH DEVICE CONFIGURATION =====
const char* DEVICE_ID = "PEDRO1";
constexpr int WINGS_PIN=23, BEAK_PIN=18, NECK_PIN=5, EYES_PIN=4;
constexpr int GREEN_LED_PIN=2, RED_LED_PIN=15;
constexpr bool NECK_ACTIVE_HIGH=true, EYES_ACTIVE_HIGH=true, LED_ACTIVE_HIGH=true;
// Match PedroWallace v3: neck and eyes are digital, NOT servos.
constexpr int WINGS_REST=5, WINGS_MIN=5, WINGS_MAX=115;
constexpr int BEAK_REST=55, BEAK_MIN=10, BEAK_MAX=55;
constexpr int SERVO_MIN_US=500, SERVO_MAX_US=2500;
constexpr uint32_t CONTROLLER_TIMEOUT_MS=2500, STATUS_MS=500, FLASH_MS=250;
// Shared network/channel/retries: HauntConfig.h. Original ESP32 target.
// ========================================
enum PedroState : uint8_t { OFF=0, STANDBY=1, ACTIVE=2 };
Radio radio;
Ramp wings,beak;
PedroState state=OFF;
bool controllerConnected=false,neck=false,eyes=false;
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
  servoOutput(LEDC_CHANNEL_0,wings); servoOutput(LEDC_CHANNEL_1,beak);
  digitalOutput(NECK_PIN,neck,NECK_ACTIVE_HIGH); digitalOutput(EYES_PIN,eyes,EYES_ACTIVE_HIGH);
}
void park(uint32_t now) {
  wings.move(angleToUs(WINGS_REST),0,now); beak.move(angleToUs(BEAK_REST),0,now);
  neck=eyes=false; output();
}
void leds(uint32_t now) {
  bool flash=(now/FLASH_MS)%2==0;
  digitalOutput(RED_LED_PIN,!controllerConnected?flash:state==OFF,LED_ACTIVE_HIGH);
  digitalOutput(GREEN_LED_PIN,controllerConnected && (state==STANDBY || (state==ACTIVE && flash)),LED_ACTIVE_HIGH);
}
void report() {
  auto p=radio.make(PEDRO,BRIDGE_ID,21);
  p.payload[0]=state; p.payload[1]=controllerConnected;
  put16(p.payload+2,usToAngle(wings.current)); put16(p.payload+4,usToAngle(wings.target));
  put16(p.payload+6,usToAngle(beak.current)); put16(p.payload+8,usToAngle(beak.target));
  p.payload[10]=neck; p.payload[11]=eyes; p.payload[12]=wings.moving()||beak.moving();
  put32(p.payload+13,commandSession); put32(p.payload+17,commandSequence);
  radio.send(p); lastStatus=millis();
}
Code command(const Received& r) {
  const auto& p=r.packet;
  if(p.type!=COMMAND || p.length!=17 || p.payload[4]!=PEDRO_POSE) return INVALID;
  auto peer=radio.registry.find(p.src); if(peer&&peer->conflict) return CONFLICT;
  int requestedState=get16(p.payload+5),wingAngle=get16(p.payload+11),beakAngle=get16(p.payload+13);
  uint32_t duration=get32(p.payload+7),now=millis();
  if(requestedState>ACTIVE || wingAngle<WINGS_MIN || wingAngle>WINGS_MAX ||
     beakAngle<BEAK_MIN || beakAngle>BEAK_MAX || duration>30000 || p.payload[15]>1 || p.payload[16]>1) return INVALID;
  state=PedroState(requestedState); controllerConnected=true; lastController=now;
  if(state==OFF) park(now);
  else {
    if(wings.target!=angleToUs(wingAngle) || !wings.moving()) wings.move(angleToUs(wingAngle),duration,now); if(beak.target!=angleToUs(beakAngle) || !beak.moving()) beak.move(angleToUs(beakAngle),duration,now);
    neck=p.payload[15]; eyes=p.payload[16]; output();
  }
  commandSession=p.session; commandSequence=p.seq; leds(now); report(); return ACCEPTED;
}
bool setupServo(int pin,ledc_channel_t channelNumber) {
  ledc_channel_config_t channel{};
  channel.gpio_num=pin; channel.speed_mode=LEDC_HIGH_SPEED_MODE; channel.channel=channelNumber;
  channel.timer_sel=LEDC_TIMER_0; channel.intr_type=LEDC_INTR_DISABLE;
  return ledc_channel_config(&channel)==ESP_OK;
}
void setup() {
  pinMode(NECK_PIN,OUTPUT); pinMode(EYES_PIN,OUTPUT); pinMode(GREEN_LED_PIN,OUTPUT); pinMode(RED_LED_PIN,OUTPUT);
  neck=eyes=false; leds(millis());
  digitalOutput(NECK_PIN,false,NECK_ACTIVE_HIGH); digitalOutput(EYES_PIN,false,EYES_ACTIVE_HIGH);
  ledc_timer_config_t timer{};
  timer.speed_mode=LEDC_HIGH_SPEED_MODE; timer.timer_num=LEDC_TIMER_0;
  timer.duty_resolution=LEDC_TIMER_16_BIT; timer.freq_hz=50; timer.clk_cfg=LEDC_AUTO_CLK;
  if(ledc_timer_config(&timer)!=ESP_OK || !setupServo(WINGS_PIN,LEDC_CHANNEL_0) || !setupServo(BEAK_PIN,LEDC_CHANNEL_1)) {
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
  leds(now);
}
void loop() {
  uint32_t now=millis();
  bool completed=wings.tick(now); completed=beak.tick(now)||completed; output();
  radio.poll(); now=millis(); controllerTick(now);
  if(completed || now-lastStatus>=STATUS_MS) report();
  if(now-lastDiagnostic>=10000) { lastDiagnostic=now; radio.diagnostic(); }
  delay(2);
}
