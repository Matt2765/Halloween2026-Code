# Unified ESP-NOW installation and protocol v1

## Lantern extension

The additive lantern integration is documented in [lanternNode/README.md](lanternNode/README.md).
Reflash the bridge and new lantern nodes; network/version/channel and existing
node payloads are unchanged. Type **9 lantern**, 19 bytes: state u8 (0..5 in
README order), synced u8 (0/1), generated brightness u8, next cue u32, sync
generation u32, associated command session u32 and sequence u32.

Operation **5 lantern state** uses a **15-byte command**: intended boot session
u32, operation u8, state u16, numbered cue u32, sync generation u32. The existing
11-byte command layout remains for other operations. USB `op:"lantern"` uses
`value` for the state index, `duration_ms` for the cue number (not a duration),
and adds `sync_generation`. UUID `command_id` remains the delivery correlation
ID. Device `kind:"lantern"` values are `lantern_state`, `synced`, `brightness`,
`next_command_id`, `sync_generation`, `command_session`, `command_seq`, `ready`.
Reports occur every 500 ms and on transitions, expire after six seconds at the
host, and use the existing replaceable telemetry slots. Commands retain the
existing per-device addressing, bridge retries, boot fence and ACK semantics.
RSM adds `lantern(command_id, state, lantern_ids=None)` and `get_lantern_state`.

All seven participating sketches must be reflashed together. There is no legacy
radio fallback. The retired dimmerEsp and remoteSensor_TRANS/RECEIVER variants
remain removed. Nano/Uno dimmers and the standalone MAC utility are outside this
protocol. No firmware upload or physical actuator test was performed during implementation.

## Build and shared library setup

The reusable Arduino library is `Esp32/libraries/HauntProtocol`. Its only shared
network configuration is `src/HauntConfig.h`: network `0x4848`, version `1`, Wi-Fi
channel `1`, bridge ID `BRIDGE`, USB `921600`, four total attempts, 50 ms retry
spacing plus 0–15 ms jitter, and a 400 ms delivery lifetime. All IDs are case
sensitive. Do not change the bridge ID in just one sketch.

Validated build target: original ESP32 Dev Module, `esp32:esp32:esp32`, Espressif
Arduino core **3.3.8**, ArduinoJson **6.21.5**, Adafruit VL53L1X **3.1.2**, and
Adafruit BusIO **1.17.4**. The servo retains the original ESP32 high-speed LEDC
timer, 50 Hz, 16-bit output; an ESP32-C3/S3 is not a drop-in servo target.
Receive callbacks have IDF 4/5 signatures; only the listed core was compiled.
No send callback is required; immediate send errors are checked directly.

Arduino CLI, from the repository root:

```powershell
arduino-cli core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core install esp32:esp32@3.3.8 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli lib install "ArduinoJson@6.21.5" "Adafruit VL53L1X@3.1.2" "Adafruit BusIO@1.17.4"
arduino-cli compile --fqbn esp32:esp32:esp32 --libraries Esp32/libraries Esp32/transceiver
```

Use the same command with each sketch directory below. `--libraries` points at
the repository directly, so no library copy is needed for CLI compilation.

For Arduino IDE, open Preferences and find **Sketchbook location**. Once, create
a junction at `<sketchbook>/libraries/HauntProtocol` pointing to this repository's
`Esp32/libraries/HauntProtocol`, then restart the IDE. Example PowerShell:

```powershell
New-Item -ItemType Junction -Path "<sketchbook>/libraries/HauntProtocol" -Target "<repository>/Esp32/libraries/HauntProtocol"
```

Replace the two placeholders with absolute paths. The destination must not
already contain a library. Alternatively copy the library there, but repeat the
copy after every shared-library edit. Install the same core/libraries through
Boards Manager/Library Manager. Open the `.ino` in its existing sketch directory.

## Exactly what to edit for each flash

