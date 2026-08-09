"""Binary protocol towards the RP2040 signal generator.

This is the exact mirror of ``firmware/pico/src/protocol.h`` -- if you change a
field here, change it there too.
"""

from __future__ import annotations

from typing import Iterable, Sequence

MAGIC = b"\xa5\x5a"
VERSION = 1

TYPE_CHANNELS = 0x01
TYPE_CONFIG = 0x02

FORMATS = {"off": 0, "ppm": 1, "sbus": 2}
FLAG_INVERT = 0x01

MAX_PORTS = 8
MAX_CH = 16


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def build_frame(frame_type: int, payload: bytes) -> bytes:
    body = bytes([VERSION, frame_type]) + len(payload).to_bytes(2, "little") + payload
    return MAGIC + body + crc16(body).to_bytes(2, "little")


def build_config(ports: Sequence["PortWire"]) -> bytes:
    """``ports`` must be ordered by port id, starting at 0 with no gaps."""
    if len(ports) > MAX_PORTS:
        raise ValueError(f"at most {MAX_PORTS} ports, got {len(ports)}")

    payload = bytearray([len(ports)])
    for port in ports:
        payload.append(FORMATS[port.format])
        payload.append(FLAG_INVERT if port.polarity == "inverted" else 0)
        payload.append(port.nchan)
        payload += port.frame_us.to_bytes(2, "little")
        payload += port.sync_us.to_bytes(2, "little")
        payload += port.min_us.to_bytes(2, "little")
        payload += port.max_us.to_bytes(2, "little")
        if len(port.failsafe) != port.nchan:
            raise ValueError(
                f"port {port.name}: {len(port.failsafe)} failsafe values for {port.nchan} channels"
            )
        for value in port.failsafe:
            payload += int(value).to_bytes(2, "little")
    return build_frame(TYPE_CONFIG, bytes(payload))


def build_channels(seq: int, per_port_values: Iterable[Sequence[int]]) -> bytes:
    values = list(per_port_values)
    if len(values) > MAX_PORTS:
        raise ValueError(f"at most {MAX_PORTS} ports, got {len(values)}")

    payload = bytearray([seq & 0xFF, len(values)])
    for channels in values:
        if len(channels) > MAX_CH:
            raise ValueError(f"at most {MAX_CH} channels per port, got {len(channels)}")
        payload.append(len(channels))
        for value in channels:
            payload += int(value).to_bytes(2, "little")
    return build_frame(TYPE_CHANNELS, bytes(payload))


class PortWire:
    """The subset of a port configuration that goes over the wire."""

    __slots__ = (
        "name",
        "format",
        "polarity",
        "nchan",
        "frame_us",
        "sync_us",
        "min_us",
        "max_us",
        "failsafe",
    )

    def __init__(
        self,
        name: str,
        format: str,
        polarity: str,
        nchan: int,
        frame_us: int,
        sync_us: int,
        min_us: int,
        max_us: int,
        failsafe: Sequence[int],
    ) -> None:
        self.name = name
        self.format = format
        self.polarity = polarity
        self.nchan = nchan
        self.frame_us = frame_us
        self.sync_us = sync_us
        self.min_us = min_us
        self.max_us = max_us
        self.failsafe = list(failsafe)
