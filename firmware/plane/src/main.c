// Airborne light controller.
//
// Reads four "data" channels from the receiver -- cue, hue, brightness and
// speed -- and generates the actual light pattern on board. The radio link only
// carries about 45 updates per second with roughly 6 usable bits per channel,
// which is plenty for fades and cue changes but not for strobes or chases, so
// anything fast is generated here.
//
// Navigation lights are drawn on top of every pattern and never switch off.

#include <stdio.h>

#include "hardware/pio.h"
#include "pico/stdlib.h"
#include "pico/time.h"

#include "config.h"
#include "effects.h"
#include "rc_decode.h"
#include "rc_input.h"
#include "ws2812.pio.h"

static rgb_t s_pixels[LED_COUNT];
static PIO s_pio = pio0;
static uint s_sm = 0;

static void ws2812_show(const rgb_t *pixels, uint16_t count) {
    for (uint16_t i = 0; i < count; i++) {
        // WS2812 wants GRB, left aligned in the 32 bit word.
        uint32_t grb = ((uint32_t)pixels[i].g << 16) | ((uint32_t)pixels[i].r << 8) |
                       (uint32_t)pixels[i].b;
        pio_sm_put_blocking(s_pio, s_sm, grb << 8u);
    }
}

#define decode_step(us, steps) rc_decode_step((us), RC_MIN_US, RC_MAX_US, (steps))
#define decode_u8(us)          rc_decode_u8((us), RC_MIN_US, RC_MAX_US)

int main(void) {
    stdio_init_all();

    uint offset = pio_add_program(s_pio, &ws2812_program);
    ws2812_program_init(s_pio, s_sm, offset, LED_PIN);

    effects_init();
    rc_input_init();

    rc_state_t rc = {0};
    show_state_t show = {0};
    absolute_time_t next = get_absolute_time();
    uint32_t last_log_ms = 0;

    while (true) {
        rc_input_poll(&rc);
        uint32_t now_ms = to_ms_since_boot(get_absolute_time());

        if (rc.valid) {
            // With SBUS the model sits at its configured offset inside the
            // 16 channel frame; with PWM the four wires are the four channels.
            uint8_t base = (rc.source == RC_SOURCE_SBUS) ? RC_BASE_CHANNEL : 1;
            show.cue = decode_step(rc_channel_us(&rc, base), CUE_STEPS);
            show.hue = decode_u8(rc_channel_us(&rc, base + 1));
            show.brightness = decode_u8(rc_channel_us(&rc, base + 2));
            show.param = decode_u8(rc_channel_us(&rc, base + 3));
            effects_render(&show, now_ms, s_pixels, LED_COUNT);
        } else {
            effects_render_failsafe(now_ms, s_pixels, LED_COUNT);
        }

        effects_apply_nav(s_pixels, LED_COUNT);
        ws2812_show(s_pixels, LED_COUNT);

        if (now_ms - last_log_ms >= 1000) {
            last_log_ms = now_ms;
            printf("src=%d cue=%u hue=%u bri=%u param=%u\n", (int)rc.source,
                   show.cue, show.hue, show.brightness, show.param);
        }

        next = delayed_by_us(next, 1000000 / RENDER_HZ);
        sleep_until(next);
    }
}
