# User Guide

Refer to `MainCode/INSTALLATION_INSTRUCTIONS.md` for help setting up the project environment.

For the coordinated ESP32 firmware update, per-board flash settings, PIR wiring,
and Python protocol APIs, see [Unified ESP-NOW setup and protocol](Esp32/PROTOCOL.md).

## Table of Contents

- 1. Project Overview
- 2. Key Components
- 3. Patterns & Conventions
- 4. Developer Workflows
- 5. Integration Points
- 6. Audio Manager Guide
  - 6.1 Device Setup
  - 6.2 Finding Audio Device Indexes
  - 6.3 Channel Tables
  - 6.4 Mono Named Channels
  - 6.5 Stereo Named Channels
  - 6.6 Determining Physical Speaker Channels
  - 6.7 play_audio(...)
  - 6.8 Common Playback Examples
  - 6.9 Lower-Level Playback Helpers
  - 6.10 Shutdown Behavior
  - 6.11 Registering Channels in Code
  - 6.12 Troubleshooting
- 7. BreakCheck Guide
  - 7.1 What BreakCheck Checks
  - 7.2 When to Use BreakCheck
  - 7.3 Common Loop Pattern
  - 7.4 BreakCheck Debug Output
  - 7.5 Important Notes
- 8. Dimmer Controller Guide
  - 8.1 Device Setup
  - 8.2 Initialization and Simulated Mode
  - 8.3 Setting Brightness
  - 8.4 Flicker Effects
  - 8.5 Stopping Effects
  - 8.6 Tuning Helpers
  - 8.7 Diagnostics
- 9. Examples
- 10. Special Notes

---
---

## 1. Project Overview
This codebase controls a multi-room haunted house automation system for Halloween events. It orchestrates audio, lighting, sensors, and hardware such as Arduino and ESP32 devices across themed rooms. The system is modular, with clear separation between control logic, room behaviors, UI, and hardware integration.

## 2. Key Components
- `MainCode/control/`: Core logic for hardware, sensors, audio, lighting, and system state.
- `MainCode/rooms/`: Room-specific logic. Each room imports shared context and audio control.
- `MainCode/ui/`: User interfaces, including a Tkinter GUI (`gui.py`) and HTTP server (`http_server.py`).
- `MainCode/utils/`: Utility functions for logging, timing, and debugging.
- `MainCode/context.py`: Central state shared across modules.
- `MainCode/main.py`: Main entry point for running the system.

## 3. Patterns & Conventions
- **Room modules**: Import `context.house` and `control.audio_manager.play_audio` for state and sound.
- **Hardware abstraction**: All Arduino and sensor logic is in `control/`. Use provided functions (e.g., `connectArduino`, `setDoorState`)â€”do not access hardware directly from rooms/UI.
- **Logging**: Use `utils.tools.log_event` for event logging. Log file: `logs/haunt_log.txt`.
- **Threading/Processes**: System uses threads and processes for parallel tasks (audio, HTTP server, GUI, etc.).
- **State management**: Shared state is in `context.py` and `house_state.py`.

## 4. Developer Workflows
- **Run the system**: Start from `MainCode/main.py`.
- **Debugging**: Use `utils/debug.py` and log files. Many modules have debug helpers.
- **Adding a room**: Copy an existing room module, import `context.house`, and register with the system.
- **Hardware integration**: Add new hardware logic in `control/`, not in rooms or UI.

## 5. Integration Points
- **Arduino**: Controlled via `control/arduino.py` (uses pymata4).
- **ESP32**: Code in `Esp32/` (not Python); communicates with main system via sensors/network.
- **Audio**: Managed by `control/audio_manager.py` using `sounddevice` and `soundfile`.
- **UI**: Tkinter GUI and HTTP server run in parallel threads.

---
---

## 6. Audio Manager Guide

The audio system is managed by `MainCode/control/audio_manager.py`. Room code should normally use:

```python
from control.audio_manager import play_audio
```

The main idea is:

- Audio hardware is configured once at the top of `audio_manager.py`.
- Named locations like `"Room_1"` or custom room names map to physical output channels.
- Each physical device uses one persistent mixer stream. Multiple sounds can overlap without repeatedly opening the device.
- Short clips are cached in memory, while long files are streamed through a bounded buffer.
- Audio files are loaded from `Assets/SoundDir` by default.

