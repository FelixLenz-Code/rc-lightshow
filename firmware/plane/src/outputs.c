#include "outputs.h"

#include <string.h>

#include "hardware/gpio.h"
#include "hardware/pio.h"
#include "pico/stdlib.h"

#include "config.h"
#include "relay_logic.h"
#include "ws2812.pio.h"

static const zone_cfg_t s_zones[] = ZONES;
// A model may carry nothing but relays, and a table of zero elements is not
// standard C -- so every optional table is guarded the same way.
#if OUTPUT_COUNT > 0
static const output_cfg_t  s_outputs[]  = OUTPUTS;
static const segment_cfg_t s_segments[] = SEGMENTS;

// Every physical chain lives in one flat buffer; `first` says where each one
// starts. Pixels no segment covers are never written and stay black, which is
// what an unlit stretch of chain should be.
static rgb_t s_frame[OUTPUT_PIXEL_TOTAL];

// One PIO state machine per chain: pio0 takes the first four, pio1 the rest.
static PIO  s_output_pio[OUTPUT_COUNT];
static uint s_output_sm[OUTPUT_COUNT];
#endif
#if NAV_COUNT > 0
static const nav_light_t s_nav[] = NAV_LIGHTS;
#endif

#if RELAY_COUNT > 0
static const relay_cfg_t s_relays[] = RELAYS;
static relay_state_t     s_relay_state[RELAY_COUNT];
#endif

_Static_assert(ZONE_COUNT    <= MAX_ZONES,    "too many zones");
_Static_assert(OUTPUT_COUNT  <= MAX_OUTPUTS,  "too many LED outputs, only 8 PIO state machines exist");
_Static_assert(SEGMENT_COUNT <= MAX_SEGMENTS, "too many segments");
_Static_assert(RELAY_COUNT   <= MAX_RELAYS,   "too many relays");
_Static_assert(NAV_COUNT     <= MAX_NAV_LIGHTS, "too many navigation lights");

void outputs_init(void) {
#if OUTPUT_COUNT > 0
    int offset[2] = {-1, -1};

    for (uint8_t i = 0; i < OUTPUT_COUNT; i++) {
        PIO pio = i < 4 ? pio0 : pio1;
        uint block = i < 4 ? 0u : 1u;
        if (offset[block] < 0) {
            offset[block] = (int)pio_add_program(pio, &ws2812_program);
        }
        s_output_pio[i] = pio;
        s_output_sm[i] = i % 4;
        pio_sm_claim(pio, s_output_sm[i]);
        ws2812_program_init(pio, s_output_sm[i], (uint)offset[block], s_outputs[i].pin);
    }
#endif

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
#if OUTPUT_COUNT > 0
    for (uint8_t i = 0; i < SEGMENT_COUNT; i++) {
        if (s_segments[i].zone != zone) continue;
        uint16_t end = (uint16_t)(s_segments[i].offset + s_segments[i].count);
        if (end > needed) needed = end;
    }
#else
    (void)zone;
#endif
    return needed > MAX_ZONE_PIXELS ? MAX_ZONE_PIXELS : needed;
}

void outputs_show(uint8_t zone, const rgb_t *pixels) {
#if OUTPUT_COUNT == 0
    (void)zone; (void)pixels;
#else
    uint16_t available = outputs_zone_pixels(zone);

    for (uint8_t i = 0; i < SEGMENT_COUNT; i++) {
        const segment_cfg_t *seg = &s_segments[i];
        if (seg->zone != zone) continue;

        rgb_t *chain = &s_frame[s_outputs[seg->output].first + seg->start];
        for (uint16_t p = 0; p < seg->count; p++) {
            uint16_t source = seg->reverse ? (uint16_t)(seg->count - 1u - p) : p;
            source = (uint16_t)(seg->offset + source);
            chain[p] = source < available ? pixels[source] : (rgb_t){0, 0, 0};
        }
    }
#endif
}

void outputs_flush(void) {
#if OUTPUT_COUNT > 0
    // Navigation lights win over whatever the effects produced. Stamping them
    // into the buffer costs one pass over the table rather than a lookup per
    // pixel, and it puts them on chains no zone covers just as readily.
#if NAV_COUNT > 0
    for (uint8_t n = 0; n < NAV_COUNT; n++) {
        const nav_light_t *nav = &s_nav[n];
        if (nav->index >= s_outputs[nav->output].count) continue;
        s_frame[s_outputs[nav->output].first + nav->index] = (rgb_t){
            effects_gamma(nav->r), effects_gamma(nav->g), effects_gamma(nav->b),
        };
    }
#endif

    for (uint8_t i = 0; i < OUTPUT_COUNT; i++) {
        const rgb_t *chain = &s_frame[s_outputs[i].first];
        for (uint16_t p = 0; p < s_outputs[i].count; p++) {
            uint32_t grb = ((uint32_t)chain[p].g << 16) |
                           ((uint32_t)chain[p].r << 8) | (uint32_t)chain[p].b;
            pio_sm_put_blocking(s_output_pio[i], s_output_sm[i], grb << 8u);
        }
    }
#endif
}

// What the last bus frame said about the directly switched relays.
static uint8_t s_bus_relays;
static bool    s_bus_all_off;

void outputs_set_bus_relays(uint8_t bitmap, bool all_off) {
    s_bus_relays = bitmap;
    s_bus_all_off = all_off;
}

void outputs_update_relays(uint32_t now_ms) {
#if RELAY_COUNT > 0
    for (uint8_t i = 0; i < RELAY_COUNT; i++) {
        const relay_cfg_t *relay = &s_relays[i];
        // Position in the table is the bit in the frame; nothing has to be
        // looked up, and nothing can point at the wrong slot.
        relay_inputs_t in = {
            .bus_on = (s_bus_relays >> (i & 7u)) & 1u,
            .all_off = s_bus_all_off,
        };

        bool state = relay_step(&s_relay_state[i], relay_wants(&in), now_ms,
                                relay->min_on_ms, relay->min_off_ms);
        gpio_put(relay->pin, relay_pin_level(state, relay->active_low));
    }
#else
    (void)now_ms;
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

// Base RC channel of a zone. In bus mode no zone owns channels of its own; the
// generator writes the bus's first channel here, which is what the measure
// build wants to print.
uint8_t outputs_zone_base_channel(uint8_t zone) {
    return zone < ZONE_COUNT ? s_zones[zone].base_channel : 1;
}
