#define PEDRO_WINGS_ENABLED 1 // Retain coverage for the restored-servo configuration.
#include "../pedroNode.ino"
#include <cassert>
#include <cstdio>
Received pose(PedroState requested,int wing=115,int mouth=10,uint32_t duration=0) {
 Received r;auto& p=r.packet;p.type=COMMAND;p.flags=ACK_REQUIRED;p.length=17;
 strcpy(p.src,"BRIDGE");strcpy(p.dst,"PEDRO1");p.session=2;p.seq=3;
 put32(p.payload,1);p.payload[4]=PEDRO_POSE;put16(p.payload+5,requested);
 put32(p.payload+7,duration);put16(p.payload+11,wing);put16(p.payload+13,mouth);
 p.payload[15]=p.payload[16]=1;return r;
}
int main() {
 setup();assert(!controllerConnected && state==OFF);
 assert(levels[RED_LED_PIN] && !levels[GREEN_LED_PIN]);
 assert(usToAngle(wings.current)==5 && usToAngle(beak.current)==55);
 controllerTick(250);assert(!levels[RED_LED_PIN] && !levels[GREEN_LED_PIN]);
 fakeNow=500;assert(command(pose(STANDBY))==ACCEPTED);
 assert(controllerConnected && state==STANDBY && levels[GREEN_LED_PIN] && !levels[RED_LED_PIN]);
 assert(neck && eyes && usToAngle(wings.current)==115 && usToAngle(beak.current)==10);
 fakeNow=750;assert(command(pose(ACTIVE))==ACCEPTED);
 assert(!levels[GREEN_LED_PIN] && !levels[RED_LED_PIN]);leds(1000);assert(levels[GREEN_LED_PIN]);
 auto invalid=pose(ACTIVE,116);fakeNow=1000;
 assert(command(invalid)==INVALID && lastController==750 && usToAngle(wings.current)==115);
 invalid=pose(ACTIVE,5,9);assert(command(invalid)==INVALID);
 invalid=pose(ACTIVE);invalid.packet.payload[15]=2;assert(command(invalid)==INVALID);
 invalid=pose(ACTIVE);invalid.packet.length=11;assert(command(invalid)==INVALID);
 // An OFF command overrides all supplied outputs and maintains the host lease.
 assert(command(pose(OFF))==ACCEPTED && controllerConnected && state==OFF);
 assert(levels[RED_LED_PIN] && !levels[GREEN_LED_PIN] && !neck && !eyes);
 assert(usToAngle(wings.current)==5 && usToAngle(beak.current)==55);
 fakeNow=3499;controllerTick(fakeNow);assert(controllerConnected);
 fakeNow=3500;controllerTick(fakeNow);assert(!controllerConnected && state==OFF);
 // Full pose validation occurs before touching any output or refreshing lease.
 fakeNow=4000;assert(command(pose(ACTIVE,115,10,1000))==ACCEPTED);
 wings.tick(4500);beak.tick(4500);assert(wings.moving() && beak.moving());
 fakeNow=4500;assert(command(pose(STANDBY,5,55,0))==ACCEPTED);
 assert(!wings.moving() && !beak.moving() && usToAngle(wings.current)==5);
 // Loss during a move cancels both ramps and turns off digital outputs.
 fakeNow=5000;assert(command(pose(ACTIVE,115,10,10000))==ACCEPTED);
 fakeNow=7500;controllerTick(fakeNow);
 assert(!controllerConnected && !wings.moving() && !beak.moving() && !neck && !eyes);
 assert(usToAngle(wings.current)==5 && usToAngle(beak.current)==55);
 // Millis wrap cannot keep a disconnected controller alive.
 fakeNow=0xffffff00;assert(command(pose(STANDBY))==ACCEPTED);
 fakeNow=uint32_t(0xffffff00+2500);controllerTick(fakeNow);assert(!controllerConnected);
 uint8_t wire[110];Packet decoded;auto p=pose(ACTIVE).packet;
 auto n=encode(p,wire);assert(n==63 && decode(wire,n,decoded));
 p.length=11;assert(!shape(p));p=pose(ACTIVE).packet;put16(p.payload+5,3);assert(!shape(p));
 p=pose(ACTIVE).packet;put32(p.payload+7,30001);assert(!shape(p));
 auto status=radio.make(PEDRO,BRIDGE_ID,21);assert(shape(status));
 status.payload[11]=2;assert(!shape(status));
 // Existing servo and lantern wire shapes remain unchanged.
 p=Packet{};p.type=COMMAND;p.flags=ACK_REQUIRED;p.length=11;
 strcpy(p.src,"BRIDGE");strcpy(p.dst,"SERVO1");p.payload[4]=MOVE;assert(shape(p));
 p.length=15;p.payload[4]=LANTERN_STATE;put32(p.payload+7,1);assert(shape(p));
 puts("Pedro firmware behavior and wire compatibility checks passed");
}
