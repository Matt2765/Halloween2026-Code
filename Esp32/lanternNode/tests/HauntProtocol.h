#pragma once
#include "../../libraries/HauntProtocol/src/HauntWire.h"
#include <cstdlib>
#define LOW 0
#define INPUT_PULLUP 1
inline uint32_t fakeNow=0;
inline int fakeButton=1;
inline uint32_t millis(){return fakeNow;}
inline void delay(uint32_t){}
inline void pinMode(int,int){}
inline int digitalRead(int){return fakeButton;}
inline uint32_t esp_random(){return 123;}
inline void randomSeed(uint32_t){}
inline long random(long lo,long hi){return lo+std::rand()%(hi-lo);}
struct FakeEsp {void restart(){std::abort();}};
inline FakeEsp ESP;
namespace haunt {
struct Received {Packet packet;};
struct Radio {
 Registry registry; uint32_t session=1;
 bool begin(const char*,Code(*)(const Received&)){return true;}
 Packet make(Type type,const char* dst,uint8_t length){Packet p;p.type=type;p.length=length;strcpy(p.src,"LANTERN1");strcpy(p.dst,dst);return p;}
 bool send(const Packet&){return true;}
 void poll(){}
 void diagnostic(){}
};
}

