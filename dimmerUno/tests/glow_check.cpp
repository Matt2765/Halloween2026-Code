#include <assert.h>
#include "../Glow.h"
#include "../Schedule.h"

int main() {
  GlowRamp glow;
  glow.lowDelay = 6871;
  glow.highDelay = 6148;
  glow.rampMs = 2500;
  glow.startMs = 100;
  assert(glow.delayAt(100) == 6871);
  assert(glow.delayAt(2600) == 6148);
  assert(glow.delayAt(5100) == 6871);
  // Firing time stays continuous and monotonic in each half of the cycle.
  for (uint32_t t = 101; t <= 2600; ++t) {
    assert(glow.delayAt(t) <= glow.delayAt(t - 1));
    assert(glow.delayAt(t - 1) - glow.delayAt(t) <= 1);
  }
  for (uint32_t t = 2601; t <= 5100; ++t)
    assert(glow.delayAt(t) >= glow.delayAt(t - 1));
  // A delayed loop catches up from elapsed time, without accumulating drift.
  assert(glow.delayAt(1350) == 6510);
  assert(glow.delayAt(11350) == 6510);
  glow.startMs = UINT32_MAX - 100;
  assert(glow.delayAt(uint32_t(glow.startMs + 2500)) == 6148);

  // Eight independent timelines, including channels rising while others fall.
  GlowRamp channels[8];
  for (uint8_t ch = 0; ch < 8; ++ch) {
    channels[ch].lowDelay = 6871;
    channels[ch].highDelay = 6148;
    channels[ch].rampMs = 1000 + ch * 250;
    channels[ch].startMs = ch * 100;
  }
  for (uint32_t now = 1000; now < 10000; now += 5) {
    uint16_t delays[8];
    for (uint8_t ch = 0; ch < 8; ++ch) delays[ch] = channels[ch].delayAt(now);
    Schedule schedule = {};
    buildSchedule(schedule, delays);
    // Every channel retains its own ON/OFF times, even when times coincide.
    for (uint8_t ch = 0; ch < 8; ++ch) {
      uint8_t starts = 0, stops = 0;
      for (uint8_t i = 0; i < schedule.count; ++i) {
        if (schedule.events[i].onMask & (1u << ch)) {
          ++starts;
          assert(schedule.events[i].ticks == delays[ch] * 2);
        }
        if (schedule.events[i].offMask & (1u << ch)) {
          ++stops;
          assert(schedule.events[i].ticks == (delays[ch] + PULSE_US) * 2);
        }
      }
      assert(starts == 1 && stops == 1);
    }
  }
  // All eight at the same brightness merge into two simultaneous gate events.
  uint16_t equalDelays[8] = {6500,6500,6500,6500,6500,6500,6500,6500};
  Schedule simultaneous = {};
  buildSchedule(simultaneous, equalDelays);
  assert(simultaneous.count == 2);
  assert(simultaneous.events[0].onMask == 0xff);
  assert(simultaneous.events[1].offMask == 0xff);
}
