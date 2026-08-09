#include "effects.h"

#include <math.h>
#include <stdbool.h>
#include <string.h>

#include "config.h"

typedef struct {
    uint16_t index;
    uint8_t r, g, b;
} nav_light_t;

#if NAV_COUNT > 0
static const nav_light_t s_nav[] = NAV_LIGHTS;
#endif
static uint8_t s_gamma[256];
static uint32_t s_rand = 0x12345678;

// ---------------------------------------------------------------- helpers ---

static uint8_t xorshift(void) {
    s_rand ^= s_rand << 13;
    s_rand ^= s_rand >> 17;
    s_rand ^= s_rand << 5;
    return (uint8_t)(s_rand >> 16);
}

// Integer HSV with full saturation; hue 0..255 walks the colour wheel.
static rgb_t hsv(uint8_t hue, uint8_t value) {
    uint8_t sector = hue / 43;
    uint8_t offset = (uint8_t)((hue - sector * 43) * 6);
    uint8_t p = 0;
    uint8_t q = (uint8_t)(((uint16_t)value * (255 - offset)) >> 8);
    uint8_t t = (uint8_t)(((uint16_t)value * offset) >> 8);

    switch (sector) {
    case 0:  return (rgb_t){value, t, p};
    case 1:  return (rgb_t){q, value, p};
    case 2:  return (rgb_t){p, value, t};
    case 3:  return (rgb_t){p, q, value};
    case 4:  return (rgb_t){t, p, value};
    default: return (rgb_t){value, p, q};
    }
}

static inline uint8_t scale8(uint8_t value, uint8_t scale) {
    return (uint8_t)(((uint16_t)value * (uint16_t)scale) >> 8);
}

static void fill(rgb_t *pixels, uint16_t count, rgb_t colour) {
    for (uint16_t i = 0; i < count; i++) pixels[i] = colour;
}

// The show dimmer, the safety ceiling and gamma correction, applied once at the
// end so every effect gets the same treatment.
static void finish(rgb_t *pixels, uint16_t count, uint8_t brightness) {
    uint8_t level = scale8(brightness, MAX_BRIGHTNESS);
    for (uint16_t i = 0; i < count; i++) {
        pixels[i].r = s_gamma[scale8(pixels[i].r, level)];
        pixels[i].g = s_gamma[scale8(pixels[i].g, level)];
        pixels[i].b = s_gamma[scale8(pixels[i].b, level)];
    }
}

// param 0..255 maps to a 2000 ms .. 100 ms cycle.
static uint32_t period_ms(uint8_t param) {
    return 2000u - ((uint32_t)param * 1900u) / 255u;
}

// Position inside the current cycle, 0..255.
static uint8_t phase(uint32_t now_ms, uint32_t period) {
    return (uint8_t)(((now_ms % period) * 256u) / period);
}

// Triangle wave, so fades go up and back down smoothly.
static uint8_t triangle(uint8_t x) {
    return x < 128 ? (uint8_t)(x * 2) : (uint8_t)((255 - x) * 2);
}

// ---------------------------------------------------------------- effects ---

#define EFFECT_COUNT 11

