// PPM frame layout.
//
// Kept free of SDK dependencies so the timing maths can be verified on a PC --
// see tools/ctest/ and host/tests/test_ppm_frame.py. A mistake here would show
// up as every channel being slightly wrong in the transmitter, which is exactly
// the kind of bug that is painful to find with an oscilloscope.
//
// The buffer holds alternating mark and space durations for the PIO program:
// one mark/space pair per channel plus a closing sync pair. A channel slot runs
// from one rising edge to the next and equals the channel value, so the space
// is the value minus the mark.

#ifndef LIGHTSHOW_PPM_FRAME_H
#define LIGHTSHOW_PPM_FRAME_H

#include <stdint.h>

// The PIO program spends three fixed cycles per half period (out, set, and the
// jmp that falls through), so the loop counter is the duration minus three.
#define PPM_OVERHEAD_TICKS 3
#define PPM_MIN_TICKS      4
// Smallest idle gap at the end of a frame, so the receiving end always
// recognises the sync pulse.
#define PPM_MIN_SYNC_US 3000

static inline uint32_t ppm_ticks(uint32_t us) {
    return us > PPM_MIN_TICKS ? us - PPM_OVERHEAD_TICKS : 1;
}

// Microseconds a buffer entry actually produces -- the inverse of ppm_ticks().
static inline uint32_t ppm_ticks_to_us(uint32_t ticks) {
    return ticks + PPM_OVERHEAD_TICKS;
}

// Fills `out` with 2 * (nchan + 1) words and returns that count.
static inline uint32_t ppm_build_buffer(const uint16_t *values, uint8_t nchan,
                                        uint16_t sync_us, uint16_t frame_us,
                                        uint16_t min_us, uint16_t max_us,
                                        uint32_t *out) {
    const uint32_t mark = sync_us;
    uint32_t used = 0;

    for (uint8_t i = 0; i < nchan; i++) {
        uint32_t v = values[i];
        if (v < min_us) v = min_us;
        if (v > max_us) v = max_us;
        // The mark has to fit inside the channel slot.
        uint32_t space = v > mark + PPM_MIN_TICKS ? v - mark : PPM_MIN_TICKS;

        out[2 * i]     = ppm_ticks(mark);
        out[2 * i + 1] = ppm_ticks(space);
        used += mark + space;
    }

    uint32_t rest = PPM_MIN_SYNC_US;
    if ((uint32_t)frame_us > used + mark + PPM_MIN_SYNC_US) {
        rest = (uint32_t)frame_us - used - mark;
    }
    out[2 * nchan]     = ppm_ticks(mark);
    out[2 * nchan + 1] = ppm_ticks(rest);

    return 2u * (uint32_t)(nchan + 1u);
}

#endif // LIGHTSHOW_PPM_FRAME_H
