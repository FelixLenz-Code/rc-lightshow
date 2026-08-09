#ifndef LIGHTSHOW_PORTS_H
#define LIGHTSHOW_PORTS_H

#include <stdbool.h>
#include <stdint.h>
#include "protocol.h"

typedef struct {
    uint8_t  format;      // LS_FMT_*
    uint8_t  flags;       // LS_FLAG_*
    uint8_t  nchan;
    uint16_t frame_us;    // PPM frame length, or SBUS frame interval
    uint16_t sync_us;     // PPM mark width (unused for SBUS)
    uint16_t min_us;
    uint16_t max_us;
    uint16_t failsafe[LS_MAX_CH];
} ls_port_cfg_t;

// GPIOs carrying the eight trainer outputs, port 0 first.
extern const uint8_t LS_PORT_GPIO[LS_MAX_PORTS];

// Tears down any running configuration and brings the given ports up.
// Returns false if the configuration is not usable; in that case all outputs
// stay idle.
bool ports_configure(const ls_port_cfg_t *cfgs, uint8_t nports);

// Latest channel values in microseconds. Ignored for ports that are not
// configured, and clamped to the port's min/max.
void ports_set_channels(uint8_t port, const uint16_t *values_us, uint8_t nchan);

// Drives every configured port to its failsafe values.
void ports_apply_failsafe(void);

uint8_t ports_count(void);
bool ports_configured(void);

#endif // LIGHTSHOW_PORTS_H
