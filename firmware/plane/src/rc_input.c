#include "rc_input.h"

#include <string.h>

#include "hardware/gpio.h"
#include "hardware/uart.h"
#include "pico/stdlib.h"
#include "pico/time.h"

#include "config.h"

#define SBUS_FRAME_LEN 25
#define SBUS_HEADER    0x0F
#define SBUS_FLAG_FAILSAFE 0x08
// A gap this long means the next byte starts a new frame.
#define SBUS_GAP_US 2000

// ---------------------------------------------------------------- SBUS ------

static uint8_t  s_sbus_buf[SBUS_FRAME_LEN];
static uint8_t  s_sbus_index;
static uint32_t s_sbus_last_byte_us;
static uint16_t s_sbus_us[RC_MAX_CHANNELS];
static uint32_t s_sbus_last_frame_ms;
static uint32_t s_sbus_frames;

static void sbus_decode(const uint8_t *frame) {
    if (frame[23] & SBUS_FLAG_FAILSAFE) {
        return;  // receiver lost the transmitter; keep the last good values
    }

    // 16 channels of 11 bits, packed LSB first across bytes 1..22.
    uint32_t bitpos = 0;
    for (uint8_t ch = 0; ch < RC_MAX_CHANNELS; ch++) {
        uint16_t raw = 0;
        for (uint8_t b = 0; b < 11; b++) {
            if (frame[1 + (bitpos >> 3)] & (1u << (bitpos & 7))) {
                raw |= (uint16_t)(1u << b);
            }
            bitpos++;
        }
        // Inverse of the scaling the ground station applies: 172 -> 1000 us,
        // 1811 -> 2000 us.
        int32_t us = 1000 + ((int32_t)raw - 172) * 1000 / 1639;
        if (us < 500) us = 500;
        if (us > 2500) us = 2500;
        s_sbus_us[ch] = (uint16_t)us;
    }
    s_sbus_last_frame_ms = to_ms_since_boot(get_absolute_time());
    s_sbus_frames++;
}

static void sbus_poll(void) {
    while (uart_is_readable(SBUS_UART)) {
        uint8_t byte = uart_getc(SBUS_UART);
        uint32_t now = time_us_32();

        if (now - s_sbus_last_byte_us > SBUS_GAP_US) {
            s_sbus_index = 0;   // frame gap: resynchronise
        }
        s_sbus_last_byte_us = now;

        if (s_sbus_index == 0 && byte != SBUS_HEADER) {
            continue;
        }
        s_sbus_buf[s_sbus_index++] = byte;
        if (s_sbus_index == SBUS_FRAME_LEN) {
            s_sbus_index = 0;
            sbus_decode(s_sbus_buf);
        }
    }
}

// ---------------------------------------------------------------- public ----

void rc_input_init(void) {
    memset(s_sbus_us, 0, sizeof(s_sbus_us));
    for (uint8_t i = 0; i < RC_MAX_CHANNELS; i++) {
        s_sbus_us[i] = (RC_MIN_US + RC_MAX_US) / 2;
    }

    // SBUS is an inverted UART, so invert the pin and let the hardware do
    // 100000 baud 8E2 -- no PIO needed on the receiving side.
    uart_init(SBUS_UART, 100000);
    gpio_set_function(SBUS_RX_PIN, GPIO_FUNC_UART);
    gpio_set_inover(SBUS_RX_PIN, GPIO_OVERRIDE_INVERT);
    // Pull the pad down explicitly. Inverted, that is the idle level, so an
    // unplugged receiver reads as a quiet line instead of a stream of framing
    // errors. The RP2040 happens to reset its pads this way, but relying on
    // that would make an external pull-up on this line silently fatal.
    gpio_pull_down(SBUS_RX_PIN);
    uart_set_format(SBUS_UART, 8, 2, UART_PARITY_EVEN);
    uart_set_fifo_enabled(SBUS_UART, true);
}

void rc_input_poll(rc_state_t *out) {
    sbus_poll();

    uint32_t now_ms = to_ms_since_boot(get_absolute_time());

    if (now_ms - s_sbus_last_frame_ms < RC_TIMEOUT_MS && s_sbus_last_frame_ms != 0) {
        memcpy(out->channel_us, s_sbus_us, sizeof(s_sbus_us));
        out->channel_count = RC_MAX_CHANNELS;
        out->source = RC_SOURCE_SBUS;
        out->valid = true;
        out->frames = s_sbus_frames;
        return;
    }

    // Nothing fresh. Report the link as dead rather than holding the last
    // values -- the caller runs its failsafe pattern on that.
    for (uint8_t i = 0; i < RC_MAX_CHANNELS; i++) {
        out->channel_us[i] = RC_MIN_US;
    }
    out->channel_count = 0;
    out->source = RC_SOURCE_NONE;
    out->valid = false;
    out->frames = s_sbus_frames;
}

uint16_t rc_channel_us(const rc_state_t *state, uint8_t channel) {
    if (channel == 0 || channel > state->channel_count) {
        return RC_MIN_US;
    }
    return state->channel_us[channel - 1];
}
