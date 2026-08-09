// Wire protocol between the host bridge and the RP2040 signal generator.
//
// Host -> Pico: binary frames (see below).
// Pico -> Host: newline terminated ASCII status lines, so a plain `cat /dev/ttyACM0`
//               is enough to debug the link.
//
// Frame layout (all multi byte fields little endian):
//
//   A5 5A | ver u8 | type u8 | len u16 | payload[len] | crc16 u16
//
// crc16 is CRC-16/CCITT-FALSE over ver, type, len and payload.
//
// CONFIG payload (type 0x02), sent once at startup, resent whenever the host reconnects:
//   nports u8
//   per port: format u8, flags u8, nchan u8,
//             frame_us u16, sync_us u16, min_us u16, max_us u16,
//             failsafe[nchan] u16
//
// CHANNELS payload (type 0x01), sent at the host tick rate:
//   seq u8, nports u8
//   per port: nchan u8, values[nchan] u16   (microseconds)
//
// Channel frames are ignored until a CONFIG frame has been accepted.

#ifndef LIGHTSHOW_PROTOCOL_H
#define LIGHTSHOW_PROTOCOL_H

#include <stdint.h>

#define LS_MAGIC0 0xA5
#define LS_MAGIC1 0x5A
#define LS_VERSION 1

#define LS_TYPE_CHANNELS 0x01
#define LS_TYPE_CONFIG   0x02

#define LS_MAX_PORTS 8
#define LS_MAX_CH    16

// Port output formats.
#define LS_FMT_OFF  0
#define LS_FMT_PPM  1
#define LS_FMT_SBUS 2

// Port flags.
#define LS_FLAG_INVERT 0x01

// Largest frame the firmware must be able to buffer: a CONFIG frame with all
// ports at 11 fixed bytes plus one failsafe word per channel.
#define LS_MAX_PAYLOAD (1 + LS_MAX_PORTS * (11 + 2 * LS_MAX_CH))
#define LS_MAX_FRAME   (6 + LS_MAX_PAYLOAD + 2)

// No valid channel frame for this long -> every port falls back to its failsafe values.
#define LS_FAILSAFE_TIMEOUT_MS 250

uint16_t ls_crc16(const uint8_t *data, uint32_t len);

#endif // LIGHTSHOW_PROTOCOL_H
