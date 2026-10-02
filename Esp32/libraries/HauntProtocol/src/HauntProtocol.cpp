#include "HauntProtocol.h"
namespace haunt {
Radio* Radio::active_=nullptr;
bool Radio::begin(const char* id,Handler handler,Result result) {
  if(!validId(id)) return false;
  strcpy(id_,id); handler_=handler; result_=result;
  // Persist once per boot, not per packet. Light sleep keeps this session alive.
  Preferences prefs;
  if(!prefs.begin("haunt",false)) return false;
  session=prefs.getUInt("boot",0)+1;
  bool saved=prefs.putUInt("boot",session)==4; prefs.end();
  if(!saved) return false;
  urgent_=xQueueCreate(32,sizeof(Received)); telemetry_=xQueueCreate(16,sizeof(Received));
  if(!urgent_||!telemetry_) return false;
  WiFi.persistent(false); WiFi.mode(WIFI_STA);
  // ESP-NOW is the live control link. Modem sleep can otherwise add periodic
  // latency while an unassociated station wakes for radio traffic.
  if(esp_wifi_set_ps(WIFI_PS_NONE)!=ESP_OK||
     esp_wifi_set_channel(CHANNEL,WIFI_SECOND_CHAN_NONE)!=ESP_OK||
     esp_now_init()!=ESP_OK) return false;
  esp_now_peer_info_t peer{}; memcpy(peer.peer_addr,BROADCAST_MAC,6); peer.channel=CHANNEL; peer.ifidx=WIFI_IF_STA;
  if(esp_now_add_peer(&peer)!=ESP_OK) return false;
  active_=this; return esp_now_register_recv_cb(callback)==ESP_OK;
}
void Radio::receive(const uint8_t* mac,const uint8_t* data,int n) {
  auto* a=active_; if(!a) return;
  Received r{};
  if(n<0||!decode(data,size_t(n),r.packet)) { __atomic_fetch_add(&a->callbackMalformed_,1,__ATOMIC_RELAXED); return; }
  if(strcmp(r.packet.dst,a->id_) && strcmp(r.packet.dst,"*")) return;
  // Commands only originate at the bridge; general broadcasts cannot actuate.
  if(r.packet.type==COMMAND && strcmp(r.packet.src,BRIDGE_ID)) return;
  memcpy(r.mac,mac,6); r.rxMs=millis();
  auto q=(r.packet.flags||r.packet.type==ACK) ? a->urgent_ : a->telemetry_;
  // ESP-NOW callbacks run in the Wi-Fi task, NOT an ISR.
  if(xQueueSend(q,&r,0)!=pdTRUE) __atomic_fetch_add(&a->callbackDrops_,1,__ATOMIC_RELAXED);
  uint32_t depth=uxQueueMessagesWaiting(q);
  if(depth>__atomic_load_n(&a->callbackHigh_,__ATOMIC_RELAXED)) __atomic_store_n(&a->callbackHigh_,depth,__ATOMIC_RELAXED);
}
Packet Radio::make(Type type,const char* destination,uint8_t length,bool reliable) {
  Packet p; p.type=type; p.length=length; p.flags=reliable?ACK_REQUIRED:0;
  strcpy(p.src,id_); if(validId(destination,true)) strcpy(p.dst,destination);
  p.session=session; p.seq=++sequence; return p;
}
bool Radio::transmit(const Packet& p) {
  uint8_t bytes[HEADER+MAX_PAYLOAD]; size_t n=encode(p,bytes);
  if(!n||esp_now_send(BROADCAST_MAC,bytes,n)!=ESP_OK) { stats.sendErrors++; return false; } return true;
}
bool Radio::send(const Packet& p) {
  if(!shape(p)) return false;
  if(!p.flags) return transmit(p);
  // A distance snapshot supersedes its predecessor, including lost-ACK retries.
  if(p.type==TOF) for(auto& slot:pending_)
    if(slot.used && slot.packet.type==TOF && !strcmp(slot.packet.dst,p.dst)) slot.used=false;
  for(auto& slot:pending_) if(!slot.used) {
    slot=Pending{}; slot.used=true; slot.packet=p; slot.began=millis(); slot.next=slot.began; return true;
  }
  stats.drops++; return false;
}
bool Radio::busy() const { for(auto& p:pending_) if(p.used) return true; return false; }
void Radio::cancel(const char* destination,Code why) {
  for(auto& p:pending_) if(p.used&&(!destination||!strcmp(destination,p.packet.dst))) {
    p.used=false; if(result_) result_(p.packet,why,millis()-p.began);
  }
}
void Radio::ack(const Packet& original,Code code) {
  if(!original.flags||strcmp(original.dst,id_)) return;
  auto p=make(ACK,original.src,9); put32(p.payload,original.session); put32(p.payload+4,original.seq); p.payload[8]=code; transmit(p);
}
void Radio::process(const Received& r) {
  const Packet& p=r.packet;
  // Bound queued radio work as well as outbound retries. No success ACK for expiry.
  if(millis()-r.rxMs>DELIVERY_LIFETIME_MS) { stats.drops++; return; }
  PeerState* peer=nullptr; Code code=registry.inspect(p,r.mac,millis(),peer);
  if(code!=ACCEPTED) {
    if(code==CONFLICT) { stats.conflicts++; if(handler_) handler_(r); }
    if(code!=QUEUE_FULL) ack(p,code); return;
  }
  for(auto& slot:pending_) if(slot.used && slot.packet.type==COMMAND && !strcmp(slot.packet.dst,p.src) && get32(slot.packet.payload)!=p.session) {
    slot.used=false; if(result_) result_(slot.packet,UNCONFIRMED,millis()-slot.began);
  }
  if(p.type==TOF) peer->continuous=true;
  if(peer->continuous && (p.type==TOF||p.type==DIAGNOSTIC) && (!peer->seen||newer(p.seq,peer->lastSeen))) {
    if(peer->seen) { uint32_t gap=p.seq-peer->lastSeen-1; peer->gaps+=gap; stats.gaps+=gap; }
    peer->lastSeen=p.seq; peer->seen=true;
  }
  if(p.type==ACK) {
    for(auto& slot:pending_) if(slot.used && !strcmp(p.src,slot.packet.dst) && get32(p.payload)==slot.packet.session && get32(p.payload+4)==slot.packet.seq) {
      // Commands are tied to the actuator boot session as well as bridge identity.
      if(slot.packet.type==COMMAND && p.session!=get32(slot.packet.payload)) continue;
      slot.used=false; if(result_) result_(slot.packet,Code(p.payload[8]),millis()-slot.began); break;
    }
    return;
  }
  if(receipts_.find(p,code)) { stats.duplicates++; ack(p,code); return; }
  if(peer->initialized[stream(p)] && peer->seq[stream(p)]==p.seq) {
    stats.duplicates++; ack(p,ACCEPTED); return;
  }
  code=registry.order(p,*peer);
  if(code!=ACCEPTED) { ack(p,code); return; }
  if(p.type==COMMAND && get32(p.payload)!=session) code=WRONG_SESSION;
  else code=handler_?handler_(r):INVALID;
  if(code==QUEUE_FULL) return; // no receipt or successful ACK before queue acceptance
  if(code==ACCEPTED) {
    registry.commit(p,*peer);
  }
  if(p.flags) receipts_.add(p,code);
  ack(p,code);
}
void Radio::poll() {
  stats.drops+=__atomic_exchange_n(&callbackDrops_,0,__ATOMIC_RELAXED);
  stats.malformed+=__atomic_exchange_n(&callbackMalformed_,0,__ATOMIC_RELAXED);
  stats.highWater=__atomic_load_n(&callbackHigh_,__ATOMIC_RELAXED);
  Received r;
  for(int i=0;i<32 && xQueueReceive(urgent_,&r,0)==pdTRUE;i++) process(r);
  for(int i=0;i<8 && xQueueReceive(telemetry_,&r,0)==pdTRUE;i++) process(r);
  uint32_t now=millis();
  for(auto& p:pending_) if(p.used) {
    const uint32_t lifetime=p.packet.type==TOF ? 100 : DELIVERY_LIFETIME_MS;
    if((p.attempts>=ATTEMPTS && due(now,p.next)) || now-p.began>=lifetime) {
      p.used=false; stats.unconfirmed++; if(result_) result_(p.packet,UNCONFIRMED,now-p.began); continue;
    }
    if(!due(now,p.next)) continue;
    if(p.attempts++) stats.retries++;
    transmit(p.packet); p.next=now+RETRY_MS+(esp_random()%JITTER_MS);
  }
}
void Radio::diagnostic() {
  auto p=make(DIAGNOSTIC,BRIDGE_ID,24);
  uint32_t values[]={stats.drops,stats.highWater,stats.retries,stats.unconfirmed,stats.duplicates,stats.sendErrors};
  for(int i=0;i<6;i++) put32(p.payload+i*4,values[i]); send(p);
}
}
