#include "../mosfetNode.ino"
#include <cassert>
#include <cstdio>
Received setPin(int pin,bool on,uint32_t sequence=1) {
 Received r;auto& p=r.packet;p.type=COMMAND;p.flags=ACK_REQUIRED;p.length=12;
 strcpy(p.src,"BRIDGE");strcpy(p.dst,"MOSFET1");p.session=2;p.seq=sequence;
 put32(p.payload,1);p.payload[4]=MOSFET_SET;put16(p.payload+5,on);p.payload[11]=pin;
 return r;
}
int main() {
 setup();assert(OUTPUT_COUNT==20 && onPins==0);
 for(auto pin:OUTPUT_PINS) assert(levels[pin]==LOW && (availablePins&(uint64_t(1)<<pin)));
 assert(command(setPin(13,true))==ACCEPTED && levels[13]==HIGH);
 assert(command(setPin(14,true,2))==ACCEPTED && levels[13]==HIGH && levels[14]==HIGH);
 assert(command(setPin(13,false,3))==ACCEPTED && levels[13]==LOW && levels[14]==HIGH);
 auto before=onPins;assert(command(setPin(34,true))==INVALID && onPins==before);
 assert(command(setPin(6,true))==INVALID && onPins==before);
 auto bad=setPin(13,true);put16(bad.packet.payload+5,2);assert(command(bad)==INVALID);
 bad=setPin(13,true);put32(bad.packet.payload+7,1);assert(command(bad)==INVALID);
 bad=setPin(13,true);bad.packet.length=11;assert(command(bad)==INVALID);
 assert(commandSequence==3 && commandSession==2);
 fakeNow=1000000;loop();assert(levels[14]==HIGH); // Latched, no heartbeat needed.
 auto p=setPin(13,true).packet;uint8_t wire[110];Packet decoded;
 auto n=encode(p,wire);assert(n==58 && decode(wire,n,decoded));
 p.length=11;assert(!shape(p));p=setPin(40,true).packet;assert(!shape(p));
 p=setPin(13,true).packet;put32(p.payload+7,1);assert(!shape(p));
 // Per-pin ordering allows older commands on another GPIO to arrive independently.
 Registry registry;uint8_t mac[6]={1};PeerState* peer=nullptr;
 auto first=setPin(13,true,10).packet;assert(registry.inspect(first,mac,0,peer)==ACCEPTED);
 registry.commit(first,*peer);
 auto other=setPin(14,true,9).packet;assert(registry.order(other,*peer)==ACCEPTED);
 registry.commit(other,*peer);auto stale=setPin(13,false,9).packet;
 assert(registry.order(stale,*peer)==SUPERSEDED);
 auto fresh=setPin(13,false,11).packet;assert(registry.order(fresh,*peer)==ACCEPTED);
 assert(stream(first)!=stream(other) && stream(first)<STREAM_COUNT);
 auto telemetry=radio.make(MOSFET,BRIDGE_ID,24);
 put64(telemetry.payload,availablePins);put64(telemetry.payload+8,onPins);assert(shape(telemetry));
 put64(telemetry.payload+8,uint64_t(1)<<34);assert(!shape(telemetry));
 puts("MOSFET GPIO, latching, validation, codec and per-pin ordering checks passed");
}