### 6.1 Device Setup

At the top of `audio_manager.py`, two physical output devices are configured. These numbers are examples; use the indexes from your own device scan:

```python
PRIMARY_DEVICE_INDEX = 3
SECONDARY_DEVICE_INDEX = 6
FALLBACK_TO_SYSTEM_DEFAULT = True
```

`PRIMARY_DEVICE_INDEX` is the main show audio device. In this project it is used for the HDMI/AVR-style output and the `primary_channels` table.

`SECONDARY_DEVICE_INDEX` is the second multichannel device. In this project it is used for the USB 7.1-style output and the `secondary_channels` table.

> *NOTE*
> - The primary and secondary devices can be any output devices with enough channels for the table you assign to them. They do not have to be HDMI or USB specifically. For example, either table can point to any 7.1-compatible output device. Just make sure the channel indexes in that table are valid for that device.
> - A 7.1 device usually exposes 8 output channels indexed 0-7. A 5.1 device usually exposes 6 output channels indexed 0-5. If your table uses indexes 6 or 7, use a device that actually supports those channels.
> - If using a device with less than 8 channels, you may adjust the table size.

`FALLBACK_TO_SYSTEM_DEFAULT = True` means that if the configured device is invalid or cannot open, the system will try the Windows default output device. All fallback playback preserves the original stereo source on outputs 0/1 when available, including requests originally addressed to a mono room or "all". Mono sources feed both sides; a one-channel fallback downmixes both source sides. This is mostly useful for test environments where the real speaker system is not connected.

When the same file is sent to different fallback routes within 0.5 seconds with
identical gain, loop and shutdown settings, those requests share one playback.
This avoids doubled volume and delayed copies of the same music on laptop speakers.
Repeating a request to the same route remains a separate playback. Configured
show devices retain independent voices on their mapped channels.

Audio stays in float32. Equal sample rates bypass conversion; different rates
use SoXR VHQ with continuous state across streamed blocks. Conversion applies
3 dB of fixed headroom to accommodate reconstructed peaks without pumping.
Install `MainCode/requirements.txt` in each Python environment to get SoXR.
Diagnostics report `clipped_samples` and underruns; excessive gain or many
different overlapping sounds can still overload an output.

Optional `PRIMARY_DEVICE_NAME` and `SECONDARY_DEVICE_NAME` settings accept a
device-name fragment (or `None`). They protect against a saved index pointing
to another device after unplugging HDMI/USB hardware. The configured output must
also support every channel index in its table; otherwise fallback is used.
The template leaves the name settings unset so you can configure your hardware.

Each playback-start log reports the actual device name, index, host API, routed
output channels, and whether fallback was used. Primary/secondary identify the
logical routing table, not the physical speaker device.

System startup calls `initialize_audio()` on the main thread before launching
the GUI and rooms. The streams stay open for subsequent playback. Standalone
programs can call this helper before creating playback worker threads.

If the Windows default cannot open, fallback tries smaller channel counts and
other available outputs. If the selected fallback device already has an open
mixer, the system reuses that stream. Secondary fallback also prefers the
system default over an unrelated primary show device.
Check the startup log to confirm the actual output: fallback
does not preserve discrete room isolation.
With fallback disabled, a failed configured device raises an error.

### 6.2 Finding Audio Device Indexes

Run `MainCode/utils/audioDeviceScanner.py` to list the audio devices that Python can see:

The scanner calls `sounddevice.query_devices()` and prints the device list. Look for output devices with output channels greater than `0`.

Example output might look like:

```text
3 Speakers (Realtek(R) Audio), MME (0 in, 8 out)
6 Speakers (2- CUBILUX CA7), Windows WASAPI (0 in, 8 out)
11 Speakers (Realtek(R) Audio), Windows WASAPI (0 in, 8 out)
```

In that example:

```python
PRIMARY_DEVICE_INDEX = 6
SECONDARY_DEVICE_INDEX = 11
```

> *NOTE*: We ignored index 3, even though it is the same device, because WASAPI is preferred over MME. Preference from best to worst would be WASAPI > DirectSound > MME > ASIO

