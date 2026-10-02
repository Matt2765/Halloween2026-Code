#pragma once
#include <stdint.h>
namespace haunt {
// Shared installation settings. Reflash every participating board when changed.
constexpr uint16_t NETWORK = 0x4848;
constexpr uint8_t VERSION = 1;
constexpr const char* FIRMWARE = "haunt-1.0.1";
constexpr const char* BRIDGE_ID = "BRIDGE";
constexpr uint8_t CHANNEL = 1;
constexpr uint32_t USB_BAUD = 921600;
constexpr uint8_t ATTEMPTS = 4; // total, including first send
constexpr uint32_t RETRY_MS = 50, JITTER_MS = 16;
constexpr uint32_t DELIVERY_LIFETIME_MS = 400;
constexpr uint8_t MAX_PENDING = 16, MAX_DEVICES = 64;
constexpr uint8_t BROADCAST_MAC[6] = {255,255,255,255,255,255};
}
