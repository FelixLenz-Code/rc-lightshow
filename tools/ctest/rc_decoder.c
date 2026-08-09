// Dumps the airborne decoder's view of every possible pulse width, so
// host/tests/test_cross_check.py can confirm that what the ground station
// encodes is exactly what the model decodes.
//
//   rc_decoder step <steps> <min_us> <max_us>
//   rc_decoder u8 <min_us> <max_us>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rc_decode.h"

int main(int argc, char **argv) {
    if (argc >= 5 && strcmp(argv[1], "step") == 0) {
        int steps = atoi(argv[2]);
        int min_us = atoi(argv[3]);
        int max_us = atoi(argv[4]);
        for (int us = min_us; us <= max_us; us++) {
            printf("%d %u\n", us,
                   rc_decode_step((uint16_t)us, (uint16_t)min_us, (uint16_t)max_us,
                                  (uint8_t)steps));
        }
        return 0;
    }
    if (argc >= 4 && strcmp(argv[1], "u8") == 0) {
        int min_us = atoi(argv[2]);
        int max_us = atoi(argv[3]);
        for (int us = min_us; us <= max_us; us++) {
            printf("%d %u\n", us,
                   rc_decode_u8((uint16_t)us, (uint16_t)min_us, (uint16_t)max_us));
        }
        return 0;
    }
    fprintf(stderr, "usage: rc_decoder step <steps> <min> <max> | u8 <min> <max>\n");
    return 2;
}
