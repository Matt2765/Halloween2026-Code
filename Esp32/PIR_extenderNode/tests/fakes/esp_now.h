#pragma once
#include "WiFi.h"
struct esp_now_peer_info_t {uint8_t peer_addr[6]={};int channel=0,ifidx=0;};
struct esp_now_recv_info_t {const uint8_t* src_addr;};
struct Transmission {std::vector<uint8_t> bytes;};
inline std::vector<Transmission> sent;
inline int esp_now_init(){return ESP_OK;}
inline int esp_now_add_peer(const esp_now_peer_info_t*){return ESP_OK;}
template<class T> int esp_now_register_recv_cb(T){return ESP_OK;}
inline int esp_now_send(const uint8_t*,const uint8_t* bytes,size_t n){sent.push_back({{bytes,bytes+n}});return ESP_OK;}
