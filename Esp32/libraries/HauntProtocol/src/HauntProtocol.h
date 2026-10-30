#pragma once
#include "HauntWire.h"
#include "HauntExtender.h"
#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_idf_version.h>
#include <Preferences.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
namespace haunt {
struct Received {
  Packet packet; uint8_t mac[6]; uint32_t rxMs=0;
  uint8_t hops=0,floodMac[6]={}; uint32_t floodSession=0,floodSequence=0;
};
struct Pending { bool used=false; Packet packet; uint32_t began=0, next=0; uint8_t attempts=0; };
struct Counters { uint32_t drops=0,highWater=0,retries=0,unconfirmed=0,duplicates=0,malformed=0,sendErrors=0,gaps=0,conflicts=0; };
class Radio {
public:
  using Handler=Code (*)(const Received&);
  using Result=void (*)(const Packet&,Code,uint32_t);
  Registry registry; Counters stats;
  uint32_t session=0,sequence=0;
  bool begin(const char* id, Handler handler, Result result=nullptr);
  void poll();
  Packet make(Type type,const char* destination,uint8_t length,bool reliable=false);
  bool send(const Packet& p);
  void cancel(const char* destination=nullptr,Code why=SUPERSEDED,uint8_t operation=0,int pin=-1);
  bool busy() const;
  void diagnostic();
  void enableExtender() { extender_=true; } // Call before begin(); endpoints need no setup change.
  uint32_t forwardedPackets=0,forwardFailures=0;
private:
  char id_[16]={}; Handler handler_=nullptr; Result result_=nullptr;
  QueueHandle_t urgent_=nullptr,telemetry_=nullptr;
  QueueHandle_t forwardUrgent_=nullptr,forwardTelemetry_=nullptr;
  bool extender_=false;
  uint8_t localMac_[6]={}; uint32_t floodSequence_=0;
  ExtenderSeen extenderSeen_;
  Pending pending_[MAX_PENDING]; Receipts receipts_;
  uint32_t callbackDrops_=0,callbackMalformed_=0,callbackHigh_=0;
  static Radio* active_;
  static void receive(const uint8_t*,const uint8_t*,int);
#if ESP_IDF_VERSION_MAJOR >= 5
  static void callback(const esp_now_recv_info_t* info,const uint8_t* data,int n) { if(info) receive(info->src_addr,data,n); }
#else
  static void callback(const uint8_t* mac,const uint8_t* data,int n) { receive(mac,data,n); }
#endif
  bool transmit(const Packet& p);
  void forward(const Received& r);
  void ack(const Packet& p,Code code);
  void process(const Received& r);
};
}
