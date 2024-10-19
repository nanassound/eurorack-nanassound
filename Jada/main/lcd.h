#ifndef LCD_H
#define LCD_H

#include "esp_err.h"
#include "lvgl.h"

esp_err_t lcd_open(void);
esp_err_t lcd_close(void);
esp_err_t lcd_write(const void *buf, size_t size);
esp_err_t lcd_read(void *buf, size_t size);
lv_disp_t *lcd_get_disp(void);

#endif // LCD_H

