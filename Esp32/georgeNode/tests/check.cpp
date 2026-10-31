#include "../georgeNode.ino"
#include <cassert>
#include <cstdio>
Received pose(GeorgeState requested,int mouthAngle=120,int neckAngle=115,uint32_t duration=0) {
 Received r;auto& p=r.packet;p.type=COMMAND;p.flags=ACK_REQUIRED;p.length=16;
 strcpy(p.src,"BRIDGE");strcpy(p.dst,"GEORGE1");p.session=2;p.seq=3;
 put32(p.payload,1);p.payload[4]=GEORGE_POSE;put16(p.payload+5,requested);
 put32(p.payload+7,duration);put16(p.payload+11,mouthAngle);put16(p.payload+13,neckAngle);
 p.payload[15]=1;return r;
}
int main() {
 setup();assert(NECK_PIN==26 && MOUTH_PIN==14 && EYES_PIN==13);
 assert(!controllerConnected && state==OFF && usToAngle(mouth.current)==180 && usToAngle(neck.current)==80);
 fakeNow=500;assert(command(pose(STANDBY))==ACCEPTED);
 assert(controllerConnected && eyes && levels[EYES_PIN]);
 assert(usToAngle(mouth.current)==120 && usToAngle(neck.current)==115);
 auto invalid=pose(ACTIVE,119);fakeNow=1000;
 assert(command(invalid)==INVALID && lastController==500);
 assert(command(pose(ACTIVE,180,180))==ACCEPTED);
 assert(usToAngle(neck.current)==180);
 invalid=pose(ACTIVE,180,181);assert(command(invalid)==INVALID);
 invalid=pose(ACTIVE);invalid.packet.payload[15]=2;assert(command(invalid)==INVALID);
 invalid=pose(ACTIVE);invalid.packet.length=11;assert(command(invalid)==INVALID);
 assert(command(pose(OFF))==ACCEPTED && controllerConnected && state==OFF);
 assert(!eyes && !levels[EYES_PIN] && usToAngle(mouth.current)==180 && usToAngle(neck.current)==80);
 fakeNow=1500;assert(command(pose(ACTIVE,120,115,2000))==ACCEPTED);
 mouth.tick(2000);neck.tick(2000);
 auto began=neck.began;fakeNow=2000;
 assert(command(pose(ACTIVE,120,115,2000))==ACCEPTED && neck.began==began);
 mouth.tick(3500);neck.tick(3500);assert(!mouth.moving() && !neck.moving());
 fakeNow=4500;controllerTick(fakeNow);assert(!controllerConnected && state==OFF && !eyes);
 assert(usToAngle(mouth.current)==180 && usToAngle(neck.current)==80);
 fakeNow=0xffffff00;assert(command(pose(STANDBY))==ACCEPTED);
 fakeNow=uint32_t(0xffffff00+2500);controllerTick(fakeNow);assert(!controllerConnected);
 uint8_t wire[110];Packet decoded;auto p=pose(ACTIVE).packet;
 auto n=encode(p,wire);assert(n==62 && decode(wire,n,decoded));
 p.length=11;assert(!shape(p));p=pose(ACTIVE).packet;put16(p.payload+5,3);assert(!shape(p));
 p=pose(ACTIVE).packet;put32(p.payload+7,30001);assert(!shape(p));
 auto status=radio.make(GEORGE,BRIDGE_ID,20);assert(shape(status));
 status.payload[10]=2;assert(!shape(status));
 puts("George firmware behavior, ramps, failsafe and wire checks passed");
}
