# Pedro ESP-NOW node and Python controller

`pedroNode.ino` listens through the existing HauntProtocol USB transceiver.
`MainCode/pedro.py` replaces the supplied `PedroWallace v3.py` for **Pedro only**.
The original Downloads file is untouched. There is no Firmata or direct PC-to-bird
serial connection. Python chooses audio, random motion and beak timing; the ESP
only generates requested outputs, timed servo ramps and status indicators.

## Board and wiring

Target: the supplied Teyleten Robot 30-pin **ESP-WROOM-32 / ESP32S** development
board, Arduino **ESP32 Dev Module**, FQBN `esp32:esp32:esp32`.
Use the GPIO number printed beside each header, not a header's physical position.

| Function | Board label / GPIO | Output |
| --- | --- | --- |
| Wings | D23 / 23 | 50 Hz servo PWM; rest 5°, open 115° |
| Beak | D18 / 18 | 50 Hz servo PWM; closed 55°, open 10° |
| Neck | D5 / 5 | Digital HIGH/LOW, as in the old script |
| Eyes | D4 / 4 | Digital HIGH/LOW, as in the old script |
| Green indicator | D2 / 2 | LED output |
| Red indicator | D15 / 15 | LED output |

All digital outputs default to active HIGH. Change the polarity constants at the
top of the sketch if your existing driver circuitry is inverted. Neck is not a
third servo: the supplied Python used `'d:2:o'`, and that behavior is preserved.
Keep appropriate drivers between the GPIO and any motor, solenoid or higher
power lighting. Supply servos from their suitable power source with a common
ground to the ESP; indicator LEDs need series resistors.

GPIO2, GPIO5 and GPIO15 participate in ESP32 boot strapping. External LED/driver
circuitry must allow the required reset levels; see
[Espressif's ESP32 schematic checklist](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32/schematic-checklist.html).
If uploading fails with attached loads, check those connections. The sketch
retains your requested pin assignments.

Servo limits and the 500–2500 µs pulse calibration are in the top configuration
block. This matches the existing `servoNode` PWM implementation. Check pulse
endpoints on Pedro before loading his mechanisms: the old Firmata board's pulse
calibration is not stored in the supplied Python file. Software telemetry reports
generated PWM, not measured shaft position.

## Indicators and connection loss

| Condition | Red | Green |
| --- | --- | --- |
| Connected, commanded off | Solid | Off |
| No accepted Pedro controller command for 2.5 seconds, including startup | Flashing | Off |
| Connected, standby | Off | Solid |
| Connected, talking/active | Off | Flashing |

Flash phases are 250 ms each. The Python worker sends full poses whenever they
change and at least every 500 ms while unchanged. The regular main-app host
heartbeat alone cannot keep Pedro's green indicator alive. Rejected commands,
diagnostics, unrelated traffic and duplicate command retries do not refresh the
Pedro lease. A bridge ID conflict also drops the lease.

On boot, off or link loss the ESP immediately parks wings at 5°, closes the beak
at 55°, sets neck/eyes inactive and cancels ramps. Parked servos still receive
PWM. Link loss takes precedence over commanded off for the indicator. Therefore
Ctrl+C briefly sends off/park, then the indicator becomes flashing red when the
controller exits. Use `--off` to keep Python connected with a solid red indicator.

Standby retains idle wing, neck and eye motion; the beak moves only while a quip
is playing. The beak uses the original 0.2, 0.2, 0.1, 0.1, 0.4, 0.3 second
open/close rhythm. Wings alternate after 1–6 seconds, neck after 1–3 seconds,
and eyes stay lit for 3–7 seconds between brief 80–160 ms blinks. Quips do not repeat
consecutively when more than one exists, with a 45–90 second interval between
successful plays. Playback completion replaces the original hardcoded duration
tables. Missed acknowledgments and brief availability gaps do not interrupt a
playing quip: Python allows up to **2 seconds since the last accepted command**
for communication to recover, sending fresh current poses after failed deliveries.
It does not replay old poses or restart the voice line for an isolated loss.
Sustained loss, a changed host/boot session, ID conflicts and invalid commands
still stop playback. The ESP's independent 2.5-second park timeout is unchanged.
Reconnect begins from standby
and may choose a new quip, without resuming interrupted playback.

## Main system and audio

The main GUI and HTTP remote page have **Start Pedro** and **Stop Pedro** controls.
Pedro starts independently when the main system is ONLINE, including before
START HOUSE. He does not automatically start with START HOUSE. Shutdown and any
transition away from ONLINE stop his show, cancel his audio and park the bird.
The stopped main-system service continues sending off heartbeats, so the red
indicator stays solid while the connection is healthy.

Audio now goes through `control.audio_manager.play_audio`, using the existing
named channel maps, mixer, gain and output fallback behavior. The default route
is **`CabinRoom_Wall`** (primary output index 1, zero based, in the current map).
The default quip folder is this workspace's **`Assets/SoundDir/Quips`**.

From a room, sequence, or the main system:

```python
from control.pedro_service import start_pedro, stop_pedro, pedro_status

start_pedro()  # Default CabinRoom_Wall route and configured channel gain.
stop_pedro()
start_pedro("Basement", gain=0.8)  # Same channel names/gain semantics as play_audio.
status = pedro_status()
```

`start_pedro` returns True if started or already running, False if offline or
settings are invalid (details go to the main system log). Repeated starts do not
spawn duplicate shows. Stop before changing settings; the next start reuses the
existing hardware controller and main RSM. Optional keywords include `quips`,
`background`, `background_channel`, `background_gain` and `interval=(10, 15)`.
Ambience is disabled by default; both ambience and voice use the audio manager.
The remote endpoints are `/PedroStart` and `/PedroStop`.

Stopping Pedro cancels only his own playback handles, including on fallback
outputs when another room is playing the same file. Other room audio continues.
The shared audio API now returns a `PlaybackHandle` for file playback, with
`done` (threading Event), `cancelled`, and `stop()`. Existing calls may ignore the
return value. Natural completion drives Pedro's talking state; no duration
countdown or ffplay subprocess is used. `honor_breakcheck=False` lets separately
started Pedro run while HouseActive is False; shutdown still cancels his audio.

Restart the main application to load these Python changes. Do not run the
standalone Pedro CLI at the same time against the main system's occupied COM
port. The integrated service never initializes or stops the shared RSM.

## Build and standalone use

For the initial protocol installation, rebuild and flash **the transceiver and
Pedro node** with this checkout's shared library. Existing sensors, servos,
Sprite and lantern nodes need no reflash for this additive extension. Network
ID, wire version, channel, existing payloads, retries, boot fencing and
command-result handling are unchanged. Set Pedro's unique `DEVICE_ID` (default
`PEDRO1`) before flashing. The main-system/audio integration is Python-only and
requires no additional ESP reflash.

