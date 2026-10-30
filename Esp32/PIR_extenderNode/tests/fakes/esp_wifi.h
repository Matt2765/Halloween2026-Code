#pragma once
#include "WiFi.h"
inline int esp_wifi_set_ps(int){return ESP_OK;}
inline int esp_wifi_set_channel(int,int){return ESP_OK;}
inline int esp_wifi_get_mac(int,uint8_t* mac){memcpy(mac,fakeMac,6);return ESP_OK;}