Device indexes can change when USB devices are unplugged, replugged, disabled, or when Windows changes audio drivers. If audio starts routing to the wrong place, scan devices again and update the indexes.

Do not choose devices with `0` output channels. A microphone may appear in the device list, but it cannot be used for playback.

### 6.3 Channel Tables

Named channels exist in two dictionaries in `audio_manager.py`. The tables below
are examples. Use the names and indexes in your project's actual configuration.

The primary device uses:

```python
primary_channels = {
    "Room_1": {"index": 0, "gain": 1.0},
    "Room_2": {"index": 1, "gain": 1.0},
    "Room_3": {"index": 2, "gain": 1.0},
    "primary_LFE": {"index": 3, "gain": 1.0},
    "Room_4": {"index": 4, "gain": 1.0},
    "Room_5": {"index": 5, "gain": 1.0},
    "primary_BL": {"index": 6, "gain": 1.0},
    "primary_BR": {"index": 7, "gain": 1.0},
}
```

The secondary device uses:

```python
secondary_channels = {
    "secondary_FL": {"index": 0, "gain": 1.0},
    "secondary_FR": {"index": 1, "gain": 1.0},
    "secondary_C": {"index": 2, "gain": 1.0},
    "secondary_LFE": {"index": 3, "gain": 1.0},
    "secondary_SL": {"index": 4, "gain": 1.0},
    "secondary_SR": {"index": 5, "gain": 1.0},
    "secondary_BL": {"index": 6, "gain": 1.0},
    "secondary_BR": {"index": 7, "gain": 1.0},
}
```

Each entry has:

`index`: The physical output channel number on that device. Channel indexes are zero-based, so the first channel is `0`, not `1`.

`gain`: Volume multiplier for that named channel. `1.0` is normal volume, `0.5` is half volume, and `1.5` is louder.

Speaker label meanings:

- `FL`: front left
- `FR`: front right
- `C`: center
- `LFE`: subwoofer / low-frequency effects
- `SL`: side left
- `SR`: side right
- `BL`: back left
- `BR`: back right

### 6.4 Mono Named Channels

A mono named channel routes audio to one physical output channel. Stereo source files are automatically folded down using both left and right channels. This is the standard setup for playing individual sounds on separate speakers.

Set it in the table:

```python
"Room_3": {"index": 2, "gain": 1.0}
```

Use it like this:

```python
play_audio("Room_3", "effect.wav")
```

This plays `Assets/SoundDir/effect.wav` on physical channel `2` of the primary device, using the default channel gain of `1.0`.

### 6.5 Stereo Named Channels

You may map any two channels to play in stereo.
Stereo mappings can be written in either of these forms.

**Single-entry form**

The format is:

```python
"stereo_{name}": {"index": [left_channel_index, right_channel_index], "gain": gain_float}
```

Example:
```python
"stereo_graveyard": {"index": [3, 1], "gain": 1.0}
```
where 3 is the LEFT speaker and 1 is the RIGHT speaker.

**Left/right split-entry form**

The format is:
```python
"stereo_{name}_L": {"index": channel, "gain": gain_float}
```
or
```python
"stereo_{name}_R": {"index": channel, "gain": gain_float}
```

Example:
```python
"stereo_graveyard_L": {"index": 0, "gain": 1.0}
"stereo_graveyard_R": {"index": 1, "gain": 1.0}
```

Then call it without the `stereo_` prefix:

```python
play_audio("graveyard", "scene.wav")
```

`audio_manager.py` automatically looks for `stereo_graveyard`, or for `stereo_graveyard_L` and `stereo_graveyard_R`.

### 6.6 Determining Physical Speaker Channels

The only reliable way to map speakers is to test each channel on the actual hardware.

Use this process:

1. Connect the audio device and set Windows to the expected speaker layout.
2. Run `audioDeviceScanner.py`.
3. Put the correct device index into `PRIMARY_DEVICE_INDEX` or `SECONDARY_DEVICE_INDEX`.
4. Run speakerTest.py
5. Write down which physical speaker plays for each channel index.
6. Update `primary_channels` and `secondary_channels` with the names you want to use.

