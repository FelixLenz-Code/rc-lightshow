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

#if BUS_MODE
#include "bus.h"

// In bus mode a frame refreshes one zone, so the others have to be remembered
// between frames -- there is no channel holding them any more.
static bus_zone_t s_zones[BUS_ZONES];
static uint8_t    s_bus_relays;
// Nothing may light up before a frame has actually been understood.
static bool       s_all_off = true;
static uint32_t   s_last_bus_frame;
// Only read by the measure build's console line, but kept unconditionally so
// the two builds decode through exactly the same code.
static uint8_t    s_last_zone;
static int8_t     s_last_fix = -1;
static uint32_t   s_bus_bad;
static bool       s_last_ok;

static void bus_all_off(void) {
    for (uint8_t zone = 0; zone < BUS_ZONES; zone++) {
        s_zones[zone] = (bus_zone_t){0};
    }
    s_bus_relays = 0;
    s_all_off = true;
}

// Reads the eight bus channels of a newly arrived RC frame. A frame that does
// not decode changes nothing: holding the last good state is always better than
// acting on a guess.
static void bus_poll(const rc_state_t *rc) {
    if (!rc->valid || rc->source != RC_SOURCE_SBUS) return;
    if (rc->frames == s_last_bus_frame) return;
    s_last_bus_frame = rc->frames;

    uint8_t symbols[BUS_SYMBOLS];
    for (uint8_t i = 0; i < BUS_SYMBOLS; i++) {
        symbols[i] = bus_us_to_symbol(
            rc_channel_us(rc, (uint8_t)(BUS_FIRST_CHANNEL + i)),
            RC_MIN_US, RC_MAX_US);
    }

    bus_frame_t frame;
    s_last_ok = bus_decode(symbols, BUS_ZONES, BUS_RELAY_COUNT, &frame);
    if (!s_last_ok) {
        s_bus_bad++;
        return;
    }
    s_last_zone = frame.zone;
    s_last_fix = frame.corrected;

    // One frame addresses one zone, so a static failsafe frame could never
    // darken the rest. This command means all of them, at once -- and it takes
    // three fields to say, so a stray frame cannot blank the model by accident.
    if (bus_is_all_off(&frame.state)) {
        bus_all_off();
        return;
    }
    s_zones[frame.zone] = frame.state;
    s_bus_relays = frame.relays;
    s_all_off = false;
}
#endif

