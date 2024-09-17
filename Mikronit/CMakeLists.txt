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

# Add any user requested libraries
target_link_libraries(Mikronit 
        hardware_i2c
        hardware_pio
        pico_ssd1306
        )

pico_add_extra_outputs(Mikronit)

add_dependencies(Mikronit pico_ssd1306)
