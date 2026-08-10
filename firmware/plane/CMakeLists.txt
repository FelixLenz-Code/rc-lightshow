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
    src/outputs.c
)

pico_generate_pio_header(lightshow_plane ${CMAKE_CURRENT_LIST_DIR}/src/ws2812.pio)

target_include_directories(lightshow_plane PRIVATE src ${CMAKE_CURRENT_LIST_DIR})

# Per-model header generated from show.yaml, e.g.
#   cmake -S firmware/plane -B build/plane-eule -DPLANE_CONFIG=generated/eule.h
# Without it, the documented example in src/config.h is used.
if(DEFINED PLANE_CONFIG)
    target_compile_definitions(lightshow_plane PRIVATE
        PLANE_CONFIG_HEADER="${PLANE_CONFIG}")

    # Name the image after the model. With several aircraft in the hangar, a
    # file called lightshow_plane.uf2 in four build directories is asking for
    # the wrong one to be flashed -- and the pin assignment differs per model.
    get_filename_component(PLANE_MODEL "${PLANE_CONFIG}" NAME_WE)
    set_target_properties(lightshow_plane PROPERTIES
        OUTPUT_NAME "lightshow_plane_${PLANE_MODEL}")
    message(STATUS "Plane configuration: ${PLANE_CONFIG} -> lightshow_plane_${PLANE_MODEL}.uf2")
else()
    message(STATUS "Plane configuration: built-in example from src/config.h")
endif()

# Our own sources only -- the SDK is not warning clean and is not our business.
target_compile_options(lightshow_plane PRIVATE -Wall -Wextra)

target_link_libraries(lightshow_plane
    pico_stdlib
    hardware_pio
    hardware_uart
    hardware_clocks
)

# Measurement build: dumps the raw microseconds of every RC frame, so the link
# can be characterised on the bench.
#
#   cmake -S firmware/plane -B build/plane-measure -DMEASURE=ON
#
# It also turns USB stdio back on. USB is off in the flight build because the
# port is unpowered in the air -- on a bench that does not apply, and it saves
# needing a USB-to-UART adapter for the console.
option(MEASURE "Build the link measurement firmware" OFF)

if(MEASURE)
    target_compile_definitions(lightshow_plane PRIVATE MEASURE_MODE=1)
    pico_enable_stdio_usb(lightshow_plane 1)
    pico_enable_stdio_uart(lightshow_plane 1)
    message(STATUS "Measurement mode: MEAS lines on USB and UART")
else()
    # Debug output on the UART pins; USB stays free (and unpowered in flight).
    pico_enable_stdio_usb(lightshow_plane 0)
    pico_enable_stdio_uart(lightshow_plane 1)
endif()

pico_add_extra_outputs(lightshow_plane)
