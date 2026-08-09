#include "ports.h"

#include <string.h>

#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "hardware/gpio.h"
#include "hardware/irq.h"
#include "hardware/pio.h"
#include "pico/stdlib.h"
#include "pico/time.h"

#include "ppm.pio.h"
#include "ppm_frame.h"
#include "sbus.pio.h"

// GPIO2..GPIO9 -- GPIO0/1 stay free for the debug UART, GPIO25 is the LED.
const uint8_t LS_PORT_GPIO[LS_MAX_PORTS] = {2, 3, 4, 5, 6, 7, 8, 9};

// Longest PPM buffer: one mark/space pair per channel plus the sync pair.
#define PPM_WORDS_MAX (2 * (LS_MAX_CH + 1))
// SBUS: 25 bytes x 12 bits, padded up to whole words.
#define SBUS_BITS  (25 * 12)
#define SBUS_WORDS ((SBUS_BITS + 31) / 32)

#define BUF_WORDS (PPM_WORDS_MAX > SBUS_WORDS ? PPM_WORDS_MAX : SBUS_WORDS)

typedef struct {
    ls_port_cfg_t cfg;
    bool     active;
    uint     gpio;
    PIO      pio;
    uint     sm;
    int      dma;
    uint32_t buf[BUF_WORDS];
    uint32_t nwords;
    volatile uint16_t values[LS_MAX_CH];
    repeating_timer_t timer;
    bool     timer_active;
} ls_port_t;

static ls_port_t s_ports[LS_MAX_PORTS];
static uint8_t s_nports;
static bool s_configured;
static bool s_irq_installed;
// Static zero initialisation would make every dma field look like channel 0,
// which the teardown would then happily unclaim.
static bool s_ports_reset;

// Program offsets per PIO block, -1 when the program is not loaded.
static int s_ppm_offset[2];
static int s_sbus_offset[2];

static inline uint pio_index(PIO pio) { return pio == pio0 ? 0 : 1; }

// ---------------------------------------------------------------- PPM ------

static void ppm_build(ls_port_t *p) {
    uint16_t values[LS_MAX_CH];
    for (uint8_t i = 0; i < p->cfg.nchan; i++) {
        values[i] = p->values[i];
    }
    p->nwords = ppm_build_buffer(values, p->cfg.nchan, p->cfg.sync_us,
                                 p->cfg.frame_us, p->cfg.min_us, p->cfg.max_us,
                                 p->buf);
}

// --------------------------------------------------------------- SBUS ------

static inline uint16_t sbus_value(uint16_t us, uint16_t min_us, uint16_t max_us) {
    if (us < min_us) us = min_us;
    if (us > max_us) us = max_us;
    // 1000 us -> 172, 2000 us -> 1811, the usual SBUS scaling.
    int32_t v = 172 + ((int32_t)(us - 1000) * 1639) / 1000;
    if (v < 0) v = 0;
    if (v > 2047) v = 2047;
    return (uint16_t)v;
}

static void sbus_build(ls_port_t *p) {
    uint8_t frame[25];
    memset(frame, 0, sizeof(frame));
    frame[0] = 0x0F;

    // 16 channels of 11 bits, packed LSB first across bytes 1..22.
    uint32_t bitpos = 0;
    for (uint8_t i = 0; i < LS_MAX_CH; i++) {
        uint16_t v = i < p->cfg.nchan
                         ? sbus_value(p->values[i], p->cfg.min_us, p->cfg.max_us)
                         : sbus_value(1500, 1000, 2000);
        for (uint8_t b = 0; b < 11; b++) {
            if (v & (1u << b)) {
                frame[1 + (bitpos >> 3)] |= (uint8_t)(1u << (bitpos & 7));
            }
            bitpos++;
        }
    }
    // frame[23] flags and frame[24] footer stay zero.

    // Render start bit, 8 data bits, even parity and two stop bits per byte.
    // Idle is high, so padding at the end of the buffer is all ones.
    memset(p->buf, 0xFF, SBUS_WORDS * sizeof(uint32_t));
    uint32_t bit = 0;
    for (uint8_t i = 0; i < 25; i++) {
        uint8_t byte = frame[i];
        uint8_t ones = 0;

        p->buf[bit >> 5] &= ~(1u << (bit & 31));         // start bit: 0
        bit++;
        for (uint8_t b = 0; b < 8; b++) {
            if (byte & (1u << b)) {
                ones++;
            } else {
                p->buf[bit >> 5] &= ~(1u << (bit & 31));
            }
            bit++;
        }
        if (ones & 1) {                                   // even parity
            // parity bit 1 -- buffer already holds ones
        } else {
            p->buf[bit >> 5] &= ~(1u << (bit & 31));
        }
        bit++;
        bit += 2;                                         // two stop bits: 1
    }
    p->nwords = SBUS_WORDS;
}

