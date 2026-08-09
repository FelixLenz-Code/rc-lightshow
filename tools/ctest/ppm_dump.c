// Renders one PPM frame and prints the real pulse timing in microseconds, so
// host/tests/test_ppm_frame.py can verify the frame maths without an
// oscilloscope.
//
//   ppm_dump <sync_us> <frame_us> <min_us> <max_us> <value_us>...
//
// Output: one line per half period, "<mark|space> <microseconds>".

#include <stdio.h>
#include <stdlib.h>

#include "ppm_frame.h"

#define MAX_CH 16

int main(int argc, char **argv) {
    if (argc < 6) {
        fprintf(stderr,
                "usage: ppm_dump <sync_us> <frame_us> <min_us> <max_us> <value_us>...\n");
        return 2;
    }

    uint16_t sync_us = (uint16_t)atoi(argv[1]);
    uint16_t frame_us = (uint16_t)atoi(argv[2]);
    uint16_t min_us = (uint16_t)atoi(argv[3]);
    uint16_t max_us = (uint16_t)atoi(argv[4]);

    uint16_t values[MAX_CH];
    int nchan = argc - 5;
    if (nchan > MAX_CH) nchan = MAX_CH;
    for (int i = 0; i < nchan; i++) {
        values[i] = (uint16_t)atoi(argv[5 + i]);
    }

    uint32_t buffer[2 * (MAX_CH + 1)];
    uint32_t words = ppm_build_buffer(values, (uint8_t)nchan, sync_us, frame_us,
                                      min_us, max_us, buffer);

    for (uint32_t i = 0; i < words; i++) {
        printf("%s %u\n", (i % 2) ? "space" : "mark",
               (unsigned)ppm_ticks_to_us(buffer[i]));
    }
    return 0;
}
