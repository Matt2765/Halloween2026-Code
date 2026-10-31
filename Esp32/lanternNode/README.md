# Handheld lanterns

Flash this sketch once per board, setting `DEVICE_ID` to `LANTERN1` through
`LANTERN4`. Set `LIGHT_PIN`, `SYNC_BUTTON_PIN`, output polarity, brightness limit,
and fade/ramp durations and strobe timing ranges in the configuration block.
`MAX_BRIGHTNESS` is 51 (20% of full PWM) for normal modes, fades, ramps,
and sync-feedback flashes. Strobe has a separate `STROBE_BRIGHTNESS` limit of
204 (80% peak PWM), preserving its randomized bright pulses and dark gaps. Reflash
each wireless lantern to apply this change; restarting Python does not apply it.
IDs also appear in the GUI list.
This sketch uses low-speed LEDC PWM, supported by the original ESP32 and ESP32
variants without high-speed LEDC (including C3/S3). The defaults are configured
for the **ESP32-C3 Super Mini**: light control on **GPIO4**, sync button on
**GPIO5**. In Arduino IDE select **ESP32C3 Dev Module** for these lanterns.
Select the board matching your physical chip, and change both GPIO settings
to pins exposed on that board if using a different model.
It uses the shared HauntProtocol library. See [protocol setup](../PROTOCOL.md).

Arduino IDE must load the repository's updated HauntProtocol library. Missing
`LANTERN` or `LANTERN_STATE` compile errors mean it found an older copy. Prefer
the junction described in protocol setup so future changes stay synchronized;
restart Arduino IDE after replacing an installed copy with the junction.

