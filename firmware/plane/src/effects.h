#ifndef PLANE_EFFECTS_H
#define PLANE_EFFECTS_H

#include <stdint.h>

typedef struct {
    uint8_t r, g, b;
} rgb_t;

// What the four show channels currently say, already decoded from the RC frame.
typedef struct {
    uint8_t cue;         // effect index, 0 = off
    uint8_t hue;         // 0..255
    uint8_t brightness;  // 0..255
    uint8_t param;       // effect speed / second parameter
} show_state_t;

void effects_init(void);

// Renders the current effect into `pixels`.
void effects_render(const show_state_t *state, uint32_t now_ms,
                    rgb_t *pixels, uint16_t count);

// Shown when the RC link is gone: a slow amber pulse, distinct from any cue.
void effects_render_failsafe(uint32_t now_ms, rgb_t *pixels, uint16_t count);

// Gamma 2.2 lookup. The output stage uses it for the navigation lights so they
// sit on the same curve as everything else.
uint8_t effects_gamma(uint8_t value);

// Number of effects that are actually implemented; higher cue values fall back
// to a steady colour rather than doing nothing.
uint8_t effects_count(void);

#endif // PLANE_EFFECTS_H
