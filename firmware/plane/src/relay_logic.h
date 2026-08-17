// Relay switching: what a relay wants to do, and how fast it is allowed to.
//
// A MOSFET can follow a 10 Hz strobe forever. A mechanical relay cannot: it
// needs 5..10 ms to move, clatters audibly and wears out after a few hundred
// thousand operations. The minimum times let a slow relay ride on the same
// effect without chattering -- it simply switches less often than the LEDs.
//
// SDK independent on purpose, so both the decision and the timing can be tested
// on a PC; see tools/ctest/relay_sim.c and host/tests/test_relay_logic.py.

#ifndef PLANE_RELAY_LOGIC_H
#define PLANE_RELAY_LOGIC_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    // Follows one pixel of the zone, so the relay blinks exactly with the
    // effect. Costs no extra RC channel. `arg` is the pixel index.
    RELAY_SRC_PIXEL = 0,
    // On while the zone's master dimmer is above `threshold`.
    RELAY_SRC_BRIGHTNESS,
    // On from cue `arg` upwards. Cue 0 always switches everything off.
    RELAY_SRC_CUE,
    // On while RC channel `arg` (1 based, absolute) is above `threshold`.
    RELAY_SRC_CHANNEL,
    // Switched straight over the bus: `arg` is the slot in the frame's relay
    // field. The only source that does not hang off a zone's state, which is
    // exactly why it costs payload bits.
    RELAY_SRC_BUS,
} relay_source_t;

typedef struct {
    uint8_t cue;
    uint8_t brightness;
    uint8_t pixel_level;    // brightest component of the referenced pixel
    uint8_t channel_level;  // referenced RC channel, decoded to 0..255
    bool    pixel_valid;    // false when the pixel index is out of range
    bool    bus_on;         // this relay's own bit in the last bus frame
    bool    all_off;        // failsafe, blackout or a frame carrying CUE_ALL_OFF
} relay_inputs_t;

typedef struct {
    bool     state;
    bool     started;
    uint32_t last_change_ms;
} relay_state_t;

// Whether the relay should be on, ignoring the minimum times.
static inline bool relay_wants(relay_source_t source, uint16_t arg,
                               uint8_t threshold, const relay_inputs_t *in) {
    // Nothing survives this: failsafe, blackout, or a frame that says so.
    if (in->all_off) return false;

    // A bus relay is switched directly and deliberately does not hang off a
    // zone's cue -- being independent of the zones is what it is for.
    if (source == RELAY_SRC_BUS) {
        (void)arg;
        return in->bus_on;
    }

    // Cue 0 means "everything off" -- that has to include the relays.
    if (in->cue == 0) return false;

    switch (source) {
    case RELAY_SRC_PIXEL:
        return in->pixel_valid && in->pixel_level > threshold;
    case RELAY_SRC_BRIGHTNESS:
        return in->brightness > threshold;
    case RELAY_SRC_CUE:
        return in->cue >= arg;
    case RELAY_SRC_CHANNEL:
        return in->channel_level > threshold;
    case RELAY_SRC_BUS:
        break;                          // handled above
    }
    return false;
}

// Advances one relay towards `want` and returns the state it should hold now.
//
// A pending change is not queued: if the input returns to the current state
// while the minimum time is still running, nothing happens at all. That is what
// keeps a slow relay calm during a fast strobe instead of making it lag behind
// by one flash.
static inline bool relay_step(relay_state_t *relay, bool want, uint32_t now_ms,
                              uint16_t min_on_ms, uint16_t min_off_ms) {
    if (!relay->started) {
        relay->started = true;
        relay->state = want;
        relay->last_change_ms = now_ms;
        return relay->state;
    }
    if (want == relay->state) {
        return relay->state;
    }

    // Leaving the current state costs the minimum time of that state.
    uint32_t required = relay->state ? min_on_ms : min_off_ms;
    if (now_ms - relay->last_change_ms < required) {
        return relay->state;
    }

    relay->state = want;
    relay->last_change_ms = now_ms;
    return relay->state;
}

// Level a driver pin has to be driven to. Most ready-made relay boards switch
// on when their input is pulled low.
static inline bool relay_pin_level(bool state, bool active_low) {
    return active_low ? !state : state;
}

#endif // PLANE_RELAY_LOGIC_H