Each sketch starts with `PER-FLASH DEVICE CONFIGURATION`. Assign a unique
`DEVICE_ID` to every board, including boards of different types. Use 1–15 ASCII
letters, digits, `_` or `-`; overlong IDs are rejected, never shortened.

| Board / sketch | Current ID | Per-board settings in the top block |
| --- | --- | --- |
| USB bridge / `transceiver` | shared `BRIDGE` | Usually nothing; `HEARTBEAT_MS=1000`, `HOST_TIMEOUT_MS=1500` |
| VL53L1X / `remoteSensorTOF` | `TOF5` | `DEVICE_ID`; `I2C_SDA=21`, `I2C_SCL=22`; `DISTANCE_MODE=1` (short; 2 selects long); `TIMING_BUDGET_MS=100`, `REPORT_MS=100` |
| Single button / `remoteButton` | `BTN3` | `DEVICE_ID`; `BUTTON_PINS={32}`, `BUTTON_IDS={1}`; `DEBOUNCE_MS=30`, `HELD_REPORT_MS=2000`, `IDLE_SLEEP=true` |
| Four-button panel / `remoteMultiButton` | `Multi_BTN1` | `DEVICE_ID`; `BUTTON_PINS={26,25,33,32}`, `BUTTON_IDS={1,2,3,4}`; same debounce/report/sleep settings |
| Servo / `servoNode` | `SERVO1` | `DEVICE_ID`; `SERVO_PIN=18`; `DEFAULT_ANGLE=90`, `MIN_ANGLE=0`, `MAX_ANGLE=180`; `SERVO_MIN_US=500`, `SERVO_MAX_US=2500`; moving/idle reports `200/2000` ms |
| Sprite / `spriteEsp` | `SPRITE1` | `DEVICE_ID`; `SPR_TX_PIN=17`, `SPR_RX_PIN=16`, `SPR_BAUD=9600`; `MAX_FILE_INDEX=200`, `STARTUP_INDEX=0`; `STATUS_MS=2000` |
| HC-SR501 / `remotePIR` | `PIR1` | `DEVICE_ID`; `PIR_PIN=27`; `WARMUP_MS=60000`, `STATUS_MS=2000` |

Existing room callers expect `TOF1`–`TOF5`, `BTN1`–`BTN4`, `Multi_BTN1`,
`SERVO1` and `SPRITE1`; flash each physical board with its corresponding ID.
Keep panel indices one-based and unique. All existing GPIO assignments are
preserved. Buttons connect their GPIO to ground and use internal pull-ups.
Both button sketches now use light sleep so their session and sequence survive
idle/wake without repeated NVS writes. The single button trades some deep-sleep
savings for reliable release handling; measure actual battery life on the bench.

The servo's existing NVS `servo/boot_deg` overrides `DEFAULT_ANGLE`. Changing the
compile-time fallback does not overwrite a previously saved default. The existing
`set_default` operation saves the angle and moves there in 300 ms. Normal moves
start at the current local output. Zero-duration moves update the full ramp state.
There is no automatic return-to-default on disconnect. Sprite still issues its
startup file byte at boot; its UART remains binary file selection, not text.

Python's USB port is still configured in `MainCode/control/system.py` (`COM6`).
The GUI's existing ID lists and new `PIR1` list are in `MainCode/ui/gui.py`.

## PIR wiring and interpretation

