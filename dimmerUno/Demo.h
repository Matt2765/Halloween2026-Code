#pragma once
#include <stdint.h>

constexpr uint8_t DEFAULT_DEMO_PEAK = 100; // Calibrated maximum (original SET 95).
constexpr uint16_t DEMO_UPDATE_MS = 20;

// Repeatable noise avoids random-state coupling to the other channel's ramp.
inline uint8_t fireNoise(uint32_t index) {
  index ^= index >> 16;
  index *= 0x7feb352dUL;
  index ^= index >> 15;
  return index % 101;
}

inline uint8_t blendedFireNoise(uint32_t elapsedMs, uint16_t intervalMs) {
  const uint32_t index = elapsedMs / intervalMs;
  const int16_t a = fireNoise(index);
  const int16_t b = fireNoise(index + 1);
  return a + int32_t(b - a) * int32_t(elapsedMs % intervalMs) / intervalMs;
}

inline uint8_t fireDemoLevel(uint8_t ch, uint32_t elapsedMs, uint8_t peak) {
  if (ch == 0) {
    // Fast flame flutter layered over slower changes in the ember glow.
    const uint8_t intensity = 20 + blendedFireNoise(elapsedMs, 100) / 2 +
                             uint16_t(blendedFireNoise(elapsedMs, 470)) * 30 / 100;
    return uint16_t(intensity) * peak / 100;
  }
  if (ch == 1) {
    const uint16_t phase = elapsedMs % 6000;
    const uint16_t ramp = phase <= 3000 ? phase : 6000 - phase;
    return uint32_t(ramp) * peak / 3000; // Three seconds up, three down.
  }
  return 0;
}

// Independent repeating timelines. Other channels keep moving when a channel
// begins, reverses, finishes or waits OFF. No shared ramp-completion barrier.
inline uint8_t demoLevel(uint8_t ch, uint32_t elapsedMs, uint8_t peak) {
  const uint16_t start = ch * 650;
  if (elapsedMs < start) return 0;
  const uint16_t up = 2400 + ch * 170;
  const uint16_t hold = 400;
  const uint16_t down = 2800 + ch * 230;
  const uint16_t rest = 1100 + ch * 90;
  uint16_t phase = (elapsedMs - start) % (up + hold + down + rest);
  if (phase < up) return uint32_t(phase) * peak / up;
  phase -= up;
  if (phase < hold) return peak;
  phase -= hold;
  if (phase < down) return uint32_t(down - phase) * peak / down;
  return 0;
}