### 6.7 `play_audio(...)`

Most code should use:

```python
play_audio(target_or_text, maybe_file=None, *, gain=None, base_folder=None, tts_rate=0, looping=False, threaded=True)
```

Arguments:

`target_or_text` 
This argument can be: 
- The named channel (ex. Room_1)
- "all" (plays on all channels)
- Any other string. This will be played as TTS (text-to-speech)
- "channel: text" for TTS on a specific channel.

`gain`: Optional volume multiplier for this playback only. If `None`, the channel table gain is used. If provided, it overrides the table gain.

`base_folder`: Optional folder to load audio from. If omitted, audio files are loaded from `Assets/SoundDir`.

`tts_rate`: Text-to-speech speed adjustment. On Windows this is clamped from `-10` to `10`. `0` is normal.

`looping`: False by default. If `True`, file audio loops until stopped by `BreakCheck()` or `stop_all_audio()`. TTS does not loop.

`threaded`: True by default. If `True`, the sound is submitted to the persistent mixer and the caller continues immediately. If `False`, the caller waits until the sound finishes or is stopped. TTS is always non-blocking (intentional).

### 6.8 Common Playback Examples

Play a WAV on a named room channel:

```python
play_audio("Room_3", "effect.wav")
```

Play louder or quieter for one call:

```python
play_audio("Room_2", "effect.wav", gain=0.8)
```

Start looping ambience:

```python
play_audio("Room_5", "ambience.wav", gain=1.0, looping=True)
```

Block until a scene file finishes:

```python
play_audio("secondary_FL", "scene.wav", gain=0.4, threaded=False)
```

Broadcast a WAV to every output channel on the primary device:

```python
play_audio("all", "systemTest.wav")
```

Speak text-to-speech on all primary channels:

```python
play_audio("System rebooting", gain=0.3)
```

Speak text-to-speech on a named channel:

```python
play_audio("Room_3: This is a test message", gain=0.7)
```

### 6.9 Lower-Level Playback Helpers

`play_to_named_channel(...)` is what `play_audio("Room_3", "file.wav")` calls internally:

```python
play_to_named_channel(
    wav_file,
    target_name,
    gain_override=None,
    base_folder=None,
    looping=False,
    honor_shutdown=True,
    honor_breakcheck=True,
    threaded=True,
)
```

Use this only when you specifically need `honor_shutdown` or `honor_breakcheck`. Useful if you have an audio file that needs to be played through system shutdown, such as a warning message.

To let a file finish during shutdown, set both `honor_shutdown=False` and
`honor_breakcheck=False`: the shutdown state also triggers BreakCheck.

`play_to_all_channels(...)` broadcasts a file or TTS to all channels on the primary device:

```python
play_to_all_channels(
    wav_or_text,
    tts_rate=0,
    gain_override=None,
    base_folder=None,
    looping=False,
    honor_shutdown=True,
    honor_breakcheck=True,
    threaded=True,
)
```

For normal use, always use `play_audio(...)`.

### 6.10 Shutdown Behavior

Normal file playback respects shutdown:

```python
play_audio("Room_3", "effect.wav")
```

`stop_all_audio()` signals all normal file streams to stop and waits briefly for them to finish. TTS streams ignore this and finish naturally.

TTS is intentionally immune to shutdown and `BreakCheck()` so emergency/status voice lines can still finish. For example in shutdown.py we have:

```python
play_audio("emergency shutdown activated")
```

You may intentionally call `stop_all_audio()` as shown below:

```python
from control.audio_manager import stop_all_audio

stop_all_audio()
```

Otherwise it will only be called within shutdown.py

### 6.11 Registering Channels in Code

Most permanent channel changes should be made directly in the `primary_channels` and `secondary_channels` tables.

Temporary runtime registration is also available:

```python
from control.audio_manager import register_primary_channel, register_secondary_channel, set_channel_gain

register_primary_channel("custom_primary_output", 4, gain=1.0)
register_secondary_channel("custom_secondary_output", 6, gain=0.8)
set_channel_gain("Room_3", 1.2)
```

These changes only last for the current Python process.

### 6.12 Troubleshooting

