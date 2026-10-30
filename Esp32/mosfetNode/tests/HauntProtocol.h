#pragma once
#include "../../pedroNode/tests/HauntProtocol.h"
struct FakeSerial {
  void begin(unsigned long) {}
  template<class... Args> void printf(const char*, Args...) {}
  void println(const char*) {}
};
inline FakeSerial Serial;
