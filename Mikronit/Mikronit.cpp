#include <stdio.h>
#include <math.h>
#include <stdlib.h>
#include <time.h>
#include "pico-ssd1306/ssd1306.h"
#include "pico-ssd1306/textRenderer/TextRenderer.h"
#include "pico/stdlib.h"
#include "pico/audio_i2s.h"
#include "pico/time.h"
#include "hardware/i2c.h"
#include <random>

// Add these declarations
#ifndef FAUSTFLOAT
#define FAUSTFLOAT float
#endif

using namespace pico_ssd1306;

class UI {
public:
    virtual ~UI() {}
    virtual void openVerticalBox(const char* label) {}
    virtual void closeBox() {}
    virtual void declare(FAUSTFLOAT* zone, const char* key, const char* value) {}
    virtual void addHorizontalSlider(const char* label, FAUSTFLOAT* zone, FAUSTFLOAT init, FAUSTFLOAT min, FAUSTFLOAT max, FAUSTFLOAT step) {}
};

// Minimal Meta implementation
class Meta {
public:
    virtual ~Meta() {}
    virtual void declare(const char* key, const char* value) {}
};

// Add this minimal dsp class definition
class dsp {
public:
    virtual ~dsp() {}
    virtual int getNumInputs() = 0;
    virtual int getNumOutputs() = 0;
    virtual void buildUserInterface(UI* ui_interface) = 0;
    virtual void init(int sample_rate) = 0;
    virtual void compute(int count, FAUSTFLOAT** inputs, FAUSTFLOAT** outputs) = 0;
};

// Now include the Faust-generated file
#include "osc.cpp"  // Include the Faust-generated file

// I2C defines
#define I2C_PORT i2c0
#define I2C_SDA 8
#define I2C_SCL 9

// Audio I2S defines
#define I2S_BCK_PIN 16
#define I2S_LCK_PIN 17
#define I2S_DIN_PIN 18

#define SINE_WAVE_TABLE_LEN 2048
#define SAMPLES_PER_BUFFER 256

static int16_t sine_wave_table[SINE_WAVE_TABLE_LEN];

struct audio_buffer_pool *init_audio() {
    static audio_format_t audio_format = {
        .sample_freq = 44100,
        .format = AUDIO_BUFFER_FORMAT_PCM_S16,
        .channel_count = 1,
    };

    static struct audio_buffer_format producer_format = {
        .format = &audio_format,
        .sample_stride = 2
    };

    struct audio_buffer_pool *producer_pool = audio_new_producer_pool(&producer_format, 3, SAMPLES_PER_BUFFER);

    struct audio_i2s_config config = {
        .data_pin = I2S_DIN_PIN,
        .clock_pin_base = I2S_BCK_PIN,
        .dma_channel = 0,
        .pio_sm = 0,
    };

    const struct audio_format *output_format = audio_i2s_setup(&audio_format, &config);
    if (!output_format) {
        panic("PicoAudio: Unable to open audio device.\n");
    }

    bool ok = audio_i2s_connect(producer_pool);
    assert(ok);
    audio_i2s_set_enabled(true);

    return producer_pool;
}

float random_float(float min, float max) {
    static std::random_device rd;
    static std::mt19937 gen(rd());
    std::uniform_real_distribution<> dis(min, max);
    return dis(gen);
}

int main() {
    stdio_init_all();
    
    // Initialize I2C for display
    i2c_init(i2c0, 400000);
    gpio_set_function(4, GPIO_FUNC_I2C);
    gpio_set_function(5, GPIO_FUNC_I2C);
    gpio_pull_up(4);
    gpio_pull_up(5);

    // Initialize display
    SSD1306 display = SSD1306(i2c0, 0x3C, Size::W128xH32);

    struct audio_buffer_pool *ap = init_audio();
    
    mydsp* dsp = new mydsp();
    dsp->init(44100);  // Initialize with your sample rate

    dsp->setVolume(-20.0f);  // Set volume to -10 dB

    float currentFreq = 440.0f;  // Start with A4 note
    float targetFreq = currentFreq;
    const float interpolationFactor = 0.01f;  // Adjust this for smoother/faster transitions

    int cycleCount = 0;
    const int DISPLAY_UPDATE_INTERVAL = 1000;  // Update display every 1000 cycles

    while (true) {
        struct audio_buffer *buffer = take_audio_buffer(ap, true);
        int16_t *samples = (int16_t *) buffer->buffer->bytes;
        
        // Gradually change frequency
        currentFreq = currentFreq + (targetFreq - currentFreq) * interpolationFactor;
        dsp->setFreq(currentFreq);

        // Occasionally set a new target frequency
        if (random_float(0, 1) < 0.01) {  // 1% chance each loop
            targetFreq = random_float(100.0f, 2000.0f);
            printf("New target frequency: %.2f Hz\n", targetFreq);
        }
        
        float* outputs[1] = { new float[buffer->max_sample_count] };
        dsp->compute(buffer->max_sample_count, NULL, outputs);

        for (uint i = 0; i < buffer->max_sample_count; i++) {
            samples[i] = (int16_t)(outputs[0][i] * 32767.0f);
        }

        delete[] outputs[0];

        buffer->sample_count = buffer->max_sample_count;
        give_audio_buffer(ap, buffer);

        // Update display less frequently
        if (++cycleCount >= DISPLAY_UPDATE_INTERVAL) {
            cycleCount = 0;
            display.clear();
            char freqStr[20];
            snprintf(freqStr, sizeof(freqStr), "Freq: %.2f Hz", currentFreq);
            drawText(&display, font_8x8, freqStr, 0, 0);
            display.sendBuffer();
            printf("Updated display with: %s\n", freqStr);
        }

        printf("Current frequency: %.2f Hz\n", currentFreq);
    }

    delete dsp;
    return 0;
}