If you see `Configured primary device ... has no output channels` or the corresponding secondary-device message, the selected index probably refers to an input device. Run `audioDeviceScanner.py` again.

If you see `Failed to open configured ... mixer ...; fallback attempts: ...`,
all attempted outputs failed to open. Check device indexes, Windows sound
settings, sample rate, and whether another app is holding exclusive access.

If audio plays from laptop speakers instead of the show system, the configured device probably failed and fallback was used. Check the log for:

```text
[Audio] PRIMARY configured mixer failed (...); using fallback idx=...
```

If audio routes to the wrong physical speaker, the device index may be correct but the channel map is wrong. Re-test physical channels and update `index` values in the channel tables.

An out-of-range channel index now raises a clear configuration error rather
than playing on a different speaker. Update the table to match the device.

Run `python MainCode/utils/audio_mixer_diagnostic.py` from the project folder
for a silent device inventory. Add `--exercise --wav PATH` to explicitly play
through every configured entry, test overlaps, and print underrun counters.
The standalone speaker test and exercise diagnostic set the active/online
state needed for file playback; rooms still follow normal BreakCheck behavior.

After changing device indexes, restart the program to reopen its persistent
streams. For the software verification results, see
[Audio feature audit](AUDIO_FEATURE_AUDIT.md).

---
---

## 7. BreakCheck Guide

`BreakCheck()` is defined in `MainCode/utils/tools.py` and is one of the most important safety/control helpers in the project.

Room code should import it like this:

```python
from utils.tools import BreakCheck
```

The main idea is:

- `BreakCheck()` tells long-running loops and effects when they should stop.
- It returns `True` when the house is no longer actively running.
- It returns `False` when the house is still active and online.
- Room scripts, effects, audio playback, lightning, dimmer flicker, and sensor wait loops use it to exit cleanly.

### 7.1 What BreakCheck Checks

`BreakCheck()` returns `True` if either of these is true:

```python
not house.HouseActive
house.systemState != "ONLINE"
```

In plain English:

- If the house is not active, stop the current room/effect loop.
- If the system is not online, stop the current room/effect loop.

If neither condition is true, `BreakCheck()` returns `False`.

### 7.2 When to Use BreakCheck

Use `BreakCheck()` anywhere code might wait, loop, sleep repeatedly, or run an effect for a long time.

Common places:

- `while` loops inside room scripts
- waiting for sensors or buttons
- timed sequences
- repeated light/relay changes
- lightning effects
- any loop that should stop during shutdown

Do not put long blocking sleeps in room code without checking `BreakCheck()` periodically.

### 7.3 Common Loop Pattern

Use this pattern for loops that should stop when the house stops:

```python
while not BreakCheck():
    # do room/effect work here
    time.sleep(0.05)
```

Use this pattern when waiting for a sensor:

```python
while not sensor_is_triggered():
    if BreakCheck():
        return
    time.sleep(0.05)
```

For longer waits, split the wait into smaller chunks:

```python
for _ in range(10):
    if BreakCheck():
        return
    time.sleep(1)
```

You never want:

```python
time.sleep(10)
```

because the long sleep cannot react quickly to shutdown.

### 7.4 BreakCheck Debug Output

When `BreakCheck()` triggers, it logs:

```text
BreakCheck triggered: System no longer active.
```

If `house.DEBUG_BREAKCHECK` is `True`, it also prints where `BreakCheck()` was called from:

```text
[BreakCheck DEBUG] Called from function_name() in file.py:123 (thread: thread_name)
```

This is useful when trying to find which room, effect, or thread exited during shutdown.

`house.DEBUG_BREAKCHECK` is configured in `MainCode/house_state.py`.

### 7.5 Important Notes

`BreakCheck()` will return `True` during shutdown, reboot, emergency shutdown, soft shutdown, or when the house is not actively running.

If a room/effect does not have adequate `BreakCheck()`, it may continue running after shutdown!

TTS audio intentionally ignores `BreakCheck()` in some cases so shutdown/status voice lines can finish.

---
---

## 8. Dimmer Controller Guide

The dimmer system is managed by `MainCode/control/dimmer_controller.py`. Room code can import either the module or specific functions:

```python
from control import dimmer_controller as dim
```

