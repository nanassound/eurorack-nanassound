// main.cpp
#include <stdio.h>
#include "pico/stdlib.h"
#include "FreeRTOS.h"
#include "task.h"

// Task to print "Hello World"
void hello_task(void *params) {
    while (true) {
        printf("Hello World\n");
        vTaskDelay(pdMS_TO_TICKS(1000));  // Delay for 1000 ms
    }
}

int main() {
    stdio_init_all();

    // Create FreeRTOS task
    xTaskCreate(hello_task, "Hello Task", 256, NULL, 1, NULL);

    // Start the scheduler
    vTaskStartScheduler();

    // Should never reach here
    while (true) {}
    return 0;
}