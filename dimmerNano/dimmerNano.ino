// Standalone KRIDA 8CH leading-edge bench test. No external libraries.
// Classic 16 MHz ATmega328P UNO/Nano ONLY. SYNC D2; CH1..8 D3..D10.
// Serial Monitor: 115200 baud, newline. Starts with every channel OFF.
#include <Arduino.h>
#include <util/atomic.h>
#include <string.h>
#include "Schedule.h"
#include "Demo.h"

#if !defined(__AVR_ATmega328P__) || F_CPU != 16000000UL
#error "Select a classic 16 MHz ATmega328P UNO or Nano"
#endif

constexpr bool ACTIVE_HIGH = true; // Existing Nano wiring assumption.
constexpr int SYNC_EDGE = RISING;
constexpr uint16_t CHATTER_US = 4000;
constexpr uint8_t LOCK_INTERVALS = 3;

// loop() builds the unpublished bank, then publishes one byte atomically.
// ZC copies that bank into its own schedule; neither ISR ever reads a bank
// while loop() writes it. Changes take effect only at the next valid crossing.
Schedule banks[2] = {};
volatile uint8_t published = 0;
Schedule active = {}; // Only accessed by ISRs (AVR interrupts do not nest).
uint8_t eventIndex = 0;
uint8_t gateMask = 0;
uint16_t requested[8] = {OFF_DELAY, OFF_DELAY, OFF_DELAY, OFF_DELAY,
                         OFF_DELAY, OFF_DELAY, OFF_DELAY, OFF_DELAY};
volatile bool haveEdge = false;
volatile uint8_t goodIntervals = 0;
volatile uint32_t lastEdgeUs = 0;
volatile uint16_t measuredHalfUs = 0;
volatile uint16_t invalidEdges = 0, chatterEdges = 0, lostSync = 0;
volatile uint16_t lateCycles = 0, maxLateTicks = 0;
bool demoRunning = false;
bool fireDemo = false;
uint8_t demoPeak = DEFAULT_DEMO_PEAK;
uint32_t demoStartMs = 0, demoUpdateMs = 0;

// Fixed port mapping preserves serial D0/D1, SYNC D2 and other pins.
// Equal timestamps change together per port; the two port writes have small skew.
void writeGates(uint8_t mask) {
  gateMask = mask;
  const uint8_t pins = ACTIVE_HIGH ? mask : uint8_t(~mask);
  PORTD = (PORTD & 0x07) | ((pins & 0x1f) << 3);
  PORTB = (PORTB & 0xf8) | (pins >> 5);
}

void cancelEvents() {
  TIMSK1 &= ~_BV(OCIE1A);
  active.count = 0;
  eventIndex = 0;
  writeGates(0);
}

void armNextEvent() {
  if (eventIndex >= active.count) {
    TIMSK1 &= ~_BV(OCIE1A);
    return;
  }
  const uint16_t target = active.events[eventIndex].ticks;
  OCR1A = target;
  TIFR1 = _BV(OCF1A);
  // A target can pass while OCR/flags are being written. Re-arm ahead of now
  // instead of waiting for a 32.768 ms timer wrap. ISR never applies early events.
  const uint16_t now = TCNT1;
  if (int16_t(target - now) <= 16) OCR1A = now + 32;
  TIMSK1 |= _BV(OCIE1A);
}

void onZeroCross() {
  const uint32_t now = micros();
  const uint32_t interval = now - lastEdgeUs;
  if (haveEdge && interval < CHATTER_US) {
    ++chatterEdges;
    return; // Rejected noise does not redefine the current time origin.
  }

  TIMSK1 = 0;
  TCNT1 = 0; // Normal mode: the ONLY reset within this half-cycle.
  TIFR1 = _BV(OCF1A) | _BV(OCF1B) | _BV(TOV1);
  cancelEvents();
  OCR1B = MAX_HALF_US * 2;
  TIMSK1 = _BV(OCIE1B); // Independent deadline, including while all channels OFF.

  if (haveEdge && interval >= MIN_HALF_US && interval <= MAX_HALF_US) {
    measuredHalfUs = uint16_t(interval);
    if (goodIntervals < LOCK_INTERVALS) ++goodIntervals;
  } else {
    if (haveEdge) ++invalidEdges;
    goodIntervals = 0;
  }
  haveEdge = true;
  lastEdgeUs = now; // Invalid intervals still re-anchor, allowing recovery.
  if (goodIntervals < LOCK_INTERVALS) return;

  const uint8_t bank = published;
  active.count = banks[bank].count;
  for (uint8_t i = 0; i < active.count; ++i) active.events[i] = banks[bank].events[i];
  armNextEvent();
}

