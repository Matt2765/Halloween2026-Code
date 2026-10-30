#pragma once
#include "HauntWire.h"
namespace haunt {
// A separate envelope leaves the existing direct packet format unchanged.
// Original MAC, ID, session and sequence survive every hop.
constexpr uint8_t EXTENDER_HOPS=3;
constexpr size_t EXTENDER_HEADER=27, EXTENDER_MAX_BYTES=EXTENDER_HEADER+HEADER+MAX_PAYLOAD;
struct ExtendedPacket {
  Packet packet;
  uint8_t originMac[6]={}, floodMac[6]={};
  uint32_t floodSession=0,floodSequence=0;
  uint16_t ageMs=0;
  uint8_t hops=1;
};
inline bool extenderFrame(const uint8_t* bytes,size_t n) {
  return bytes && n>=3 && bytes[0]==0x48 && bytes[1]==0x58 && bytes[2]==1;
}
inline size_t encodeExtended(const ExtendedPacket& frame,uint8_t* bytes) {
  if(!frame.hops || frame.hops>EXTENDER_HOPS || frame.ageMs>DELIVERY_LIFETIME_MS ||
     !frame.floodSession || !frame.floodSequence) return 0;
  size_t n=encode(frame.packet,bytes+EXTENDER_HEADER);
  if(!n) return 0;
  bytes[0]=0x48; bytes[1]=0x58; bytes[2]=1; bytes[3]=frame.hops;
  put16(bytes+4,frame.ageMs);
  memcpy(bytes+6,frame.originMac,6); memcpy(bytes+12,frame.floodMac,6);
  put32(bytes+18,frame.floodSession); put32(bytes+22,frame.floodSequence);
  bytes[26]=uint8_t(n);
  return EXTENDER_HEADER+n;
}
inline bool decodeExtended(const uint8_t* bytes,size_t n,ExtendedPacket& frame) {
  if(!extenderFrame(bytes,n) || n<EXTENDER_HEADER+HEADER || n>EXTENDER_MAX_BYTES ||
     !bytes[3] || bytes[3]>EXTENDER_HOPS || get16(bytes+4)>DELIVERY_LIFETIME_MS ||
     n!=EXTENDER_HEADER+bytes[26] || !get32(bytes+18) || !get32(bytes+22)) return false;
  frame=ExtendedPacket{};
  if(!decode(bytes+EXTENDER_HEADER,bytes[26],frame.packet)) return false; // No nested envelopes.
  frame.hops=bytes[3]; frame.ageMs=get16(bytes+4);
  memcpy(frame.originMac,bytes+6,6); memcpy(frame.floodMac,bytes+12,6);
  frame.floodSession=get32(bytes+18); frame.floodSequence=get32(bytes+22);
  return true;
}
struct ExtenderSeen {
  struct Entry { bool used=false; uint8_t mac[6]={},hops=0; uint32_t session=0,seq=0,at=0; } entries[128];
  uint8_t next=0;
  bool duplicate(const ExtendedPacket& frame,uint32_t now) {
    for(auto& e:entries) if(e.used && now-e.at<=DELIVERY_LIFETIME_MS &&
        !memcmp(e.mac,frame.floodMac,6) && e.session==frame.floodSession && e.seq==frame.floodSequence) {
      if(frame.hops>=e.hops) return true;
      e.hops=frame.hops; return false; // A shorter route can still reach further nodes.
    }
    auto& e=entries[next++%128]; e.used=true; e.hops=frame.hops;
    memcpy(e.mac,frame.floodMac,6); e.session=frame.floodSession; e.seq=frame.floodSequence; e.at=now;
    return false;
  }
};
static_assert(EXTENDER_MAX_BYTES<=250,"Extender frames must fit ESP-NOW v1");
}