From the repository root:

```powershell
arduino-cli compile --fqbn esp32:esp32:esp32 --libraries Esp32/libraries Esp32/transceiver
arduino-cli compile --fqbn esp32:esp32:esp32 --libraries Esp32/libraries Esp32/pedroNode
python -m pip install -r MainCode/requirements.txt
python MainCode/pedro.py --port COM6 --channel CabinRoom_Wall
```

The standalone CLI also uses the audio manager. It initializes mixers on the
main thread, owns its own RSM, and uses `Assets/SoundDir/Quips` by default.
Quip files may be MP3, WAV, OGG or FLAC. Pass `--quips` to change their folder,
`--channel` for another named route, and `--gain` to override channel gain.

```powershell
python MainCode/pedro.py --port COM6 --channel CabinRoom_Wall --gain 0.8 --once
python MainCode/pedro.py --port COM6 --background "C:\path\2hrSWAMP.mp3"
python MainCode/pedro.py --port COM6 --standby
python MainCode/pedro.py --port COM6 --off
python MainCode/pedro.py --simulate --standby
```

`--standby` and `--off` need no audio assets or mixer initialization. Simulation
prints poses and does not open serial; normal simulation mode still plays audio
through the audio manager. Ctrl+C stops audio, parks Pedro and stops the CLI's
monitor. No hardware or playback begins merely by importing `pedro`.

Low-level host API (full pose commands, not the automatic show):

```python
cid = rsm.pedro("PEDRO1", state="active", wings=115, beak=10,
                neck=True, eyes=True, ramp_ms=0)
result = rsm.command_status(cid)
state = rsm.get_pedro_state("PEDRO1")
```

Send a complete pose at least every 500 ms. Each pose replaces all outputs;
newer poses supersede older bridge deliveries. A repeated pose with a nonzero
`ramp_ms` starts a new ramp from current output; the provided controller uses
instantaneous poses (`ramp_ms=0`). An accepted result proves command acceptance,
not physical motion. There is no host command replay after USB reconnect.

## Additive wire extension

Type **10 PEDRO**, 21-byte telemetry payload:

| Offset | Field |
| --- | --- |
| 0 | state u8: 0 off, 1 standby, 2 active |
| 1 | controller connected u8 (0/1) |
| 2, 4 | wings generated angle and target, u16 each |
| 6, 8 | beak generated angle and target, u16 each |
| 10, 11, 12 | neck, eyes, either servo ramp moving, u8 each (0/1) |
| 13, 17 | associated bridge command session and sequence, u32 each |

Operation **6 PEDRO_POSE**, 17-byte reliable COMMAND payload:
target boot session u32, operation u8, state u16, ramp duration u32 ms,
wings u16, beak u16, neck u8, eyes u8. All integers use the existing little-endian
codec. The 11-byte legacy and 15-byte lantern command shapes are unchanged.

USB uses `op:"pedro"`, `value` for state, `duration_ms` for ramp duration and
adds `wings`, `beak`, `neck`, `eyes`. Target-session fencing and the existing
32-character host/command IDs apply. Telemetry uses `kind:"pedro"` and `vals`
keys matching the shared `get_pedro_state()` response. Reports occur every
500 ms, on accepted poses, on ramp completion and on link-loss transitions.

## Validation

Both sketches compile for original ESP32 with locally installed Espressif core
**3.3.11** and ArduinoJson **7.4.3**. Firmware behavior/codec checks exercise the
actual sketch with fake I/O; Python tests cover pose validation/addressing,
delivery results, reboot/freshness, lease refresh, disconnects and audio failure.

```powershell
python -m unittest discover -s MainCode/tests -v
python -m compileall -q MainCode
.tools/zig-x86_64-windows-0.14.1/zig.exe c++ -std=c++17 -IEsp32/pedroNode/tests Esp32/pedroNode/tests/check.cpp -o .tools/pedro-check.exe
.tools/pedro-check.exe
```

No board was flashed and no physical actuator test was performed. Before the
show, verify both servo endpoints, digital output polarity, all four indicator
states and the 2.5-second park by stopping the Pedro process while the bridge
remains running. Check audio synchronization with Pedro's actual recordings.
