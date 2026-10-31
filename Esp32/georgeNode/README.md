# George node and shared animatronic service

Target: **ESP32 Dev Module**, original ESP32 (`esp32:esp32:esp32`), not a C3/mini.
George was called William Wallace in the old Firmata program. This sketch uses
the existing HauntProtocol ESP-NOW network, USB bridge, logical addressing,
boot sessions, acknowledgements and retries. Python owns audio and motion timing.

| Output | GPIO | Type / calibration |
| --- | --- | --- |
| Eyes | 13 | Digital, active HIGH (configurable) |
| Mouth | 14 | Servo: open 120 degrees, closed/parked 180 degrees |
| Neck | 26 | Head rotation: forward/parked 80 degrees; default idle moves between 5 and 180 degrees |

Servo pulses use the existing Pedro calibration: 50 Hz, 500..2500 microseconds
for 0..180 degrees. Supply servos externally with a shared ground. Eyes use a
suitable driver for their load. `EYES_ACTIVE_HIGH` changes eye-driver polarity.
The old startup mouth test/infinite loop is not carried over. The closed-mouth
pose (180 degrees) is used for standby and parking. Node firmware enforces
mouth 120..180 and neck 0..180 before applying any part of a pose.
Reflash George to replace the older firmware's 115-degree neck limit.

## Main-system use

```python
from control import animatronic_service

# Generic talking animatronics: random quips, mouth timing and idle movement.
animatronic_service.pedro.start(gain=1)
animatronic_service.george.start()  # Optional; does not start with the house.
animatronic_service.george.stop()

# Direct control switches out of the generic show, including its audio.
# Values are servo ANGLES in degrees, rather than raw duty or microseconds.
animatronic_service.george.neck(80)  # Face forward
animatronic_service.george.mouth(120)
animatronic_service.george.eyes(True)
animatronic_service.george.pose(neck=5, mouth=180, eyes=False, ramp_ms=800)

# One random quip, or one chosen recording; returns to idle if enabled.
animatronic_service.george.talk()
animatronic_service.george.talk("Quip01.mp3", channel="George", gain=0.8)

# Pedro also supports manual outputs (his neck/eyes remain digital).
animatronic_service.pedro.wings(115)
animatronic_service.pedro.beak(10)  # .mouth(10) is an alias
animatronic_service.pedro.neck(True)
animatronic_service.pedro.eyes(False)
animatronic_service.pedro.start()  # Return to generic mode.
status = animatronic_service.george.status()
animatronic_service.stop_all()
```

Calls require the main system to be ONLINE and reuse its initialized RSM/audio
mixers. Start returns False for offline/invalid settings; stop before changing
an already-running show's settings. Direct output calls raise ValueError for
invalid outputs and return False if offline or no hardware link is established
within two seconds. True means handed to the worker, not confirmed physical
motion. Status exposes mode, connection and errors. Manual calls preserve the
other manually set outputs; the first manual call starts from the parked pose.

Manual mode holds the requested pose through the same 500 ms heartbeats and
never adds random movement. A reconnect discards manual poses and parks until
a fresh manual call or generic start. Repeated heartbeats preserve ongoing
servo ramps. Both characters stop/park on system shutdown. Pedro still starts
as a generic animatronic with StartHouse; George starts only when requested.

Quips are all MP3/WAV/OGG/FLAC files in these separate directories:

- `Assets/SoundDir/Quips/Pedro`
- `Assets/SoundDir/Quips/George`

The ten old root-level Pedro quips were moved into his directory. Put George's
recordings in his directory before starting his generic show. Empty directories
produce a clear start error. Default named routes are Pedro and George; both
currently map to secondary output index 1. Choose another named route with
`channel=...` or change George's map in `control/audio_manager.py` for a separate
speaker. The characters can run independently; sharing a route mixes their audio.

## Persistent idle and speech gain (both characters)

```python
from control import animatronic_service

character = animatronic_service.pedro  # Or animatronic_service.george
character.start_idle()                # Body idle only; no audio/quips required.
animatronic_service.george.start_idle(neck_min=50, neck_max=180)
character.talk(channel="Basement", gain=0.5)
character.talk("Quip01.mp3", channel="Basement", gain=0.8)
# Idle continues after each quip; only speech controls the mouth/beak.
character.stop_idle()                 # Body stops; any current speech continues.
character.stop()                      # Stop everything and park.
```