Use module **VCC → regulated 5 V**, **GND → ESP32 GND**, and **OUT → GPIO27**.
HC-SR501 supplier specifications identify a 5–20 V supply and a 3.3 V active-high
output; the module's supply and output voltage are different. These electrical
values were checked against [Addicore's HC-SR501 specifications](https://www.addicore.com/products/pir-infrared-motion-sensor-hc-sr501).
Read the actual board's VCC/OUT/GND markings rather than guessing orientation;
confirm your DIYmall unit's OUT is 3.3 V before connecting it. The physical unit
and its board revision were not available for measurement. Do not apply 5 V to
an ESP32 input or power the PIR from a GPIO.

The 60-second firmware warm-up follows the HC-SR501's approximately one-minute
initialization. Hardware jumper H enables retriggering, while L lets the output
time out; hardware delay/sensitivity controls determine HIGH duration. See
[SunFounder's HC-SR501 documentation](https://docs.sunfounder.com/projects/umsk/en/latest/01_components_basic/12-component_pir_motion.html).
Firmware samples about every 2 ms, honestly reports HIGH/LOW during warm-up with
`ready=false`, and reports a readiness transition when warm-up ends. Python
suppresses normal triggering until ready. A two-second status is its heartbeat;
after six seconds without state communication, the node is unavailable.

A heartbeat proves the ESP is communicating, not that the sensing element works.
LOW is not evidence that a door swing area is empty: PIR detects motion, not
stationary occupancy. Door control now uses PIR1 for Door 1 and PIR2 for Door 2.
Flash each PIR board with its own DEVICE_ID. HIGH holds the door open; a fresh,
ready LOW allows a requested close. The hardware's roughly three-second HIGH
hold supplies the delay; Python adds no extra cooldown. During the four-second
closing travel, HIGH or unavailable data reopens the door. A completed close
stays closed until another door command. CLOPEN opens for 12 seconds before
requesting a close. Warm-up, stale data, conflicts and bridge loss prevent close.

## Binary wire schema

Every transmission, including commands and ACKs, uses `FF:FF:FF:FF:FF:FF` and each
board registers only that peer. Logical destination filtering happens before
queueing; there is no relay, flooding, routing or room-assignment mechanism.
Network ID/version separate this installation from unrelated traffic; this is
not an authenticated or encrypted control network.

Integers are explicitly serialized **little endian**. No packed C structs go
onto the wire. The fixed header is 46 bytes:

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 2 | Network ID `0x4848` |
| 2 | 1 | Version `1` |
| 3 | 1 | Message type below |
| 4 | 1 | Flags: bit 0 ACK required; all other bits must be zero |
| 5 | 1 | Exact payload length, 0–64 structurally, type-specific lengths below |
| 6 | 16 | Source ASCII ID, NUL terminated and zero padded |
| 22 | 16 | Destination ID with same rules; `*` reserved for non-ACK general traffic |
| 38 | 4 | Sender boot session, unsigned 32-bit |
| 42 | 4 | Sender sequence, unsigned 32-bit |
| 46 | variable | Payload |

Maximum encoded size is 110 bytes, below the 250-byte ESP-NOW budget. Length
mismatch, bad padding/IDs, unsupported types/versions/flags, invalid payload
shape, and wrong destinations are rejected. Commands must originate from
`BRIDGE`, address one specific node, and require an ACK. ACKs never require ACKs.

| Type | Bytes | Payload fields in order |
| --- | --- | --- |
| 1 TOF | 5 | valid u8; distance i16 mm; sensor status i16 |
| 2 button | 2 | button index u8 (1–8); pressed u8 (0/1) |
| 3 PIR | 2 | GPIO HIGH u8 (0/1); ready u8 (0/1) |
| 4 servo | 17 | output angle u16; target u16; moving u8; PWM pulse u16 µs; associated command session u32, sequence u32; optional measured angle u16 (`65535` means absent) |
| 5 Sprite | 9 | last issued file index u8; associated command session u32, sequence u32 |
| 6 command | 11 | intended actuator boot session u32; operation u8; value u16; duration u32 ms |
| 7 ACK | 9 | original sender session u32; original sequence u32; result code u8; ACK destination identifies original sender |
| 8 diagnostic | 24 | six u32 counters: drops, receive high-water, retries, unconfirmed, duplicates, immediate send errors |

Command operations: 1 move, 2 set default, 3 play file, 4 next file. Move/default
angles are 0–180 (also checked against node limits); duration is 0–30000 ms;
Sprite indices are 0–200 (also checked against its configured maximum).
ACK codes: 0 accepted, 1 invalid command, 2 superseded, 3 wrong boot session,
4 ID conflict, 5 queue full (reserved; a busy receive handler sends no ACK),
6 unconfirmed (normally a local expiry result).

TOF retains Adafruit VL53L1X at address `0x29`. Each 100 ms report uses a new
measurement and checks both the library error and actual range status. Status 0
is valid; -2 means no new data, -3 absent/start failure, -4 range-status read
failure, and -5 distance-register read failure; positive range statuses and
other library errors are invalid. USB uses
`dist_mm:null` for invalid data, never a synthetic far distance. Range status is
read through the existing library's public API ([Adafruit source](https://github.com/adafruit/Adafruit_VL53L1X/blob/main/src/vl53l1x_class.h)).

## Ordering, retries and reset semantics

Each cold boot increments a persistent NVS `haunt/boot` counter before enabling
radio; failure to persist stops normal startup. Light sleep preserves this session
and sequence. Sequence and boot ordering use signed modular differences (the
usual half-range rule). Retries reuse the exact packet identity and bytes.
Order is tracked independently per button index; diagnostics have their own
ordering stream so they cannot suppress a button state or servo report.

Each receiver has 64 identity entries, a 64-entry reliable receipt cache, separate
32-item urgent and 16-item telemetry receive queues, and 16 pending deliveries.
There is no eviction of identity/order/conflict records during that receiver's
boot. Capacity failures are explicit drops/busy, never successful acceptance.
Two different source MACs claiming an ID quarantine it for the receiver's lifetime
and produce diagnostics. Correct the IDs, then restart the affected listeners
and Python to clear that quarantine. Replacing a board or erasing its NVS also
requires this controlled reset; an erased boot counter must not be silently
treated as newer than its previous session.

The Wi-Fi task callback validates and copies packets with ordinary FreeRTOS
queue calls. Application processing runs in `loop()`. Queued radio work older
than 400 ms is discarded without a successful ACK. Receipt/order commitment
occurs only after the application handler accepts the message. A duplicate is
ACKed again without repeating the handler; older state never replaces newer
state. Old commands already overtaken by newer accepted commands are superseded.

The default schedule is four total sends, roughly 50–65 ms apart, followed by
an ACK wait. Immediate `esp_now_send` errors count as attempts and are exposed;
radio delivery success is not an application ACK. Pending memory and lifetime
are bounded. **Unconfirmed means execution is uncertain**, not that it failed.

Sensor/button ACK means **the bridge accepted the record into its USB output
queue**. Actuator ACK means **the node validated and accepted the command**.
TOF ACK means acceptance into a replaceable latest-measurement slot: a newer
distance replaces the previous one while USB is stalled. TOF is not an event log.
Neither proves Python ran a room effect, a servo shaft moved, or playback started.
The servo has no position feedback: all angles/moving/completion reports describe
PWM generation. Sprite reports serial issuance, never confirmed playback.

The bridge owns command radio retries. A newer servo move/default cancels older
pending commands to that device. Target boot sessions prevent a stale command
from executing after an actuator restart; a newly observed actuator session
cancels its pending command as unconfirmed. USB reconnect uses a new host token,
cancels pending bridge work, and never requeues old Python commands. Bridge RAM
and its retry queue disappear on reset. There is no exactly-once promise across
crashes and an already-issued/in-flight command cannot be recalled. A newer
command cannot supersede an older one at the actuator until it reaches that node.

## USB NDJSON and Python APIs

USB stays at **921600 baud**. One bridge writer emits complete newline-delimited
JSON records. Each has `v:1`. The writer handles partial serial writes without
interleaving; its fixed-capacity queues are allocated once. Accepted transitions
and command results use an 80-line nonreplaceable queue, with reliable-record
admission limited to 48 to reserve command-result capacity. Button snapshots
use that bounded urgent queue. TOF and periodic PIR/servo/Sprite records
coalesce in 64 per-device slots. USB backpressure stops new reliable-record
acceptance at capacity; accepted records are not silently evicted.
USB disconnect/reset can still lose queued records; an ACK is not durable storage.

Common device record:

```json
{"v":1,"type":"device","id":"PIR1","kind":"pir","session":3,"seq":12,"mac":"AA:BB:CC:DD:EE:FF","fw":"haunt-1.0.0","rx_ms":9000,"queue_ms":2,"event":false,"vals":{"output":true,"ready":true}}
```

Kinds are `tof`, `button`, `pir`, `servo`, `sprite`; `vals` mirrors the binary
fields. Servo adds `angle` as a compatibility alias of `output_angle`, and
`measured_angle:null`. Sprite includes `serial_issued:true` and
`playback_confirmed:false`. `fw` names this coordinated firmware release.
Diagnostics are `type:diagnostic`, `id`, `vals`, or `error:"id_conflict"`.
The one-second `type:bridge` heartbeat includes `session`, `fw`, `ready`, and
`diagnostics`: RX/USB drops and high-water marks, retries, unconfirmed, duplicates,
malformed, send errors, sequence gaps and conflicts. TOF reports use application
ACKs, but keep only the newest pending snapshot and expire retries after 100 ms.
TOF reports have `event:false` even when acknowledged. Gaps count skipped sequence
numbers observed at reception, including reordering; they are not delay in ms or
a definitive count of permanently lost measurements. `rx_ms` is bridge uptime,
so it normally increases continuously. `queue_ms` is bridge queue residence and
does not measure radio or host/Serial Monitor buffering.

Firmware `haunt-1.0.1` includes the latest-snapshot fix. Rebuild and flash the
bridge and TOF node with the updated library. Verify that serial records show
this firmware string. Build success does not establish physical sensor range
or end-to-end latency; verify responsiveness with a moving target after flashing.
Node diagnostics run every ten seconds for powered sensors/actuators; buttons
send diagnostics before sleep. Diagnostics do not refresh measurement age.

The host sends `{"v":1,"type":"hello","host":"<32-character token>"}` and waits
for the echoed `hello` plus bridge session before sending commands. It sends a
`host_heartbeat` with that token every 500 ms; bridge timeout is 1500 ms. Commands:

```json
{"v":1,"type":"command","host":"0123456789abcdef0123456789abcdef","command_id":"abcdef0123456789abcdef0123456789","id":"SERVO1","target_session":3,"op":"move","value":120,"duration_ms":800}
```

Results have `type:command_result`, `command_id`, `id`, `status`, `reason`, and
radio `session`/`seq`. Status is `pending`, `accepted`, `rejected`, `unconfirmed`,
or `superseded`. `elapsed_ms` uses the bridge retry clock. `rtt_ms` is populated
only for an acknowledged result (and includes retries); pending/local cancellation/
unconfirmed results use null. USB input is bounded to 511 bytes; oversize input is discarded
through newline and reported. The host never retries a USB command with a new
identity. Command IDs are correlation IDs; do not manually resend USB commands.

Python preserves `init`, `stop`, `get`, `get_value`, `snapshot`, `obstructed`,
`get_distance_filtered`, `get_button_value`, `servo`, `sprite_play`, `tx_to_id`,
and explicitly addressed `tx_broadcast`. Command helpers return a UUID immediately;
inspect it with `command_status(cid)`. Use `device_status`, `get_pir_state`,
`get_servo_state`, `healthy`, and `command_failure` for state/diagnostics. No
existing MAC helper callers were found; `tx_to_mac` now raises a clear deprecation
error. `button_pop` explicitly remains unsupported. `set_far_distance_mm` only
warns; it cannot turn invalid data into clear. `get_latency_ms` returns None,
because unrelated ESP uptime clocks cannot establish one-way latency.

Host freshness uses monotonic time, with bridge queue residence deducted using
the bridge's own clock. It is not a radio-latency measurement. TOF becomes stale
after 350 ms and unavailable at six seconds. Moving servo reports become stale
after one second; idle reports remain current until six seconds. PIR/Sprite
availability expires at six seconds. Bridge silence reconnects after 3.5 seconds,
so a quiet radio network no longer causes USB reconnect loops.

Buttons publish debounced press and release transitions, and snapshots every
two seconds while held. A held state expires to **None/unknown after six seconds**;
a received release remains last-known released/sleeping, not continuously online.
Every panel index retains independent state and age. Existing room polling
continues: `is True` means pressed; None cannot finish a hold as though released.
There are no synthesized releases, stretched taps, or hidden event consumers.
**Latest-state polling can still miss a complete tap between Python checks.**

## Verification and coordinated bench rollout

Completed validation: all seven sketches compile with the versions listed above;
16 Python tests pass; the native production-code failure suite passes; Python
compileall passes. These are compilation/simulation results, not hardware validation.

Automated checks (no hardware opened):

```powershell
python -m compileall -q MainCode
python -m unittest discover -s tests -v
```

Native tests compile the actual codec, radio implementation and bridge against
small fake GPIO/serial/queue primitives. With a C++17 compiler and ArduinoJson 6:

```text
c++ -std=c++17 -Itests/native/stubs -IEsp32/libraries/HauntProtocol/src -I<ArduinoJson>/src tests/native/test_protocol.cpp Esp32/libraries/HauntProtocol/src/HauntProtocol.cpp -o protocol-tests
```

Run the resulting executable. Windows validation used Zig 0.14.1's `zig c++`.
Tests cover malformed/oversized/wrong-version and wrong-destination packets,
duplicate/lost ACK handling, queue refusal before ACK, ordering and session/sequence
wrap, independent long button holds, zero-duration/superseding ramps, matching ACK
identities, unconfirmed/restarted commands, bridge JSON integrity and heartbeat,
Python freshness/latest-state behavior, and real door-loop emergency/unknown paths.

Bench sequence after separately authorizing hardware work:

1. Stop room effects and isolate actuator loads. Assign unique IDs and verify wiring.
2. Flash the bridge, then TOF/buttons/PIR; keep old-protocol boards off. Start the
   updated Python monitor and confirm the quiet one-second bridge heartbeat.
3. Flash servo and Sprite boards with loads isolated. Confirm their existing startup
   behavior and reported readiness before enabling room effects. Reflashing/rebooting
   itself initializes servo output and issues Sprite's startup file byte.
4. Hold a button over ten seconds, overlap panel buttons, and release them in a
   different order. Check independent states, release after long hold, wake/sleep,
   and last-heard age. Remove bridge reception while held and verify None at six seconds.
5. Disconnect/obscure/fault the TOF. Confirm invalid/stale is displayed and cannot
   trigger a TOF room effect. Verify PIR door reopen and shutdown paths before enabling loads.
6. Let PIR warm up, exercise H/L modes and the hardware hold-time control, then
   disconnect it. Check immediate transitions, two-second status, and six-second expiry.
7. With a safe unloaded servo, test a timed move followed by a zero-duration move,
   then rapid newer targets. Check reported output and completion, not shaft feedback.
   Verify Sprite play/next bytes and playback separately on the real player.
8. Interrupt USB and reboot nodes during commands. Expect accepted/rejected/unconfirmed
   results, no automatic replay, and no old target resuming after a newer accepted one.
   Inspect `healthy()` and device diagnostics while testing radio loss/queue pressure.

Remaining hardware verification: radio loss/range and queue load on the installed
network; actual PIR output voltage/noise/warm-up; VL53L1X invalid-range behavior;
button wake reliability and battery current; servo power, pulse limits and physical
motion; Sprite UART/playback; and the GUI's rendered fit on the target display.
Software ACKs and compile/test success do not establish those physical results.