or:

```python
from control.dimmer_controller import dim, dimmer_flicker
```

The main idea is:

- `dim(value)` sets CH1 brightness from `0` to `100`; add `channel=2` through `8` for another output.
- `dimmer_flicker(...)` creates smooth randomized flicker effects.
- If the dimmer board is not connected, the controller logs the failure and enters simulated mode. Enable wire debug to log individual simulated commands.
- The controller rate-limits serial writes and drains Arduino/UNO serial output in a background thread.

### 8.1 Device Setup

Upload `dimmerUno/dimmerUno.ino` to a classic 16 MHz ATmega328P UNO, or
`dimmerNano/dimmerNano.ino` to the equivalent Nano. Both folders contain the same
tested KRIDA eight-channel scheduler and their own `Schedule.h` and `Demo.h`.
No RBDdimmer library is required. For older Nano bootloaders, select
**ATmega328P (Old Bootloader)** when uploading.

Wiring is **SYNC -> D2; CH1..CH8 -> D3..D10**, with the KRIDA logic ground and
supply connected as appropriate for the board. The firmware targets 60 Hz and
uses Timer1 exclusively. Do not combine it with Servo/Timer1 PWM libraries.
Both sketches preserve the tested calibration: new 100 uses a 730 us firing
delay, matching the original test's 95; 0 never fires.

Close Serial Monitor before running Python. Upload the updated firmware first:
Python verifies `VERSION` -> `KRIDA8 V1` and will reject the old single-channel
firmware. Serial commands are `SET ch pct` -> `ACK SET ch pct`, `OFF` -> `OK OFF`,
and `INFO` for diagnostics. Legacy manual `SET pct` targets CH1. The earlier
Nano `D,...` and UNO `RAW` protocols are replaced.

`DEMO` starts the eight-channel staggered ramps; `DEMO2` flickers CH1 like fire
while CH2 ramps. Both default to the calibrated maximum. Use `STOP` or `OFF`
to stop. See `dimmerKridaTest/README.md` for timing and bench test details.

At the top of `dimmer_controller.py`, the serial settings are configured:

```python
PORT = "COM7"
BAUD = 115200
TIMEOUT = 0.10
```

`PORT` is the COM port for the dimmer board.

`BAUD` must match the baud rate used by the arduino (you can leave it at 115200 if using my code).

`TIMEOUT` controls how long serial reads wait before returning.

If the dimmer board is on a different port, either update `PORT` in `dimmer_controller.py` or pass a port to `init()`:

```python
dim.init("COM8")
```

### 8.2 Initialization and Simulated Mode

The dimmer is initialized as a persistent service during startup in system.py:

```python
import control.dimmer_controller as dim

dim.init()
```

The controller waits two seconds for the Arduino reset, starts its background
reader, verifies the protocol and sends acknowledged `OFF`. Initialization
leaves every channel off and returns `True` for hardware or `False` for simulation.
The prior automatic startup brightness of 15 is removed.

If the board is missing or the port cannot open, the controller logs the connection failure and enters simulated mode:

```text
[dimmer_controller] Running in simulated mode.
```

In simulated mode, calls like `dim(50)` and `dimmer_flicker(...)` still work from the rest of the program's perspective, but no hardware command is sent.

### 8.3 Setting Brightness

Use `dim(value)` to set brightness:

```python
dim.dim(100)
```

or, if imported directly:

```python
dim(100)
```

Brightness is clamped from `0` to `100`; non-finite values and channels outside
integer 1..8 are rejected. Percentages describe the calibrated firing-angle
range, not measured watts or perceived brightness.

```python
dim.dim(100)                # Existing calls still control CH1
dim.dim(40, channel=2)      # Independently control CH2
dim.dim(75, channel=8)
print(dim.get_current_pct(2))
dim.all_off()              # Stop all effects/demos and clear all eight outputs
```

Examples:

```python
dim(0)    # off
dim(50)   # midpoint of the calibrated control range
dim(100)  # full brightness
```

With ACK pacing enabled (the default), `dim(...)` returns `True` only after
receiving the matching channel/value acknowledgement. It returns `False` for
an unchanged, non-stale value or a failed command. Channel caches and resend
timers are independent. Disabling ACK pacing only confirms the serial write.