Connect the sync button between its GPIO and GND. The light output is a 5 kHz,
8-bit PWM control signal. Use a suitable LED driver or MOSFET circuit with common
ground; the ESP32 GPIO must not supply the lantern lamp's power. The existing
lamp electronics must support external PWM dimming. Confirm that before wiring.
For C3, GPIO32 is unavailable; GPIO18/19 are USB pins and GPIO2/8/9 are boot
strapping pins. GPIO4/5 avoid those functions. See
[Espressif's C3 GPIO reference](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32c3/api-reference/peripherals/gpio.html).

## Operation

* Boot: indefinite normal flickering, ignores house commands.
* Debounced button press: immediately clears the previous sequence, waits for
  cue 1, and returns to normal flickering. Release before three seconds gives
  three quick flashes (100 ms on/off).
* Hold three seconds: exits sync, gives two slow flashes (400 ms on/off), then
  continues indefinite normal flickering. Release does not trigger another reset.
* Another short press starts again at cue 1, even during a fade or feedback.
* A synced lantern accepts its next numbered cue or a newer cue in the same
  sync generation, then waits for the accepted cue plus one. Older/duplicate
  cues are rejected. State changes interrupt the
  previous effect; feedback briefly overlays the commanded light output.
* Normal flickering stays between 170 and 255 before the brightness limit.
  Intense flickering uses 12..255 with faster variations. Fade-out variants
  decay over 1800/2800 ms by default and finish at `off`.
* Entering `flickering_on` or `intense_flickering_on` while the light is dark ramps the
  flicker brightness up over **1500 ms**. `FLICKER_ON_RAMP_MS` is configurable
  up to 2000 ms. The check uses current generated PWM brightness, including a
  fade-out that has already gone dark, rather than requiring the `off` label.
  `DARK_BRIGHTNESS_THRESHOLD` defaults to zero; raise it if the lamp's driver
  turns visibly off at a nonzero PWM level. A threshold-triggered ramp starts
  from the current output level. Already-lit transitions are immediate;
  switching modes during a ramp preserves its original deadline. Switching
  from a dark strobe phase also ramps; sync feedback still overlays effects.
* `strobe` alternates bright flashes (200..255) with fully dark gaps. Randomized
  30..70 ms on-times and 50..140 ms off-times give it an erratic flicker feel.
  It starts immediately and continues until another cue or a sync-button reset.
* Link loss preserves the current effect and sequence. The next house cue can
  bring a latched lantern forward without replaying missed effects. There is
  no offline command buffering. Reboot returns to unsynced indefinite flickering.

## Room calls through RSM

```python
from control import remote_sensor_monitor as RSM

# All fresh, synced lanterns waiting for cue 1:
deliveries = RSM.lantern(command_id=1, state="intense_flickering_on")

# A specific lantern, still subject to sync/sequence checks:
deliveries = RSM.lantern(2, "flicker_out", lantern_ids="LANTERN1")

# Several specific lanterns:
deliveries = RSM.lantern(3, "solid_on", lantern_ids=["LANTERN1", "LANTERN2"])

# A jumpscare strobe for the group whose intended next house cue is 4:
deliveries = RSM.lantern(4, "strobe")

for device_id, delivery_id in deliveries.items():
    result = RSM.command_status(delivery_id)  # Poll later; initially queued/pending.
state = RSM.get_lantern_state("LANTERN1")
```

Allowed states: `off`, `solid_on`, `flickering_on`, `intense_flickering_on`,
`flicker_out`, `intense_flicker_out`, `strobe`. Cue IDs are integers 1..4294967294; they are
different from the UUID delivery IDs used by `command_status`. After the last
possible cue, sync must be reset. An empty group returns `{}`.

Untargeted house cue 1 latches all fresh, synced lanterns waiting for 1 into
that group's sequence. Python tracks intended progress separately from actual
telemetry: if one lantern misses cue 7 or its ACK, the group's cue 8 still targets
it. Firmware accepts that newer cue and immediately applies its current effect,
without replaying cue 7. A missed effect can remain in place until the next cue;
there is no additional host retry loop. The bridge retains its four radio attempts.
An `unconfirmed` result is still reported honestly, not converted to success.
The GUI's `wait N` remains the node's confirmed state.

Multiple groups can be in different rooms. A later cue 1 only enrolls newly
synced lanterns; it never pulls an existing group back to the start. Every
re-sync or reboot detaches the old membership by generation/boot session. A
re-sync waits for a new cue 1 even if the old group is midway through the house.
Restarting MainCode clears memberships: sync lanterns again before starting.
Separate ACKed fan-out commands are not atomic or perfectly simultaneous.

During a room demo (`house.Demo`), Python group calls without `lantern_ids`
send the requested effect to every available, synced lantern using each
lantern's reported next cue number. This lets a newly synced lantern follow
Bathroom or another room without first receiving earlier rooms' cues. Explicit
device targets keep the supplied cue number. Normal full-house sequences keep
their original cue numbers. Sync-button requirements and firmware sequence
checks still apply; past effects are never replayed.

Pressing sync increments a generation in the node. Commands carry the generation
observed by RSM as well as the persistent boot session, so delayed commands from
before a reset are rejected. The host can briefly have old telemetry immediately
after a button press; wait for updated `sync_generation` before sending cue 1.

The GUI shows all four lanterns' reported state plus `wait N` or `free`, or
unavailable/conflict. Brightness is generated PWM, not measured lamp output.

## Flash and bench checks

For the group-latching update, restart MainCode and reflash every lantern that
will participate. The bridge wire format is unchanged, so an already-current
bridge needs no reflash for this update. Preserve each board's unique DEVICE_ID.

```powershell
arduino-cli compile --fqbn esp32:esp32:esp32c3 --libraries Esp32/libraries Esp32/lanternNode
arduino-cli compile --fqbn esp32:esp32:esp32 --libraries Esp32/libraries Esp32/transceiver
```

On each board, verify boot flicker; short press feedback and wait 1; refusal of
old-generation and duplicate cues; forward jumps after a lost cue;
acceptance/advancement of each state; both fades ending off;
mid-effect reset; long-hold feedback and ignored commands; another short press;
off-to-flicker ramps, immediate already-lit changes, irregular strobing, and
four-lantern fan-out. Test reset while a command is in flight, USB disconnect,
and node reboot. Check the GUI at the operator display's DPI scaling. Physical
PWM, lamp dimming, wireless timing and battery runtime require a hardware test.

Implementation validation: lantern builds pass for original ESP32, ESP32-C3,
and ESP32-S3 with the installed Espressif Arduino core **3.3.11**. The bridge
build passes for its original ESP32 target (`esp32:esp32:esp32`).
Seven RSM tests pass (`python -m unittest discover -s MainCode/tests -v`). The
native harness in `tests/` exercises the actual sketch's short/long presses,
reset generation, sequence refusal, both completed fades, off-only ramps,
strobe phases, timer wraparound and wire compatibility.
The compact GUI status panel ends at y=943 within the existing 465x1080 window
with the tested device states at Tk scaling 1.33, 1.67 and 2.0. PIR1..PIR5 appear
in their own column beside TOF and Buttons. No firmware was uploaded or tested on physical lamps.
