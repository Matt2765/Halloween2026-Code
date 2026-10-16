#pragma once
#include <stdint.h>

// Interpolate firing times directly, retaining sub-percent brightness steps.
// Unsigned elapsed arithmetic also works across the millis() rollover.
struct GlowRamp {
  bool running = false;
  uint16_t lowDelay = 0, highDelay = 0, rampMs = 0;
  uint32_t startMs = 0;

  uint16_t delayAt(uint32_t now) const {
    const uint32_t phase = uint32_t(now - startMs) % (uint32_t(rampMs) * 2);
    const uint32_t progress = phase <= rampMs ? phase : uint32_t(rampMs) * 2 - phase;
    return lowDelay - uint32_t(lowDelay - highDelay) * progress / rampMs;
  }
};
