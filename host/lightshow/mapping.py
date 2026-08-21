"""The channel values the bridge sends when no show is running.

There was a MIDI input here once, turning control changes from a DAW into RC
channel values. The editor in the interface replaced it, so what is left is the
other half of the job: the frame that goes out between shows --
every zone dark, every relay in its failsafe state -- and the blackout switch,
which has to work whatever the source is.

The show itself is built in `timeline.py`, which writes its own frames.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from . import bus as bus_mode
from .config import CHANNELS_PER_ZONE, ChannelCfg, ModelCfg, PortCfg, ShowCfg


@dataclass
class Slot:
    """One RC channel of one model, for the views that list them."""

    model: ModelCfg
    port: PortCfg
    channel: ChannelCfg
    port_index: int                # channel index inside the transmitter frame

    def microseconds(self) -> int:
        return self.channel.failsafe


class Mapper:
    """Thread safe: the interface edits, the sending loop reads."""

    def __init__(self, show: ShowCfg) -> None:
        self.show = show
        self._lock = threading.Lock()
        self.blackout = False
        self._build()

    def reload(self, show: ShowCfg) -> None:
        """Takes a freshly edited configuration without a restart.

        Everything below `_build` is derived from the configuration, so a model
        that changed its zones, its channels or its transmitter leaves stale
        slots behind. Rebuilding them wholesale is both simpler and safer than
        patching: there is no partial state to get wrong, and no old slot can
        survive to keep driving a channel that no longer belongs to it.

        The blackout is deliberately kept -- it belongs to the running session,
        not to the file.
        """
        with self._lock:
            self.show = show
            self._build()

    def _build(self) -> None:
        self.slots: list[Slot] = []
        # Bus models do not own channel positions, so they get an encoder that
        # turns their zone states into the eight values that go on the wire.
        self.bus_encoders: dict[str, bus_mode.Encoder] = {}
        # model name -> its slots in channel order, so a frame does not have to
        # filter the whole slot list once per zone.
        self._slots_by_model: dict[str, list[Slot]] = {}

        for model in self.show.models:
            port = self.show.port_by_id(model.tx_port)
            for index, channel in enumerate(model.channels):
                slot = Slot(model=model, port=port, channel=channel,
                            port_index=model.tx_offset + index)
                self.slots.append(slot)
                self._slots_by_model.setdefault(model.name, []).append(slot)

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

    def set_blackout(self, on: bool) -> None:
        with self._lock:
            self.blackout = on

    # ----------------------------------------------------------------- output

    def frame(self) -> list[list[int]]:
        """Channel values in microseconds, one list per transmitter port."""
        with self._lock:
            blackout = self.blackout
            now = time.monotonic()
            values = [
                [port.min_us] * port.nchan for port in self.show.ports
            ]
            # Nothing writes a channel directly any more: every model's eight
            # channels are one code word, and the encoder owns all eight.

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
        """Copies the model's resting state into its encoder, zone by zone."""
        slots = self._slots_by_model.get(model.name, [])
        for zone in range(model.zone_count):
            first = zone * CHANNELS_PER_ZONE
            group = slots[first:first + CHANNELS_PER_ZONE]
            if len(group) < CHANNELS_PER_ZONE:
                continue
            encoder.set_zone_us(zone, *(slot.microseconds() for slot in group))

    def snapshot(self) -> tuple[bool, list[tuple[Slot, int]]]:
        """(blackout, [(slot, microseconds)]) for the monitor.

        Deliberately not read back off the wire: those eight channels are code
        symbols of one RS(8,6) frame, and a symbol is not the value it helps
        encode. The monitor shows what each slot holds.
        """
        with self._lock:
            blackout = self.blackout
            return blackout, [(slot, slot.microseconds()) for slot in self.slots]
