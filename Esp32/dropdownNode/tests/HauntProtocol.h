#pragma once
#include "../../libraries/HauntProtocol/src/HauntWire.h"
#include <algorithm>
#include <cstdlib>
#include <cstdio>
#include <string>
#include <vector>
#define LOW 0
#define HIGH 1
#define OUTPUT 1
#define INPUT_PULLUP 2
inline uint32_t fakeNow=0;
inline int levels[40]={};
inline uint32_t millis(){return fakeNow;}
inline void delay(uint32_t){}
inline void pinMode(int,int){}
inline void digitalWrite(int pin,int level){levels[pin]=level;}
inline int digitalRead(int pin){return levels[pin];}
inline int constrain(int value,int low,int high){return std::clamp(value,low,high);}
inline int savedAngle=90;
inline bool saveWorks=true;
struct Preferences {
 bool begin(const char*,bool){return true;}
 int getInt(const char*,int){return savedAngle;}
 size_t putInt(const char*,int value){if(!saveWorks)return 0;savedAngle=value;return 4;}
 void end(){}
};
struct FakeEsp {void restart(){std::abort();}};
inline FakeEsp ESP;
struct FakeSerial {
 bool connected=false; int capacity=512; std::string written;
 void begin(unsigned long){}
 explicit operator bool() const {return connected;}
 int availableForWrite() const {return capacity;}
 size_t write(const uint8_t* data,size_t n){written.append(reinterpret_cast<const char*>(data),n);return n;}
};
inline FakeSerial Serial;
namespace haunt {
struct Received {Packet packet;};
struct Radio {
 struct {uint32_t drops=0,sendErrors=0,retries=0,unconfirmed=0;} stats;
 Registry registry; uint32_t session=1,sequence=0;
 std::vector<Packet> sent;
 bool begin(const char*,Code(*)(const Received&)){return true;}
 Packet make(Type type,const char* dst,uint8_t length,bool reliable=false){
   Packet p;p.type=type;p.length=length;p.flags=reliable?ACK_REQUIRED:0;
   strcpy(p.src,"DROPDOWN1");strcpy(p.dst,dst);p.session=session;p.seq=++sequence;return p;
 }
 bool send(const Packet& p){if(!shape(p))std::abort();sent.push_back(p);return true;}
 void poll(){}
 void diagnostic(){}
};
}
