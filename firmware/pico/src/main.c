// Lightshow trainer-port signal generator.
//
// Reads channel frames from the host bridge over USB CDC and drives up to eight
// independent PPM or SBUS outputs into the trainer ("Lehrer/Schueler") jacks of
// RC transmitters. Output format, polarity and timing are configured per port
// by the host, so a different transmitter brand only means a different line in
// the show configuration.

#include <stdio.h>

#include "pico/stdlib.h"
#include "pico/time.h"

#include "link.h"
#include "ports.h"
#include "protocol.h"
#include "selftest.h"

#define STATUS_INTERVAL_MS 1000

// Applied at boot so the outputs are defined even before the host connects:
// eight positive-shift PPM ports with every channel at its low end, which the
// airborne controllers read as "lights off".
static void apply_boot_defaults(void) {
    ls_port_cfg_t cfgs[LS_MAX_PORTS];
    for (uint8_t i = 0; i < LS_MAX_PORTS; i++) {
        cfgs[i].format = LS_FMT_PPM;
        cfgs[i].flags = 0;
        cfgs[i].nchan = 8;
        cfgs[i].frame_us = 22500;
        cfgs[i].sync_us = 400;
        cfgs[i].min_us = 1000;
        cfgs[i].max_us = 2000;
        for (uint8_t c = 0; c < LS_MAX_CH; c++) cfgs[i].failsafe[c] = 1000;
    }
    ports_configure(cfgs, LS_MAX_PORTS);
}

int main(void) {
    stdio_init_all();

    gpio_init(PICO_DEFAULT_LED_PIN);
    gpio_set_dir(PICO_DEFAULT_LED_PIN, GPIO_OUT);

    link_init();
    apply_boot_defaults();
    selftest_init();

    absolute_time_t last_frame = get_absolute_time();
    absolute_time_t last_status = get_absolute_time();
    bool link_live = false;

    while (true) {
        // Drain everything the host has sent since the last pass.
        int c;
        while ((c = getchar_timeout_us(0)) != PICO_ERROR_TIMEOUT) {
            if (link_feed((uint8_t)c)) {
                last_frame = get_absolute_time();
                link_live = true;
            }
        }

        int64_t since_us = absolute_time_diff_us(last_frame, get_absolute_time());
        if (link_live && since_us > LS_FAILSAFE_TIMEOUT_MS * 1000) {
            ports_apply_failsafe();
            link_live = false;
        }

        // Solid while the host is feeding us, slow blink once it is gone.
        uint32_t ms = to_ms_since_boot(get_absolute_time());
        gpio_put(PICO_DEFAULT_LED_PIN, link_live ? 1 : ((ms / 500) & 1));

        if (absolute_time_diff_us(last_status, get_absolute_time()) >
            STATUS_INTERVAL_MS * 1000) {
            last_status = get_absolute_time();
            const link_stats_t *s = link_get_stats();
            printf("STAT link=%d ports=%u frames=%lu crc_err=%lu bad=%lu gaps=%lu cfg=%lu\n",
                   link_live ? 1 : 0, ports_count(),
                   (unsigned long)s->frames_ok, (unsigned long)s->crc_errors,
                   (unsigned long)s->bad_frames, (unsigned long)s->seq_gaps,
                   (unsigned long)s->config_count);

            // Only speaks up when something is wired to the self-test pin.
            char report[256];
            if (selftest_report(report, sizeof(report))) {
                printf("%s\n", report);
            }
        }

        tight_loop_contents();
    }
}
