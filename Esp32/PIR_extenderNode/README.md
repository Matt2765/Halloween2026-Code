# PIR + generic ESP-NOW extender

This sketch reports its HC-SR501 PIR exactly like `remotePIR` and relays **all
HauntProtocol device types** in both directions: sensor telemetry, commands,
acknowledgements and diagnostics. There is no MOSFET-only allowlist and no change
to Python device IDs or commands.

## Flashing for the current installation

Flash these three boards with the updated shared library:

1. The PIR board being converted: this sketch.
2. The COM6 USB bridge: `transceiver`.
3. MOSFET1: `mosfetNode`.

Other nodes can keep their firmware and talk directly to the bridge. Reflash an
additional node only when it needs to receive through an extender. Updating the
library on disk does not update a board that was already flashed. Stop Python
before uploading to its COM6 bridge. No boards are uploaded automatically.

Default settings are original ESP32/WROOM, `DEVICE_ID="PIR4"`, PIR OUT on GPIO13,
60-second warm-up and two-second status reports. Keep the replaced board's
unique PIR ID; never run two physical boards with the same ID. Additional
extenders need different PIR IDs. The radio stays awake continuously.

Put each extender where it can hear the preceding radio and the next radio.
Multiple extenders can provide coverage in separate areas or form a chain of
up to **three extender hops**. They must share the existing network and channel.
There is no pairing, route configuration or extra COM port on the PC.

## Delivery behavior

The extender wraps the original frame with its original source MAC and an
expiring flood identifier. Receiving endpoints unwrap it before their existing
identity, session, sequence and command checks. Direct and extended copies
therefore identify the same device; they do not create duplicate-ID conflicts
or execute the same command twice.

An extender forwards each flood once per route depth. A hop limit and bounded
duplicate cache prevent endless loops between overlapping extenders. A shorter
path may still be forwarded. Original sender retries create new floods, so a
lost relay transmission can recover; extenders do not acknowledge commands for
the destination, replay stored actions or run independent retry loops. Work
older than the existing 400 ms delivery lifetime is dropped. Transport queues
have fixed capacities and favor commands/ACKs over periodic telemetry.

All radios still share one channel, so extra extenders consume airtime and do
not guarantee range or delivery. Old firmware can ignore the new envelopes and
continue using direct frames; its malformed-packet counter may include envelopes.
Test placement with actual hardware, especially PIR freshness and door timing.

## Build

Some Arduino tools reject `+` in sketch names. Keep this requested source name,
but copy its `.ino` into a folder named `PIR_extenderNode` and rename the copy to
`PIR_extenderNode.ino` for those tools. Build for `esp32:esp32:esp32` with the
repository `Esp32/libraries` directory. The validated staging folder is
`.tools/PIR_extenderNode`.

From the repository root, after editing the source's PIR ID/pin:

```powershell
New-Item -ItemType Directory -Force .tools/PIR_extenderNode
Copy-Item 'Esp32/PIR+extenderNode/PIR+extenderNode.ino' .tools/PIR_extenderNode/PIR_extenderNode.ino
arduino-cli compile --fqbn esp32:esp32:esp32 --libraries Esp32/libraries .tools/PIR_extenderNode
```

The native transport harness exercises the actual shared `Radio` implementation
with fake radio/queue backends (no hardware):

```powershell
.tools/zig-x86_64-windows-0.14.1/zig.exe c++ -std=c++17 '-IEsp32/PIR+extenderNode/tests/fakes' -IEsp32/libraries/HauntProtocol/src 'Esp32/PIR+extenderNode/tests/check.cpp' -o .tools/extender-check.exe
.tools/extender-check.exe
```

USB diagnostics use 115200 baud and show PIR state, bridge ACK outcomes,
forwarded-frame count and forwarding failures. `SERIAL_DEBUG` controls these
node-local messages independently of Python's `house.DEBUG_INFO`.
