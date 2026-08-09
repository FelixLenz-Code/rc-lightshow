#include "link.h"

#include <string.h>

#include "ports.h"
#include "protocol.h"

typedef enum {
    ST_MAGIC0 = 0,
    ST_MAGIC1,
    ST_HEADER,   // ver, type, len_lo, len_hi
    ST_PAYLOAD,
    ST_CRC,
} parse_state_t;

static parse_state_t s_state;
static uint8_t  s_header[4];
static uint8_t  s_payload[LS_MAX_PAYLOAD];
static uint16_t s_len;
static uint16_t s_got;
static uint8_t  s_crc_buf[2];
static link_stats_t s_stats;

static inline uint16_t rd_u16(const uint8_t *p) {
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static void handle_config(const uint8_t *p, uint16_t len) {
    if (len < 1) { s_stats.bad_frames++; return; }

    uint8_t nports = p[0];
    if (nports > LS_MAX_PORTS) { s_stats.bad_frames++; return; }

    ls_port_cfg_t cfgs[LS_MAX_PORTS];
    memset(cfgs, 0, sizeof(cfgs));

    uint16_t off = 1;
    for (uint8_t i = 0; i < nports; i++) {
        if (off + 11 > len) { s_stats.bad_frames++; return; }
        ls_port_cfg_t *c = &cfgs[i];
        c->format   = p[off + 0];
        c->flags    = p[off + 1];
        c->nchan    = p[off + 2];
        c->frame_us = rd_u16(&p[off + 3]);
        c->sync_us  = rd_u16(&p[off + 5]);
        c->min_us   = rd_u16(&p[off + 7]);
        c->max_us   = rd_u16(&p[off + 9]);
        off += 11;

        if (c->nchan > LS_MAX_CH) { s_stats.bad_frames++; return; }
        if (off + 2u * c->nchan > len) { s_stats.bad_frames++; return; }
        for (uint8_t ch = 0; ch < c->nchan; ch++) {
            c->failsafe[ch] = rd_u16(&p[off + 2 * ch]);
        }
        off += 2u * c->nchan;
    }

    if (ports_configure(cfgs, nports)) {
        s_stats.config_count++;
        s_stats.have_seq = false;
    } else {
        s_stats.bad_frames++;
    }
}

static bool handle_channels(const uint8_t *p, uint16_t len) {
    if (!ports_configured()) { s_stats.bad_frames++; return false; }
    if (len < 2) { s_stats.bad_frames++; return false; }

    uint8_t seq = p[0];
    uint8_t nports = p[1];
    if (nports > ports_count()) { s_stats.bad_frames++; return false; }

    uint16_t off = 2;
    for (uint8_t i = 0; i < nports; i++) {
        if (off + 1 > len) { s_stats.bad_frames++; return false; }
        uint8_t nchan = p[off++];
        if (nchan > LS_MAX_CH || off + 2u * nchan > len) {
            s_stats.bad_frames++;
            return false;
        }
        uint16_t values[LS_MAX_CH];
        for (uint8_t ch = 0; ch < nchan; ch++) {
            values[ch] = rd_u16(&p[off + 2 * ch]);
        }
        off += 2u * nchan;
        ports_set_channels(i, values, nchan);
    }

    if (s_stats.have_seq && (uint8_t)(s_stats.last_seq + 1) != seq) {
        s_stats.seq_gaps++;
    }
    s_stats.last_seq = seq;
    s_stats.have_seq = true;
    return true;
}

void link_init(void) {
    s_state = ST_MAGIC0;
    s_len = 0;
    s_got = 0;
    memset(&s_stats, 0, sizeof(s_stats));
}

bool link_feed(uint8_t byte) {
    switch (s_state) {
    case ST_MAGIC0:
        if (byte == LS_MAGIC0) s_state = ST_MAGIC1;
        return false;

    case ST_MAGIC1:
        // A second 0xA5 keeps us waiting for the 0x5A, so a truncated frame
        // followed by a fresh one still resynchronises.
        s_state = (byte == LS_MAGIC1) ? ST_HEADER : (byte == LS_MAGIC0 ? ST_MAGIC1 : ST_MAGIC0);
        s_got = 0;
        return false;

    case ST_HEADER:
        s_header[s_got++] = byte;
        if (s_got < 4) return false;
        s_len = rd_u16(&s_header[2]);
        if (s_header[0] != LS_VERSION || s_len > LS_MAX_PAYLOAD) {
            s_stats.bad_frames++;
            s_state = ST_MAGIC0;
            return false;
        }
        s_got = 0;
        s_state = s_len ? ST_PAYLOAD : ST_CRC;
        return false;

    case ST_PAYLOAD:
        s_payload[s_got++] = byte;
        if (s_got < s_len) return false;
        s_got = 0;
        s_state = ST_CRC;
        return false;

    case ST_CRC: {
        s_crc_buf[s_got++] = byte;
        if (s_got < 2) return false;
        s_state = ST_MAGIC0;
        s_got = 0;

        uint16_t want = rd_u16(s_crc_buf);
        uint16_t crc = ls_crc16(s_header, 4);
        // Continue the CRC over the payload without copying it together.
        for (uint16_t i = 0; i < s_len; i++) {
            crc ^= (uint16_t)s_payload[i] << 8;
            for (int b = 0; b < 8; b++) {
                crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
            }
        }
        if (crc != want) {
            s_stats.crc_errors++;
            return false;
        }

        s_stats.frames_ok++;
        switch (s_header[1]) {
        case LS_TYPE_CONFIG:
            handle_config(s_payload, s_len);
            return false;
        case LS_TYPE_CHANNELS:
            return handle_channels(s_payload, s_len);
        default:
            s_stats.bad_frames++;
            return false;
        }
    }
    }
    return false;
}

const link_stats_t *link_get_stats(void) { return &s_stats; }
