cmake_minimum_required(VERSION 3.13)

# Pull in the SDK; PICO_SDK_PATH must point at a pico-sdk checkout.
include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)

project(lightshow_tx C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(lightshow_tx
    src/main.c
    src/link.c
    src/ports.c
    src/crc16.c
)

pico_generate_pio_header(lightshow_tx ${CMAKE_CURRENT_LIST_DIR}/src/ppm.pio)
pico_generate_pio_header(lightshow_tx ${CMAKE_CURRENT_LIST_DIR}/src/sbus.pio)

target_include_directories(lightshow_tx PRIVATE src)

# Our own sources only -- the SDK is not warning clean and is not our business.
target_compile_options(lightshow_tx PRIVATE -Wall -Wextra)

target_link_libraries(lightshow_tx
    pico_stdlib
    hardware_pio
    hardware_dma
    hardware_clocks
)

# Binary protocol on USB, debug console on the UART pins.
pico_enable_stdio_usb(lightshow_tx 1)
pico_enable_stdio_uart(lightshow_tx 0)

pico_add_extra_outputs(lightshow_tx)
