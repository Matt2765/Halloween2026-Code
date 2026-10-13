#pragma once
constexpr int ESP_OK=0,LEDC_LOW_SPEED_MODE=0,LEDC_TIMER_0=0,LEDC_TIMER_14_BIT=14,LEDC_AUTO_CLK=0,LEDC_INTR_DISABLE=0;
enum ledc_channel_t {LEDC_CHANNEL_0=0};
struct ledc_timer_config_t {int speed_mode,timer_num,duty_resolution,freq_hz,clk_cfg;};
struct ledc_channel_config_t {int gpio_num,speed_mode,channel,timer_sel,intr_type;};
inline int duty=0;
inline int ledc_set_duty(int,int,int value){duty=value;return ESP_OK;}
inline int ledc_update_duty(int,int){return ESP_OK;}
inline int ledc_timer_config(ledc_timer_config_t* timer){return timer->duty_resolution==14?ESP_OK:1;}
inline int ledc_channel_config(ledc_channel_config_t*){return ESP_OK;}
