# Generic MOSFET node

Original **ESP32 Dev Module / ESP32-WROOM**, logical ID **MOSFET1** by default.
Uses the existing HauntProtocol ESP-NOW network, COM6 USB bridge, boot/session
fencing, ACKs and retry owner. No separate serial connection is opened by Python.

Edit these settings at the top of `mosfetNode.ino`:

```cpp
const char* DEVICE_ID = "MOSFET1";
constexpr uint8_t OUTPUT_PINS[] = {0,2,4,5,12,13,14,15,16,17,18,19,21,22,23,25,26,27,32,33};
constexpr bool ACTIVE_HIGH = true;
```

`OUTPUT_COUNT` is calculated from the list. Remove entries to limit which pins
can be switched. For only your laser MOSFET, use `OUTPUT_PINS[] = {13}`.
P13 means **GPIO13**, not the board header's thirteenth physical pin.

The initial list contains all 20 WROOM outputs that do not overlap UART0 or
flash. GPIO1/3 remain reserved for USB/serial diagnostics; GPIO6..11 for flash;
GPIO34..39 are input-only. GPIO0/2/5/12/15 are boot-strapping pins and attached
circuits must preserve their required startup levels. GPIO16/17 must be removed
on modules that use them for PSRAM (such as WROVER). This configuration is for
original ESP32/WROOM, rather than C3/S3 boards. Pin restrictions:
[Espressif GPIO documentation](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/gpio.html).

Outputs are driven OFF at startup, before radio initialization. `True` drives
HIGH with ACTIVE_HIGH=true, `False` drives LOW. With ACTIVE_HIGH=false, electrical
levels are inverted. Output state latches until a later command or node restart;
it does not expire on a timer or turn off merely because the host disconnects.
Send False explicitly from your effect's stop/shutdown routine.

## Python

Inside the running main system, reuse its initialized RSM:

```python
from control import remote_sensor_monitor as rsm

results = rsm.mosfet(["MOSFET1"], 13, True)   # Laser MOSFET ON
rsm.mosfet(["MOSFET1"], 13, False)           # OFF
rsm.mosfet(["MOSFET1", "MOSFET2"], 13, True) # Same GPIO on multiple nodes
rsm.mosfet("MOSFET1", 14, True)             # One string ID also works

for node_id, command_id in results.items():
    print(node_id, rsm.command_status(command_id))

state = rsm.get_mosfet_state("MOSFET1")
# available_pins: configured GPIO numbers; on_pins: outputs commanded ON.
```

Returns `{node_id: command_id}` immediately. It is not an atomic group operation;
check each delivery result. The node rejects pins outside its configured list.
Missing/unavailable devices and wrong device kinds fail through existing command
status handling. True/False must be actual booleans. An accepted command confirms
the node applied the output request, rather than measuring MOSFET/load operation.
Telemetry reports all output states every second and after accepted commands.
Different GPIOs have independent ordering and retry cancellation, so switching
one does not discard a queued command to another.

## Build and install

**Flash both mosfetNode and the updated USB transceiver.** Updating the library
on the PC alone does not update firmware on COM6. Stop MainCode before uploading
the bridge on COM6, then restart MainCode after both firmware updates. The Arduino
IDE library junction configured for this project follows the repository library.
Existing other nodes do not need reflashing for this additive protocol extension.
No firmware has been uploaded automatically.

```powershell
arduino-cli compile --fqbn esp32:esp32:esp32 --libraries Esp32/libraries Esp32/mosfetNode
arduino-cli compile --fqbn esp32:esp32:esp32 --libraries Esp32/libraries Esp32/transceiver
```

## Wire extension

Type **13 MOSFET**, 24 bytes: configured-pin bitmap u64, ON-pin bitmap u64,
command session u32, command sequence u32. A bit corresponds to its GPIO number;
ON bits must be a subset of configured bits. Integers are little endian.

Operation **9 MOSFET_SET**, reliable COMMAND of 12 bytes: target session u32,
operation u8, ON/OFF value u16 (0/1), duration u32 (must be 0), GPIO u8 (0..39).
Ordering stream is `11 + GPIO`; original streams 0..10 remain unchanged. Bridge
retry supersession applies only to older requests for that same node and GPIO.

USB command op is `mosfet`, with `pin` plus existing `value` and `duration_ms`.
Telemetry kind is `mosfet`; vals contain `available_pins`, `on_pins`, `ready`,
`command_session`, and `command_seq`. Existing network/channel/version and other
command formats remain unchanged.

## Checks

### Troubleshooting device-not-seen errors

With `SERIAL_DIAGNOSTICS=true`, connect the MOSFET board's USB port and open
its serial monitor at **115200 baud**. Reset the board. The boot banner prints
its device ID, network and channel, followed by radio initialization success
or failure. Every ten seconds it prints uptime, report counts, send failures
and the last accepted command sequence. Repeated boot banners indicate resets.
`reports_sent` means the local Wi-Fi stack accepted the transmission, not that
the bridge received it. This node-local debug setting is independent of
Python's `house.DEBUG_INFO`. Outputs still boot OFF.

```powershell
python -m unittest discover -s MainCode/tests -p test_mosfet.py
.tools/zig-x86_64-windows-0.14.1/zig.exe c++ -std=c++17 -IEsp32/mosfetNode/tests Esp32/mosfetNode/tests/check.cpp -o .tools/mosfet-check.exe
.tools/mosfet-check.exe
```
