// Bus mode: the eight light channels as one addressed data frame.
//
// The classic layout spends four RC channels on one zone, so eight channels
// are two zones. Bus mode reads the same eight channels as eight 5 bit symbols
// -- the very quantisation the cue channel already uses -- and carries a small
// frame in them: one zone's state plus every relay. Zones take turns, one per
// RC frame, so more zones cost latency rather than channels.
//
// RS(8,6) over GF(32) guards the frame. Two parity symbols buy *either* the
// repair of one wrong symbol *or* the detection of two -- not both, and which
// one to take was decided by measurement on 17.08.2026.
//
// Repairing accepts everything within distance one of a code word: 8*31+1 =
// 249 words per code word, so **24 % of all possible frames pass**. Detecting
// only accepts code words, one in 1024. That matters because this wire carries
// frames from elsewhere -- a transmitter that drops its trainer input puts its
// own channel values on it, and on the bench such a frame passed the repairing
// decoder every single time and overwrote a zone.
//
// What repairing would have bought: one single-symbol error in 1233 frames.
// A tenth of a percent, against a factor of 249 in false acceptance. So
// detection is the default; a rejected frame leaves the last good state alone.
// Set BUS_CORRECT for a link where symbol errors are the real problem and
// nothing foreign can reach the wire.
//
// This header is free of SDK dependencies so tools/ctest can compile it for
// the host and check it against the Python side.

#ifndef LIGHTSHOW_BUS_H
#define LIGHTSHOW_BUS_H

#include <stdbool.h>
#include <stdint.h>

// Repair one wrong symbol instead of detecting two; see the note above.
#ifndef BUS_CORRECT
#define BUS_CORRECT 0
#endif

#define BUS_SYMBOLS       8    // channels on the wire
#define BUS_DATA_SYMBOLS  6    // RS(8,6)
#define BUS_SYMBOL_BITS   5
#define BUS_PAYLOAD_BITS  (BUS_DATA_SYMBOLS * BUS_SYMBOL_BITS)   // 30
#define BUS_MAX_ZONES     8
#define BUS_MAX_RELAYS    8

// Field widths of one zone's state, in the order they sit in the payload.
#define BUS_CUE_BITS        5
#define BUS_HUE_BITS        6
#define BUS_BRIGHTNESS_BITS 8
#define BUS_PARAM_BITS      5
#define BUS_ZONE_STATE_BITS (BUS_CUE_BITS + BUS_HUE_BITS + \
                             BUS_BRIGHTNESS_BITS + BUS_PARAM_BITS)

// A fixed pattern at the front of every frame, checked before anything else.
// The parity alone cannot tell our frames from somebody else's: one random
// frame in 1024 is a valid code word, and a transmitter that drops its trainer
// input repeats the same substitute values for ever. On the bench that pattern
// *was* a code word -- it passed every time and overwrote a zone. Two bits cost
// one relay slot in the tighter configurations and turn away three out of four
// foreign frames on top of the parity.
#define BUS_MAGIC_BITS 2
#define BUS_MAGIC      0x2

typedef struct {
    uint8_t cue;          // 0..31, a cue step
    uint8_t hue;          // 0..255, widened from six bits
    uint8_t brightness;   // 0..255
    uint8_t param;        // 0..255, widened from five bits
} bus_zone_t;

// "Everything off, every zone", carried by the ground station's failsafe frame
// and by a blackout. A frame addresses one zone, so without this a held
// failsafe frame could only ever darken the one zone it names.
//
// It takes three fields to say it, not one. All-zero payload bits with cue 31
// is precisely what a stray frame lands on -- that happened on the bench, and
// the model went dark for it. Demanding the maxima of hue and param as well
// puts sixteen specific bits in the way, and no real zone state can collide
// because cue 31 is reserved on the wire regardless.
//
// Owned here rather than in the generated header: these describe the wire, not
// the model. host/tests/test_bus.py checks them against the Python side.
#define BUS_CUE_ALL_OFF   31
#define BUS_HUE_ALL_OFF   63
#define BUS_PARAM_ALL_OFF 31

// The fields arrive widened to 0..255, so compare against the widened maxima.
static inline bool bus_is_all_off(const bus_zone_t *state) {
    return state->cue == BUS_CUE_ALL_OFF && state->hue == 255
           && state->param == 255;
}

typedef struct {
    uint8_t    zone;        // which zone this frame addressed
    bus_zone_t state;
    uint8_t    relays;      // bit i is relay i, 0 based
    int8_t     corrected;   // -1 when nothing needed repair, else the symbol
} bus_frame_t;

// How many address bits `zones` zones need; none at all for a single zone.
uint8_t bus_address_bits(uint8_t zones);

// True when this combination fits into the 30 bit payload.
bool bus_fits(uint8_t zones, uint8_t relays);

// One RC channel value to a symbol, the inverse of the ground station's
// placement of a symbol in the middle of its band.
uint8_t bus_us_to_symbol(uint16_t microseconds, uint16_t min_us, uint16_t max_us);

// Eight symbols in, one frame out. False when the damage is beyond repair --
// the caller must then keep the previous state rather than act on rubbish.
bool bus_decode(const uint8_t symbols[BUS_SYMBOLS], uint8_t zones,
                uint8_t relays, bus_frame_t *out);

#endif // LIGHTSHOW_BUS_H
