#pragma once
#include "HauntProtocol.h"
#include <driver/gpio.h>
namespace haunt {
// Light sleep preserves session, sequence and independent debounce state.
class Buttons {
  Radio radio_; Debounced inputs_[8];
  const int* pins_; const uint8_t* ids_; uint8_t count_;
  uint32_t debounce_,held_,lastHeld_=0,lastActive_=0;
  bool sleep_,initial_=true;
  uint32_t began_=0;
  void report(uint8_t i,bool edge) {
    auto p=radio_.make(BUTTON,BRIDGE_ID,2,edge);
    p.payload[0]=ids_[i]; p.payload[1]=inputs_[i].stable;
    if(!radio_.send(p)) radio_.diagnostic();
  }
public:
  bool begin(const char* id,const int* pins,const uint8_t* ids,uint8_t count,uint32_t debounce,uint32_t held,bool sleep) {
    if(count>8) return false;
    pins_=pins; ids_=ids; count_=count; debounce_=debounce; held_=held; sleep_=sleep;
    for(uint8_t i=0;i<count_;i++) { if(ids[i]<1||ids[i]>8) return false; pinMode(pins[i],INPUT_PULLUP); }
    lastActive_=began_=millis(); return radio_.begin(id,nullptr);
  }
  void tick() {
    radio_.poll(); uint32_t now=millis(); bool any=false;
    for(uint8_t i=0;i<count_;i++) {
      bool raw=digitalRead(pins_[i])==LOW;
      if(inputs_[i].sample(raw,now,debounce_)) { report(i,true); lastActive_=now; }
      any|=raw||inputs_[i].stable;
    }
    if(initial_ && now-began_>=debounce_) {
      initial_=false;
      for(uint8_t i=0;i<count_;i++) if(inputs_[i].raw==inputs_[i].stable) report(i,false);
    }
    if(any) {
      lastActive_=now;
      if(now-lastHeld_>=held_) {
        lastHeld_=now;
        for(uint8_t i=0;i<count_;i++) if(inputs_[i].stable) report(i,false);
      }
    }
    if(sleep_&&!any&&!radio_.busy()&&now-lastActive_>=500) {
      radio_.diagnostic(); delay(5);
      esp_wifi_stop();
      esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_ALL);
      for(uint8_t i=0;i<count_;i++) gpio_wakeup_enable(gpio_num_t(pins_[i]),GPIO_INTR_LOW_LEVEL);
      esp_sleep_enable_gpio_wakeup();
      esp_sleep_pd_config(ESP_PD_DOMAIN_RTC_PERIPH,ESP_PD_OPTION_ON);
      esp_light_sleep_start();
      esp_wifi_start(); esp_wifi_set_channel(CHANNEL,WIFI_SECOND_CHAN_NONE);
      lastActive_=millis();
    }
    delay(2);
  }
};
}
