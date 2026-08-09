// Runs the airborne relay logic on the host so its timing can be tested.
//
//   relay_sim step <min_on_ms> <min_off_ms>
//       stdin:  "<time_ms> <want>" per line
//       stdout: "<time_ms> <state>" per line
//
//   relay_sim want <source> <arg> <threshold>
//       stdin:  "<cue> <brightness> <pixel_level> <channel_level> <pixel_valid>"
//       stdout: "<want>" per line
//
// source: 0 pixel, 1 brightness, 2 cue, 3 channel

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "relay_logic.h"

static int run_step(int argc, char **argv) {
    if (argc < 4) return 2;
    uint16_t min_on = (uint16_t)atoi(argv[2]);
    uint16_t min_off = (uint16_t)atoi(argv[3]);

    relay_state_t relay = {0};
    unsigned long t;
    int want;
    while (scanf("%lu %d", &t, &want) == 2) {
        bool state = relay_step(&relay, want != 0, (uint32_t)t, min_on, min_off);
        printf("%lu %d\n", t, state ? 1 : 0);
    }
    return 0;
}

static int run_want(int argc, char **argv) {
    if (argc < 5) return 2;
    relay_source_t source = (relay_source_t)atoi(argv[2]);
    uint16_t arg = (uint16_t)atoi(argv[3]);
    uint8_t threshold = (uint8_t)atoi(argv[4]);

    int cue, brightness, pixel, channel, valid;
    while (scanf("%d %d %d %d %d", &cue, &brightness, &pixel, &channel, &valid) == 5) {
        relay_inputs_t in = {
            .cue = (uint8_t)cue,
            .brightness = (uint8_t)brightness,
            .pixel_level = (uint8_t)pixel,
            .channel_level = (uint8_t)channel,
            .pixel_valid = valid != 0,
        };
        printf("%d\n", relay_wants(source, arg, threshold, &in) ? 1 : 0);
    }
    return 0;
}

static int run_pin(int argc, char **argv) {
    if (argc < 3) return 2;
    bool active_low = atoi(argv[2]) != 0;

    int state;
    while (scanf("%d", &state) == 1) {
        printf("%d\n", relay_pin_level(state != 0, active_low) ? 1 : 0);
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc >= 2 && strcmp(argv[1], "step") == 0) return run_step(argc, argv);
    if (argc >= 2 && strcmp(argv[1], "want") == 0) return run_want(argc, argv);
    if (argc >= 2 && strcmp(argv[1], "pin") == 0) return run_pin(argc, argv);
    fprintf(stderr, "usage: relay_sim step <min_on> <min_off>\n"
                    "       relay_sim want <source> <arg> <threshold>\n"
                    "       relay_sim pin <active_low>\n");
    return 2;
}
