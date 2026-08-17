"""Turns incoming MIDI control changes into RC channel values in microseconds."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from . import bus as bus_mode
from .config import CHANNELS_PER_ZONE, ChannelCfg, ModelCfg, PortCfg, ShowCfg, step_us


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

        steps = self.channel.quantize
        if steps:
            # Land in the middle of each step so a noisy channel never sits on
            # a boundary. The airborne decoder splits the range the same way.
            return step_us(self.port, steps, raw * steps // (self.raw_max + 1))
        span = self.port.max_us - self.port.min_us
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
        # Bus models do not own channel positions, so they get an encoder that
        # turns their zone states into the eight values that go on the wire.
        self.bus_encoders: dict[str, bus_mode.Encoder] = {}
        # model name -> its slots in channel order, so a frame does not have to
        # filter the whole slot list once per zone.
        self._slots_by_model: dict[str, list[Slot]] = {}
        # (midi_channel, cc) -> (encoder, relay index)
        self._bus_relay_by_cc: dict[tuple[int, int], tuple[bus_mode.Encoder, int]] = {}
        self._bus_relays_by_midi: dict[int, list[tuple[bus_mode.Encoder, int]]] = {}

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
                self._slots_by_model.setdefault(model.name, []).append(slot)

            if not model.uses_bus:
                continue
            encoder = bus_mode.Encoder(
                zones=model.zone_count,
                relays_count=model.bus.relay_count,
                tx_offset=model.tx_offset,
                min_us=port.min_us,
                max_us=port.max_us,
                frame_us=port.frame_us,
            )
            self.bus_encoders[model.name] = encoder
            for index, relay in enumerate(model.bus.relays):
                encoder.set_relay(index, relay.failsafe)
                key = (model.midi_channel, relay.cc)
                self._bus_relay_by_cc[key] = (encoder, index)
                self._bus_relays_by_midi.setdefault(
                    model.midi_channel, []).append((encoder, index))

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
                for encoder, index in self._bus_relays_by_midi.get(midi_channel, []):
                    encoder.set_relay(index, False)
                return

            switch = self._bus_relay_by_cc.get((midi_channel, cc))
            if switch is not None:
                # A relay is on or off, so it follows the same threshold the
                # blackout control uses: 64 and above means on.
                encoder, index = switch
                encoder.set_relay(index, value >= 64)
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
            now = time.monotonic()
            values = [
                [port.min_us] * port.nchan for port in self.show.ports
            ]
            for slot in self.slots:
                if slot.model.uses_bus:
                    continue          # the encoder decides what goes on the wire
                port_id = slot.model.tx_port
                values[port_id][slot.port_index] = (
                    slot.channel.failsafe if blackout else slot.microseconds()
                )

            for model in self.show.models:
                encoder = self.bus_encoders.get(model.name)
                if encoder is None:
                    continue
                if blackout:
                    # One frame carrying CUE_ALL_OFF darkens every zone at once,
                    # rather than taking a full rotation to get round to them.
                    encoder.write_failsafe(values[model.tx_port])
                    continue
                self._load_zones(model, encoder)
                encoder.write(values[model.tx_port], now)
            return values

    def _load_zones(self, model: ModelCfg, encoder: bus_mode.Encoder) -> None:
        """Copies the model's MIDI state into its encoder, zone by zone."""
        slots = self._slots_by_model.get(model.name, [])
        for zone in range(model.zone_count):
            first = zone * CHANNELS_PER_ZONE
            group = slots[first:first + CHANNELS_PER_ZONE]
            if len(group) < CHANNELS_PER_ZONE:
                continue
            encoder.set_zone_us(zone, *(slot.microseconds() for slot in group))

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
                # A bus model's channels are code symbols, not its values --
                # reading them back would show the monitor nonsense.
                if sent is not None and not slot.model.uses_bus \
                        and slot.model.tx_port < len(sent):
                    port_values = sent[slot.model.tx_port]
                    if slot.port_index < len(port_values):
                        values.append((slot, port_values[slot.port_index]))
                        continue
                values.append(
                    (slot, slot.channel.failsafe if blackout else slot.microseconds()))
            return blackout, self.messages, values
