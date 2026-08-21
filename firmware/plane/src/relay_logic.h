// Relay switching: what a relay wants to do, and how fast it is allowed to.
//
// A MOSFET can follow every switch it is given. A mechanical relay cannot: it
// needs 5..10 ms to move, clatters audibly and wears out after a few hundred
// thousand operations. The minimum times let a slow relay hang on the same bit
// as a fast one -- it simply switches less often than it is told to.
//
// SDK independent on purpose, so both the decision and the timing can be tested
// on a PC; see tools/ctest/relay_sim.c and host/tests/test_relay_logic.py.

#ifndef PLANE_RELAY_LOGIC_H
#define PLANE_RELAY_LOGIC_H

#include <stdbool.h>
#include <stdint.h>

// A relay is switched over the bus and nowhere else: its own bit in the frame,
// carried in every frame rather than with a zone. There used to be sources that
// derived the state on board instead -- from a pixel, the master dimmer, a cue
// number or a raw RC channel. They cost no payload bits, but every one of them
// tied the relay to something else that was going on, and having two ways meant
// every rule about relays had two answers. One way, one answer.
typedef struct {
    bool bus_on;    // this relay's own bit in the last bus frame
    bool all_off;   // failsafe, blackout or a frame carrying CUE_ALL_OFF
} relay_inputs_t;

typedef struct {
    bool     state;
    bool     started;
    uint32_t last_change_ms;
} relay_state_t;

// Whether the relay should be on, ignoring the minimum times.
static inline bool relay_wants(const relay_inputs_t *in) {
    // Nothing survives this: failsafe, blackout, or a frame that says so.
    if (in->all_off) return false;
    return in->bus_on;
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
