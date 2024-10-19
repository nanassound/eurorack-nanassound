#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_err.h"
#include "esp_log.h"
#include "lcd.h"
#include "esp_lvgl_port.h"
static const char *TAG = "main";

extern void tempo_selector(lv_disp_t *disp);

void app_main(void)
{
    ESP_LOGI(TAG, "Initializing LCD");
    ESP_ERROR_CHECK(lcd_open());

    lv_disp_t *disp = lcd_get_disp();

    ESP_LOGI(TAG, "Display LVGL Scroll Text");
    if (lvgl_port_lock(0)) {
        tempo_selector(disp);
        lvgl_port_unlock();
    }

    // Main application loop
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(10));
        // Add your main application logic here
    }

    // Cleanup (this part will never be reached in this example)
    ESP_LOGI(TAG, "Closing LCD");
    ESP_ERROR_CHECK(lcd_close());
}
