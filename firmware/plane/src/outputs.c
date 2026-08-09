#include "outputs.h"

#include <string.h>

#include "hardware/gpio.h"
#include "hardware/pio.h"
#include "pico/stdlib.h"

#include "config.h"
#include "rc_decode.h"
#include "relay_logic.h"
#include "ws2812.pio.h"

static const zone_cfg_t  s_zones[]  = ZONES;
static const strip_cfg_t s_strips[] = STRIPS;
#if RELAY_COUNT > 0
static const relay_cfg_t s_relays[] = RELAYS;
static relay_state_t     s_relay_state[RELAY_COUNT];
#endif
#if NAV_COUNT > 0
static const nav_light_t s_nav[] = NAV_LIGHTS;
#endif

// One PIO state machine per strip: pio0 takes the first four, pio1 the rest.
static PIO  s_strip_pio[STRIP_COUNT];
static uint s_strip_sm[STRIP_COUNT];

_Static_assert(ZONE_COUNT  <= MAX_ZONES,  "too many zones");
_Static_assert(STRIP_COUNT <= MAX_STRIPS, "too many strips, only 8 PIO state machines exist");
_Static_assert(RELAY_COUNT <= MAX_RELAYS, "too many relays");
_Static_assert(NAV_COUNT   <= MAX_NAV_LIGHTS, "too many navigation lights");

void outputs_init(void) {
    int offset[2] = {-1, -1};

    for (uint8_t i = 0; i < STRIP_COUNT; i++) {
        PIO pio = i < 4 ? pio0 : pio1;
        uint block = i < 4 ? 0u : 1u;
        if (offset[block] < 0) {
            offset[block] = (int)pio_add_program(pio, &ws2812_program);
        }
        s_strip_pio[i] = pio;
        s_strip_sm[i] = i % 4;
        pio_sm_claim(pio, s_strip_sm[i]);
        ws2812_program_init(pio, s_strip_sm[i], (uint)offset[block], s_strips[i].pin);
    }

#if RELAY_COUNT > 0
    for (uint8_t i = 0; i < RELAY_COUNT; i++) {
        gpio_init(s_relays[i].pin);
        gpio_set_dir(s_relays[i].pin, GPIO_OUT);
        // Drive the off level before anything else runs, so a relay board does
        // not click on during boot.
        gpio_put(s_relays[i].pin, relay_pin_level(false, s_relays[i].active_low));
        s_relay_state[i] = (relay_state_t){0};
    }
#endif
}

uint16_t outputs_zone_pixels(uint8_t zone) {
    uint16_t needed = 0;
    for (uint8_t i = 0; i < STRIP_COUNT; i++) {
        if (s_strips[i].zone != zone) continue;
        uint16_t end = (uint16_t)(s_strips[i].offset + s_strips[i].count);
        if (end > needed) needed = end;
    }
    return needed > MAX_ZONE_PIXELS ? MAX_ZONE_PIXELS : needed;
}

// Navigation lights win over whatever the effect produced.
static bool nav_colour(uint8_t strip, uint16_t index, rgb_t *out) {
#if NAV_COUNT > 0
    for (uint8_t n = 0; n < NAV_COUNT; n++) {
        if (s_nav[n].strip == strip && s_nav[n].index == index) {
            out->r = effects_gamma(s_nav[n].r);
            out->g = effects_gamma(s_nav[n].g);
            out->b = effects_gamma(s_nav[n].b);
            return true;
        }
    }
#else
    (void)strip;
    (void)index;
    (void)out;
#endif
    return false;
}

void outputs_show(uint8_t zone, const rgb_t *pixels) {
    uint16_t available = outputs_zone_pixels(zone);

    for (uint8_t i = 0; i < STRIP_COUNT; i++) {
        const strip_cfg_t *strip = &s_strips[i];
        if (strip->zone != zone) continue;

        for (uint16_t p = 0; p < strip->count; p++) {
            uint16_t source = strip->reverse ? (uint16_t)(strip->count - 1u - p) : p;
            source = (uint16_t)(strip->offset + source);

            rgb_t colour = source < available ? pixels[source] : (rgb_t){0, 0, 0};
            nav_colour(i, p, &colour);

            uint32_t grb = ((uint32_t)colour.g << 16) | ((uint32_t)colour.r << 8) |
                           (uint32_t)colour.b;
            pio_sm_put_blocking(s_strip_pio[i], s_strip_sm[i], grb << 8u);
        }
    }
}

#if RELAY_COUNT > 0
// Collects everything relay_wants() needs; the decision itself lives in
// relay_logic.h so it can be tested without hardware.
static relay_inputs_t gather(const relay_cfg_t *relay, const show_state_t *show,
                             const rgb_t *pixels, uint16_t pixel_count,
                             const rc_state_t *rc) {
    relay_inputs_t in = {
        .cue = show->cue,
        .brightness = show->brightness,
        .pixel_level = 0,
        .channel_level = 0,
        .pixel_valid = false,
    };

    if (relay->arg < pixel_count) {
        const rgb_t *p = &pixels[relay->arg];
        uint8_t level = p->r > p->g ? p->r : p->g;
        if (p->b > level) level = p->b;
        in.pixel_level = level;
        in.pixel_valid = true;
    }
    in.channel_level = rc_decode_u8(rc_channel_us(rc, (uint8_t)relay->arg),
                                    RC_MIN_US, RC_MAX_US);
    return in;
}
#endif

void outputs_update_relays(uint8_t zone, const show_state_t *show,
                           const rgb_t *pixels, const rc_state_t *rc,
                           uint32_t now_ms) {
#if RELAY_COUNT > 0
    uint16_t pixel_count = outputs_zone_pixels(zone);

    for (uint8_t i = 0; i < RELAY_COUNT; i++) {
        if (s_relays[i].zone != zone) continue;

        relay_inputs_t in = gather(&s_relays[i], show, pixels, pixel_count, rc);
        bool want = relay_wants(s_relays[i].source, s_relays[i].arg,
                                s_relays[i].threshold, &in);
        bool state = relay_step(&s_relay_state[i], want, now_ms,
                                s_relays[i].min_on_ms, s_relays[i].min_off_ms);
        gpio_put(s_relays[i].pin, relay_pin_level(state, s_relays[i].active_low));
    }
#else
    (void)zone; (void)show; (void)pixels; (void)rc; (void)now_ms;
#endif
}

void outputs_relays_off(void) {
#if RELAY_COUNT > 0
    for (uint8_t i = 0; i < RELAY_COUNT; i++) {
        // Bypasses the minimum times on purpose: losing the link is not the
        // moment to keep a smoke system running for another 200 ms.
        s_relay_state[i].state = false;
        s_relay_state[i].started = true;
        gpio_put(s_relays[i].pin, relay_pin_level(false, s_relays[i].active_low));
    }
#endif
}

uint8_t outputs_zone_count(void) { return ZONE_COUNT; }

// Base RC channel of a zone, used by main.c.
uint8_t outputs_zone_base_channel(uint8_t zone) {
    return zone < ZONE_COUNT ? s_zones[zone].base_channel : 1;
}
