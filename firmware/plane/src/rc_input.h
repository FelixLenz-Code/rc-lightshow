#ifndef PLANE_RC_INPUT_H
#define PLANE_RC_INPUT_H

#include <stdbool.h>
#include <stdint.h>

#define RC_MAX_CHANNELS 16

typedef enum {
    RC_SOURCE_NONE = 0,
    RC_SOURCE_SBUS,
    RC_SOURCE_PWM,
} rc_source_t;

typedef struct {
    uint16_t channel_us[RC_MAX_CHANNELS];
    uint8_t  channel_count;
    rc_source_t source;
    bool     valid;          // false once the link has been quiet for too long
} rc_state_t;

void rc_input_init(void);

// Call from the main loop; decodes whatever has arrived and ages out stale data.
void rc_input_poll(rc_state_t *out);

// Channel value in microseconds, 1-based as the transmitter counts them.
// Returns the failsafe centre when the channel is not available.
uint16_t rc_channel_us(const rc_state_t *state, uint8_t channel);

#endif // PLANE_RC_INPUT_H