static bool sbus_timer_cb(repeating_timer_t *t) {
    ls_port_t *p = (ls_port_t *)t->user_data;
    if (dma_channel_is_busy(p->dma)) {
        return true;  // previous frame still going out; skip this slot
    }
    sbus_build(p);
    dma_channel_transfer_from_buffer_now((uint)p->dma, p->buf, p->nwords);
    return true;
}

// ---------------------------------------------------------------- DMA ------

static void dma_irq_handler(void) {
    uint32_t ints = dma_hw->ints0;
    for (uint8_t i = 0; i < s_nports; i++) {
        ls_port_t *p = &s_ports[i];
        if (!p->active || p->cfg.format != LS_FMT_PPM || p->dma < 0) continue;
        if (!(ints & (1u << p->dma))) continue;

        dma_hw->ints0 = 1u << p->dma;
        // The DMA is done, so the buffer is ours again. Refill it with the
        // current channel values and immediately queue the next frame; the PIO
        // FIFO still holds several milliseconds of playback.
        ppm_build(p);
        dma_channel_transfer_from_buffer_now((uint)p->dma, p->buf, p->nwords);
    }
}

// -------------------------------------------------------------- teardown ---

static void ports_teardown(void) {
    if (!s_ports_reset) {
        for (uint8_t i = 0; i < LS_MAX_PORTS; i++) {
            s_ports[i].dma = -1;
        }
        s_ports_reset = true;
    }

    for (uint8_t i = 0; i < LS_MAX_PORTS; i++) {
        ls_port_t *p = &s_ports[i];
        if (p->timer_active) {
            cancel_repeating_timer(&p->timer);
            p->timer_active = false;
        }
        if (p->dma >= 0) {
            dma_channel_set_irq0_enabled(p->dma, false);
            dma_channel_abort(p->dma);
            dma_channel_unclaim(p->dma);
            p->dma = -1;
        }
        if (p->active) {
            pio_sm_set_enabled(p->pio, p->sm, false);
            pio_sm_unclaim(p->pio, p->sm);
            gpio_set_outover(p->gpio, GPIO_OVERRIDE_NORMAL);
            gpio_init(p->gpio);
            gpio_set_dir(p->gpio, GPIO_OUT);
            gpio_put(p->gpio, 0);
            p->active = false;
        }
    }
    pio_clear_instruction_memory(pio0);
    pio_clear_instruction_memory(pio1);
    s_ppm_offset[0] = s_ppm_offset[1] = -1;
    s_sbus_offset[0] = s_sbus_offset[1] = -1;
    s_nports = 0;
    s_configured = false;
}

// ------------------------------------------------------------- configure ---

static bool cfg_valid(const ls_port_cfg_t *c) {
    if (c->format == LS_FMT_OFF) return true;
    if (c->format != LS_FMT_PPM && c->format != LS_FMT_SBUS) return false;
    if (c->nchan == 0 || c->nchan > LS_MAX_CH) return false;
    if (c->min_us < 500 || c->max_us > 2500 || c->min_us >= c->max_us) return false;
    if (c->format == LS_FMT_PPM) {
        if (c->sync_us < 50 || c->sync_us > 800) return false;
        // The frame has to hold every channel at its maximum plus a sync gap.
        uint32_t needed = (uint32_t)c->nchan * c->max_us + c->sync_us + PPM_MIN_SYNC_US;
        if (c->frame_us < needed) return false;
    } else {
        if (c->frame_us < 4000) return false;  // one SBUS frame takes ~3 ms
    }
    return true;
}

