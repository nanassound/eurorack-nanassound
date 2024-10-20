#ifndef ROTARY_ENCODER_H
#define ROTARY_ENCODER_H

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

esp_err_t rotary_encoder_init(int gpio_a, int gpio_b);
int rotary_encoder_get_count(void);
bool rotary_encoder_get_event(int *count, TickType_t ticks_to_wait);

#endif // ROTARY_ENCODER_H

