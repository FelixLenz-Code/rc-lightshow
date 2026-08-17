// Output stage of the airborne controller.
//
// A model declares three tables in config.h:
//
//   zones   -- each zone has its own block of four RC channels and therefore
//              its own effect. One zone is the normal case; a second one lets
//              the wings run a different pattern than the fuselage.
//   strips  -- WS2812 chains. Several strips may share a zone; their `offset`
//              decides whether they mirror each other or form one long virtual
//              chain that a chase can run across.
//   relays  -- switched outputs, each following a configurable source.
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

#define MAX_ZONES        4
#define MAX_STRIPS       8   // 4 PIO state machines per block, two blocks
#define MAX_RELAYS       8
#define MAX_ZONE_PIXELS  256
#define MAX_NAV_LIGHTS   16

typedef struct {
    uint8_t base_channel;   // first of this zone's four RC channels, 1 based
} zone_cfg_t;

typedef struct {
    uint8_t  pin;
    uint16_t count;
    uint8_t  zone;
    uint16_t offset;   // position inside the zone's virtual chain
    bool     reverse;  // strip physically mounted the other way round
} strip_cfg_t;

// relay_source_t and the switching logic live in relay_logic.h, which is free
// of SDK dependencies so both can be tested on a PC.

typedef struct {
    uint8_t        pin;
    uint8_t        zone;
    relay_source_t source;
    uint16_t       arg;
    uint8_t        threshold;   // 0..255, meaning depends on the source
    bool           active_low;  // most ready-made relay boards are
    uint16_t       min_on_ms;   // 0 for MOSFETs
    uint16_t       min_off_ms;
} relay_cfg_t;

typedef struct {
    uint8_t  strip;
    uint16_t index;
    uint8_t  r, g, b;
} nav_light_t;

void outputs_init(void);

// Length of the virtual chain a zone has to render, in pixels.
uint16_t outputs_zone_pixels(uint8_t zone);

// Pushes a rendered zone to all its strips, stamping the navigation lights on
// top. `pixels` must hold outputs_zone_pixels(zone) entries.
void outputs_show(uint8_t zone, const rgb_t *pixels);

// Evaluates every relay of one zone. `pixels` is the buffer just rendered.
void outputs_update_relays(uint8_t zone, const show_state_t *show,
                           const rgb_t *pixels, const rc_state_t *rc,
                           uint32_t now_ms);

// Drops every relay, whatever the minimum times say. Used on RC loss.
void outputs_relays_off(void);

// What the last bus frame said: a bit per directly switched relay, and whether
// everything has to stay dark regardless. Only bus builds call this; in a
// classic build the values simply stay zero and no relay source reads them.
void outputs_set_bus_relays(uint8_t bitmap, bool all_off);

uint8_t outputs_zone_count(void);

// First of a zone's four RC channels, 1 based.
uint8_t outputs_zone_base_channel(uint8_t zone);

#endif // PLANE_OUTPUTS_H