bool ports_configure(const ls_port_cfg_t *cfgs, uint8_t nports) {
    if (nports > LS_MAX_PORTS) return false;
    for (uint8_t i = 0; i < nports; i++) {
        if (!cfg_valid(&cfgs[i])) return false;
    }

    ports_teardown();

    if (!s_irq_installed) {
        irq_add_shared_handler(DMA_IRQ_0, dma_irq_handler,
                               PICO_SHARED_IRQ_HANDLER_DEFAULT_ORDER_PRIORITY);
        irq_set_enabled(DMA_IRQ_0, true);
        s_irq_installed = true;
    }

    for (uint8_t i = 0; i < nports; i++) {
        ls_port_t *p = &s_ports[i];
        p->cfg = cfgs[i];
        p->gpio = LS_PORT_GPIO[i];
        p->dma = -1;
        for (uint8_t c = 0; c < LS_MAX_CH; c++) {
            p->values[c] = p->cfg.failsafe[c];
        }

        if (p->cfg.format == LS_FMT_OFF) continue;

        // Ports 0..3 live on pio0, ports 4..7 on pio1.
        p->pio = i < 4 ? pio0 : pio1;
        p->sm = i % 4;
        pio_sm_claim(p->pio, p->sm);
        uint blk = pio_index(p->pio);

        if (p->cfg.format == LS_FMT_PPM) {
            if (s_ppm_offset[blk] < 0) {
                s_ppm_offset[blk] = (int)pio_add_program(p->pio, &ppm_program);
            }
            ppm_program_init(p->pio, p->sm, (uint)s_ppm_offset[blk], p->gpio);
            ppm_build(p);
            // "normal" means positive shift: idle low with high sync pulses.
            gpio_set_outover(p->gpio, (p->cfg.flags & LS_FLAG_INVERT)
                                          ? GPIO_OVERRIDE_INVERT
                                          : GPIO_OVERRIDE_NORMAL);
        } else {
            if (s_sbus_offset[blk] < 0) {
                s_sbus_offset[blk] = (int)pio_add_program(p->pio, &sbus_bits_program);
            }
            sbus_bits_program_init(p->pio, p->sm, (uint)s_sbus_offset[blk], p->gpio);
            sbus_build(p);
            // SBUS is an inverted UART, so "normal" already means inverted at
            // the connector; the flag selects the uninverted variant.
            gpio_set_outover(p->gpio, (p->cfg.flags & LS_FLAG_INVERT)
                                          ? GPIO_OVERRIDE_NORMAL
                                          : GPIO_OVERRIDE_INVERT);
        }

        p->dma = dma_claim_unused_channel(false);
        if (p->dma < 0) {
            ports_teardown();
            return false;
        }
        dma_channel_config dc = dma_channel_get_default_config((uint)p->dma);
        channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
        channel_config_set_read_increment(&dc, true);
        channel_config_set_write_increment(&dc, false);
        channel_config_set_dreq(&dc, pio_get_dreq(p->pio, p->sm, true));
        dma_channel_configure((uint)p->dma, &dc, &p->pio->txf[p->sm], p->buf,
                              p->nwords, false);

        p->active = true;
        pio_sm_set_enabled(p->pio, p->sm, true);

        if (p->cfg.format == LS_FMT_PPM) {
            dma_channel_set_irq0_enabled((uint)p->dma, true);
            dma_channel_start((uint)p->dma);
        } else {
            add_repeating_timer_us(-(int64_t)p->cfg.frame_us, sbus_timer_cb, p,
                                   &p->timer);
            p->timer_active = true;
        }
    }

    s_nports = nports;
    s_configured = true;
    return true;
}

// ----------------------------------------------------------------- data ----

void ports_set_channels(uint8_t port, const uint16_t *values_us, uint8_t nchan) {
    if (port >= s_nports) return;
    ls_port_t *p = &s_ports[port];
    if (!p->active) return;
    if (nchan > p->cfg.nchan) nchan = p->cfg.nchan;
    for (uint8_t i = 0; i < nchan; i++) {
        uint16_t v = values_us[i];
        if (v < p->cfg.min_us) v = p->cfg.min_us;
        if (v > p->cfg.max_us) v = p->cfg.max_us;
        p->values[i] = v;
    }
}

void ports_apply_failsafe(void) {
    for (uint8_t i = 0; i < s_nports; i++) {
        ls_port_t *p = &s_ports[i];
        if (!p->active) continue;
        for (uint8_t c = 0; c < p->cfg.nchan; c++) {
            p->values[c] = p->cfg.failsafe[c];
        }
    }
}

uint8_t ports_count(void) { return s_nports; }
bool ports_configured(void) { return s_configured; }
