# Device recovery and diagnostics

Python now records identity conflicts, old boot counters, and rejected sequences.
With `house.DEBUG_INFO=True`, logs include observed/expected MAC addresses, boot
sessions, sequences, first sightings, restarts, and telemetry returns. Repeated
rejections are limited to one log per device/reason per ten seconds. Meaningful
conflict and boot-counter errors remain visible with debugging off; detailed
sequence traces and telemetry-return traces require debugging on.

The receiver sends rejection diagnostics at most once per device per second.
These messages do not refresh the device's measurement or button state age.
Silent powered sensors and expired held buttons produce an unavailable event.
Released battery buttons can legitimately sleep, so their silence is only logged
with debugging on. Existing firmware does not identify whether a released button
is sleeping or powered but disconnected; silence alone cannot distinguish them.

## Recovery rules

Both receiver and Python keep the first recognized MAC for each logical ID.
Another MAC reporting that ID blocks it. The original MAC may resume after the
competitor has been quiet for ten seconds, using fresh, correctly ordered device
telemetry. Another report from a competing MAC blocks it again and restarts that
wait. The competing MAC never automatically becomes the owner. Replacing a board
with another MAC requires deliberate reconfiguration/reinitialization.

No ordering history is cleared on USB reconnect or elapsed silence. Old boot
counters, old/duplicate sequences, queued expired recovery frames, radio
diagnostics, ACKs, and commands cannot unlock the receiver's conflict state.
A newer boot counter from the same MAC continues to reset previous button states.
Recovery does not replay commands or manufacture a button press/release. A fresh
real press after recovery can trigger the normal room logic.

An old boot counter (for example after erasing board storage) stays blocked and
is now diagnosed instead of silently ignored. This change cannot repair a board
that has stopped transmitting or establish the cause of the October 30 incident;
that incident's logs did not contain the required rejection/identity evidence.

## Activation

1. Compile and flash `Esp32/transceiver/transceiver.ino` onto the COM6 receiver
   using the updated repository `Esp32/libraries` library.
2. Restart Python once to load the monitor changes and configured `DEBUG_INFO`.
3. Bench-test BTN4 battery removal/reinsertion and receiver USB reconnection.
   Confirm BTN4 updates resume and other devices remain usable.

Only the receiver needs a firmware update for this receiver-side recovery and
USB diagnostic path. Button and sensor packet formats remain unchanged. No
physical board was flashed or live house behavior tested during this change.

## Automated checks

From the repository root:

```powershell
python -m unittest discover -s MainCode/tests -p test_device_recovery.py -v
& .tools/zig-x86_64-windows-0.14.1/zig.exe c++ -std=c++17 '-IEsp32/PIR_extenderNode/tests/fakes' -IEsp32/libraries/HauntProtocol/src Esp32/PIR_extenderNode/tests/recovery.cpp -o .tools/recovery-check.exe
& .tools/recovery-check.exe
& 'C:/Program Files/Arduino IDE/resources/app/lib/backend/resources/arduino-cli.exe' compile --fqbn esp32:esp32:esp32 --libraries Esp32/libraries --build-path .tools/device-recovery-bridge-build Esp32/transceiver
```

The native harness exercises the actual shared radio implementation, including
duplicate identity quarantine, clock wrap, replay rejection, reboots, rejection
callbacks, and another device remaining operational throughout recovery.
