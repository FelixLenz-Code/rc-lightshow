// Per-model configuration for the airborne light controller.
//
// This is the file you edit for each aircraft: how many LEDs, which receiver
// channels carry the show data, and where the navigation lights sit.

#ifndef PLANE_CONFIG_H
#define PLANE_CONFIG_H

// ---------------------------------------------------------------- pixels ---

#define LED_PIN       0     // WS2812 data, through a 74AHCT125 level shifter
#define LED_COUNT     60
#define RENDER_HZ     200   // effect update rate, independent of the RC rate

// Global ceiling on brightness, 0..255. Keeps the current draw and the pilot's
// night vision in check; the show dimmer scales below this.
#define MAX_BRIGHTNESS 200

// ------------------------------------------------------- navigation lights -
//
// Drawn after every effect, so they are always on and always the same colour.
// The pilot needs them to see the aircraft's attitude -- do not fold them into
// the show. Set NAV_COUNT to 0 if this model carries separate nav lights.

#define NAV_COUNT 3
#define NAV_LIGHTS { \
    {0,           255,   0,   0},  /* left wingtip, red   */ \
    {LED_COUNT/2,   0, 255,   0},  /* right wingtip, green */ \
    {LED_COUNT-1, 255, 255, 255},  /* tail, white         */ \
}

// ------------------------------------------------------------- RC input ----
//
// SBUS is preferred: one wire carries all 16 channels, so several models can
// share one transmitter. PWM is the fallback for receivers without SBUS.
// Both are read; SBUS wins whenever its frames are fresh.

#define SBUS_UART      uart1
#define SBUS_RX_PIN    5

// First show channel, counted from 1 as the transmitter shows it. A model at
// tx_offset 4 in show.yaml uses RC_BASE_CHANNEL 5.
#define RC_BASE_CHANNEL 1

// Four PWM inputs, used only when no SBUS frames arrive.
#define PWM_PINS {10, 11, 12, 13}
#define PWM_COUNT 4

// Channel range, matching min_us/max_us in show.yaml.
#define RC_MIN_US 1000
#define RC_MAX_US 2000

// Number of cue steps; must match `quantize` on the cue channel.
#define CUE_STEPS 32

// No valid RC data for this long -> failsafe pattern.
#define RC_TIMEOUT_MS 500

#endif // PLANE_CONFIG_H