void effects_render(const show_state_t *state, uint32_t now_ms,
                    rgb_t *pixels, uint16_t count) {
    if (state->cue == 0 || state->brightness == 0) {
        memset(pixels, 0, count * sizeof(rgb_t));
        return;
    }

    const uint32_t period = period_ms(state->param);
    const uint8_t ph = phase(now_ms, period);
    const rgb_t base = hsv(state->hue, 255);
    uint8_t effect = state->cue;
    if (effect >= EFFECT_COUNT) effect = 1;  // unknown cue: steady colour

    switch (effect) {
    case 1:  // solid
        fill(pixels, count, base);
        break;

    case 2: {  // breathe
        uint8_t level = triangle(ph);
        fill(pixels, count, (rgb_t){scale8(base.r, level), scale8(base.g, level),
                                    scale8(base.b, level)});
        break;
    }

    case 3:  // strobe: short flash at the start of each cycle
        fill(pixels, count, ph < 24 ? base : (rgb_t){0, 0, 0});
        break;

    case 4:  // double strobe
        fill(pixels, count,
             (ph < 16 || (ph >= 40 && ph < 56)) ? base : (rgb_t){0, 0, 0});
        break;

    case 5: {  // chase: a lit block running along the strip
        uint16_t head = (uint16_t)(((uint32_t)ph * count) >> 8);
        uint16_t width = count / 6 + 1;
        for (uint16_t i = 0; i < count; i++) {
            uint16_t distance = (uint16_t)((i + count - head) % count);
            pixels[i] = distance < width ? base : (rgb_t){0, 0, 0};
        }
        break;
    }

    case 6: {  // comet with a fading tail
        uint16_t head = (uint16_t)(((uint32_t)ph * count) >> 8);
        for (uint16_t i = 0; i < count; i++) {
            uint16_t distance = (uint16_t)((i + count - head) % count);
            uint8_t level = distance > 255 ? 0 : (uint8_t)(255 - distance * 255 / count);
            level = scale8(level, level);  // squared falloff, reads as a tail
            pixels[i] = (rgb_t){scale8(base.r, level), scale8(base.g, level),
                                scale8(base.b, level)};
        }
        break;
    }

    case 7:  // sparkle
        for (uint16_t i = 0; i < count; i++) {
            pixels[i] = (xorshift() < 24) ? base : (rgb_t){0, 0, 0};
        }
        break;

    case 8:  // rainbow rotating around the airframe
        for (uint16_t i = 0; i < count; i++) {
            pixels[i] = hsv((uint8_t)(state->hue + ph + i * 256 / count), 255);
        }
        break;

    case 9:  // police: alternating halves, hue ignored
        for (uint16_t i = 0; i < count; i++) {
            bool front = i < count / 2;
            bool first = ph < 128;
            pixels[i] = (front == first) ? (rgb_t){255, 0, 0} : (rgb_t){0, 0, 255};
        }
        break;

    case 10: {  // theater chase, every third pixel
        uint8_t step = (uint8_t)(((uint32_t)ph * 3) >> 8);
        for (uint16_t i = 0; i < count; i++) {
            pixels[i] = (i % 3 == step) ? base : (rgb_t){0, 0, 0};
        }
        break;
    }

    default:
        fill(pixels, count, base);
        break;
    }

    finish(pixels, count, state->brightness);
}

void effects_render_failsafe(uint32_t now_ms, rgb_t *pixels, uint16_t count) {
    // Slow amber pulse at a fixed, low level: unmistakably not part of the show
    // and still bright enough to find the model.
    uint8_t level = triangle(phase(now_ms, 2000));
    rgb_t colour = {scale8(255, level), scale8(120, level), 0};
    fill(pixels, count, colour);
    finish(pixels, count, 96);
}

void effects_apply_nav(rgb_t *pixels, uint16_t count) {
#if NAV_COUNT > 0
    for (uint16_t i = 0; i < sizeof(s_nav) / sizeof(s_nav[0]); i++) {
        if (s_nav[i].index >= count) continue;
        pixels[s_nav[i].index] = (rgb_t){
            s_gamma[scale8(s_nav[i].r, MAX_BRIGHTNESS)],
            s_gamma[scale8(s_nav[i].g, MAX_BRIGHTNESS)],
            s_gamma[scale8(s_nav[i].b, MAX_BRIGHTNESS)],
        };
    }
#else
    (void)pixels;
    (void)count;
#endif
}

uint8_t effects_count(void) { return EFFECT_COUNT; }

void effects_init(void) {
    // Gamma 2.2 so a linear dimmer channel looks linear to the eye. Built once
    // at boot; everything afterwards is a table lookup.
    for (int i = 0; i < 256; i++) {
        float normalised = powf((float)i / 255.0f, 2.2f);
        s_gamma[i] = (uint8_t)(normalised * 255.0f + 0.5f);
    }
}
