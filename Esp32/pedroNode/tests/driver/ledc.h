#pragma once
constexpr int ESP_OK=0,LEDC_HIGH_SPEED_MODE=0,LEDC_TIMER_0=0,LEDC_TIMER_16_BIT=16,LEDC_AUTO_CLK=0,LEDC_INTR_DISABLE=0;
enum ledc_channel_t {LEDC_CHANNEL_0=0,LEDC_CHANNEL_1=1};
struct ledc_timer_config_t {int speed_mode,timer_num,duty_resolution,freq_hz,clk_cfg;};
struct ledc_channel_config_t {int gpio_num,speed_mode,channel,timer_sel,intr_type;};
inline int duties[2]={};
inline int ledc_set_duty(int,int channel,int duty){duties[channel]=duty;return ESP_OK;}
inline int ledc_update_duty(int,int){return ESP_OK;}
inline int ledc_timer_config(ledc_timer_config_t*){return ESP_OK;}
inline int ledc_channel_config(ledc_channel_config_t*){return ESP_OK;}
