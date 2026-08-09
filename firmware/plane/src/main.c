// Airborne light controller.
//
// Reads four "data" channels per zone from the receiver -- cue, hue, brightness
// and speed -- and generates the actual light pattern on board. The radio link
// only carries about 45 updates per second with roughly 6 usable bits per
// channel, which is plenty for fades and cue changes but not for strobes or
// chases, so anything fast is generated here.
//
// Outputs are declared as tables in config.h: any number of WS2812 strips and
// up to eight switched relay outputs, grouped into zones.
//
// Navigation lights are drawn on top of every pattern and never switch off.

#include <stdio.h>

#include "pico/stdlib.h"
#include "pico/time.h"

#include "config.h"
#include "effects.h"
#include "outputs.h"
#include "rc_decode.h"
#include "rc_input.h"

#define decode_step(us, steps) rc_decode_step((us), RC_MIN_US, RC_MAX_US, (steps))
#define decode_u8(us)          rc_decode_u8((us), RC_MIN_US, RC_MAX_US)

static rgb_t s_pixels[MAX_ZONE_PIXELS];

int main(void) {
    stdio_init_all();

    effects_init();
    outputs_init();
    rc_input_init();

    // Says which model this board is configured for. The pin assignment differs
    // between models, so flashing the wrong image is worth noticing early.
    printf("\nlightshow plane: model=%s zones=%u strips=%u relays=%u\n",
           PLANE_MODEL_NAME, ZONE_COUNT, STRIP_COUNT, RELAY_COUNT);

    rc_state_t rc = {0};
    absolute_time_t next = get_absolute_time();
    uint32_t last_log_ms = 0;
    show_state_t last_logged = {0};

    while (true) {
        rc_input_poll(&rc);
        uint32_t now_ms = to_ms_since_boot(get_absolute_time());

        if (!rc.valid) {
            outputs_relays_off();
        }

        for (uint8_t zone = 0; zone < outputs_zone_count(); zone++) {
            uint16_t count = outputs_zone_pixels(zone);
            show_state_t show = {0};

            if (rc.valid) {
                // With SBUS the zone sits at its configured place inside the
                // 16 channel frame. With PWM the four wires are the four
                // channels, so every zone reads the same block.
                uint8_t base = (rc.source == RC_SOURCE_SBUS)
                                   ? outputs_zone_base_channel(zone)
                                   : 1;
                show.cue = decode_step(rc_channel_us(&rc, base), CUE_STEPS);
                show.hue = decode_u8(rc_channel_us(&rc, base + 1));
                show.brightness = decode_u8(rc_channel_us(&rc, base + 2));
                show.param = decode_u8(rc_channel_us(&rc, base + 3));
                effects_render(&show, now_ms, s_pixels, count);
                outputs_update_relays(zone, &show, s_pixels, &rc, now_ms);
            } else {
                effects_render_failsafe(now_ms, s_pixels, count);
            }

            outputs_show(zone, s_pixels);
            if (zone == 0) last_logged = show;
        }

        if (now_ms - last_log_ms >= 1000) {
            last_log_ms = now_ms;
            printf("%s src=%d cue=%u hue=%u bri=%u param=%u\n",
                   PLANE_MODEL_NAME, (int)rc.source, last_logged.cue,
                   last_logged.hue, last_logged.brightness, last_logged.param);
        }

        next = delayed_by_us(next, 1000000 / RENDER_HZ);
        sleep_until(next);
    }
}
