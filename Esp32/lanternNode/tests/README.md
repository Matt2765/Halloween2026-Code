# Native lantern behavior checks

This harness includes the actual sketch with fake radio/GPIO/PWM backends.
It checks timing and command/state behavior without physical ESP32 hardware.
It does not validate real radio transport, lamp electronics or GPIO wiring.

From the repository root with a C++17 compiler:

```powershell
g++ -std=c++17 -IEsp32/lanternNode/tests Esp32/lanternNode/tests/check.cpp -o .tools/lantern-check.exe
& .tools/lantern-check.exe
```

The repository's local verification compiler can be substituted with
`.tools/zig-x86_64-windows-0.14.1/zig.exe c++`.
The `tests` folder is excluded from Arduino sketch source compilation.
