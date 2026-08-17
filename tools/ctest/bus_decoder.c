// Reads bus frames on stdin and prints what the firmware made of them, so the
// Python suite can check the encoder against the decoder that actually flies.
//
//   frame <zones> <relays> <s0..s7>  -> "ok zone cue hue brightness param
//                                        relays corrected", or "reject"
//   us <microseconds> <min> <max>    -> "symbol <n>"

#include <stdio.h>
#include <string.h>

#include "bus.h"

int main(void) {
    char what[16];

    while (scanf("%15s", what) == 1) {
        if (strcmp(what, "frame") == 0) {
            unsigned zones, relays, symbol[BUS_SYMBOLS];
            if (scanf("%u %u %u %u %u %u %u %u %u %u", &zones, &relays,
                      &symbol[0], &symbol[1], &symbol[2], &symbol[3],
                      &symbol[4], &symbol[5], &symbol[6], &symbol[7]) != 10) {
                break;
            }
            uint8_t symbols[BUS_SYMBOLS];
            for (int i = 0; i < BUS_SYMBOLS; i++) symbols[i] = (uint8_t)symbol[i];

            bus_frame_t frame;
            if (!bus_decode(symbols, (uint8_t)zones, (uint8_t)relays, &frame)) {
                printf("reject\n");
                continue;
            }
            printf("ok %u %u %u %u %u %u %d\n",
                   frame.zone, frame.state.cue, frame.state.hue,
                   frame.state.brightness, frame.state.param,
                   frame.relays, frame.corrected);
        } else if (strcmp(what, "consts") == 0) {
            // So the test can check both sides agree on the wire's constants.
            printf("consts %d %d %d %d %d %d\n", BUS_SYMBOLS, BUS_DATA_SYMBOLS,
                   BUS_PAYLOAD_BITS, BUS_CUE_ALL_OFF, BUS_HUE_ALL_OFF,
                   BUS_PARAM_ALL_OFF);
        } else if (strcmp(what, "us") == 0) {
            unsigned microseconds, min_us, max_us;
            if (scanf("%u %u %u", &microseconds, &min_us, &max_us) != 3) break;
            printf("symbol %u\n", bus_us_to_symbol((uint16_t)microseconds,
                                                   (uint16_t)min_us,
                                                   (uint16_t)max_us));
        } else {
            break;
        }
    }
    return 0;
}
