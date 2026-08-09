cmake_minimum_required(VERSION 3.13)

# Raspberry Pi Pico, same board as the ground station. Override with
# -DPICO_BOARD=<name> for a smaller variant, e.g. waveshare_rp2040_zero --
# the pin assignment in src/config.h is available on both.
if(NOT DEFINED PICO_BOARD)
    set(PICO_BOARD pico)
endif()

include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)

project(lightshow_plane C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(lightshow_plane
    src/main.c
    src/rc_input.c
    src/effects.c
)

pico_generate_pio_header(lightshow_plane ${CMAKE_CURRENT_LIST_DIR}/src/ws2812.pio)

target_include_directories(lightshow_plane PRIVATE src)

# Our own sources only -- the SDK is not warning clean and is not our business.
target_compile_options(lightshow_plane PRIVATE -Wall -Wextra)

target_link_libraries(lightshow_plane
    pico_stdlib
    hardware_pio
    hardware_uart
    hardware_clocks
)

# Debug output on the UART pins; USB stays free (and unpowered in flight).
pico_enable_stdio_usb(lightshow_plane 0)
pico_enable_stdio_uart(lightshow_plane 1)

pico_add_extra_outputs(lightshow_plane)
