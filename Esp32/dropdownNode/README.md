# dropdownNode

Powered ESP32-C3 Super Mini node combining the existing servo controls, one debounced remote
button, and an actor-ready LED. Edit the configuration at the top of
`dropdownNode.ino` before flashing each board. Default logical ID: `DROPDOWN1`.

| Connection | Default |
| --- | --- |
| Servo signal | GPIO 4 |
| Button | GPIO 5 to GPIO 6 (or GND), internal pull-up, pressed = LOW |
| Button return | GPIO 6, output held LOW after startup |
| Blue onboard LED | GPIO 8, active LOW, off at startup |
| Servo startup angle | 90 degrees, or the saved `set_default` value |
| Servo pulse range | 500–2500 microseconds at 50 Hz |
| Button debounce | 30 ms |

LED pins/polarity vary by board: set `LED_PIN` and `LED_ACTIVE_HIGH` to match
yours. This sketch uses low-speed, 14-bit LEDC at 50 Hz for the C3, preserving
servoNode's angle/ramp behavior. GPIO 6 is a logic LOW for the button return only;
use an actual GND pin for the servo and power-supply ground.
Power the servo from an appropriate supply with
a common ground to the ESP32. Adjust pulse/angle limits to your mechanism.
GPIO 4 and GPIO 5 refer to the board's printed GPIO numbers. GPIO 8 drives the
onboard blue LED; the red power indicator is not controlled by this sketch.

## RSM usage

```python
from control import remote_sensor_monitor as rsm

# The application normally initializes RSM once at startup.
rsm.init()

move_id = rsm.servo("DROPDOWN1", 120, ramp_ms=800)
ready_id = rsm.led("DROPDOWN1", True)
rsm.led("DROPDOWN1", False)

pressed = rsm.get_button_value("DROPDOWN1")  # Same as (..., 1).
if pressed is True:
    pass  # Trigger your room action here.

state = rsm.get_servo_state("DROPDOWN1")
led_on = rsm.get_value("DROPDOWN1", "led")
result = rsm.command_status(ready_id)

# Persist startup position; also moves to it over 300 ms, as on servoNode.
rsm.tx_to_id("DROPDOWN1", {"set_default": 90})
```

LED commands require a Python boolean and return the usual command ID. The LED
stays at its last accepted setting until another LED command or a reboot; it
does not automatically track servo completion or host availability. Room code
decides when the dropdown is ready. Servo and LED commands have independent
ordering and retry cancellation, so either may be issued while the other is pending.

Press/release transitions use application ACKs and the existing bounded retries.
Every report includes servo, button and LED state under one identity. Reports
arrive every 200 ms while moving and 2 seconds when idle (held or released).
Idle snapshots now also use application ACKs and bounded retries; moving snapshots
remain single-send updates. This improves idle availability under packet loss but
does not prove the underlying radio or board fault is resolved.
Both button states become `None` after 6 seconds without telemetry or on an ID
conflict. Latest-state polling can miss a complete tap between checks, just as
with the existing remote buttons. Servo angles describe PWM, not measured motion.

## Rollout and protocol

Flash the updated `transceiver` bridge and new `dropdownNode`, and run the updated
Python RSM. Existing nodes retain their wire formats and need no reflash.
Before building in Arduino IDE, copy the repository's complete
`Esp32/libraries/HauntProtocol` folder into your sketchbook's `libraries` folder,
replacing the older installed HauntProtocol copy. On this workstation that is
`C:\Users\minen\Documents\Arduino\libraries\HauntProtocol`.
Repeat this copy after protocol-library updates. Missing `DROPDOWN` or `LED`
compiler errors mean an older library copy is being used. The CLI command below
selects the repository library explicitly; Arduino IDE uses the installed copy.

In Arduino IDE select **ESP32C3 Dev Module**
and enable **USB CDC On Boot** for the Super Mini's native USB port. Compile:

```powershell
arduino-cli compile --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc --libraries Esp32/libraries Esp32/dropdownNode
```

### Direct USB diagnostics

Build `dropdown-2026-10-12-r2` outputs a health line once per second to its native
USB port with USB CDC On Boot enabled. Connect a USB data cable and open Serial
Monitor at 115200 baud. The sketch never waits for USB, and skips logging if the
output buffer has insufficient space, so an absent/slow monitor cannot block it.

The line includes the node build, ID, uptime, boot session, attempted reports,
received command-handler calls, maximum loop gap, queue drops, synchronous send
errors, retry count and unconfirmed reliable deliveries. The command count includes
invalid handler requests but excludes duplicate retries handled by the radio layer.
Increasing reports with low loop gaps but rising unconfirmed counts indicates
reports are being attempted without application ACKs; a large loop gap indicates
the application was delayed. Synchronous `send_errors=0` alone does not establish
over-the-air delivery. A changed boot session indicates a restart.

Flash only the dropdown to apply these reporting and USB diagnostic changes; the
wire format and shared radio library are unchanged. Restart the Python application
to retain received radio counters across subsequent telemetry snapshots.

Python's `house.DEBUG_INFO` controls the detailed dropdown command/result,
restart and telemetry-recovery log lines. Set it before starting the monitor;
restart the application after changing the configuration. Normal button events,
bridge connection/error messages and the live status panel remain available.
This Python setting does not control the board's separate native USB health output.

Hardware references: [Apache NuttX Super Mini board documentation](https://github.com/apache/nuttx/blob/master/Documentation/platforms/risc-v/esp32c3/boards/esp32c3-supermini/index.rst)
(GPIO 8 active-low LED), [Espressif C3 LEDC documentation](https://docs.espressif.com/projects/esp-idf/en/v4.4/esp32c3/api-reference/peripherals/ledc.html)
(low-speed mode and 14-bit resolution).

Type **11 dropdown** has 19 bytes: the unchanged 17-byte servo telemetry layout,
followed by pressed u8 and LED-on u8 (both 0/1). Reliable flags mark button edges
and the initial settled snapshot. USB uses `kind:"dropdown"`, the existing servo
fields, and `btn:1`, `pressed`, `led`. Operation **7 LED** uses the existing
11-byte command layout, with value 0/1 and duration 0; USB uses `op:"led"`.
LED commands use ordering stream 10; servo commands retain stream 0.

Bench-check startup position/LED, button bounce and long holds, servo ramps,
rapid alternating servo/LED commands, and node disconnects before installation.
Software tests do not establish physical wiring or motion.
