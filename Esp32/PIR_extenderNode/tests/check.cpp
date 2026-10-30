#include <Arduino.h>
#include <cassert>
#define private public
#include <HauntProtocol.h>
#undef private
#include "../../libraries/HauntProtocol/src/HauntProtocol.cpp"
using namespace haunt;
int executions=0,accepted=0,telemetry=0;
uint8_t lastOrigin[6]={};
Code endpoint(const Received& r){
 if(r.packet.type!=COMMAND)return INVALID;
 executions++;return ACCEPTED;
}
Code bridgeReceiver(const Received& r){telemetry++;memcpy(lastOrigin,r.mac,6);return ACCEPTED;}
void result(const Packet&,Code code,uint32_t){if(code==ACCEPTED)accepted++;}
void begin(Radio& radio,const char* id,uint8_t mac,Radio::Handler fn=nullptr,Radio::Result cb=nullptr){
 memset(fakeMac,0,6);fakeMac[5]=mac;assert(radio.begin(id,fn,cb));
}
std::vector<uint8_t> take(){assert(sent.size()==1);auto bytes=sent[0].bytes;sent.clear();return bytes;}
void inject(Radio& receiver,const std::vector<uint8_t>& bytes,uint8_t physicalMac){
 uint8_t mac[6]={};mac[5]=physicalMac;
 Radio::active_=&receiver;Radio::receive(mac,bytes.data(),int(bytes.size()));receiver.poll();
}
int main(){
 Radio bridge,node,r1,r2,r3;
 r1.enableExtender();r2.enableExtender();r3.enableExtender();
 begin(bridge,"BRIDGE",1,bridgeReceiver,result);begin(node,"MOSFET1",2,endpoint);
 begin(r1,"PIR4",3);begin(r2,"PIR5",4);begin(r3,"PIR6",5);
 // Telemetry across two extenders preserves the original physical node identity.
 auto status=node.make(MOSFET,BRIDGE_ID,24);put64(status.payload,uint64_t(1)<<13);
 assert(node.send(status));auto directStatus=take();
 inject(r1,directStatus,2);auto first=take();
 ExtendedPacket decoded;assert(decodeExtended(first.data(),first.size(),decoded)&&decoded.hops==1);
 inject(r2,first,3);auto second=take();
 inject(bridge,second,4);assert(telemetry==1&&lastOrigin[5]==2&&sent.empty());
 inject(bridge,directStatus,2);assert(!bridge.registry.find("MOSFET1")->conflict);
 // Command and acknowledgement travel both ways; only the endpoint accepts it.
 auto command=bridge.make(COMMAND,"MOSFET1",12,true);
 put32(command.payload,node.session);command.payload[4]=MOSFET_SET;
 put16(command.payload+5,1);command.payload[11]=13;
 assert(bridge.send(command));bridge.poll();auto directCommand=take();
 inject(r2,directCommand,1);auto down1=take();inject(r1,down1,4);auto down2=take();
 inject(node,down2,3);auto directAck=take();assert(executions==1);
 inject(r1,directAck,2);auto ack1=take();inject(r2,ack1,3);auto ack2=take();
 inject(bridge,ack2,4);assert(accepted==1&&!bridge.busy());
 inject(node,directCommand,1);take();assert(executions==1&&!node.registry.find("BRIDGE")->conflict);
 // The same flood is not reflected indefinitely between overlapping extenders.
 inject(r2,first,3);assert(sent.empty());
 inject(r3,second,4);auto third=take();
 assert(decodeExtended(third.data(),third.size(),decoded)&&decoded.hops==3);
 inject(r1,third,5);assert(sent.empty());
 // Retrying the same original command gets a new flood ID, not a permanent suppression.
 inject(r2,directCommand,1);auto retry=take();
 ExtendedPacket original,retried;
 assert(decodeExtended(down1.data(),down1.size(),original));
 assert(decodeExtended(retry.data(),retry.size(),retried));
 assert(original.floodSequence!=retried.floodSequence);
 // A real bridge retry after a dropped forwarded transmission still reaches the node.
 auto next=bridge.make(COMMAND,"MOSFET1",12,true);
 put32(next.payload,node.session);next.payload[4]=MOSFET_SET;next.payload[11]=13;
 assert(bridge.send(next));bridge.poll();auto attempt1=take();
 inject(r2,attempt1,1);auto lost=take(); // Deliberately lose this RF transmission.
 fakeMillis+=RETRY_MS+JITTER_MS;bridge.poll();auto attempt2=take();
 inject(r2,attempt2,1);auto recovered=take();
 inject(node,recovered,4);auto recoveredAck=take();inject(bridge,recoveredAck,2);
 assert(executions==2&&accepted==2&&bridge.stats.retries==1);
 assert(r1.stats.retries==0&&r2.stats.retries==0);
 // Other node types are relayed without an ID or device-kind allowlist.
 auto button=node.make(BUTTON,BRIDGE_ID,2);strcpy(button.src,"BTN99");button.payload[0]=1;
 assert(node.send(button));auto directButton=take();inject(r1,directButton,7);auto extendedButton=take();
 assert(decodeExtended(extendedButton.data(),extendedButton.size(),decoded));
 assert(decoded.packet.type==BUTTON&&!strcmp(decoded.packet.src,"BTN99")&&decoded.originMac[5]==7);
 // Old queued forwarding cannot refresh stale actions into fresh commands.
 Radio::active_=&r1;uint8_t mac[6]={};mac[5]=1;
 Radio::receive(mac,directCommand.data(),int(directCommand.size()));
 fakeMillis+=DELIVERY_LIFETIME_MS+1;r1.poll();assert(sent.empty()&&r1.forwardFailures>0);
 // Envelopes cannot contain another envelope or extend past the hop/lifetime bounds.
 auto bad=first;bad[3]=EXTENDER_HOPS+1;assert(!decodeExtended(bad.data(),bad.size(),decoded));
 bad=first;put16(bad.data()+4,DELIVERY_LIFETIME_MS+1);assert(!decodeExtended(bad.data(),bad.size(),decoded));
 bad=first;bad.pop_back();assert(!decodeExtended(bad.data(),bad.size(),decoded));
 // The extender still sends its own ordinary PIR reports without wrapping them.
 auto pir=r1.make(PIR,BRIDGE_ID,2);pir.payload[1]=1;assert(r1.send(pir));auto own=take();
 Packet unpacked;assert(decode(own.data(),own.size(),unpacked)&&unpacked.type==PIR);
 puts("Extender transport checks passed: multi-hop telemetry, command/ACK, identity, duplicates, retries, expiry, and PIR reports");
}
