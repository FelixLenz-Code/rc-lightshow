"""Show configuration: loading and validation of ``show.yaml``."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .protocol import MAX_CH, MAX_PORTS, PortWire


class ConfigError(Exception):
    """Raised with a message that names the offending part of the file."""


@dataclass
class ChannelCfg:
    role: str
    cc: int
    cc_lsb: int | None = None      # set for 14 bit control changes
    quantize: int | None = None    # number of discrete steps, for cue channels
    invert: bool = False
    failsafe: int = 1000

    @property
    def bits(self) -> int:
        return 14 if self.cc_lsb is not None else 7


@dataclass
class PortCfg:
    id: int
    name: str
    format: str = "ppm"
    polarity: str = "normal"
    nchan: int = 8
    frame_us: int = 22500
    sync_us: int = 400
    min_us: int = 1000
    max_us: int = 2000


@dataclass
class ModelCfg:
    name: str
    midi_channel: int              # 1..16 as shown in Ardour
    tx_port: int
    tx_offset: int = 0             # first port channel this model occupies
    channels: list[ChannelCfg] = field(default_factory=list)


@dataclass
class ShowCfg:
    serial_port: str = "/dev/ttyACM0"
    rate_hz: int = 100
    midi_port_name: str = "lightshow"
    blackout_cc: int | None = 119
    global_offset_ms: int = 0
    ports: list[PortCfg] = field(default_factory=list)
    models: list[ModelCfg] = field(default_factory=list)

    def port_by_id(self, port_id: int) -> PortCfg:
        for port in self.ports:
            if port.id == port_id:
                return port
        raise ConfigError(f"no tx_port with id {port_id}")

    def wire_ports(self) -> list[PortWire]:
        """Port list for the CONFIG frame, with failsafe values filled in.

        Channels that no model drives fall back to the port minimum, which the
        airborne controllers read as "off".
        """
        wires = []
        for port in self.ports:
            failsafe = [port.min_us] * port.nchan
            for model in self.models:
                if model.tx_port != port.id:
                    continue
                for index, channel in enumerate(model.channels):
                    failsafe[model.tx_offset + index] = channel.failsafe
            wires.append(
                PortWire(
                    name=port.name,
                    format=port.format,
                    polarity=port.polarity,
                    nchan=port.nchan,
                    frame_us=port.frame_us,
                    sync_us=port.sync_us,
                    min_us=port.min_us,
                    max_us=port.max_us,
                    failsafe=failsafe,
                )
            )
        return wires


def _require(data: dict[str, Any], key: str, where: str) -> Any:
    if key not in data:
        raise ConfigError(f"{where}: missing '{key}'")
    return data[key]


def _parse_channel(data: dict[str, Any], where: str, port: PortCfg) -> ChannelCfg:
    channel = ChannelCfg(
        role=str(_require(data, "role", where)),
        cc=int(_require(data, "cc", where)),
        cc_lsb=int(data["cc_lsb"]) if data.get("cc_lsb") is not None else None,
        quantize=int(data["quantize"]) if data.get("quantize") is not None else None,
        invert=bool(data.get("invert", False)),
        failsafe=int(data.get("failsafe", port.min_us)),
    )
    for name, value in (("cc", channel.cc), ("cc_lsb", channel.cc_lsb)):
        if value is not None and not 0 <= value <= 119:
            # 120..127 are channel mode messages and must not be used as data.
            raise ConfigError(f"{where}: {name} {value} is outside 0..119")
    if channel.quantize is not None and not 2 <= channel.quantize <= 128:
        raise ConfigError(f"{where}: quantize must be between 2 and 128")
    if not port.min_us <= channel.failsafe <= port.max_us:
        raise ConfigError(
            f"{where}: failsafe {channel.failsafe} outside the port range "
            f"{port.min_us}..{port.max_us}"
        )
    return channel


def _parse_port(data: dict[str, Any]) -> PortCfg:
    where = f"tx_ports[{data.get('name', data.get('id', '?'))}]"
    port = PortCfg(
        id=int(_require(data, "id", where)),
        name=str(data.get("name", f"port{data.get('id')}")),
        format=str(data.get("format", "ppm")).lower(),
        polarity=str(data.get("polarity", "normal")).lower(),
        nchan=int(data.get("nchan", 8)),
        frame_us=int(data.get("frame_us", 22500 if data.get("format", "ppm") == "ppm" else 7000)),
        sync_us=int(data.get("sync_us", 400)),
        min_us=int(data.get("min_us", 1000)),
        max_us=int(data.get("max_us", 2000)),
    )
    if port.format not in ("ppm", "sbus", "off"):
        raise ConfigError(f"{where}: format must be ppm, sbus or off")
    if port.polarity not in ("normal", "inverted"):
        raise ConfigError(f"{where}: polarity must be normal or inverted")
    if not 0 <= port.id < MAX_PORTS:
        raise ConfigError(f"{where}: id must be between 0 and {MAX_PORTS - 1}")
    if not 1 <= port.nchan <= MAX_CH:
        raise ConfigError(f"{where}: nchan must be between 1 and {MAX_CH}")
    if port.min_us >= port.max_us:
        raise ConfigError(f"{where}: min_us must be below max_us")

    if port.format == "ppm":
        # The firmware rejects frames that cannot hold every channel at its
        # maximum plus a 3 ms sync gap -- catch it here with a useful message.
        needed = port.nchan * port.max_us + port.sync_us + 3000
        if port.frame_us < needed:
            raise ConfigError(
                f"{where}: frame_us {port.frame_us} is too short for {port.nchan} "
                f"channels, needs at least {needed}"
            )
    elif port.format == "sbus" and port.frame_us < 4000:
        raise ConfigError(f"{where}: sbus frame_us must be at least 4000")
    return port


def _parse_model(data: dict[str, Any], show: ShowCfg) -> ModelCfg:
    where = f"models[{data.get('name', '?')}]"
    model = ModelCfg(
        name=str(_require(data, "name", where)),
        midi_channel=int(_require(data, "midi_channel", where)),
        tx_port=int(_require(data, "tx_port", where)),
        tx_offset=int(data.get("tx_offset", 0)),
    )
    if not 1 <= model.midi_channel <= 16:
        raise ConfigError(f"{where}: midi_channel must be between 1 and 16")

    port = show.port_by_id(model.tx_port)
    channels = _require(data, "channels", where)
    if not isinstance(channels, list) or not channels:
        raise ConfigError(f"{where}: 'channels' must be a non-empty list")
    if model.tx_offset < 0:
        raise ConfigError(f"{where}: tx_offset cannot be negative")
    if model.tx_offset + len(channels) > port.nchan:
        raise ConfigError(
            f"{where}: channels {model.tx_offset + 1}..{model.tx_offset + len(channels)} "
            f"do not fit into port '{port.name}' with {port.nchan} channels"
        )
    model.channels = [
        _parse_channel(entry, f"{where}.channels[{index}]", port)
        for index, entry in enumerate(channels)
    ]

    seen: dict[int, str] = {}
    for channel in model.channels:
        for cc in (channel.cc, channel.cc_lsb):
            if cc is None:
                continue
            if cc in seen:
                raise ConfigError(
                    f"{where}: CC {cc} used by both '{seen[cc]}' and '{channel.role}'"
                )
            seen[cc] = channel.role
    if show.blackout_cc is not None and show.blackout_cc in seen:
        raise ConfigError(
            f"{where}: CC {show.blackout_cc} is reserved as blackout_cc but used by "
            f"'{seen[show.blackout_cc]}'"
        )
    return model


def load(path: str | Path) -> ShowCfg:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping")

    # A missing key keeps the default; an explicit `null` disables the feature.
    blackout = raw.get("blackout_cc", 119)

    show = ShowCfg(
        serial_port=str(raw.get("serial_port", "/dev/ttyACM0")),
        rate_hz=int(raw.get("rate_hz", 100)),
        midi_port_name=str(raw.get("midi_port_name", "lightshow")),
        blackout_cc=None if blackout is None else int(blackout),
        global_offset_ms=int(raw.get("global_offset_ms", 0)),
    )
    if not 10 <= show.rate_hz <= 500:
        raise ConfigError("rate_hz must be between 10 and 500")
    if show.global_offset_ms < 0:
        # We can delay the light, not advance it -- shift the audio instead.
        raise ConfigError("global_offset_ms cannot be negative")

    ports = raw.get("tx_ports") or []
    if not ports:
        raise ConfigError("no tx_ports configured")
    show.ports = [_parse_port(entry) for entry in ports]

    ids = [port.id for port in show.ports]
    if sorted(ids) != list(range(len(ids))):
        raise ConfigError(
            f"tx_port ids must start at 0 and be consecutive, got {sorted(ids)}"
        )
    show.ports.sort(key=lambda port: port.id)

    models = raw.get("models") or []
    if not models:
        raise ConfigError("no models configured")
    show.models = [_parse_model(entry, show) for entry in models]

    used: dict[tuple[int, int], str] = {}
    for model in show.models:
        for channel in model.channels:
            for cc in (channel.cc, channel.cc_lsb):
                if cc is None:
                    continue
                key = (model.midi_channel, cc)
                if key in used:
                    raise ConfigError(
                        f"MIDI channel {model.midi_channel} CC {cc} is claimed by both "
                        f"'{used[key]}' and '{model.name}'"
                    )
                used[key] = model.name

    # Several models may share one transmitter as long as their channel blocks
    # do not overlap -- that is how 16 channels feed four models.
    claimed: dict[tuple[int, int], str] = {}
    for model in show.models:
        for index in range(len(model.channels)):
            key = (model.tx_port, model.tx_offset + index)
            if key in claimed:
                raise ConfigError(
                    f"tx_port {model.tx_port} channel {model.tx_offset + index + 1} is "
                    f"claimed by both '{claimed[key]}' and '{model.name}'"
                )
            claimed[key] = model.name

    return show
