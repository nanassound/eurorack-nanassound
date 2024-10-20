/*
 * SPDX-FileCopyrightText: 2021-2022 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: CC0-1.0
 */

#include "lvgl.h"
#include "lcd_menu.h"
#include "icon_piano.c"
#include "icon_metronome.c"

void scale_selector(lv_disp_t *disp)
{
    lv_obj_t *scr = lv_disp_get_scr_act(disp);

    // Piano icon
    lv_obj_t *piano_icon = lv_img_create(scr);
    lv_img_set_src(piano_icon, &grand_piano);
    lv_obj_align(piano_icon, LV_ALIGN_LEFT_MID, 0, 0);

    // Label for scale selector
    lv_obj_t *scale_label = lv_label_create(scr);
    lv_obj_set_style_text_font(scale_label, &lv_font_montserrat_16, 0);
    lv_label_set_text(scale_label, "C");
    lv_obj_align(scale_label, LV_ALIGN_LEFT_MID, 40, 0);

    // Label for sub scale
    lv_obj_t *sub_scale_label = lv_label_create(scr);
    lv_obj_set_style_text_font(sub_scale_label, &lv_font_montserrat_12, 0);
    lv_label_set_text(sub_scale_label, "pentatonic");
    lv_obj_align(sub_scale_label, LV_ALIGN_LEFT_MID, 55, 0);
}

void tempo_selector(lv_disp_t *disp)
{
    lv_obj_t *scr = lv_disp_get_scr_act(disp);

    // Metronome icon
    lv_obj_t *metronome_icon = lv_img_create(scr);
    lv_img_set_src(metronome_icon, &icon_metronome);
    lv_obj_align(metronome_icon, LV_ALIGN_LEFT_MID, 0, 0);

    // Label for tempo selector
    lv_obj_t *tempo_label = lv_label_create(scr);
    lv_obj_set_style_text_font(tempo_label, &lv_font_montserrat_16, 0);
    lv_label_set_text(tempo_label, "120 BPM");
    lv_obj_align(tempo_label, LV_ALIGN_LEFT_MID, 40, 0);
}