int main(void) {
    stdio_init_all();

    effects_init();
    outputs_init();
    rc_input_init();

    // Says which model this board is configured for. The pin assignment differs
    // between models, so flashing the wrong image is worth noticing early.
    printf("\nlightshow plane: model=%s zones=%u strips=%u relays=%u\n",
           PLANE_MODEL_NAME, ZONE_COUNT, STRIP_COUNT, RELAY_COUNT);
#if MEASURE_MODE
    printf("MEASURE build: eine MEAS-Zeile je RC-Frame, %u Cue-Stufen, "
           "%u..%u us\n", CUE_STEPS, RC_MIN_US, RC_MAX_US);
#endif

    rc_state_t rc = {0};
    absolute_time_t next = get_absolute_time();
#if MEASURE_MODE
    uint32_t last_frames = 0;       // print only when a frame is really new
#else
    uint32_t last_log_ms = 0;
    show_state_t last_logged = {0};
#endif

    while (true) {
        rc_input_poll(&rc);
        uint32_t now_ms = to_ms_since_boot(get_absolute_time());

        if (!rc.valid) {
            outputs_relays_off();
#if BUS_MODE
            // The link is gone; the remembered zone states are stale and must
            // not come back to life when it returns.
            bus_all_off();
#endif
        }

#if BUS_MODE
        bus_poll(&rc);
        outputs_set_bus_relays(s_bus_relays, s_all_off);
#endif

        for (uint8_t zone = 0; zone < outputs_zone_count(); zone++) {
            uint16_t count = outputs_zone_pixels(zone);
            show_state_t show = {0};

            if (rc.valid) {
#if BUS_MODE
                // Nothing is decoded here: the zone's state came in on some
                // earlier frame and has been held ever since.
                show.cue = s_zones[zone].cue;
                show.hue = s_zones[zone].hue;
                show.brightness = s_zones[zone].brightness;
                show.param = s_zones[zone].param;
                if (s_all_off) {
                    show.cue = 0;
                    show.brightness = 0;
                }
#else
                // Jede Zone sitzt an ihrem konfigurierten Platz im
                // 16-Kanal-Rahmen.
                uint8_t base = outputs_zone_base_channel(zone);
                show.cue = decode_step(rc_channel_us(&rc, base), CUE_STEPS);
                show.hue = decode_u8(rc_channel_us(&rc, base + 1));
                show.brightness = decode_u8(rc_channel_us(&rc, base + 2));
                show.param = decode_u8(rc_channel_us(&rc, base + 3));
#endif
                effects_render(&show, now_ms, s_pixels, count);
                outputs_update_relays(zone, &show, s_pixels, &rc, now_ms);
            } else {
                effects_render_failsafe(now_ms, s_pixels, count);
            }

            outputs_show(zone, s_pixels);
#if !MEASURE_MODE
            if (zone == 0) last_logged = show;   // zone 0 stands in the status line
#endif
        }

#if MEASURE_MODE
        // One line per received RC frame with the raw microseconds, so the
        // bench can compare what was sent against what arrived. Printed only
        // when a frame is actually new: the receiver holds its last value, and
        // repeating it would make a dropout look like clean reception.
        if (rc.frames != last_frames) {
            last_frames = rc.frames;
            uint8_t base = outputs_zone_base_channel(0);
            printf("MEAS ms=%lu seq=%lu src=%d c%u=%u c%u=%u c%u=%u c%u=%u step=%u\n",
                   (unsigned long)now_ms, (unsigned long)rc.frames, (int)rc.source,
                   base + 0, rc_channel_us(&rc, base + 0),
                   base + 1, rc_channel_us(&rc, base + 1),
                   base + 2, rc_channel_us(&rc, base + 2),
                   base + 3, rc_channel_us(&rc, base + 3),
                   decode_step(rc_channel_us(&rc, base), CUE_STEPS));
#if BUS_MODE
            // The raw channels above are code symbols and mean nothing on
            // their own. This is what the frame actually decoded to -- which
            // zone it addressed, what that zone now holds, and whether the
            // correction had to step in. `bad` counts frames that could not be
            // decoded at all; on a healthy link it stays at zero.
            printf("BUS zone=%u cue=%u hue=%u bri=%u param=%u relays=0x%02x "
                   "fix=%d bad=%lu off=%d\n",
                   s_last_zone, s_zones[s_last_zone].cue, s_zones[s_last_zone].hue,
                   s_zones[s_last_zone].brightness, s_zones[s_last_zone].param,
                   s_bus_relays, s_last_fix, (unsigned long)s_bus_bad,
                   s_all_off ? 1 : 0);
            // All eight coded channels raw, so a rejected frame can be taken
            // apart on the bench: which symbol moved, and by how much.
            printf("RAW ok=%d", s_last_ok ? 1 : 0);
            for (uint8_t i = 0; i < BUS_SYMBOLS; i++) {
                printf(" %u", rc_channel_us(&rc, (uint8_t)(BUS_FIRST_CHANNEL + i)));
            }
            printf("\n");
#endif
        }
#else
        if (now_ms - last_log_ms >= 1000) {
            last_log_ms = now_ms;
            printf("%s src=%d cue=%u hue=%u bri=%u param=%u frames=%lu\n",
                   PLANE_MODEL_NAME, (int)rc.source, last_logged.cue,
                   last_logged.hue, last_logged.brightness, last_logged.param,
                   (unsigned long)rc.frames);
        }
#endif

        next = delayed_by_us(next, 1000000 / RENDER_HZ);
        sleep_until(next);
    }
}
