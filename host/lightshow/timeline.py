"""Turns the light blocks of a project into RC channel values.

The editor places blocks on a track; this module answers "what does every
channel look like at second t". It produces exactly the same frame shape as the
MIDI mapper, so the sending loop does not care where the values came from.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from . import bus as bus_mode
from .config import (CHANNELS_PER_ZONE, ChannelCfg, ModelCfg, PortCfg, ShowCfg,
                     level_us, step_us)
from .project import LightBlock, LightTrack, Project


@dataclass
class Binding:
    """Where one zone's four channels live in the transmitter frame.

    In bus mode `indices` is empty: a zone owns no channels of its own, and the
    model's encoder decides what the eight wire channels carry.
    """

    track: LightTrack
    port_id: int
    port: PortCfg
    indices: list[int]                 # channel index inside the port frame
    channels: list[ChannelCfg]
    model: ModelCfg | None = None
    zone: int = 0


def fade_factor(block: LightBlock, t: float) -> float:
    """Envelope of a block at time t, 0..1. Outside the block it is 0."""
    if t < block.start_s or t >= block.end_s:
        return 0.0
    since = t - block.start_s
    until = block.end_s - t
    factor = 1.0
    if block.fade_in_s > 0:
        factor = min(factor, since / block.fade_in_s)
    if block.fade_out_s > 0:
        factor = min(factor, until / block.fade_out_s)
    return max(0.0, min(1.0, factor))


def active_block(track: LightTrack, t: float) -> LightBlock | None:
    for block in track.blocks:
        if block.start_s <= t < block.end_s:
            return block
        if block.start_s > t:
            break                      # blocks are kept sorted
    return None


class Timeline:
    """Evaluates a project against a show configuration."""

    def __init__(self, show: ShowCfg, project: Project) -> None:
        self.show = show
        self.project = project
        self.bindings: list[Binding] = []
        self.warnings: list[str] = []
        self.encoders: dict[str, bus_mode.Encoder] = {}
        self._bind()

    def _bind(self) -> None:
        by_name = {model.name: model for model in self.show.models}
        for track in self.project.light_tracks:
            model = by_name.get(track.model)
            if model is None:
                self.warnings.append(
                    f"Spur '{track.title}': Modell '{track.model}' steht nicht in "
                    f"der Show-Konfiguration"
                )
                continue
            first = track.zone * CHANNELS_PER_ZONE
            if first + CHANNELS_PER_ZONE > len(model.channels):
                self.warnings.append(
                    f"Spur '{track.title}': Modell '{model.name}' hat keine Zone "
                    f"{track.zone}"
                )
                continue
            self.bindings.append(Binding(
                track=track,
                port_id=model.tx_port,
                port=self.show.port_by_id(model.tx_port),
                indices=([] if model.uses_bus else
                         [model.tx_offset + first + offset
                          for offset in range(CHANNELS_PER_ZONE)]),
                channels=model.channels[first:first + CHANNELS_PER_ZONE],
                model=model,
                zone=track.zone,
            ))

        # One encoder per bus model, shared by every track that drives it.
        for model in self.show.models:
            if not model.uses_bus:
                continue
            port = self.show.port_by_id(model.tx_port)
            self.encoders[model.name] = bus_mode.Encoder(
                zones=model.zone_count,
                relays_count=model.bus.relay_count,
                tx_offset=model.tx_offset,
                min_us=port.min_us,
                max_us=port.max_us,
                frame_us=port.frame_us,
            )

    # ------------------------------------------------------------- evaluate

    def _to_us(self, channel: ChannelCfg, port: PortCfg, value: int) -> int:
        """value is 0..255, or a step index when the channel is quantised."""
        if channel.quantize:
            step = max(0, min(channel.quantize - 1, value))
            if channel.invert:
                # The MIDI mapper inverts before quantising, which mirrors the
                # step index. Skipping it here would make the same channel mean
                # two different things depending on whether the show runs from
                # the timeline or from the DAW.
                step = channel.quantize - 1 - step
            return step_us(port, channel.quantize, step)
        level = max(0, min(255, value))
        if channel.invert:
            level = 255 - level
        return level_us(port, level)

    def frame(self, t: float) -> list[list[int]]:
        """Channel values in microseconds, one list per transmitter port."""
        values = [[port.min_us] * port.nchan for port in self.show.ports]

        # Channels nobody drives keep their configured failsafe.
        for model in self.show.models:
            if model.uses_bus:
                continue              # its channels are code symbols, not values
            for offset, channel in enumerate(model.channels):
                values[model.tx_port][model.tx_offset + offset] = channel.failsafe

        # A bus zone nobody scheduled has to be darkened explicitly: the encoder
        # keeps its last state, and there is no failsafe channel to fall back on.
        for encoder in self.encoders.values():
            for zone in range(encoder.zones):
                encoder.set_zone(zone, bus_mode.ZoneState())

        for binding in self.bindings:
            block = active_block(binding.track, t)
            if block is None or block.cue == 0:
                # Nothing scheduled: hold the failsafe, which is "off".
                continue

            level = round(block.brightness * fade_factor(block, t))
            settings = (block.cue, block.hue, level, block.param)

            encoder = (self.encoders.get(binding.model.name)
                       if binding.model is not None else None)
            if encoder is not None:
                encoder.set_zone_us(binding.zone, *[
                    self._to_us(channel, binding.port, value)
                    for channel, value in zip(binding.channels, settings)
                ])
                continue

            for index, channel, value in zip(binding.indices, binding.channels,
                                             settings):
                values[binding.port_id][index] = self._to_us(
                    channel, binding.port, value)

        now = time.monotonic()
        for model in self.show.models:
            encoder = self.encoders.get(model.name)
            if encoder is not None:
                encoder.write(values[model.tx_port], now)

        return values

    def describe(self, t: float) -> list[dict]:
        """What each track is doing right now, for the editor's playhead."""
        out = []
        for binding in self.bindings:
            block = active_block(binding.track, t)
            out.append({
                "track": binding.track.title,
                "model": binding.track.model,
                "zone": binding.track.zone,
                "cue": block.cue if block else 0,
                "label": block.label if block else "",
                "level": round(block.brightness * fade_factor(block, t)) if block else 0,
            })
        return out
