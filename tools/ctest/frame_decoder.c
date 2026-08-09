// Cross-check harness.
//
// Compiles the real firmware frame parser (firmware/pico/src/link.c and
// crc16.c) for the host, feeds it the bytes the Python ground station produces
// and prints what the firmware understood. If the two implementations ever
// disagree about CRC, endianness or field order, the comparison in
// host/tests/test_cross_check.py fails.
//
// Reads the byte stream on stdin, writes one text line per decoded event.

#include <stdio.h>
#include <string.h>

#include "link.h"
#include "ports.h"
#include "protocol.h"

// ---- Stub of the port layer: records instead of driving hardware. ----------

static ls_port_cfg_t g_cfgs[LS_MAX_PORTS];
static uint8_t g_nports;
static bool g_configured;

const uint8_t LS_PORT_GPIO[LS_MAX_PORTS] = {2, 3, 4, 5, 6, 7, 8, 9};

bool ports_configure(const ls_port_cfg_t *cfgs, uint8_t nports) {
    if (nports > LS_MAX_PORTS) return false;
    memcpy(g_cfgs, cfgs, sizeof(ls_port_cfg_t) * nports);
    g_nports = nports;
    g_configured = true;

    printf("CONFIG nports=%u\n", nports);
    for (uint8_t i = 0; i < nports; i++) {
        const ls_port_cfg_t *c = &cfgs[i];
        printf("PORT %u fmt=%u flags=%u nchan=%u frame=%u sync=%u min=%u max=%u fs=",
               i, c->format, c->flags, c->nchan, c->frame_us, c->sync_us,
               c->min_us, c->max_us);
        for (uint8_t ch = 0; ch < c->nchan; ch++) {
            printf("%s%u", ch ? "," : "", c->failsafe[ch]);
        }
        printf("\n");
    }
    return true;
}

void ports_set_channels(uint8_t port, const uint16_t *values_us, uint8_t nchan) {
    if (port >= g_nports) return;
    const ls_port_cfg_t *c = &g_cfgs[port];
    printf("CH %u ", port);
    for (uint8_t i = 0; i < nchan; i++) {
        uint16_t v = values_us[i];
        if (v < c->min_us) v = c->min_us;
        if (v > c->max_us) v = c->max_us;
        printf("%s%u", i ? "," : "", v);
    }
    printf("\n");
}

void ports_apply_failsafe(void) { printf("FAILSAFE\n"); }
uint8_t ports_count(void) { return g_nports; }
bool ports_configured(void) { return g_configured; }

// ---------------------------------------------------------------------------

int main(void) {
    link_init();

    int byte;
    while ((byte = getchar()) != EOF) {
        if (link_feed((uint8_t)byte)) {
            printf("FRAME\n");
        }
    }

    const link_stats_t *s = link_get_stats();
    printf("STATS ok=%u crc_err=%u bad=%u gaps=%u cfg=%u\n", s->frames_ok,
           s->crc_errors, s->bad_frames, s->seq_gaps, s->config_count);
    return 0;
}
