#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <vector>
#include <deque>
inline uint32_t fakeMillis=0;
inline uint32_t millis(){return fakeMillis;}
inline void delay(uint32_t ms){fakeMillis+=ms;}
inline uint32_t esp_random(){return 0;}
