# Wireless button LED control

`remoteButton.ino` supports the existing button reports plus `rsm.led()`:

```python
rsm.led("BTN4", True)   # Onboard LED and GPIO4 ON together.
rsm.led("BTN4", False)  # Both OFF.
```

Use the flashed board's `DEVICE_ID`. These calls return a delivery ID for
`rsm.command_status()`; the radio acknowledgement confirms command acceptance,
not measured light output.

Configuration at the top of the sketch:

- `ENABLE_LED_CONTROL = true` enables commands and keeps Wi-Fi awake.
- `ONBOARD_LED_PIN = 2` selects the original ESP32's onboard LED. Change this
  GPIO for your board; this implementation controls a simple GPIO LED.
- `LED_PIN = 4` selects the external indicator output.
- `LED_GND_PIN = 5` holds the external LED's ground return LOW.
- `ONBOARD_LED_ACTIVE_HIGH` and `LED_ACTIVE_HIGH` set each output's polarity.
- `DEFAULT_LED_ON = false` leaves both indicators OFF on boot.

When LED control is enabled, the node ignores `IDLE_SLEEP` and reports button
state every two seconds, including releases. Disabling LED control restores
the configured sleep behavior and leaves the LED pins untouched. The output
holds its last commanded state until another command or reboot.

Reflash the button node and restart Python to enable this feature. The existing
bridge already supports the LED operation; no bridge protocol change is needed.
The separate `remoteMultiButton` sketch keeps its existing behavior.
