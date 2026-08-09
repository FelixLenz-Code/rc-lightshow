#include "selftest.h"

#include <stdio.h>
#include <string.h>

#include "hardware/gpio.h"
#include "pico/stdlib.h"
#include "pico/time.h"

#include "protocol.h"

// One PPM frame has 2 * (channels + 1) edges; 96 covers a 16 channel frame
// twice over, which is what the analysis needs to measure a full frame.
#define EDGE_COUNT 96
// Anything longer than this is the idle gap at the end of a frame.
#define SYNC_GAP_US 2500

typedef struct {
    uint32_t t;
    uint8_t  level;
} edge_t;

static volatile edge_t s_edges[EDGE_COUNT];
static volatile uint32_t s_head;
static uint32_t s_last_head;

static void selftest_irq(uint gpio, uint32_t events) {
    if (gpio != SELFTEST_PIN) return;
    uint32_t head = s_head;
    s_edges[head % EDGE_COUNT].t = time_us_32();
    s_edges[head % EDGE_COUNT].level = (events & GPIO_IRQ_EDGE_RISE) ? 1u : 0u;
    s_head = head + 1;
}

void selftest_init(void) {
    gpio_init(SELFTEST_PIN);
    gpio_set_dir(SELFTEST_PIN, GPIO_IN);
    gpio_pull_down(SELFTEST_PIN);
    gpio_set_irq_enabled_with_callback(SELFTEST_PIN,
                                       GPIO_IRQ_EDGE_RISE | GPIO_IRQ_EDGE_FALL,
                                       true, selftest_irq);
}

bool selftest_report(char *buf, size_t len) {
    uint32_t head = s_head;
    if (head == s_last_head) {
        s_last_head = head;
        return false;  // nothing connected, or the line is dead
    }
    s_last_head = head;

    if (head < EDGE_COUNT) {
        snprintf(buf, len, "SELFTEST waiting for a full frame");
        return true;
    }

    // Copy the most recent window, then make sure it did not move underneath us.
    edge_t window[EDGE_COUNT];
    for (int attempt = 0; attempt < 2; attempt++) {
        uint32_t start = head - EDGE_COUNT;
        for (uint32_t i = 0; i < EDGE_COUNT; i++) {
            window[i].t = s_edges[(start + i) % EDGE_COUNT].t;
            window[i].level = s_edges[(start + i) % EDGE_COUNT].level;
        }
        uint32_t now = s_head;
        if (now - head < EDGE_COUNT) break;   // window still intact
        head = now;
    }

    // The sync gap is the longest interval; everything is measured from there.
    uint32_t gap_index = 0;
    uint32_t gap_length = 0;
    for (uint32_t i = 1; i < EDGE_COUNT; i++) {
        uint32_t delta = window[i].t - window[i - 1].t;
        if (delta > gap_length) {
            gap_length = delta;
            gap_index = i - 1;
        }
    }
    if (gap_length < SYNC_GAP_US) {
        snprintf(buf, len, "SELFTEST signal present but no PPM sync gap found");
        return true;
    }

    // window[gap_index] starts the gap, so its level is the idle level and the
    // next edge opens the first mark of a frame.
    const char *idle = window[gap_index].level ? "high (inverted)" : "low (normal)";
    uint32_t first = gap_index + 1;
    if (first + 2 >= EDGE_COUNT) {
        snprintf(buf, len, "SELFTEST frame straddles the buffer, retrying");
        return true;
    }

    uint32_t mark_us = window[first + 1].t - window[first].t;

    // Channel value is the interval between the starts of two marks.
    uint16_t channels[LS_MAX_CH];
    uint8_t nchan = 0;
    uint32_t i = first;
    while (i + 2 < EDGE_COUNT && nchan < LS_MAX_CH) {
        uint32_t slot = window[i + 2].t - window[i].t;
        if (slot > SYNC_GAP_US) break;   // reached the next sync gap
        channels[nchan++] = (uint16_t)slot;
        i += 2;
    }

    uint32_t frame_us = 0;
    if (i + 2 < EDGE_COUNT) {
        frame_us = window[i + 2].t - window[first].t;
    }

    int written = snprintf(buf, len,
                           "SELFTEST ppm idle=%s mark=%luus frame=%luus nch=%u [",
                           idle, (unsigned long)mark_us, (unsigned long)frame_us,
                           nchan);
    for (uint8_t c = 0; c < nchan && written > 0 && (size_t)written < len; c++) {
        written += snprintf(buf + written, len - (size_t)written, "%s%u",
                            c ? " " : "", channels[c]);
    }
    if (written > 0 && (size_t)written < len) {
        snprintf(buf + written, len - (size_t)written, "]");
    }
    return true;
}
