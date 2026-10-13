#pragma once
#include "../../libraries/HauntProtocol/src/HauntWire.h"
#include <cstdlib>
#define LOW 0
#define HIGH 1
#define OUTPUT 1
inline uint32_t fakeNow=0;
inline int levels[40]={};
inline uint32_t millis(){return fakeNow;}
inline void delay(uint32_t){}
inline void pinMode(int,int){}
inline void digitalWrite(int pin,int level){levels[pin]=level;}
struct FakeEsp {void restart(){std::abort();}};
inline FakeEsp ESP;
namespace haunt {
struct Received {Packet packet;};
struct Radio {
 Registry registry; uint32_t session=1;
 bool begin(const char*,Code(*)(const Received&)){return true;}
 Packet make(Type type,const char* dst,uint8_t length){Packet p;p.type=type;p.length=length;strcpy(p.src,"PEDRO1");strcpy(p.dst,dst);return p;}
 bool send(const Packet& p){return shape(p);}
 void poll(){}
 void diagnostic(){}
};
}
