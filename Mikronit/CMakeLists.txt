# Generated Cmake Pico project file

cmake_minimum_required(VERSION 3.13)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Initialise pico_sdk from installed location
# (note this can come from environment, CMake cache etc)

# == DO NEVER EDIT THE NEXT LINES for Raspberry Pi Pico VS Code Extension to work ==
if(WIN32)
    set(USERHOME $ENV{USERPROFILE})
else()
    set(USERHOME $ENV{HOME})
endif()
set(sdkVersion 2.0.0)
set(toolchainVersion 13_2_Rel1)
set(picotoolVersion 2.0.0)
set(picoVscode ${USERHOME}/.pico-sdk/cmake/pico-vscode.cmake)
if (EXISTS ${picoVscode})
    include(${picoVscode})
endif()
# ====================================================================================
set(PICO_BOARD pico2 CACHE STRING "Board type")

# Pull in Raspberry Pi Pico SDK (must be before project)
set(PICO_EXTRAS_PATH ${CMAKE_CURRENT_LIST_DIR}/pico-extras)
include(pico_sdk_import.cmake)
include(pico-extras/external/pico_extras_import.cmake)

add_compile_definitions(PICO_RP2350=1)

set(PICO_PLATFORM rp2350)
set(FREERTOS_KERNEL_PATH ${CMAKE_CURRENT_SOURCE_DIR}/FreeRTOS-Kernel CACHE PATH "Path to FreeRTOS kernel")
set(FREERTOS_KERNEL_RP2040_RELATIVE_PATH "portable/ThirdParty/GCC/RP2040" CACHE STRING "")
include(FreeRTOS_Kernel_import.cmake)

project(Mikronit C CXX ASM)

# Initialise the Raspberry Pi Pico SDK
pico_sdk_init()

# Add executable. Default name is the project name, version 0.1

add_executable(Mikronit Mikronit.cpp )

pico_set_program_name(Mikronit "Mikronit")
pico_set_program_version(Mikronit "0.1")

# Generate PIO headers
pico_generate_pio_header(Mikronit ${CMAKE_CURRENT_LIST_DIR}/blink.pio)
pico_generate_pio_header(Mikronit ${CMAKE_CURRENT_LIST_DIR}/audio_i2s.pio)

# Modify the below lines to enable/disable output over UART/USB
pico_enable_stdio_uart(Mikronit 0)
pico_enable_stdio_usb(Mikronit 1)

# Add the standard library to the build
target_link_libraries(Mikronit
        pico_stdlib
        pico_multicore
        pico_async_context_freertos
        pico_audio_i2s
        hardware_dma
        hardware_irq
        hardware_sync
        hardware_gpio
)

# Add the standard include files to the build
target_include_directories(Mikronit PRIVATE
  ${CMAKE_CURRENT_LIST_DIR}
  ${CMAKE_CURRENT_LIST_DIR}/.. # for our common lwipopts or any other standard includes, if required
)

# OLED SSD1306 driver
add_subdirectory(pico-ssd1306)
message(STATUS "pico_ssd1306 target: ${pico_ssd1306}")

# Pico extras
add_subdirectory(pico-extras)

# FreeRTOS
# Create freertos_config target
add_library(freertos_config INTERFACE)

target_include_directories(freertos_config SYSTEM
    INTERFACE
        ${CMAKE_CURRENT_SOURCE_DIR}/freertos_config  # The directory containing FreeRTOSConfig.h
)

target_compile_definitions(freertos_config
    INTERFACE
        projCOVERAGE_TEST=0
)

# Set the FREERTOS_CONFIG variable
set(FREERTOS_CONFIG freertos_config CACHE STRING "")
set(FREERTOS_PORT GCC_ARM_CM33_NTZ_NONSECURE CACHE STRING "")
set(FREERTOS_PORTABLE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/FreeRTOS-Kernel/portable/ThirdParty/GCC/RP2040 CACHE STRING "")

# Now add FreeRTOS-Kernel subdirectory
add_subdirectory(FreeRTOS-Kernel)

# Include FreeRTOS headers
target_include_directories(${PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/include
    ${CMAKE_CURRENT_LIST_DIR}/FreeRTOS-Kernel/include
    ${CMAKE_CURRENT_LIST_DIR}/FreeRTOS-Kernel/portable/ThirdParty/GCC/RP2040
    )

# Add any user requested libraries
target_link_libraries(Mikronit
        freertos_config
        FreeRTOS-Kernel
        FreeRTOS-Kernel-Heap4
        hardware_i2c
        hardware_pio
        pico_ssd1306
)

target_compile_definitions(Mikronit PRIVATE
    configNUMBER_OF_CORES=2
)

if(PICO_CYW43_SUPPORTED)
    # For LED support on Pico W
    target_link_libraries(Mikronit PRIVATE
        pico_cyw43_arch_none
    )
endif()

pico_add_extra_outputs(Mikronit)

add_dependencies(Mikronit pico_ssd1306)

add_compile_options(-mcpu=cortex-m33 -mthumb -mfloat-abi=hard -mfpu=fpv5-sp-d16)
add_link_options(-mcpu=cortex-m33 -mthumb -mfloat-abi=hard -mfpu=fpv5-sp-d16)
