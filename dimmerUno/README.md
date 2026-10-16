# KRIDA 8CH on classic UNO

Upload `dimmerUno.ino` with board **Arduino Uno**. Keep `Schedule.h` and `Demo.h`
and `Glow.h` in this folder. SYNC is D2; CH1..8 are D3..D10. Serial is 115200 baud.
All channels start OFF; 100 uses the tested 730 us full-brightness endpoint.

`GLOW ch low_delay_us high_delay_us ramp_ms` repeats a locally timed ramp on
one channel. For Bathroom ambient glow, `GLOW 6 6871 6148 2500` runs 15% to
25% and back, taking 2.5 seconds per direction. The sketch updates firing
delay every 5 ms; Python sends only the start and stop commands. `SET` or
`DELAY` stops the glow on that channel, `ALL` stops every glow, and `OFF`,
`STOP`, and either demo stop every glow. Other channels hold their levels.
Upload this sketch before restarting Python to enable the local glow;
older firmware uses the Python ramp fallback.

This replaces the single-channel RBDdimmer sketch. No external libraries are
needed. Python's existing `dim(value)` calls still control CH1; add `channel=2`
through `8` for other outputs. Upload before starting the updated controller.

See [setup and Python usage](../USER_GUIDE.md#8-dimmer-controller-guide) and
[scheduler details and demos](../dimmerKridaTest/README.md).
The three sketch copies are checked for equality by `tests/test_dimmer_controller.py`.