ISR(TIMER1_COMPA_vect) {
  while (eventIndex < active.count) {
    const DimmerEvent &e = active.events[eventIndex];
    const uint16_t now = TCNT1;
    if (now < e.ticks) break;
    const uint16_t late = now - e.ticks;
    if (late > maxLateTicks) maxLateTicks = late;
    if (late > LATE_LIMIT_US * 2 || now >= MIN_HALF_US * 2) {
      ++lateCycles;
      cancelEvents(); // Don't replay severely overdue gate starts.
      return;
    }
    writeGates((gateMask & uint8_t(~e.offMask)) | e.onMask);
    ++eventIndex;
  }
  armNextEvent();
}

ISR(TIMER1_COMPB_vect) {
  cancelEvents();
  TIMSK1 = 0; // No repeating comparisons on timer wrap.
  haveEdge = false;
  goodIntervals = 0;
  ++lostSync;
}

void publishSchedule() {
  const uint8_t bank = published ^ 1;
  buildSchedule(banks[bank], requested);
  ATOMIC_BLOCK(ATOMIC_RESTORESTATE) { published = bank; }
}

void stopOutputs() {
  demoRunning = false;
  for (uint8_t i = 0; i < 8; ++i) requested[i] = OFF_DELAY;
  publishSchedule();
  ATOMIC_BLOCK(ATOMIC_RESTORESTATE) { cancelEvents(); }
}

void updateDemo() {
  if (!demoRunning) return;
  const uint32_t now = millis();
  if (uint32_t(now - demoUpdateMs) < DEMO_UPDATE_MS) return;
  demoUpdateMs = now;
  bool changed = false;
  for (uint8_t ch = 0; ch < 8; ++ch) {
    const uint8_t level = fireDemo ? fireDemoLevel(ch, now - demoStartMs, demoPeak)
                                  : demoLevel(ch, now - demoStartMs, demoPeak);
    const uint16_t delay = brightnessToDelayUs(level);
    if (requested[ch] != delay) { requested[ch] = delay; changed = true; }
  }
  if (changed) publishSchedule();
}

bool parseNumber(const char *s, uint16_t &value) {
  if (!s || !*s) return false;
  value = 0;
  while (*s) {
    if (*s < '0' || *s > '9') return false;
    const uint8_t digit = *s++ - '0';
    if (value > 6553 || (value == 6553 && digit > 5)) return false;
    value = value * 10 + digit;
  }
  return true;
}

void printInfo() {
  uint16_t half, invalid, noise, lost, late, maxLate;
  uint8_t good;
  ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
    half = measuredHalfUs; invalid = invalidEdges; noise = chatterEdges;
    lost = lostSync; late = lateCycles; maxLate = maxLateTicks;
    good = goodIntervals;
  }
  Serial.print(F("SYNC=")); Serial.print(good == LOCK_INTERVALS ? F("LOCKED") : F("WAIT"));
  Serial.print(F(" LAST_HALF_US=")); Serial.print(half);
  Serial.print(F(" INVALID=")); Serial.print(invalid);
  Serial.print(F(" NOISE=")); Serial.print(noise);
  Serial.print(F(" LOST=")); Serial.print(lost);
  Serial.print(F(" LATE_CYCLES=")); Serial.print(late);
  Serial.print(F(" MAX_LATE_TICKS=")); Serial.println(maxLate);
  Serial.print(F("PULSE_US=")); Serial.print(PULSE_US);
  Serial.print(F(" FULL_ON_DELAY_US=")); Serial.print(FULL_ON_DELAY_US);
  Serial.print(F(" PENDING_EVENTS=")); Serial.println(banks[published].count);
  Serial.print(F("DEMO=")); Serial.print(demoRunning ? F("RUNNING") : F("STOPPED"));
  Serial.print(F(" MODE=")); Serial.print(fireDemo ? F("FIRE_RAMP") : F("STAGGERED"));
  Serial.print(F(" PEAK=")); Serial.println(demoPeak);
  Serial.print(F("REQUESTED_DELAY_US="));
  for (uint8_t i = 0; i < 8; ++i) {
    if (i) Serial.print(',');
    if (requested[i] == OFF_DELAY) Serial.print(F("OFF"));
    else Serial.print(requested[i]);
  }
  Serial.println();
}

