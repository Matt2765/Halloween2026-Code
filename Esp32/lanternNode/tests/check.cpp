#include "../lanternNode.ino"
#include <cassert>
#include <cstdio>
#include <initializer_list>
Received cue(uint32_t number,LightState value,uint32_t epoch) {
 Received r;auto& p=r.packet;p.type=COMMAND;p.flags=ACK_REQUIRED;p.length=15;
 strcpy(p.src,"BRIDGE");strcpy(p.dst,"LANTERN1");p.session=2;p.seq=number;
 put32(p.payload,1);p.payload[4]=LANTERN_STATE;put16(p.payload+5,value);
 put32(p.payload+7,number);put32(p.payload+11,epoch);return r;
}
void buttonAt(uint32_t at,int level) {fakeNow=at;fakeButton=level;buttonTick(at);}
int main() {
 setup(); assert(!synced && lightState==FLICKERING_ON);
 assert(command(cue(1,OFF,0))==INVALID);
 buttonAt(100,0);buttonAt(130,0);
 assert(synced && generation==1 && nextCommand==1);
 assert(command(cue(2,OFF,1))==INVALID);
 assert(command(cue(1,SOLID_ON,1))==ACCEPTED && nextCommand==2);
 assert(command(cue(1,OFF,1))==INVALID);
 buttonAt(200,1);buttonAt(230,1);assert(flashSteps==6 && flashStep==100);
 buttonAt(300,0);buttonAt(330,0);assert(nextCommand==1 && generation==2);
 assert(command(cue(1,OFF,1))==INVALID);
 buttonAt(3330,0);assert(!synced && generation==3 && flashSteps==4 && flashStep==400);
 assert(command(cue(1,OFF,3))==INVALID);
 buttonAt(3400,1);buttonAt(3430,1);assert(generation==3);
 buttonAt(3500,0);buttonAt(3530,0);assert(synced && generation==4);
 buttonAt(3600,1);buttonAt(3630,1);flashSteps=0;
 assert(command(cue(1,FLICKER_OUT,4))==ACCEPTED);
 fakeNow=4000;lightTick(fakeNow);assert(lightState==FLICKER_OUT && brightness>0);
 fakeNow=3630+FLICKER_OUT_MS;lightTick(fakeNow);assert(lightState==OFF && brightness==0);
 assert(command(cue(2,INTENSE_FLICKER_OUT,4))==ACCEPTED);
 fakeNow+=INTENSE_FLICKER_OUT_MS;lightTick(fakeNow);assert(lightState==OFF && brightness==0);
 setState(FLICKERING_ON,fakeNow);
 fakeNow+=FLICKER_ON_RAMP_MS;lightTick(fakeNow);
 for(int i=0;i<100;i++){fakeNow+=200;lightTick(fakeNow);assert(brightness>=170);}
 // Fade timers remain valid through millis wraparound.
 setState(FLICKER_OUT,0xffffff00);lightTick(0xffffff50);assert(lightState==FLICKER_OUT);
 lightTick(uint32_t(0xffffff00+FLICKER_OUT_MS));assert(lightState==OFF);
 auto valid=cue(1,OFF,4).packet;uint8_t wire[110];Packet decoded;
 auto n=encode(valid,wire);assert(n==61 && decode(wire,n,decoded));
 valid.length=11;assert(!shape(valid));valid.length=15;put16(valid.payload+5,7);assert(!shape(valid));
 for(auto mode:{FLICKERING_ON,INTENSE_FLICKERING_ON}) {
   fakeNow=100000;setState(OFF,fakeNow);lightTick(fakeNow);
   setState(mode,fakeNow);lightTick(fakeNow);assert(rampingOn && brightness==0);
   lightTick(fakeNow+FLICKER_ON_RAMP_MS/2);assert(brightness>0 && brightness<=127);
   lightTick(fakeNow+FLICKER_ON_RAMP_MS);assert(!rampingOn && brightness>=12);
   // A lit lamp changes to either flicker mode with no new ramp.
   setState(SOLID_ON,fakeNow);lightTick(fakeNow);
   setState(mode,fakeNow);lightTick(fakeNow);assert(!rampingOn && brightness>=12);
 }
 fakeNow=200000;setState(OFF,fakeNow);lightTick(fakeNow);
 setState(FLICKERING_ON,fakeNow);lightTick(fakeNow);
 fakeNow+=500;setState(INTENSE_FLICKERING_ON,fakeNow);
 assert(rampingOn && rampOnBegan==200000);
 lightTick(200000+FLICKER_ON_RAMP_MS);assert(!rampingOn);
 // An interrupting OFF cancels the ramp and the next start gets a fresh ramp.
 setState(OFF,fakeNow);lightTick(fakeNow);assert(!rampingOn && brightness==0);
 setState(FLICKERING_ON,fakeNow);assert(rampingOn && rampOnBegan==fakeNow);
 // Ramp timers work across millis wrap too.
 setState(OFF,0xffffff00);lightTick(0xffffff00);setState(FLICKERING_ON,0xffffff00);
 lightTick(0xffffff00);assert(brightness==0);
 lightTick(uint32_t(0xffffff00+FLICKER_ON_RAMP_MS));assert(!rampingOn && brightness>=170);
 // Strobe alternates bright and fully dark phases, with bounded random timings.
 fakeNow=300000;assert(command(cue(3,STROBE,4))==ACCEPTED && nextCommand==4);
 for(int i=0;i<30;i++) {
   lightTick(fakeNow);
   assert(brightness==0 || brightness>=200);
   assert(strobeLit==(i%2==0));
   uint32_t interval=nextFlicker-fakeNow;
   assert(interval>=(strobeLit?STROBE_ON_MIN_MS:STROBE_OFF_MIN_MS));
   assert(interval<=(strobeLit?STROBE_ON_MAX_MS:STROBE_OFF_MAX_MS));
   fakeNow=nextFlicker;
 }
 // A dark output gets a ramp even when the previous state was strobe.
 assert(brightness==0);setState(FLICKERING_ON,fakeNow);lightTick(fakeNow);
 assert(rampingOn && brightness==0);
 lightTick(fakeNow+FLICKER_ON_RAMP_MS);assert(!rampingOn && brightness>=170);
 // Both fades can quantize to zero before their logical OFF deadline.
 for(auto fade:{FLICKER_OUT,INTENSE_FLICKER_OUT}) {
   for(auto mode:{FLICKERING_ON,INTENSE_FLICKERING_ON}) {
     uint32_t duration=fade==FLICKER_OUT?FLICKER_OUT_MS:INTENSE_FLICKER_OUT_MS;
     fakeNow=450000;setState(fade,fakeNow);lightTick(fakeNow);
     assert(brightness>0);setState(mode,fakeNow);lightTick(fakeNow);
     assert(!rampingOn && brightness>=12);
     fakeNow=500000;setState(fade,fakeNow);
     fakeNow+=duration-1;lightTick(fakeNow);
     assert(lightState==fade && brightness==0);
     setState(mode,fakeNow);lightTick(fakeNow);
     assert(rampingOn && brightness==0);
     lightTick(fakeNow+FLICKER_ON_RAMP_MS);assert(!rampingOn && brightness>=12);
   }
 }
 // Command handling refreshes an expired fade even if the loop has not ticked yet.
 fakeNow=600000;setState(FLICKER_OUT,fakeNow);lightTick(fakeNow);assert(brightness>0);
 fakeNow+=FLICKER_OUT_MS;
 assert(command(cue(4,FLICKERING_ON,4))==ACCEPTED);
 assert(rampingOn && brightness==0 && lightState==FLICKERING_ON);
 auto strobePacket=cue(4,STROBE,4).packet;
 n=encode(strobePacket,wire);assert(n==61 && decode(wire,n,decoded));
 auto status=radio.make(LANTERN,BRIDGE_ID,19);status.payload[0]=STROBE;
 status.payload[1]=1;put32(status.payload+3,4);assert(shape(status));
 status.payload[0]=7;assert(!shape(status));
 Packet old;old.type=COMMAND;old.flags=ACK_REQUIRED;old.length=11;
 strcpy(old.src,"BRIDGE");strcpy(old.dst,"SERVO1");old.payload[4]=MOVE;assert(shape(old));
 puts("Lantern firmware behavior and wire compatibility checks passed");
}

