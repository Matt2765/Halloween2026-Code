// Real receiver transport, fake hardware. No USB or physical outputs.
#include <Arduino.h>
#include <cassert>
#define private public
#include <HauntProtocol.h>
#undef private
#include "../../libraries/HauntProtocol/src/HauntProtocol.cpp"
using namespace haunt;
int accepted=0,rejections=0;
Code lastCode=ACCEPTED;
Radio* activeBridge=nullptr;
Code accept(const Received& r) {
  if(activeBridge->registry.find(r.packet.src)->conflict) return CONFLICT;
  accepted++; return ACCEPTED;
}
void rejected(const Received&,Code code) { rejections++; lastCode=code; }
Received report(uint32_t seq=1,uint32_t session=10,uint8_t mac=1) {
  Received r{}; strcpy(r.packet.src,"BTN4");strcpy(r.packet.dst,BRIDGE_ID);
  r.packet.type=BUTTON;r.packet.length=2;r.packet.payload[0]=1;
  r.packet.seq=seq;r.packet.session=session;r.mac[5]=mac;r.rxMs=fakeMillis;
  return r;
}
int main() {
  Radio bridge; activeBridge=&bridge;assert(bridge.begin(BRIDGE_ID,accept));bridge.onRejection(rejected);
  bridge.process(report(100));assert(accepted==1);
  fakeMillis=100;bridge.process(report(1,1,2));
  assert(lastCode==CONFLICT&&bridge.registry.find("BTN4")->conflict);
  // An active competitor extends quarantine; neither board can take control.
  fakeMillis=9000;bridge.process(report(2,1,2));
  fakeMillis=18000;bridge.process(report(101));assert(accepted==1);
  fakeMillis=19000;
  // A duplicate, old boot, diagnostic, ACK or command cannot release quarantine.
  bridge.process(report(99));bridge.process(report(1000,9));
  for(auto type:{DIAGNOSTIC,ACK,COMMAND}) {
    auto r=report(101);r.packet.type=type;bridge.process(r);
    assert(bridge.registry.find("BTN4")->conflict);
  }
  // An expired queued frame must not release it either.
  auto stale=report(101);stale.rxMs=fakeMillis-DELIVERY_LIFETIME_MS-1;
  bridge.process(stale);assert(bridge.registry.find("BTN4")->conflict);
  bridge.process(report(101));assert(accepted==2&&!bridge.registry.find("BTN4")->conflict);
  // Reboot accepts a newer persistent boot counter, rejects older sessions.
  bridge.process(report(1,11));assert(accepted==3);
  bridge.process(report(500,10));assert(accepted==3&&lastCode==WRONG_SESSION);
  bridge.process(report(0,11));assert(accepted==3&&lastCode==SUPERSEDED);
  // Another device continues independently throughout quarantine.
  auto pir=report();strcpy(pir.packet.src,"PIR1");bridge.process(pir);assert(accepted==4);
  bridge.process(report(2,11,2));assert(bridge.registry.find("BTN4")->conflict);
  pir.packet.seq++;bridge.process(pir);assert(accepted==5);
  // Quiet-time arithmetic survives the 32-bit millis wrap.
  Registry registry;PeerState* peer=nullptr;auto original=report();auto other=report(1,1,2);
  assert(registry.inspect(original.packet,original.mac,0xfffff000,peer)==ACCEPTED);
  registry.commit(original.packet,*peer);
  assert(registry.inspect(other.packet,other.mac,0xfffff100,peer)==CONFLICT);
  original.packet.seq=2;
  assert(registry.inspect(original.packet,original.mac,uint32_t(0xfffff100+CONFLICT_QUIET_MS),peer)==ACCEPTED);
  assert(rejections>0);
  puts("Receiver recovery checks passed: duplicate identity, quiet time, replay guards, reboot, isolated recovery, diagnostics, and clock wrap");
}
