#include "bus.h"

// GF(2^5) with x^5 + x^2 + 1. The tables are written out rather than computed
// at boot: 94 bytes of flash against a loop that would have to run before the
// first frame can be read.
static const uint8_t GF_EXP[62] = {
     1,  2,  4,  8, 16,  5, 10, 20, 13, 26, 17,  7, 14, 28, 29, 31,
    27, 19,  3,  6, 12, 24, 21, 15, 30, 25, 23, 11, 22,  9, 18,  1,
     2,  4,  8, 16,  5, 10, 20, 13, 26, 17,  7, 14, 28, 29, 31, 27,
    19,  3,  6, 12, 24, 21, 15, 30, 25, 23, 11, 22,  9, 18,
};

static const uint8_t GF_LOG[32] = {
     0,  0,  1, 18,  2,  5, 19, 11,  3, 29,  6, 27, 20,  8, 12, 23,
     4, 10, 30, 17,  7, 22, 28, 26, 21, 25,  9, 16, 13, 14, 24, 15,
};

static uint8_t gf_mul(uint8_t a, uint8_t b) {
    if (a == 0 || b == 0) return 0;
    return GF_EXP[GF_LOG[a] + GF_LOG[b]];
}

#if BUS_CORRECT
// Only the repair needs division: locating the faulty symbol is a quotient of
// the two syndromes. The detecting decoder never asks where the damage is.
static uint8_t gf_div(uint8_t a, uint8_t b) {
    if (a == 0 || b == 0) return 0;      // b == 0 is filtered by the caller
    int diff = (int)GF_LOG[a] - (int)GF_LOG[b];
    if (diff < 0) diff += 31;
    return GF_EXP[diff];
}
#endif

uint8_t bus_address_bits(uint8_t zones) {
    if (zones <= 1) return 0;
    uint8_t bits = 0;
    uint8_t last = (uint8_t)(zones - 1);
    while (last) { bits++; last >>= 1; }
    return bits;
}

bool bus_fits(uint8_t zones, uint8_t relays) {
    if (zones < 1 || zones > BUS_MAX_ZONES) return false;
    if (relays > BUS_MAX_RELAYS) return false;
    uint16_t used = (uint16_t)relays + bus_address_bits(zones)
                    + BUS_ZONE_STATE_BITS + BUS_MAGIC_BITS;
    return used <= BUS_PAYLOAD_BITS;
}

uint8_t bus_us_to_symbol(uint16_t microseconds, uint16_t min_us, uint16_t max_us) {
    if (max_us <= min_us) return 0;
    if (microseconds <= min_us) return 0;
    uint32_t span = (uint32_t)(max_us - min_us);
    uint32_t index = ((uint32_t)(microseconds - min_us) * 32u) / span;
    return (uint8_t)(index > 31u ? 31u : index);
}

bool bus_decode(const uint8_t symbols[BUS_SYMBOLS], uint8_t zones,
                uint8_t relays, bus_frame_t *out) {
    if (out == 0 || !bus_fits(zones, relays)) return false;

    // Syndromes: the codeword at a^0 and a^1, both zero when nothing is wrong.
    uint8_t s0 = 0;
    uint8_t s1 = 0;
    for (uint8_t i = 0; i < BUS_SYMBOLS; i++) {
        uint8_t symbol = symbols[i] & 31u;
        s0 ^= symbol;
        s1 ^= gf_mul(symbol, GF_EXP[BUS_SYMBOLS - 1 - i]);
    }

    uint8_t data[BUS_DATA_SYMBOLS];
    for (uint8_t i = 0; i < BUS_DATA_SYMBOLS; i++) data[i] = symbols[i] & 31u;
    int8_t corrected = -1;

    if (s0 != 0 || s1 != 0) {
#if BUS_CORRECT
        // A single symbol fault has a non zero magnitude; anything else here
        // is more damage than this code can undo.
        if (s0 == 0) return false;
        uint8_t position = GF_LOG[gf_div(s1, s0)];
        if (position >= BUS_SYMBOLS) return false;
        uint8_t index = (uint8_t)(BUS_SYMBOLS - 1 - position);
        if (index < BUS_DATA_SYMBOLS) {
            data[index] ^= s0;
        }
        corrected = (int8_t)index;
#else
        // Not a code word: somebody else's frame, or a broken one. Either way
        // the last good state is the better answer -- see bus.h for why this
        // is the default.
        return false;
#endif
    }

    // The payload, most significant bit first.
    uint32_t bits = 0;
    for (uint8_t i = 0; i < BUS_DATA_SYMBOLS; i++) {
        bits = (bits << BUS_SYMBOL_BITS) | data[i];
    }

    uint8_t offset = BUS_PAYLOAD_BITS;
    uint8_t address = bus_address_bits(zones);

    // Checked before anything else: the parity cannot tell our frames from a
    // transmitter's own channels, and on the bench such a frame was a valid
    // code word. See bus.h.
    offset -= BUS_MAGIC_BITS;
    if (((bits >> offset) & ((1u << BUS_MAGIC_BITS) - 1u)) != BUS_MAGIC) {
        return false;
    }

    offset -= relays;
    uint32_t relay_word = relays ? ((bits >> offset) & ((1u << relays) - 1u)) : 0u;
    offset -= address;
    uint8_t zone = address ? (uint8_t)((bits >> offset) & ((1u << address) - 1u)) : 0u;

    offset -= BUS_CUE_BITS;
    uint8_t cue = (uint8_t)((bits >> offset) & 31u);
    offset -= BUS_HUE_BITS;
    uint8_t hue = (uint8_t)((bits >> offset) & 63u);
    offset -= BUS_BRIGHTNESS_BITS;
    uint8_t brightness = (uint8_t)((bits >> offset) & 255u);
    offset -= BUS_PARAM_BITS;
    uint8_t param = (uint8_t)((bits >> offset) & 31u);

    // An address the configuration cannot hold means the frame is not what it
    // claims to be, however well the syndromes came out.
    if (zone >= zones) return false;

    out->zone = zone;
    out->state.cue = cue;
    // Widen to the full byte the effects expect: 63 must become 255, not 252,
    // or full saturation would never be reachable.
    out->state.hue = (uint8_t)((hue * 255u) / 63u);
    out->state.brightness = brightness;
    out->state.param = (uint8_t)((param * 255u) / 31u);
    out->relays = 0;
    for (uint8_t i = 0; i < relays; i++) {
        if (relay_word & (1u << (relays - 1 - i))) out->relays |= (uint8_t)(1u << i);
    }
    out->corrected = corrected;
    return true;
}
