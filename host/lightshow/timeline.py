"""Turns the light blocks of a project into RC channel values.

The editor places blocks on a track; this module answers "what does every
channel look like at second t". It produces exactly the same frame shape as the
resting mapper, so the sending loop does not care where the values came from.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from . import bus as bus_mode
from .config import (CHANNELS_PER_ZONE, ChannelCfg, ModelCfg, PortCfg, ShowCfg,
                     level_us, step_us)
from .project import (LightBlock, LightTrack, Project, RelayBlock, RelayTrack)


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


@dataclass
class RelayBinding:
    """One relay track and the bit it drives."""

    track: RelayTrack
    model: ModelCfg
    relay: int


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


def relay_is_on(track: RelayTrack, t: float) -> bool:
    """A relay track has no levels: a block means on, a gap means off."""
    for block in track.blocks:
        if block.start_s <= t < block.end_s:
            return True
        if block.start_s > t:
            break                      # blocks are kept sorted
    return False


class Timeline:
    """Evaluates a project against a show configuration."""

    def __init__(self, show: ShowCfg, project: Project) -> None:
        self.show = show
        self.project = project
        self.bindings: list[Binding] = []
        self.relay_bindings: list[RelayBinding] = []
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
                # No direct channels: the encoder writes all eight.
                indices=[],
                channels=model.channels[first:first + CHANNELS_PER_ZONE],
                model=model,
                zone=track.zone,
            ))

        for track in self.project.relay_tracks:
            model = by_name.get(track.model)
            if model is None:
                self.warnings.append(
                    f"Spur '{track.title}': Modell '{track.model}' steht nicht in "
                    f"der Show-Konfiguration"
                )
                continue
            if track.relay >= model.bus.relay_count:
                self.warnings.append(
                    f"Spur '{track.title}': Modell '{model.name}' hat kein Relais "
                    f"{track.relay + 1}, nur {model.bus.relay_count}"
                )
                continue
            self.relay_bindings.append(
                RelayBinding(track=track, model=model, relay=track.relay))

        # One encoder per bus model, shared by every track that drives it.
        for model in self.show.models:
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
                # Inverting before quantising mirrors the step index, which
                # is what the airborne decoder expects.
                step = channel.quantize - 1 - step
            return step_us(port, channel.quantize, step)
        level = max(0, min(255, value))
        if channel.invert:
            level = 255 - level
        return level_us(port, level)

    def frame(self, t: float) -> list[list[int]]:
        """Channel values in microseconds, one list per transmitter port."""
        values = [[port.min_us] * port.nchan for port in self.show.ports]

        # A bus zone nobody scheduled has to be darkened explicitly: the encoder
        # keeps its last state, and there is no failsafe channel to fall back on.
        # The same goes for relays -- a bit nobody set would stay wherever the
        # last block left it, which for a smoke system is the wrong direction.
        for encoder in self.encoders.values():
            for zone in range(encoder.zones):
                encoder.set_zone(zone, bus_mode.ZoneState())
            for relay in range(encoder.relays_count):
                encoder.set_relay(relay, False)

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

        for binding in self.relay_bindings:
            encoder = self.encoders.get(binding.model.name)
            if encoder is not None:
                encoder.set_relay(binding.relay, relay_is_on(binding.track, t))

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
                "kind": "light",
                "track": binding.track.title,
                "model": binding.track.model,
                "zone": binding.track.zone,
                "cue": block.cue if block else 0,
                "label": block.label if block else "",
                "level": round(block.brightness * fade_factor(block, t)) if block else 0,
            })
        for binding in self.relay_bindings:
            out.append({
                "kind": "relay",
                "track": binding.track.title,
                "model": binding.track.model,
                "relay": binding.relay,
                "on": relay_is_on(binding.track, t),
            })
        return out
