#pragma once
struct Preferences {
 bool begin(const char*,bool){return true;}
 uint32_t getUInt(const char*,uint32_t){return 0;}
 size_t putUInt(const char*,uint32_t){return 4;}
 void end(){}
};
