# KRIDA 8CH on classic UNO

Upload `dimmerUno.ino` with board **Arduino Uno**. Keep `Schedule.h` and `Demo.h`
in this folder. SYNC is D2; CH1..8 are D3..D10. Serial is 115200 baud.
All channels start OFF; 100 uses the tested 730 us full-brightness endpoint.

This replaces the single-channel RBDdimmer sketch. No external libraries are
needed. Python's existing `dim(value)` calls still control CH1; add `channel=2`
through `8` for other outputs. Upload before starting the updated controller.

See [setup and Python usage](../USER_GUIDE.md#8-dimmer-controller-guide) and
[scheduler details and demos](../dimmerKridaTest/README.md).
The three sketch copies are checked for equality by `tests/test_dimmer_controller.py`.
