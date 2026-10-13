#include "../dropdownNode.ino"
#include <cassert>
#include <cstdio>
Received request(Op op,int value,uint32_t ms=0,uint32_t seq=1) {
 Received r;auto& p=r.packet;p.type=COMMAND;p.flags=ACK_REQUIRED;p.length=11;
 strcpy(p.src,"BRIDGE");strcpy(p.dst,"DROPDOWN1");p.session=2;p.seq=seq;
 put32(p.payload,1);p.payload[4]=op;put16(p.payload+5,value);put32(p.payload+7,ms);return r;
}
void tick(uint32_t now){fakeNow=now;loop();}
int main() {
 levels[BUTTON_PIN]=HIGH;setup();
 assert(!ledOn && levels[LED_PIN]==HIGH && usToAngle(ramp.current)==DEFAULT_ANGLE);
 tick(29);assert(radio.sent.empty());tick(30);
 assert(radio.sent.size()==1 && radio.sent.back().flags && !radio.sent.back().payload[17]);
 // Contact bounce cannot publish a press; a settled press and release are reliable.
 levels[BUTTON_PIN]=LOW;tick(100);levels[BUTTON_PIN]=HIGH;tick(110);
 levels[BUTTON_PIN]=LOW;tick(120);tick(149);assert(!button.stable);
 tick(150);assert(button.stable && radio.sent.back().flags && radio.sent.back().payload[17]);
 tick(2150);assert(button.stable && radio.sent.back().flags && radio.sent.back().payload[17]);
 levels[BUTTON_PIN]=HIGH;tick(2160);tick(2190);
 assert(!button.stable && radio.sent.back().flags && !radio.sent.back().payload[17]);
 tick(4190);assert(radio.sent.back().flags && !radio.sent.back().payload[17]);
 // Turning the actor light on/off does not change or restart a servo ramp.
 assert(command(request(MOVE,150,1000))==ACCEPTED);
 tick(4690);int halfway=ramp.current;assert(ramp.moving());
 assert(!radio.sent.back().flags); // Moving snapshots do not occupy reliable slots.
 assert(command(request(LED,1,0,2))==ACCEPTED);
 assert(ledOn && levels[LED_PIN]==LOW && ramp.current==halfway && ramp.target==angleToUs(150));
 assert(commandSequence==1 && radio.sent.back().payload[18]==1);
 assert(command(request(LED,0,0,3))==ACCEPTED && !ledOn && ramp.moving());
 tick(5190);assert(!ramp.moving() && usToAngle(ramp.current)==150);
 assert(command(request(MOVE,25))==ACCEPTED && !ramp.moving() && usToAngle(ramp.current)==25);
 assert(command(request(SET_DEFAULT,45))==ACCEPTED && savedAngle==45 && ramp.duration==300);
 saveWorks=false;int target=ramp.target;
 assert(command(request(SET_DEFAULT,60))==INVALID && ramp.target==target && savedAngle==45);
 for(auto bad:{request(MOVE,181),request(MOVE,90,30001),request(LED,2),request(LED,1,1),request(PLAY,1)})
   assert(command(bad)==INVALID);
 auto bad=request(LED,1);bad.packet.length=17;assert(command(bad)==INVALID);
 // Wire shape validation rejects malformed state and LED command values.
 auto status=radio.sent.back();uint8_t bytes[110];Packet decoded;
 auto n=encode(status,bytes);assert(n==65 && decode(bytes,n,decoded));
 status.payload[17]=2;assert(!shape(status));
 status=radio.sent.back();status.payload[18]=2;assert(!shape(status));
 assert(!shape(request(LED,2).packet) && !shape(request(LED,1,1).packet));
 // Newer LED delivery cannot suppress an older servo command, or vice versa.
 Registry registry;PeerState* peer=nullptr;uint8_t mac[6]={1,2,3,4,5,6};
 auto servo=request(MOVE,120,0,10).packet,led=request(LED,1,0,11).packet;
 assert(registry.inspect(led,mac,0,peer)==ACCEPTED);registry.commit(led,*peer);
 assert(registry.order(servo,*peer)==ACCEPTED);registry.commit(servo,*peer);
 assert(registry.order(request(LED,0,0,9).packet,*peer)==SUPERSEDED);
 assert(registry.order(request(MOVE,90,0,9).packet,*peer)==SUPERSEDED);
 // Existing servo wire format is unchanged.
 status.type=SERVO;status.length=17;assert(shape(status));
 // USB diagnostics cannot block radio processing when disconnected or full.
 auto reports=reportCount;Serial.connected=false;tick(7000);
 assert(reportCount>reports && Serial.written.empty());
 Serial.connected=true;Serial.capacity=0;reports=reportCount;tick(9000);
 assert(reportCount>reports && Serial.written.empty());
 Serial.capacity=512;tick(10000);
 assert(Serial.written.find(NODE_BUILD)!=std::string::npos);
 assert(Serial.written.find("commands=")!=std::string::npos);
 assert(Serial.written.find("max_loop_gap_ms=")!=std::string::npos);
 puts("Dropdown firmware debounce, servo/LED independence, persistence and wire checks passed");
}