To force a write even if the value is unchanged:

```python
dim(50, force=True)
```

### 8.4 Flicker Effects

Use `dimmer_flicker(...)` to create a smooth randomized flicker:

```python
dimmer_flicker(
    duration,
    min_intensity,
    max_intensity,
    flicker_length_min,
    flicker_length_max,
    threaded=False,
    ease=True,
)
```

Arguments:

`duration`: Total flicker duration in seconds.

`min_intensity`: Lowest brightness percentage.

`max_intensity`: Highest brightness percentage.

`flicker_length_min`: Shortest time for one smooth ramp segment.

`flicker_length_max`: Longest time for one smooth ramp segment.

`threaded`: If `True`, starts the flicker in a background thread and returns immediately. If `False`, blocks until the flicker finishes. False by default.

`ease`: If `True`, uses smooth cosine easing between random brightness targets.

Example:

```python
dimmer_flicker(10, 20, 80, 0.05, 0.18, threaded=True)
```

This flickers for `10` seconds, randomly moving between `20%` and `80%` brightness, with each ramp segment lasting between `0.05` and `0.18` seconds.

Add `channel=2` (or 1..8) to select the output. Each channel has its own worker;
starting CH2 does not stop CH1. Starting a new effect on the same channel
replaces that channel's previous effect. For example:

```python
dim.dimmer_flicker(30, 20, 100, 0.05, 0.18, threaded=True, channel=1)
dim.dimmer_flicker(30, 10, 80, 1.0, 3.0, threaded=True, channel=2)
```

### 8.5 Stopping Effects

Flicker effects stop when `BreakCheck()` says the house is no longer active/online. Due to this, you should not normally need to use these functions.

To stop the current flicker worker:

```python
dim.stop_flicker()
```

To wait briefly for the flicker thread to exit:

```python
dim.stop_flicker(join=True)
```

Omitting `channel` stops every Python flicker worker. Use
`dim.stop_flicker(channel=2, join=True)` to stop only CH2; outputs hold their
last value. To turn everything off, call `dim.all_off()`. `dim.close()` also
stops workers and requests OFF before closing the connection. A failed OFF
acknowledgement is logged; software cannot confirm physical output in that case.

There is also a global stop flag for dimmer effects:

```python
dim.request_stop()
```

To clear that stop flag before starting effects again:

```python
dim.clear_stop()
```

### 8.6 Tuning Helpers

The dimmer controller includes tuning helpers for serial write behavior and ramp smoothness:

```python
dim.set_write_rate_hz(30)
dim.set_keepalive(0.5)
dim.set_ack_timeout(0.25)
dim.set_ack_pacing(True)
dim.set_ramp_hz(30)
```

`set_write_rate_hz(hz)`: Caps total serial writes across all channels. With many
simultaneous effects, each gets a share of that total rate.

`set_keepalive(seconds)`: A subsequent `dim()` call resends the same value if
that channel's last successful send is older than this. There is no background
heartbeat or serial-loss watchdog; the firmware holds commands while SYNC is valid.

`set_ack_timeout(seconds)`: Sets how long to wait for dimmer ACK responses.

`set_ack_pacing(on)`: Enables or disables ACK pacing.

`set_ramp_hz(hz)`: Sets how many ramp updates are sent per second.

Most projects can leave these defaults alone unless the dimmer feels too choppy, too chatty, or unreliable.

### 8.7 Diagnostics

Enable wire debug to print each command's result and elapsed time:

```python
dim.enable_wire_debug(True)
```

Disable it:

```python
dim.enable_wire_debug(False)
```

Run an ACK latency test:

```python
dim.ack_latency_test(set_value=50, n=30)
```

If the controller is in simulated mode, the ACK latency test is skipped and logged.

---
---

## 9. Examples
- To trigger a sound in a room: `play_audio('Room_1', 'spooky.wav')`
- To log an event: `log_event('Door opened')`
- To toggle demo mode: `toggle_demo_mode(state, enable=True)`

## 10. Special Notes
- All cross-component communication should go through shared context or control modules.
- Use relative imports within `MainCode/`.

---
---
