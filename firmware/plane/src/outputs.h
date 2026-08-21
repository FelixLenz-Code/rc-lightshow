// Output stage of the airborne controller.
//
// A model declares four tables in config.h:
//
//   zones     -- each zone has its own effect. One zone is the normal case; a
//                second one lets the wings run a different pattern than the
//                fuselage. In bus mode the zones take turns on the wire.
//   outputs   -- the physical WS2812 chains. One chain is one GPIO and one PIO
//                state machine, and that is the hard limit: eight of them.
//   segments  -- a stretch of pixels on one chain, belonging to one zone. This
//                is the layer that lets a single 60 pixel chain be a wing in
//                its first half and a fuselage in its second. Several segments
//                may share a zone; their `offset` decides whether they mirror
//                each other or form one long virtual chain for a chase.
//   relays    -- switched outputs, each following a configurable source.
//
// Why the split into outputs and segments: the wire is physical and the zone is
// editorial, and they used to be the same table. That forced one chain to be
// exactly one zone, which is a soldering decision dictating a lighting decision.
//
// This header must not include config.h -- config.h includes this one to get
// the types and the limits.

#ifndef PLANE_OUTPUTS_H
#define PLANE_OUTPUTS_H

#include <stdbool.h>
#include <stdint.h>

#include "effects.h"
#include "rc_input.h"
#include "relay_logic.h"

#define MAX_ZONES          8   // the bus address field carries this many
#define MAX_OUTPUTS        8   // 4 PIO state machines per block, two blocks
#define MAX_SEGMENTS      16
#define MAX_RELAYS         8
#define MAX_ZONE_PIXELS  256   // longest virtual chain one zone may render
#define MAX_OUTPUT_PIXELS 256  // longest physical chain on one GPIO
#define MAX_NAV_LIGHTS    16

typedef struct {
    uint8_t base_channel;   // first of this zone's four RC channels, 1 based
} zone_cfg_t;

// One physical chain. `first` is where its pixels start in the shared frame
// buffer, so the buffer stays one flat array however the chains are sized.
typedef struct {
    uint8_t  pin;
    uint16_t count;
    uint16_t first;
} output_cfg_t;

// A stretch of one chain that belongs to one zone.
typedef struct {
    uint8_t  output;   // index into the outputs table
    uint16_t start;    // first pixel of this segment on that chain
    uint16_t count;
    uint8_t  zone;
    uint16_t offset;   // position inside the zone's virtual chain
    bool     reverse;  // segment physically mounted the other way round
} segment_cfg_t;

// The switching logic lives in relay_logic.h, which is free of SDK dependencies
// so both the decision and the timing can be tested on a PC.
//
// A relay carries no slot number: its position in this table *is* its bit in
// the bus frame. The ground station fills the frame from a list in the same
// order, and the configuration check holds the two side by side.
typedef struct {
    uint8_t  pin;
    bool     active_low;  // most ready-made relay boards are
    uint16_t min_on_ms;   // 0 for MOSFETs
    uint16_t min_off_ms;
} relay_cfg_t;

// Navigation lights sit on a physical chain, not on a zone -- they are a lamp
// at a wingtip, and which zone happens to cover that pixel is irrelevant.
typedef struct {
    uint8_t  output;
    uint16_t index;   // absolute pixel on that chain
    uint8_t  r, g, b;
} nav_light_t;

void outputs_init(void);

// Length of the virtual chain a zone has to render, in pixels.
uint16_t outputs_zone_pixels(uint8_t zone);

// Places a rendered zone into the frame buffer, following its segments. Call
// once per zone, then outputs_flush() once for the whole pass. `pixels` must
// hold outputs_zone_pixels(zone) entries.
void outputs_show(uint8_t zone, const rgb_t *pixels);

// Pushes every chain to its state machine, navigation lights stamped on top.
void outputs_flush(void);

// Evaluates every relay, once per render pass, from the last bus frame alone.
// Nothing about a zone reaches this any more.
void outputs_update_relays(uint32_t now_ms);

// Drops every relay, whatever the minimum times say. Used on RC loss.
void outputs_relays_off(void);

// What the last bus frame said about the directly switched relays.
void outputs_set_bus_relays(uint8_t bitmap, bool all_off);

uint8_t outputs_zone_count(void);
uint8_t outputs_zone_base_channel(uint8_t zone);

#endif // PLANE_OUTPUTS_H
