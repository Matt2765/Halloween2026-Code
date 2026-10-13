# Native dropdown behavior checks

Includes the actual sketch and wire codec with fake GPIO, PWM, preferences and
radio backends. Requires a C++17 compiler; no hardware is accessed.

```powershell
g++ -std=c++17 -IEsp32/dropdownNode/tests Esp32/dropdownNode/tests/check.cpp -o .tools/dropdown-check.exe
& .tools/dropdown-check.exe
python -m unittest discover -s MainCode/tests -p '*rsm*.py' -v
```

Tests cover the C3's active-low LED output, contact
bounce, held/released heartbeats, initial settling, independent LED and servo
commands, persisted defaults, invalid commands, wire validation and independent
command ordering. Physical radio, GPIO wiring and motion require bench checks.