void handleLine(char *line) {
  char *cmd = strtok(line, " \t");
  if (!cmd) return;
  char *arg1 = strtok(nullptr, " \t");
  char *arg2 = strtok(nullptr, " \t");
  char *extra = strtok(nullptr, " \t");
  if (!strcmp(cmd, "PING") && !arg1) { Serial.println(F("PONG")); return; }
  if (!strcmp(cmd, "VERSION") && !arg1) { Serial.println(F("KRIDA8 V1")); return; }
  if (!strcmp(cmd, "INFO") && !arg1) { printInfo(); return; }
  if ((!strcmp(cmd, "OFF") || !strcmp(cmd, "STOP")) && !arg1) {
    stopOutputs();
    Serial.println(F("OK OFF"));
    return;
  }
  uint16_t ch, value;
  // Legacy room/serial usage: SET value means channel 1.
  char firstChannel[] = "1";
  if (!strcmp(cmd, "SET") && arg1 && !arg2) { arg2 = arg1; arg1 = firstChannel; }
  if ((!strcmp(cmd, "DEMO") || !strcmp(cmd, "DEMO2")) && !arg2 &&
      (!arg1 || (parseNumber(arg1, value) && value >= 1 && value <= 100))) {
    stopOutputs();
    fireDemo = !strcmp(cmd, "DEMO2");
    demoPeak = arg1 ? uint8_t(value) : DEFAULT_DEMO_PEAK;
    demoStartMs = demoUpdateMs = millis();
    demoRunning = true;
    Serial.print(fireDemo ? F("OK DEMO2 PEAK=") : F("OK DEMO PEAK=")); Serial.println(demoPeak);
    return;
  }
  if (!strcmp(cmd, "ALL") && parseNumber(arg1, value) && value <= 100 && !arg2) {
    for (uint8_t i = 0; i < 8; ++i) requested[i] = brightnessToDelayUs(value);
  } else if ((!strcmp(cmd, "SET") || !strcmp(cmd, "DELAY")) &&
             parseNumber(arg1, ch) && ch >= 1 && ch <= 8 &&
             parseNumber(arg2, value) && !extra) {
    if (!strcmp(cmd, "SET") && value <= 100) requested[ch - 1] = brightnessToDelayUs(value);
    else if (!strcmp(cmd, "DELAY") && value >= MIN_DELAY_US && value <= MAX_DELAY_US)
      requested[ch - 1] = value;
    else { Serial.println(F("ERR range")); return; }
  } else {
    Serial.println(F("ERR use SET ch 0..100 | DELAY ch 350..7883 | ALL 0..100 | DEMO/DEMO2 [1..100] | STOP | OFF | INFO | PING"));
    return;
  }
  demoRunning = false; // Valid manual changes take control; other channels hold.
  publishSchedule();
  Serial.print(F("ACK ")); Serial.print(cmd); Serial.print(' ');
  if (strcmp(cmd, "ALL")) { Serial.print(ch); Serial.print(' '); }
  Serial.println(value);
}

void setup() {
  writeGates(0); // Idle latch before enabling output drivers.
  DDRD |= 0xf8;
  DDRB |= 0x07;
  pinMode(2, INPUT_PULLUP);
  ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
    TCCR1A = 0;
    TCCR1B = _BV(CS11); // NORMAL mode, /8 = 0.5 us. NOT CTC.
    TIMSK1 = 0;
    TCNT1 = 0;
    TIFR1 = _BV(OCF1A) | _BV(OCF1B) | _BV(TOV1);
    attachInterrupt(digitalPinToInterrupt(2), onZeroCross, SYNC_EDGE);
  }
  Serial.begin(115200);
  Serial.println(F("KRIDA 8CH TEST READY; all OFF; SET ch pct, DELAY ch us, ALL pct, DEMO/DEMO2 [peak], STOP, OFF, INFO"));
}

void loop() {
  static char line[48];
  static uint8_t length = 0;
  static bool discard = false;
  // No String, timeout reads, heap allocation or serial I/O in interrupts.
  for (uint8_t budget = 0; budget < 32 && Serial.available(); ++budget) {
    const char c = Serial.read();
    if (c == '\r' || c == '\n') {
      if (discard) Serial.println(F("ERR invalid/long line"));
      else { line[length] = 0; handleLine(line); }
      length = 0; discard = false;
    } else if (!discard) {
      if ((c < 32 && c != '\t') || c > 126 || length >= sizeof(line) - 1) discard = true;
      else line[length++] = c;
    }
  }
  updateDemo();
}
