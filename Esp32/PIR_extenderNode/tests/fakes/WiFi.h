#pragma once
constexpr int WIFI_STA=1,WIFI_IF_STA=0,WIFI_PS_NONE=0,WIFI_SECOND_CHAN_NONE=0,ESP_OK=0;
inline uint8_t fakeMac[6]={};
struct FakeWifi {void persistent(bool){} void mode(int){}};
inline FakeWifi WiFi;
