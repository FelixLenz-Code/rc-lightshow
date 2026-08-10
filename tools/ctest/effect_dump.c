// Dumps what the airborne effect engine renders, so the browser port in
// host/lightshow/web/effects.js can be checked against the real thing.
//
// The interface draws the light a model is about to show. That preview is only
// worth anything if it is the same pattern, so this compiles the actual
// effects.c and prints its pixels for host/tests/test_effects_preview.py to
// compare.
//
//   effect_dump <cue> <hue> <brightness> <param> <now_ms> <count>
//   effect_dump failsafe <now_ms> <count>

#include <stdio.h>
#include <stdlib.h>

#include "config.h"
#include "effects.h"

static void dump(const rgb_t *pixels, uint16_t count) {
    for (uint16_t i = 0; i < count; i++) {
        printf("%u %u %u\n", pixels[i].r, pixels[i].g, pixels[i].b);
    }
}

int main(int argc, char **argv) {
    static rgb_t pixels[MAX_ZONE_PIXELS];
    effects_init();

    if (argc == 4 && argv[1][0] == 'f') {
        uint32_t now = (uint32_t)strtoul(argv[2], NULL, 10);
        uint16_t count = (uint16_t)atoi(argv[3]);
        if (count > MAX_ZONE_PIXELS) count = MAX_ZONE_PIXELS;
        effects_render_failsafe(now, pixels, count);
        dump(pixels, count);
        return 0;
    }

    if (argc != 7) {
        fprintf(stderr, "usage: effect_dump <cue> <hue> <brightness> <param>"
                        " <now_ms> <count>\n"
                        "       effect_dump failsafe <now_ms> <count>\n");
        return 2;
    }

    show_state_t show = {
        .cue        = (uint8_t)atoi(argv[1]),
        .hue        = (uint8_t)atoi(argv[2]),
        .brightness = (uint8_t)atoi(argv[3]),
        .param      = (uint8_t)atoi(argv[4]),
    };
    uint32_t now = (uint32_t)strtoul(argv[5], NULL, 10);
    uint16_t count = (uint16_t)atoi(argv[6]);
    if (count > MAX_ZONE_PIXELS) count = MAX_ZONE_PIXELS;

    effects_render(&show, now, pixels, count);
    dump(pixels, count);
    return 0;
}
