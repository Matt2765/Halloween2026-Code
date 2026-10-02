# KRIDA 8CH on classic Nano

Upload `dimmerNano.ino` with board **Arduino Nano**, processor **ATmega328P**
(select **Old Bootloader** if needed for your board). Keep `Schedule.h` and
`Demo.h` in this folder. Requires the classic 16 MHz ATmega328P Nano.
SYNC is D2; CH1..8 are D3..D10. Serial is 115200 baud.

This replaces the old CTC scheduler with the tested event scheduler, including
overlapping pulses, zero-cross recovery and the calibrated 730 us full-on
endpoint. All channels start OFF. No external libraries are needed.

See [setup and Python usage](../USER_GUIDE.md#8-dimmer-controller-guide) and
[scheduler details and demos](../dimmerKridaTest/README.md).
The three sketch copies are checked for equality by `tests/test_dimmer_controller.py`.
