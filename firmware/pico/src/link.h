#ifndef LIGHTSHOW_LINK_H
#define LIGHTSHOW_LINK_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    uint32_t frames_ok;
    uint32_t crc_errors;
    uint32_t bad_frames;    // unknown type, bad length or rejected config
    uint32_t seq_gaps;
    uint32_t config_count;
    uint8_t  last_seq;
    bool     have_seq;
} link_stats_t;

void link_init(void);

// Feeds one received byte into the parser. Returns true when that byte
// completed a valid CHANNELS frame, which is what resets the failsafe timer.
bool link_feed(uint8_t byte);

const link_stats_t *link_get_stats(void);

#endif // LIGHTSHOW_LINK_H
