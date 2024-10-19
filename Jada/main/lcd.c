#include "lcd.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_err.h"
#include "esp_log.h"
#include "driver/i2c_master.h"
#include "esp_lvgl_port.h"
#include "lvgl.h"

#if CONFIG_EXAMPLE_LCD_CONTROLLER_SH1107
#include "esp_lcd_sh1107.h"
#else
#include "esp_lcd_panel_vendor.h"
#endif

static const char *TAG = "lcd";

// LCD configuration
#define I2C_BUS_PORT  0
#define EXAMPLE_LCD_PIXEL_CLOCK_HZ    (400 * 1000)
#define EXAMPLE_PIN_NUM_SDA           6
#define EXAMPLE_PIN_NUM_SCL           7
#define EXAMPLE_PIN_NUM_RST           -1
#define EXAMPLE_I2C_HW_ADDR           0x3C

#if CONFIG_EXAMPLE_LCD_CONTROLLER_SSD1306
#define EXAMPLE_LCD_H_RES              128
#define EXAMPLE_LCD_V_RES              32
#elif CONFIG_EXAMPLE_LCD_CONTROLLER_SH1107
#define EXAMPLE_LCD_H_RES              64
#define EXAMPLE_LCD_V_RES              128
#endif

#define EXAMPLE_LCD_CMD_BITS           8
#define EXAMPLE_LCD_PARAM_BITS         8

// LCD handle structure
typedef struct {
    i2c_master_bus_handle_t i2c_bus;
    esp_lcd_panel_io_handle_t io_handle;
    esp_lcd_panel_handle_t panel_handle;
    lv_disp_t *disp;
} lcd_handle_t;

static lcd_handle_t lcd_handle;

esp_err_t lcd_open(void)
{
    ESP_LOGI(TAG, "Initialize I2C bus");
    i2c_master_bus_config_t bus_config = {
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .i2c_port = I2C_BUS_PORT,
        .sda_io_num = EXAMPLE_PIN_NUM_SDA,
        .scl_io_num = EXAMPLE_PIN_NUM_SCL,
        .flags.enable_internal_pullup = true,
    };
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_config, &lcd_handle.i2c_bus));

    ESP_LOGI(TAG, "Install panel IO");
    esp_lcd_panel_io_i2c_config_t io_config = {
        .dev_addr = EXAMPLE_I2C_HW_ADDR,
        .scl_speed_hz = EXAMPLE_LCD_PIXEL_CLOCK_HZ,
        .control_phase_bytes = 1,
        .lcd_cmd_bits = EXAMPLE_LCD_CMD_BITS,
        .lcd_param_bits = EXAMPLE_LCD_CMD_BITS,
#if CONFIG_EXAMPLE_LCD_CONTROLLER_SSD1306
        .dc_bit_offset = 6,
#elif CONFIG_EXAMPLE_LCD_CONTROLLER_SH1107
        .dc_bit_offset = 0,
        .flags = {
            .disable_control_phase = 1,
        }
#endif
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c(lcd_handle.i2c_bus, &io_config, &lcd_handle.io_handle));

    ESP_LOGI(TAG, "Install LCD panel driver");
    esp_lcd_panel_dev_config_t panel_config = {
        .bits_per_pixel = 1,
        .reset_gpio_num = EXAMPLE_PIN_NUM_RST,
    };
#if CONFIG_EXAMPLE_LCD_CONTROLLER_SSD1306
    esp_lcd_panel_ssd1306_config_t ssd1306_config = {
        .height = EXAMPLE_LCD_V_RES,
    };
    panel_config.vendor_config = &ssd1306_config;
    ESP_ERROR_CHECK(esp_lcd_new_panel_ssd1306(lcd_handle.io_handle, &panel_config, &lcd_handle.panel_handle));
#elif CONFIG_EXAMPLE_LCD_CONTROLLER_SH1107
    ESP_ERROR_CHECK(esp_lcd_new_panel_sh1107(lcd_handle.io_handle, &panel_config, &lcd_handle.panel_handle));
#endif

    ESP_ERROR_CHECK(esp_lcd_panel_reset(lcd_handle.panel_handle));
    ESP_ERROR_CHECK(esp_lcd_panel_init(lcd_handle.panel_handle));
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(lcd_handle.panel_handle, true));

#if CONFIG_EXAMPLE_LCD_CONTROLLER_SH1107
    ESP_ERROR_CHECK(esp_lcd_panel_invert_color(lcd_handle.panel_handle, true));
#endif

    ESP_LOGI(TAG, "Initialize LVGL");
    const lvgl_port_cfg_t lvgl_cfg = ESP_LVGL_PORT_INIT_CONFIG();
    lvgl_port_init(&lvgl_cfg);

    const lvgl_port_display_cfg_t disp_cfg = {
        .io_handle = lcd_handle.io_handle,
        .panel_handle = lcd_handle.panel_handle,
        .buffer_size = EXAMPLE_LCD_H_RES * EXAMPLE_LCD_V_RES,
        .double_buffer = true,
        .hres = EXAMPLE_LCD_H_RES,
        .vres = EXAMPLE_LCD_V_RES,
        .monochrome = true,
        .rotation = {
            .swap_xy = false,
            .mirror_x = false,
            .mirror_y = false,
        }
    };
    lcd_handle.disp = lvgl_port_add_disp(&disp_cfg);

    lv_disp_set_rotation(lcd_handle.disp, LV_DISP_ROT_NONE);

    return ESP_OK;
}

esp_err_t lcd_close(void)
{
    // Implement cleanup and deinitialization here
    // For example:
    // lvgl_port_remove_disp(lcd_handle.disp);
    // esp_lcd_panel_del(lcd_handle.panel_handle);
    // esp_lcd_panel_io_del(lcd_handle.io_handle);
    // i2c_del_master_bus(lcd_handle.i2c_bus);
    return ESP_OK;
}

esp_err_t lcd_write(const void *buf, size_t size)
{
    if (lvgl_port_lock(0)) {
        // Implement your write logic here
        // For example, you might want to update the LVGL display
        // with the content of buf
        
        lvgl_port_unlock();
    }
    return ESP_OK;
}

esp_err_t lcd_read(void *buf, size_t size)
{
    // Implement read functionality if needed
    return ESP_OK;
}

lv_disp_t *lcd_get_disp(void)
{
    return lcd_handle.disp;
}

