#pragma once
#include <stdint.h>

// Nominal 60 Hz only. Times reference the selected SYNC edge, not measured 0 V.
constexpr uint16_t HALF_US = 8333;
constexpr uint16_t MIN_DELAY_US = 350;
// User-observed full brightness: the original SET 95 fired at 730 us.
// This is load calibration, not proof of full electrical conduction.
constexpr uint16_t FULL_ON_DELAY_US = 730;
constexpr uint16_t PULSE_US = 100; // Bench starting point; not a verified KRIDA minimum.
constexpr uint16_t END_GUARD_US = 350;
constexpr uint16_t MAX_DELAY_US = HALF_US - PULSE_US - END_GUARD_US;
constexpr uint16_t MIN_HALF_US = 8100;
constexpr uint16_t MAX_HALF_US = 8600;
constexpr uint16_t LATE_LIMIT_US = 50;
constexpr uint16_t OFF_DELAY = 0xffff;
static_assert(MAX_DELAY_US + PULSE_US + LATE_LIMIT_US < MIN_HALF_US,
              "Pulse plus allowed lateness must end before earliest accepted crossing");
static_assert(FULL_ON_DELAY_US >= MIN_DELAY_US && FULL_ON_DELAY_US < MAX_DELAY_US,
              "Calibrated full-on delay must be within the test window");

struct DimmerEvent {
  uint16_t ticks;
  uint8_t onMask;
  uint8_t offMask;
};
struct Schedule {
  DimmerEvent events[16];
  uint8_t count;
};

inline uint16_t brightnessToDelayUs(uint8_t pct) {
  if (pct == 0) return OFF_DELAY;
  if (pct == 100) return FULL_ON_DELAY_US;
  // Linear firing angle across the usable window; not linear watts or light.
  return FULL_ON_DELAY_US + (uint32_t)(100 - pct) *
         (MAX_DELAY_US - FULL_ON_DELAY_US) / 99;
}

inline void insertEvent(Schedule &s, uint16_t ticks, uint8_t on, uint8_t off) {
  uint8_t i = 0;
  while (i < s.count && s.events[i].ticks < ticks) ++i;
  if (i < s.count && s.events[i].ticks == ticks) {
    s.events[i].onMask |= on;
    s.events[i].offMask |= off;
    return;
  }
  for (uint8_t j = s.count; j > i; --j) s.events[j] = s.events[j - 1];
  s.events[i] = {ticks, on, off};
  ++s.count;
}

inline void buildSchedule(Schedule &s, const uint16_t delays[8]) {
  s.count = 0;
  for (uint8_t ch = 0; ch < 8; ++ch) {
    if (delays[ch] == OFF_DELAY) continue;
    const uint8_t mask = uint8_t(1u << ch);
    insertEvent(s, delays[ch] * 2, mask, 0);
    insertEvent(s, (delays[ch] + PULSE_US) * 2, 0, mask);
  }
}
