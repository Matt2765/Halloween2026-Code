#pragma once
constexpr int LEDC_LOW_SPEED_MODE=0,LEDC_CHANNEL_0=0,LEDC_TIMER_0=0,LEDC_TIMER_8_BIT=8,LEDC_AUTO_CLK=0,LEDC_INTR_DISABLE=0;
struct ledc_timer_config_t {int speed_mode,timer_num,duty_resolution,freq_hz,clk_cfg;};
struct ledc_channel_config_t {int gpio_num,speed_mode,channel,timer_sel,intr_type;};
inline void ledc_set_duty(int,int,int){}
inline void ledc_update_duty(int,int){}
inline void ledc_timer_config(ledc_timer_config_t*){}
inline void ledc_channel_config(ledc_channel_config_t*){}

