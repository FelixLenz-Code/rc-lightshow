"""Serial link to the RP2040 signal generator, with automatic reconnect."""

from __future__ import annotations

import time
from collections import deque
from typing import Sequence

import serial

from .protocol import PortWire, build_channels, build_config

RECONNECT_INTERVAL_S = 1.0


class PicoLink:
    def __init__(self, device: str, wire_ports: Sequence[PortWire], dry_run: bool = False) -> None:
        self.device = device
        self.wire_ports = list(wire_ports)
        self.dry_run = dry_run
        self.status_lines: deque[str] = deque(maxlen=20)
        self.frames_sent = 0
        self.last_error: str | None = None

        self._serial: serial.Serial | None = None
        self._next_attempt = 0.0
        self._rx = bytearray()
        self._suspended = False

    @property
    def connected(self) -> bool:
        return self.dry_run or self._serial is not None

    def suspend(self) -> None:
        """Releases the port and keeps it released until resume().

        Flashing the ground station needs the device free: the bootloader is
        entered by opening it at 1200 baud. A plain close() would not do, since
        the sending loop calls poll() a hundred times a second and would grab
        the port back long before the flasher gets to it.
        """
        self._suspended = True
        self.close()

    def resume(self) -> None:
        self._suspended = False
        # The board has just rebooted into fresh firmware; let it enumerate
        # before the first reconnect attempt.
        self._next_attempt = time.monotonic() + RECONNECT_INTERVAL_S

    def poll(self) -> None:
        """Reconnects when needed and collects status lines from the firmware."""
        if self.dry_run or self._suspended:
            return

        if self._serial is None:
            now = time.monotonic()
            if now < self._next_attempt:
                return
            self._next_attempt = now + RECONNECT_INTERVAL_S
            try:
                self._serial = serial.Serial(self.device, baudrate=115200, timeout=0)
            except (OSError, serial.SerialException) as exc:
                self.last_error = str(exc)
                return
            self.last_error = None
            self._rx.clear()
            self._send_raw(build_config(self.wire_ports))
            return

        try:
            pending = self._serial.in_waiting
            if pending:
                self._rx += self._serial.read(pending)
        except (OSError, serial.SerialException) as exc:
            self._drop(str(exc))
            return

        while b"\n" in self._rx:
            line, _, rest = self._rx.partition(b"\n")
            self._rx = bytearray(rest)
            text = line.decode("utf-8", "replace").strip()
            if text:
                self.status_lines.append(text)

    def send(self, seq: int, frames: Sequence[Sequence[int]]) -> bool:
        if self._suspended:
            return False
        payload = build_channels(seq, frames)
        if self.dry_run:
            self.frames_sent += 1
            return True
        if self._serial is None:
            return False
        return self._send_raw(payload)

    def _send_raw(self, data: bytes) -> bool:
        if self._serial is None:
            return False
        try:
            self._serial.write(data)
        except (OSError, serial.SerialException) as exc:
            self._drop(str(exc))
            return False
        self.frames_sent += 1
        return True

    def _drop(self, error: str) -> None:
        self.last_error = error
        try:
            if self._serial is not None:
                self._serial.close()
        except Exception:
            pass
        self._serial = None
        self._next_attempt = time.monotonic() + RECONNECT_INTERVAL_S

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None
