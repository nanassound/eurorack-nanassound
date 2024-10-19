#ifdef __has_include
    #if __has_include("lvgl.h")
        #ifndef LV_LVGL_H_INCLUDE_SIMPLE
            #define LV_LVGL_H_INCLUDE_SIMPLE
        #endif
    #endif
#endif

#if defined(LV_LVGL_H_INCLUDE_SIMPLE)
    #include "lvgl.h"
#else
    #include "lvgl/lvgl.h"
#endif


#ifndef LV_ATTRIBUTE_MEM_ALIGN
#define LV_ATTRIBUTE_MEM_ALIGN
#endif

#ifndef LV_ATTRIBUTE_IMG_GRAND_PIANO
#define LV_ATTRIBUTE_IMG_GRAND_PIANO
#endif

const LV_ATTRIBUTE_MEM_ALIGN LV_ATTRIBUTE_LARGE_CONST LV_ATTRIBUTE_IMG_GRAND_PIANO uint8_t grand_piano_map[] = {
  0x03, 0xf8, 0x00, 0x00, 
  0x03, 0xf8, 0x00, 0x00, 
  0x0c, 0x06, 0x00, 0x00, 
  0x08, 0x06, 0x00, 0x00, 
  0x30, 0x01, 0x80, 0x00, 
  0x20, 0x01, 0x80, 0x00, 
  0xc0, 0x00, 0x60, 0x00, 
  0xc0, 0x00, 0x60, 0x00, 
  0xc0, 0x00, 0x60, 0x00, 
  0xc0, 0x00, 0x10, 0x00, 
  0xc0, 0x00, 0x18, 0x00, 
  0xc0, 0x00, 0x07, 0xc0, 
  0xc0, 0x00, 0x07, 0xc0, 
  0xc0, 0x00, 0x00, 0x3c, 
  0xc0, 0x00, 0x00, 0x3c, 
  0xc0, 0x00, 0x00, 0x03, 
  0xc0, 0x00, 0x00, 0x03, 
  0xc0, 0x00, 0x00, 0x03, 
  0xc0, 0x00, 0x00, 0x03, 
  0xc0, 0x00, 0x00, 0x03, 
  0xc0, 0x00, 0x00, 0x03, 
  0xff, 0xff, 0xff, 0xff, 
  0xff, 0xff, 0xff, 0xff, 
  0xff, 0xff, 0xff, 0xff, 
  0xff, 0xff, 0xff, 0xff, 
  0xff, 0xff, 0xff, 0xff, 
  0xfd, 0xd9, 0x9b, 0xbf, 
  0xfc, 0x99, 0x99, 0x3f, 
  0xfc, 0x99, 0x99, 0x3f, 
  0xfc, 0x99, 0x99, 0x3f, 
  0x3f, 0xff, 0xff, 0xfc, 
  0x3f, 0xff, 0xff, 0xfc, 
};

const lv_img_dsc_t grand_piano = {
  .header.cf = LV_IMG_CF_ALPHA_1BIT,
  .header.always_zero = 0,
  .header.reserved = 0,
  .header.w = 32,
  .header.h = 32,
  .data_size = 128,
  .data = grand_piano_map,
};
