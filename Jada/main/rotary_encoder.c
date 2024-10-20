#include "rotary_encoder.h"
#include "esp_log.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

static const char *TAG = "rotary_encoder";

#define ROTARY_ENCODER_A_GPIO CONFIG_ROT_ENC_A_GPIO
#define ROTARY_ENCODER_B_GPIO CONFIG_ROT_ENC_B_GPIO

static volatile int encoder_value = 0;
static volatile int last_a = 0;
static volatile int last_b = 0;

static QueueHandle_t encoder_event_queue;

static void IRAM_ATTR gpio_isr_handler(void* arg)
{
    uint32_t gpio_num = (uint32_t) arg;
    xQueueSendFromISR(encoder_event_queue, &gpio_num, NULL);
}

static void encoder_task(void* arg)
{
    uint32_t gpio_num;
    while(1) {
        if(xQueueReceive(encoder_event_queue, &gpio_num, portMAX_DELAY)) {
            int a = gpio_get_level(ROTARY_ENCODER_A_GPIO);
            int b = gpio_get_level(ROTARY_ENCODER_B_GPIO);

            if (gpio_num == ROTARY_ENCODER_A_GPIO) {
                if (a != last_a) {
                    if (b != a) {
                        encoder_value++;
                    } else {
                        encoder_value--;
                    }
                }
            } else {
                if (b != last_b) {
                    if (a == b) {
                        encoder_value++;
                    } else {
                        encoder_value--;
                    }
                }
            }

            last_a = a;
            last_b = b;

            ESP_LOGI(TAG, "Encoder value: %d", encoder_value);
        }
    }
}

esp_err_t rotary_encoder_init(int gpio_a, int gpio_b)
{
    ESP_LOGI(TAG, "Initializing rotary encoder");

    gpio_config_t io_conf = {
        .intr_type = GPIO_INTR_ANYEDGE,
        .mode = GPIO_MODE_INPUT,
        .pin_bit_mask = (1ULL << gpio_a) | (1ULL << gpio_b),
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
    };
    gpio_config(&io_conf);

    encoder_event_queue = xQueueCreate(10, sizeof(uint32_t));
    xTaskCreate(encoder_task, "encoder_task", 2048, NULL, 10, NULL);

    gpio_install_isr_service(0);
    gpio_isr_handler_add(gpio_a, gpio_isr_handler, (void*) gpio_a);
    gpio_isr_handler_add(gpio_b, gpio_isr_handler, (void*) gpio_b);

    ESP_LOGI(TAG, "Rotary encoder initialization complete");
    return ESP_OK;
}

int rotary_encoder_get_count(void)
{
    return encoder_value;
}

bool rotary_encoder_get_event(int *count, TickType_t ticks_to_wait)
{
    *count = encoder_value;
    return true;
}
