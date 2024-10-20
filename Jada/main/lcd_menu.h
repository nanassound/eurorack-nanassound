#ifndef LCD_MENU_H
#define LCD_MENU_H

#include "lvgl.h"

// Function prototypes
void scale_selector(lv_disp_t *disp);
void tempo_selector(lv_disp_t *disp);

// Font declarations
LV_FONT_DECLARE(lv_font_montserrat_12);
LV_FONT_DECLARE(lv_font_montserrat_14);
LV_FONT_DECLARE(lv_font_montserrat_16);

#endif // LCD_MENU_H

