"""Turns incoming MIDI control changes into RC channel values in microseconds."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .config import ChannelCfg, ModelCfg, PortCfg, ShowCfg


@dataclass
class Slot:
    """One RC channel of one model."""

    model: ModelCfg
    port: PortCfg
    channel: ChannelCfg
    port_index: int                # channel index inside the transmitter frame
    raw: int | None = None         # last received value, None until the first CC
    msb: int = 0
    lsb: int = 0

    @property
    def raw_max(self) -> int:
        return (1 << self.channel.bits) - 1

    def microseconds(self) -> int:
        if self.raw is None:
            return self.channel.failsafe

        raw = self.raw
        if self.channel.invert:
            raw = self.raw_max - raw

        span = self.port.max_us - self.port.min_us
        steps = self.channel.quantize
        if steps:
            # Land in the middle of each step so a noisy channel never sits on
            # a boundary. The airborne decoder splits the range the same way.
            index = min(steps - 1, raw * steps // (self.raw_max + 1))
            return self.port.min_us + round(span * (index + 0.5) / steps)
        return self.port.min_us + round(span * raw / self.raw_max)


class Mapper:
    """Thread safe: MIDI arrives on the rtmidi thread, frames are read by the sender."""

    def __init__(self, show: ShowCfg) -> None:
        self.show = show
        self._lock = threading.Lock()
        self.blackout = False
        self.messages = 0

        self.slots: list[Slot] = []
        # (midi_channel, cc) -> (slot, is_lsb)
        self._by_cc: dict[tuple[int, int], tuple[Slot, bool]] = {}
        # midi_channel -> slots, for panic handling
        self._by_midi: dict[int, list[Slot]] = {}

        for model in show.models:
            port = show.port_by_id(model.tx_port)
            for index, channel in enumerate(model.channels):
                slot = Slot(
                    model=model,
                    port=port,
                    channel=channel,
                    port_index=model.tx_offset + index,
                )
                self.slots.append(slot)
                self._by_cc[(model.midi_channel, channel.cc)] = (slot, False)
                if channel.cc_lsb is not None:
                    self._by_cc[(model.midi_channel, channel.cc_lsb)] = (slot, True)
                self._by_midi.setdefault(model.midi_channel, []).append(slot)

    # ------------------------------------------------------------------ input

    def handle_control_change(self, midi_channel: int, cc: int, value: int) -> None:
        """``midi_channel`` is 1..16, matching what Ardour displays."""
        with self._lock:
            self.messages += 1

            if self.show.blackout_cc is not None and cc == self.show.blackout_cc:
                self.blackout = value >= 64
                return

            if cc in (120, 123):
                # All sound off / all notes off: Ardour sends these on stop and
                # on panic, and a show that keeps glowing after stop is wrong.
                for slot in self._by_midi.get(midi_channel, []):
                    slot.raw = None
                    slot.msb = slot.lsb = 0
                return

            entry = self._by_cc.get((midi_channel, cc))
            if entry is None:
                return
            slot, is_lsb = entry

            if slot.channel.bits == 7:
                slot.raw = value
                return

            if is_lsb:
                slot.lsb = value
            else:
                slot.msb = value
                # A bare MSB without a following LSB must still move the channel,
                # so take effect immediately and let the LSB refine it.
            slot.raw = (slot.msb << 7) | slot.lsb

    def set_blackout(self, on: bool) -> None:
        with self._lock:
            self.blackout = on

    def reset(self) -> None:
        with self._lock:
            for slot in self.slots:
                slot.raw = None
                slot.msb = slot.lsb = 0

    # ----------------------------------------------------------------- output

    def frame(self) -> list[list[int]]:
        """Channel values in microseconds, one list per transmitter port."""
        with self._lock:
            blackout = self.blackout
            values = [
                [port.min_us] * port.nchan for port in self.show.ports
            ]
            for slot in self.slots:
                port_id = slot.model.tx_port
                values[port_id][slot.port_index] = (
                    slot.channel.failsafe if blackout else slot.microseconds()
                )
            return values

    def snapshot(self, sent: list[list[int]] | None = None
                 ) -> tuple[bool, int, list[tuple[Slot, int]]]:
        """(blackout, message count, [(slot, microseconds)]) for the monitor.

        ``sent`` is the frame the sending loop last produced. Passing it makes
        the monitor show what actually goes to the transmitters, which during a
        running show comes from the project timeline rather than from MIDI.
        """
        with self._lock:
            blackout = self.blackout
            values = []
            for slot in self.slots:
                if sent is not None and slot.model.tx_port < len(sent):
                    port_values = sent[slot.model.tx_port]
                    if slot.port_index < len(port_values):
                        values.append((slot, port_values[slot.port_index]))
                        continue
                values.append(
                    (slot, slot.channel.failsafe if blackout else slot.microseconds()))
            return blackout, self.messages, values
