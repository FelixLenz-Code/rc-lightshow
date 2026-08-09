// Decoding of the "data bus" channels.
//
// Deliberately free of any SDK dependency so it can be compiled and tested on a
// PC against the ground station's encoder -- see tools/ctest/.

#ifndef PLANE_RC_DECODE_H
#define PLANE_RC_DECODE_H

#include <stdint.h>

// Undo the quantisation the ground station applies. It places each step in the
// middle of its band, so plain truncation lands back on the same index even
// when the servo pulse is a few microseconds off.
static inline uint8_t rc_decode_step(uint16_t us, uint16_t min_us, uint16_t max_us,
                                     uint8_t steps) {
    if (steps == 0) return 0;
    if (us <= min_us) return 0;
    if (us >= max_us) return (uint8_t)(steps - 1);
    uint32_t index = (uint32_t)(us - min_us) * steps / (uint32_t)(max_us - min_us);
    return index >= steps ? (uint8_t)(steps - 1) : (uint8_t)index;
}

// Continuous channel to 0..255.
static inline uint8_t rc_decode_u8(uint16_t us, uint16_t min_us, uint16_t max_us) {
    if (us <= min_us) return 0;
    if (us >= max_us) return 255;
    return (uint8_t)((uint32_t)(us - min_us) * 255u / (uint32_t)(max_us - min_us));
}

#endif // PLANE_RC_DECODE_H
