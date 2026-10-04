#pragma once
#include "HauntConfig.h"
#include <stddef.h>
#include <string.h>
namespace haunt {
constexpr size_t ID_BYTES = 16, HEADER = 46, MAX_PAYLOAD = 64;
enum Type : uint8_t { TOF=1, BUTTON=2, PIR=3, SERVO=4, SPRITE=5, COMMAND=6, ACK=7, DIAGNOSTIC=8, LANTERN=9 };
enum Code : uint8_t { ACCEPTED=0, INVALID=1, SUPERSEDED=2, WRONG_SESSION=3, CONFLICT=4, QUEUE_FULL=5, UNCONFIRMED=6 };
enum Op : uint8_t { MOVE=1, SET_DEFAULT=2, PLAY=3, NEXT=4, LANTERN_STATE=5 };
constexpr uint8_t ACK_REQUIRED = 1;
constexpr uint8_t LANTERN_STATE_MAX = 6; // Existing 0..5 unchanged; 6 = strobe.
inline bool newer(uint32_t a, uint32_t b) { return int32_t(a-b)>0; }
inline bool due(uint32_t now, uint32_t at) { return int32_t(now-at)>=0; }
inline void put16(uint8_t* p, uint16_t v) { p[0]=v; p[1]=v>>8; }
inline void put32(uint8_t* p, uint32_t v) { for(int i=0;i<4;i++) p[i]=v>>(8*i); }
inline uint16_t get16(const uint8_t* p) { return uint16_t(p[0]) | uint16_t(p[1])<<8; }
inline uint32_t get32(const uint8_t* p) { return uint32_t(p[0]) | uint32_t(p[1])<<8 | uint32_t(p[2])<<16 | uint32_t(p[3])<<24; }
inline bool validId(const char* id, bool all=false) {
  if(!id) return false;
  size_t n=0;
  for(;n<ID_BYTES && id[n];n++) {
    char c=id[n];
    if(!((c>='A'&&c<='Z')||(c>='a'&&c<='z')||(c>='0'&&c<='9')||c=='_'||c=='-'||(all&&c=='*'&&n==0&&id[1]==0))) return false;
  }
  return n>0 && n<ID_BYTES;
}
struct Packet {
  Type type=TOF; uint8_t flags=0, length=0;
  char src[ID_BYTES]={}, dst[ID_BYTES]={};
  uint32_t session=0, seq=0;
  uint8_t payload[MAX_PAYLOAD]={};
};
inline bool shape(const Packet& p) {
  if(!validId(p.src)||!validId(p.dst,true)||p.flags>1||p.length>MAX_PAYLOAD) return false;
  if(p.flags && (!strcmp(p.dst,"*") || (p.type!=TOF&&p.type!=BUTTON&&p.type!=PIR&&p.type!=COMMAND))) return false;
  const uint8_t* b=p.payload;
  switch(p.type) {
    case TOF: return p.length==5 && b[0]<=1 && (!b[0] || (int16_t(get16(b+1))>=0 && get16(b+3)==0));
    case BUTTON: return p.length==2 && b[0]>=1 && b[0]<=8 && b[1]<=1;
    case PIR: return p.length==2 && b[0]<=1 && b[1]<=1;
    case SERVO: return p.length==17 && b[4]<=1 && get16(b)<=180 && get16(b+2)<=180 && (get16(b+15)==0xffff || get16(b+15)<=180);
    case SPRITE: return p.length==9 && b[0]<=200;
    case LANTERN: return p.length==19 && b[0]<=LANTERN_STATE_MAX && b[1]<=1 && get32(b+3)>=1;
    case COMMAND: return p.flags==ACK_REQUIRED && strcmp(p.dst,"*") &&
      ((p.length==11 && b[4]!=LANTERN_STATE) ||
       (p.length==15 && b[4]==LANTERN_STATE && get16(b+5)<=LANTERN_STATE_MAX && get32(b+7)>=1 && get32(b+7)<0xffffffff));
    case ACK: return p.length==9 && !p.flags && b[8]<=UNCONFIRMED && strcmp(p.dst,"*");
    case DIAGNOSTIC: return p.length==24;
    default: return false;
  }
}
// Little endian integers; IDs are zero padded ASCII, at most 15 bytes, never truncated.
inline size_t encode(const Packet& p, uint8_t* out) {
  if(!shape(p)) return 0;
  memset(out,0,HEADER+p.length);
  put16(out,NETWORK); out[2]=VERSION; out[3]=p.type; out[4]=p.flags; out[5]=p.length;
  memcpy(out+6,p.src,strlen(p.src)); memcpy(out+22,p.dst,strlen(p.dst));
  put32(out+38,p.session); put32(out+42,p.seq); memcpy(out+HEADER,p.payload,p.length);
  return HEADER+p.length;
}
inline bool decode(const uint8_t* in, size_t n, Packet& p) {
  if(!in||n<HEADER||n>250||get16(in)!=NETWORK||in[2]!=VERSION||in[5]>MAX_PAYLOAD||n!=HEADER+in[5]) return false;
  p=Packet{}; p.type=Type(in[3]); p.flags=in[4]; p.length=in[5];
  memcpy(p.src,in+6,16); memcpy(p.dst,in+22,16);
  if(!validId(p.src)||!validId(p.dst,true)) return false;
  for(size_t i=strlen(p.src);i<16;i++) if(p.src[i]) return false;
  for(size_t i=strlen(p.dst);i<16;i++) if(p.dst[i]) return false;
  p.session=get32(in+38); p.seq=get32(in+42); memcpy(p.payload,in+HEADER,p.length);
  return shape(p);
}
inline uint8_t stream(const Packet& p) { return p.type==DIAGNOSTIC ? 9 : p.type==BUTTON ? p.payload[0] : 0; }
struct PeerState {
  char id[16]={}; uint8_t mac[6]={}; uint32_t session=0, heard=0;
  bool conflict=false, initialized[10]={}, seen=false,continuous=false;
  uint32_t seq[10]={}, gaps=0,lastSeen=0;
};
// Lifetime registry: fail closed at capacity; do not evict ordering/conflict evidence.
struct Registry {
  PeerState peers[MAX_DEVICES];
  PeerState* find(const char* id) { for(auto& e:peers) if(!strcmp(e.id,id)) return &e; return nullptr; }
  Code inspect(const Packet& p, const uint8_t* mac, uint32_t now, PeerState*& e) {
    e=find(p.src);
    if(!e) for(auto& slot:peers) if(!slot.id[0]) { e=&slot; strcpy(e->id,p.src); memcpy(e->mac,mac,6); e->session=p.session; break; }
    if(!e) return QUEUE_FULL;
    if(memcmp(e->mac,mac,6)) e->conflict=true;
    if(e->conflict) return CONFLICT;
    if(e->session!=p.session) {
      if(!newer(p.session,e->session)) return WRONG_SESSION;
      e->session=p.session; memset(e->initialized,0,sizeof(e->initialized));
      e->seen=false;
      e->continuous=false;
    }
    e->heard=now;
    return ACCEPTED;
  }
  Code order(const Packet& p, const PeerState& e) const {
    auto s=stream(p);
    return e.initialized[s] && !newer(p.seq,e.seq[s]) ? SUPERSEDED : ACCEPTED;
  }
  void commit(const Packet& p, PeerState& e) { auto s=stream(p); e.seq[s]=p.seq; e.initialized[s]=true; }
};
struct Receipt { char src[16]={}; uint32_t session=0,seq=0; Code code=ACCEPTED; };
struct Receipts {
  Receipt items[64]; uint8_t next=0;
  bool find(const Packet& p, Code& code) const {
    for(auto& r:items) if(!strcmp(r.src,p.src)&&r.session==p.session&&r.seq==p.seq) { code=r.code; return true; } return false;
  }
  void add(const Packet& p, Code code) { auto& r=items[next++%64]; strcpy(r.src,p.src); r.session=p.session; r.seq=p.seq; r.code=code; }
};
struct Ramp {
  int current=1500,start=1500,target=1500; uint32_t began=0,duration=0;
  bool moving() const { return duration!=0; }
  bool tick(uint32_t now) {
    if(!duration) return false;
    uint32_t elapsed=now-began;
    if(elapsed>=duration) { current=target; duration=0; return true; }
    current=start+int((int64_t(target-start)*elapsed)/duration); return false;
  }
  void move(int value,uint32_t ms,uint32_t now) {
    tick(now); start=current; target=value; began=now; duration=ms;
    if(!ms) current=start=target;
  }
};
struct Debounced {
  bool raw=false,stable=false; uint32_t changed=0;
  bool sample(bool value,uint32_t now,uint32_t debounce) {
    if(value!=raw) { raw=value; changed=now; }
    if(raw!=stable && now-changed>=debounce) { stable=raw; return true; }
    return false;
  }
};
static_assert(HEADER+MAX_PAYLOAD<=250,"ESP-NOW v1 budget");
}
