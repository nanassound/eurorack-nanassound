#include <stdio.h>
#include <math.h>
#include "pico/stdlib.h"
#include "pico-ssd1306/ssd1306.h"
#include "pico-ssd1306/textRenderer/TextRenderer.h"
#include "pico/audio_i2s.h"
#include "hardware/dma.h"
#include "hardware/i2c.h"
#include "hardware/irq.h"
#include "hardware/pio.h"
#include "hardware/uart.h"

// I2C defines
#define I2C_PORT i2c0
#define I2C_SDA 8
#define I2C_SCL 9

// Audio I2S defines
#define SAMPLE_RATE 44100
#define BUFFER_SIZE 1024
#define NUM_FREQUENCIES 3

// I2S pin configurations
#define I2S_BCK_PIN 16 // BCK is 16
#define I2S_LCK_PIN 17 // LCK is 17
#define I2S_DIN_PIN 18 // DIN is 18

// Sine wave frequencies
const float frequencies[NUM_FREQUENCIES] = {440.0f, 880.0f, 1320.0f};

using namespace pico_ssd1306;

#define VOLUME 1.0f // Volume control (0.0 to 1.0)

void fill_audio_buffer(int16_t *audio_buffer, SSD1306 *display) {
    int16_t amplitude = 32767 * VOLUME; // Max amplitude scaled by volume
    int period = SAMPLE_RATE / frequencies[0]; // Period of the square wave

    for (int i = 0; i < BUFFER_SIZE; i++) {
        if ((i / (period / 2)) % 2 == 0) {
            audio_buffer[i] = amplitude; // High part of the square wave
        } else {
            audio_buffer[i] = -amplitude; // Low part of the square wave
        }
    }

    // Debug: Print first few samples
    for (int i = 0; i < 10; i++) {
        printf("Sample %d: %d\n", i, audio_buffer[i]);
    }
}

int main() {
    stdio_init_all();

    // I2C Initialization
    i2c_init(I2C_PORT, 1000 * 1000);
    gpio_set_function(I2C_SDA, GPIO_FUNC_I2C);
    gpio_set_function(I2C_SCL, GPIO_FUNC_I2C);
    gpio_pull_up(I2C_SDA);
    gpio_pull_up(I2C_SCL);

    // Initialize OLED display
    SSD1306 display = SSD1306(I2C_PORT, 0x3C, Size::W128xH32);
    display.setOrientation(1);
    drawText(&display, font_8x8, "Nanas Sound", 0, 0);
    drawText(&display, font_12x16, "Synth WIP", 0, 16);
    display.sendBuffer();

    // Audio I2S setup
    audio_format_t audio_format = {
        .sample_freq = SAMPLE_RATE,
        .format = AUDIO_BUFFER_FORMAT_PCM_S16,
        .channel_count = 2,
    };

    audio_buffer_format_t audio_buffer_format = {
        .format = &audio_format,
        .sample_stride = static_cast<uint16_t>(sizeof(int16_t) * audio_format.channel_count),
    };

    audio_i2s_config_t config = {
        .data_pin = I2S_DIN_PIN,
        .clock_pin_base = I2S_BCK_PIN,
        .dma_channel = 0,
        .pio_sm = 0,
    };

    audio_i2s_setup(&audio_format, &config);

    // Create audio buffer structure
    mem_buffer_t audio_buffer_mem;
    audio_buffer_mem.size = BUFFER_SIZE * sizeof(int16_t);
    audio_buffer_mem.bytes = (uint8_t *)malloc(audio_buffer_mem.size);

    audio_buffer_t audio_buffer_struct = {
        .buffer = &audio_buffer_mem,
        .format = &audio_buffer_format,
        .sample_count = BUFFER_SIZE,
        .max_sample_count = BUFFER_SIZE,
        .user_data = 0,
        .next = NULL,
    };

    // Create producer and consumer pools
    audio_buffer_pool_t *producer_pool = audio_new_producer_pool(&audio_buffer_format, 4, BUFFER_SIZE);
    audio_buffer_pool_t *consumer_pool = audio_new_consumer_pool(&audio_buffer_format, 4, BUFFER_SIZE);

    audio_connection_t audio_connection = {
        .producer_pool_take = producer_pool_take_buffer_default,
        .producer_pool_give = producer_pool_give_buffer_default,
        .consumer_pool_take = consumer_pool_take_buffer_default,
        .consumer_pool_give = consumer_pool_give_buffer_default,
    };

    // Complete the connection
    audio_complete_connection(&audio_connection, producer_pool, consumer_pool);

    while (true) {
        // Check if there's a free buffer available
        audio_buffer_t *free_buffer = get_free_audio_buffer(audio_connection.producer_pool, false);
        if (free_buffer) {
            // Fill the audio buffer with samples
            fill_audio_buffer((int16_t *)audio_buffer_mem.bytes, &display);

            // Play the audio buffer
            give_audio_buffer(audio_connection.producer_pool, &audio_buffer_struct);

            // Return the free buffer to the pool
            queue_free_audio_buffer(audio_connection.producer_pool, free_buffer);
        } else {
            printf("Producer pool is full, cannot give audio buffer.\n");
            drawText(&display, font_12x16, "Buffer full", 0, 16);
            display.sendBuffer();
        }

        // Wait for the buffer to finish playing
        // Uncomment the following lines if you want to wait for the buffer to finish
        /*
        while (audio_buffer_struct.sample_count > 0) {
            sleep_ms(100); // Polling delay
        }
        */

        printf("Playing square wave at %0.1f Hz\n", frequencies[0]);

        // Debugging output
        display.clear();
        char buffer[50];
        snprintf(buffer, sizeof(buffer), "%0.1f Hz", frequencies[0]);
        drawText(&display, font_8x8, buffer, 0, 16);
        display.sendBuffer();

        sleep_ms(1000);
    }

    // Free allocated memory
    free(audio_buffer_mem.bytes);

    return 0;
}