`idle()` / `idle(True)` alias `start_idle()`; `idle(False)` aliases `stop_idle()`.
Gain is explicit on each talk call: None uses the configured route gain, 0 is
silent, 0.5 scales to half amplitude, 1 uses unity gain, and values above 1 amplify.
Gain must be finite and nonnegative. Speech remains nonblocking.

Idle and speech share one pose worker, so idle never replaces a talking pose.
Enabling idle during speech does not restart/cancel the quip. Stopping idle during
speech parks only non-mouth outputs while mouth timing/audio finish normally.
After `stop_idle()`, body animation remains disabled until `start_idle()` is called.
If persistent idle is disabled, a completed quip parks. Direct manual output calls
still take over from the show and stop its audio/idle. System shutdown stops both
idle and speech. Status includes `idle_enabled` and mode `idle` when idle-only.
These changes are Python-only; restart MainCode and refresh the web page, with
no ESP firmware update required.

## Web tests

On the remote web page, open **Test > Animatronics** for Pedro and George.
Each character has speaker route/gain, Start talking, Play one quip, Start idle,
Stop idle, Stop & park,
live connection/mode/error status, and individual calibrated output controls.
Manual output tests stop that character's talking show and hold the pose.
Stop before changing an already-running show's voice settings. George has mouth
and neck angle controls plus eyes On/Off; Pedro has wings/beak angles and digital
neck/eyes controls. The **Speakers** group contains only speaker audio tests.
The system must be ONLINE. Restart MainCode and refresh the page after updating.

## Build / installation

Rebuild and flash **George and the USB transceiver** with the shared library.
Existing nodes need no reflash for George's additive protocol extension. The
Pedro sketch additionally preserves in-progress ramps on repeated target poses;
reflash Pedro to pick up that manual-control refinement.

```powershell
arduino-cli compile --fqbn esp32:esp32:esp32 --libraries Esp32/libraries Esp32/georgeNode
arduino-cli compile --fqbn esp32:esp32:esp32 --libraries Esp32/libraries Esp32/transceiver
arduino-cli compile --fqbn esp32:esp32:esp32 --libraries Esp32/libraries Esp32/pedroNode
python MainCode/Animatronics/george.py --port COM6 --standby
python MainCode/Animatronics/george.py --port COM6 --once
python MainCode/Animatronics/george.py --simulate --off
```

Restart MainCode after the service rename. Do not run a standalone CLI while
MainCode owns the USB transceiver's COM port. No hardware opens on import.

George has no external status LEDs; GPIO2 and GPIO15 are unused by this sketch.
Connection and operating state are available through telemetry and `status()`.
After 2.5 seconds without an accepted pose, the
node parks mouth/neck and turns eyes off. USB debug output is independent of
Python's DEBUG_INFO setting.

## Additive wire / USB layout

Type 12 GEORGE telemetry, 20 bytes: state u8, controller connected u8, mouth
current u16, mouth target u16, neck current u16, neck target u16, eyes u8,
moving u8, command session u32, command sequence u32. All integers little endian;
angles describe PWM output, not measured physical position.

Operation 8 GEORGE_POSE command, 16 bytes: target boot session u32, operation u8,
state u16 (off=0, standby=1, active=2), ramp duration u32 (0..30000 ms), mouth
u16, neck u16, eyes u8. Uses the existing reliable COMMAND envelope and stream 0.
USB adds op/kind `george`, command keys mouth/neck/eyes, and state index in value.
Telemetry keys: george_state, controller_connected, mouth_angle, mouth_target,
neck_angle, neck_target, eyes, moving, command_session, command_seq, ready.
RSM helpers: `george(...)`, `get_george_state(...)`, `command_status(...)`.

Host-side behavior tests:

```powershell
.tools/zig-x86_64-windows-0.14.1/zig.exe c++ -std=c++17 -IEsp32/georgeNode/tests Esp32/georgeNode/tests/check.cpp -o .tools/george-check.exe
.tools/george-check.exe
python -m unittest discover -s MainCode/tests -p test_animatronics.py
```


## Finish speech through a node restart

George's current quip now plays to the end if his ESP32 restarts or its wireless
link drops. Motion parks when that happens and is not replayed/resumed midway
through the line on reconnection. After playback completes, the normal idle/
parking policy applies, including Basement's extra 15 seconds of idle. A new
quip still waits for an available hardware link. Explicit stop, manual takeover
and system shutdown continue cancelling speech immediately. This policy is
configured by `GeorgeController.finish_audio_on_link_loss=True`; Pedro retains
his existing link-loss cancellation policy. Restart MainCode; no reflash needed.
