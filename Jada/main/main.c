#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_err.h"
#include "esp_log.h"
#include "lcd.h"
#include "lcd_menu.h"
#include "esp_lvgl_port.h"
#include "rotary_encoder.h"

static const char *TAG = "main";

#define ROT_ENC_A_GPIO CONFIG_ROT_ENC_A_GPIO
#define ROT_ENC_B_GPIO CONFIG_ROT_ENC_B_GPIO

// Define an enum for menu states
typedef enum {
    MENU_TEMPO,
    MENU_SCALE
} menu_state_t;

// Global variable to keep track of the current menu state
static menu_state_t current_menu = MENU_TEMPO;

// Function prototypes
void rotary_encoder_task(void *pvParameters);
void update_menu(lv_disp_t *disp);

void app_main(void)
{
    ESP_LOGI(TAG, "Initializing LCD");
    ESP_ERROR_CHECK(lcd_open());

    lv_disp_t *disp = lcd_get_disp();

    ESP_LOGI(TAG, "Initializing rotary encoder");
    ESP_ERROR_CHECK(rotary_encoder_init(ROT_ENC_A_GPIO, ROT_ENC_B_GPIO));

    // Create a task for handling rotary encoder events
    xTaskCreate(rotary_encoder_task, "rotary_encoder_task", 2048, (void*)disp, 5, NULL);

    // Initial menu display
    update_menu(disp);

    // Main loop (can be used for other tasks if needed)
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(1000));  // Delay for 1 second
    }

    // Cleanup (this part will never be reached in this example)
    ESP_LOGI(TAG, "Closing LCD");
    ESP_ERROR_CHECK(lcd_close());
}

void rotary_encoder_task(void *pvParameters)
{
    lv_disp_t *disp = (lv_disp_t *)pvParameters;
    int last_count = 0;

    while (1) {
        int count = rotary_encoder_get_count();
        
        if (count != last_count) {
            ESP_LOGI(TAG, "Rotary encoder count changed, new count: %d", count);
            
            // Toggle menu state
            current_menu = (current_menu == MENU_TEMPO) ? MENU_SCALE : MENU_TEMPO;
            
            // Update the menu
            update_menu(disp);
            
            last_count = count;
        }

        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

void update_menu(lv_disp_t *disp)
{
    if (lvgl_port_lock(0)) {
        // Clear the screen
        lv_obj_t *scr = lv_disp_get_scr_act(disp);
        lv_obj_clean(scr);

        // Small delay to ensure screen is cleared
        vTaskDelay(pdMS_TO_TICKS(10));

        if (current_menu == MENU_TEMPO) {
            ESP_LOGI(TAG, "Displaying Tempo Selector");
            tempo_selector(disp);
        } else {
            ESP_LOGI(TAG, "Displaying Scale Selector");
            scale_selector(disp);
        }
        lvgl_port_unlock();
    }
}
