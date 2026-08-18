"""Show configuration: loading and validation of ``show.yaml``."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import bus as bus_mode
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


# GPIOs a Raspberry Pi Pico brings out on its header. 23, 24 and 25 are wired to
# the on-board regulator, USB sensing and the LED; 29 measures VSYS.
PICO_USABLE_GPIO = set(range(0, 23)) | {26, 27, 28}

# The airborne firmware reads SBUS with uart1, and the RP2040 only routes that
# peripheral's RX line to four pins -- GPIO 25 is the on-board LED, so three are
# left on the header. Any other pin gets funcsel UART and then sits on TX, CTS or
# RTS: the image builds, boots and reports itself normally, and never receives a
# single frame. That is an afternoon of searching, so it is refused here.
PICO_UART1_RX_GPIO = {5, 9, 21}

# GPIO number -> physical pin on the Pico header, so the wiring overview can
# name the pin you actually have to solder to.
PICO_PHYSICAL_PIN = {
    0: 1, 1: 2, 2: 4, 3: 5, 4: 6, 5: 7, 6: 9, 7: 10, 8: 11, 9: 12,
    10: 14, 11: 15, 12: 16, 13: 17, 14: 19, 15: 20, 16: 21, 17: 22,
    18: 24, 19: 25, 20: 26, 21: 27, 22: 29, 26: 31, 27: 32, 28: 34,
}

RELAY_SOURCES = ("pixel", "brightness", "cue", "channel", "bus")

# A zone is four channels in this order, and both the airborne firmware and the
# project timeline address them by position, not by name. So the order is not a
# convention -- it is the wiring, and a swapped pair means the model reacts to
# the wrong channel without anything looking wrong anywhere.
CHANNEL_ROLES = ("cue", "hue", "brightness", "param")

MAX_STRIPS = 8      # one PIO state machine each
MAX_RELAYS = 8
MAX_ZONE_PIXELS = 256
CHANNELS_PER_ZONE = 4


@dataclass
class StripCfg:
    name: str
    pin: int
    count: int
    zone: int = 0
    offset: int = 0        # position inside the zone's virtual chain
    reverse: bool = False


@dataclass
class RelayCfg:
    name: str
    pin: int
    zone: int = 0
    source: str = "pixel"  # one of RELAY_SOURCES
    arg: int = 0
    threshold: int = 64
    active_low: bool = False
    min_on_ms: int = 0     # 0 for MOSFETs, ~200 for mechanical relays
    min_off_ms: int = 0


@dataclass
class NavLightCfg:
    strip: int
    index: int
    color: tuple[int, int, int] = (255, 255, 255)


@dataclass
class PlaneCfg:
    """Everything the airborne controller needs; generated into a config.h."""

    board: str = "pico"
    sbus_pin: int = 5
    max_brightness: int = 200
    render_hz: int = 200
    strips: list[StripCfg] = field(default_factory=list)
    relays: list[RelayCfg] = field(default_factory=list)
    nav_lights: list[NavLightCfg] = field(default_factory=list)


@dataclass
class BusRelayCfg:
    """A relay switched straight over the bus, with a control change of its own."""

    name: str
    cc: int
    failsafe: bool = False         # state before the first message arrives


@dataclass
class BusCfg:
    """Bus mode: the model's eight channels carry one addressed data frame.

    Without it, four channels are one zone and eight channels are two, full
    stop. With it, the same eight channels carry a zone address and a payload,
    so a model can have more zones than channels -- paid for in latency, since
    one zone is refreshed per RC frame.
    """

    enabled: bool = False
    relays: list[BusRelayCfg] = field(default_factory=list)

    @property
    def relay_count(self) -> int:
        return len(self.relays)


@dataclass
class ModelCfg:
    name: str
    midi_channel: int              # 1..16 as shown in Ardour
    tx_port: int
    tx_offset: int = 0             # first port channel this model occupies
    channels: list[ChannelCfg] = field(default_factory=list)
    plane: PlaneCfg | None = None
    bus: BusCfg | None = None

    @property
    def zone_count(self) -> int:
        """One zone per group of four channels."""
        return max(1, len(self.channels) // CHANNELS_PER_ZONE)

    @property
    def uses_bus(self) -> bool:
        return self.bus is not None and self.bus.enabled

    @property
    def wire_channels(self) -> int:
        """How many RC channels the model occupies on its transmitter.

        In bus mode that is always the eight the code needs, however many zones
        the model has -- which is the whole point of the mode.
        """
        from .bus import SYMBOLS
        return SYMBOLS if self.uses_bus else len(self.channels)

    def zone_base_channel(self, zone: int) -> int:
        """First RC channel of a zone, counted as the transmitter counts.

        Meaningless in bus mode, where no zone owns channels of its own.
        """
        return self.tx_offset + zone * CHANNELS_PER_ZONE + 1


@dataclass
class ShowCfg:
    serial_port: str = "/dev/ttyACM0"
    rate_hz: int = 100
    midi_port_name: str = "lightshow"
    blackout_cc: int | None = 119
    global_offset_ms: int = 0
    # Above this, a bus zone waits so long for its turn that a cue change no
    # longer lands on the beat. Nothing is forbidden -- combinations past it
    # are shown as such, and the choice stays with whoever runs the show.
    bus_latency_limit_ms: int = 150
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
        from . import bus as bus_mode

        wires = []
        for port in self.ports:
            failsafe = [port.min_us] * port.nchan
            for model in self.models:
                if model.tx_port != port.id:
                    continue
                if model.uses_bus:
                    # A per channel failsafe means nothing here: the eight
                    # channels are one code word, and eight independent
                    # "sensible" values are not a code word at all. What the
                    # ground station must hold is a valid frame saying "off".
                    symbols = bus_mode.failsafe_frame(
                        model.zone_count, model.bus.relay_count)
                    for index, symbol in enumerate(symbols):
                        failsafe[model.tx_offset + index] = bus_mode.symbol_to_us(
                            symbol, port.min_us, port.max_us)
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


def step_us(port: PortCfg, steps: int, index: int) -> int:
    """Microseconds for one step of a quantised channel.

    Each step sits in the *middle* of its band, so a channel that arrives a few
    microseconds off still truncates back to the same index on board. Both the
    MIDI mapper and the project timeline encode through here, and so does the
    link measurement -- a sweep that used its own formula would measure the
    wrong thing.
    """
    span = port.max_us - port.min_us
    index = max(0, min(steps - 1, index))
    return port.min_us + round(span * (index + 0.5) / steps)


def ppm_frame_minimum(nchan: int, max_us: int = 2000, sync_us: int = 400) -> int:
    """Shortest PPM frame that can hold `nchan` channels at their maximum.

    Every channel at full length, the sync pulse, and 3 ms of gap so the
    receiver can tell where the frame ends. The airborne firmware rejects
    anything shorter, so this is what the model wizard suggests and what the
    configuration check enforces -- one rule, one place.
    """
    return nchan * max_us + sync_us + 3000


def level_us(port: PortCfg, level: int) -> int:
    """Microseconds for a continuous channel, 0..255."""
    span = port.max_us - port.min_us
    return port.min_us + round(span * max(0, min(255, level)) / 255)


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


def _check_gpio(pin: int, where: str, what: str) -> None:
    if pin not in PICO_USABLE_GPIO:
        raise ConfigError(
            f"{where}: GPIO {pin} for {what} is not on the Pico header "
            f"(usable: 0-22 and 26-28)"
        )


def _parse_plane(data: dict[str, Any], where: str, model: ModelCfg) -> PlaneCfg:
    plane = PlaneCfg(
        board=str(data.get("board", "pico")),
        sbus_pin=int(data.get("sbus_pin", 5)),
        max_brightness=int(data.get("max_brightness", 200)),
        render_hz=int(data.get("render_hz", 200)),
    )
    if not 1 <= plane.max_brightness <= 255:
        raise ConfigError(f"{where}: max_brightness must be between 1 and 255")
    if not 30 <= plane.render_hz <= 1000:
        raise ConfigError(f"{where}: render_hz must be between 30 and 1000")

    # PWM ist ersatzlos entfallen -- der Empfaenger spricht nur noch SBUS. Eine
    # alte Konfiguration darf nicht stillschweigend durchrutschen, sonst glaubt
    # jemand weiter an einen Rueckfallpfad, den es nicht mehr gibt.
    if "pwm_pins" in data:
        raise ConfigError(
            f"{where}: pwm_pins does not exist any more -- the airborne firmware "
            f"reads SBUS only. Remove the key; GPIO 10-13 are free for strips or "
            f"relays now"
        )

    _check_gpio(plane.sbus_pin, where, "SBUS input")
    if plane.sbus_pin not in PICO_UART1_RX_GPIO:
        raise ConfigError(
            f"{where}: GPIO {plane.sbus_pin} cannot receive SBUS -- the firmware "
            f"uses uart1, whose RX line only reaches GPIO "
            f"{', '.join(str(p) for p in sorted(PICO_UART1_RX_GPIO))}"
        )

    strips = data.get("strips") or []
    relays = data.get("relays") or []
    if len(strips) > MAX_STRIPS:
        raise ConfigError(
            f"{where}: {len(strips)} strips, but only {MAX_STRIPS} PIO state "
            f"machines exist"
        )
    if len(relays) > MAX_RELAYS:
        raise ConfigError(f"{where}: at most {MAX_RELAYS} relays, got {len(relays)}")

    zones = model.zone_count
    for index, entry in enumerate(strips):
        spot = f"{where}.strips[{index}]"
        strip = StripCfg(
            name=str(entry.get("name", f"strip{index}")),
            pin=int(_require(entry, "pin", spot)),
            count=int(_require(entry, "count", spot)),
            zone=int(entry.get("zone", 0)),
            offset=int(entry.get("offset", 0)),
            reverse=bool(entry.get("reverse", False)),
        )
        _check_gpio(strip.pin, spot, "WS2812 data")
        if strip.count < 1:
            raise ConfigError(f"{spot}: count must be at least 1")
        if not 0 <= strip.zone < zones:
            raise ConfigError(
                f"{spot}: zone {strip.zone} does not exist, the model has "
                f"{zones} zone(s) ({len(model.channels)} channels)"
            )
        if strip.offset + strip.count > MAX_ZONE_PIXELS:
            raise ConfigError(
                f"{spot}: reaches pixel {strip.offset + strip.count}, the "
                f"firmware buffers {MAX_ZONE_PIXELS} per zone"
            )
        plane.strips.append(strip)

    for index, entry in enumerate(relays):
        spot = f"{where}.relays[{index}]"
        relay = RelayCfg(
            name=str(entry.get("name", f"relay{index}")),
            pin=int(_require(entry, "pin", spot)),
            zone=int(entry.get("zone", 0)),
            source=str(entry.get("source", "pixel")).lower(),
            arg=int(entry.get("arg", 0)),
            threshold=int(entry.get("threshold", 64)),
            active_low=bool(entry.get("active_low", False)),
            min_on_ms=int(entry.get("min_on_ms", 0)),
            min_off_ms=int(entry.get("min_off_ms", 0)),
        )
        _check_gpio(relay.pin, spot, "relay driver")
        if relay.source not in RELAY_SOURCES:
            raise ConfigError(
                f"{spot}: source must be one of {', '.join(RELAY_SOURCES)}"
            )
        if not 0 <= relay.zone < zones:
            raise ConfigError(f"{spot}: zone {relay.zone} does not exist")
        if not 0 <= relay.threshold <= 255:
            raise ConfigError(f"{spot}: threshold must be between 0 and 255")
        if relay.min_on_ms < 0 or relay.min_off_ms < 0:
            raise ConfigError(f"{spot}: minimum times cannot be negative")

        if relay.source == "pixel":
            # The virtual chain is as long as the furthest strip reaches, not as
            # long as the pixel counts added up: strips sharing an offset mirror
            # each other. Summing would accept an index the firmware then reads
            # as out of range, and the relay would simply never switch.
            zone_pixels = max(
                (s.offset + s.count for s in plane.strips if s.zone == relay.zone),
                default=0,
            )
            if zone_pixels and relay.arg >= zone_pixels:
                raise ConfigError(
                    f"{spot}: follows pixel {relay.arg}, but zone {relay.zone} "
                    f"only has {zone_pixels}"
                )
        elif relay.source == "cue":
            if not 1 <= relay.arg <= 31:
                raise ConfigError(f"{spot}: cue must be between 1 and 31")
        elif relay.source == "channel":
            if not 1 <= relay.arg <= MAX_CH:
                raise ConfigError(f"{spot}: channel must be between 1 and {MAX_CH}")
        elif relay.source == "bus":
            # `arg` is the slot in the model's bus.relays list, so the wire and
            # the aircraft agree on which bit means which relay.
            available = model.bus.relay_count if model.uses_bus else 0
            if not available:
                raise ConfigError(
                    f"{spot}: source 'bus' needs the model to run in bus mode "
                    f"with at least one entry under bus.relays"
                )
            if not 0 <= relay.arg < available:
                raise ConfigError(
                    f"{spot}: bus relay {relay.arg}, but the model declares "
                    f"{available} ({', '.join(r.name for r in model.bus.relays)})"
                )
        plane.relays.append(relay)

    for index, entry in enumerate(data.get("nav_lights") or []):
        spot = f"{where}.nav_lights[{index}]"
        colour = entry.get("color", [255, 255, 255])
        if len(colour) != 3 or any(not 0 <= int(c) <= 255 for c in colour):
            raise ConfigError(f"{spot}: color must be three values between 0 and 255")
        nav = NavLightCfg(
            strip=int(_require(entry, "strip", spot)),
            index=int(_require(entry, "index", spot)),
            color=(int(colour[0]), int(colour[1]), int(colour[2])),
        )
        if not 0 <= nav.strip < len(plane.strips):
            raise ConfigError(f"{spot}: strip {nav.strip} does not exist")
        if nav.index >= plane.strips[nav.strip].count:
            raise ConfigError(
                f"{spot}: pixel {nav.index} is beyond strip "
                f"'{plane.strips[nav.strip].name}' with "
                f"{plane.strips[nav.strip].count} pixels"
            )
        plane.nav_lights.append(nav)

    # One pin can only do one job. The UART pins are reserved for the console.
    used: dict[int, str] = {0: "debug UART TX", 1: "debug UART RX",
                            plane.sbus_pin: "SBUS input"}
    for strip in plane.strips:
        if strip.pin in used:
            raise ConfigError(
                f"{where}: GPIO {strip.pin} is used by both {used[strip.pin]} "
                f"and strip '{strip.name}'"
            )
        used[strip.pin] = f"strip '{strip.name}'"
    for relay in plane.relays:
        if relay.pin in used:
            raise ConfigError(
                f"{where}: GPIO {relay.pin} is used by both {used[relay.pin]} "
                f"and relay '{relay.name}'"
            )
        used[relay.pin] = f"relay '{relay.name}'"

    return plane


def _parse_port(data: dict[str, Any]) -> PortCfg:
    where = f"tx_ports[{data.get('name', data.get('id', '?'))}]"
    # Lower case before the default frame length is picked from it, or
    # `format: PPM` would silently get the much shorter SBUS default.
    fmt = str(data.get("format", "ppm")).lower()
    port = PortCfg(
        id=int(_require(data, "id", where)),
        name=str(data.get("name", f"port{data.get('id')}")),
        format=fmt,
        polarity=str(data.get("polarity", "normal")).lower(),
        nchan=int(data.get("nchan", 8)),
        frame_us=int(data.get("frame_us", 22500 if fmt == "ppm" else 7000)),
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
    # The same window the firmware accepts in cfg_valid(). Checking it here
    # turns "the board ignores my configuration" into a message at startup.
    if port.min_us < 500 or port.max_us > 2500:
        raise ConfigError(
            f"{where}: the pulse range must stay within 500..2500 us, got "
            f"{port.min_us}..{port.max_us}"
        )

    if port.format == "ppm":
        if not 50 <= port.sync_us <= 800:
            raise ConfigError(
                f"{where}: sync_us {port.sync_us} is outside 50..800, which is "
                f"what the firmware accepts"
            )
        # The firmware rejects frames that cannot hold every channel at its
        # maximum plus a 3 ms sync gap -- catch it here with a useful message.
        needed = ppm_frame_minimum(port.nchan, port.max_us, port.sync_us)
        if port.frame_us < needed:
            raise ConfigError(
                f"{where}: frame_us {port.frame_us} is too short for {port.nchan} "
                f"channels, needs at least {needed}"
            )
    elif port.format == "sbus" and port.frame_us < 4000:
        raise ConfigError(f"{where}: sbus frame_us must be at least 4000")
    return port


def _parse_bus(data: Any, where: str) -> BusCfg | None:
    """The `bus` section of a model. Absent or false means classic channels."""
    if data is None or data is False:
        return None
    if data is True:
        return BusCfg(enabled=True)
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: must be true, false or a section")

    bus_cfg = BusCfg(enabled=bool(data.get("enabled", True)))
    entries = data.get("relays") or []
    if not isinstance(entries, list):
        raise ConfigError(f"{where}.relays: must be a list")
    for index, entry in enumerate(entries):
        spot = f"{where}.relays[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{spot}: must be a section")
        bus_cfg.relays.append(BusRelayCfg(
            name=str(entry.get("name", f"relay{index}")),
            cc=int(_require(entry, "cc", spot)),
            failsafe=bool(entry.get("failsafe", False)),
        ))
    return bus_cfg


def _check_bus(model: ModelCfg, port: PortCfg, where: str) -> None:
    """What bus mode demands beyond the ordinary channel rules."""
    zones = model.zone_count
    relays = model.bus.relay_count

    if len(model.channels) % CHANNELS_PER_ZONE != 0:
        raise ConfigError(
            f"{where}: bus mode carries whole zones, so channels come in "
            f"groups of {CHANNELS_PER_ZONE} -- got {len(model.channels)}"
        )
    if zones > bus_mode.MAX_ZONES:
        raise ConfigError(
            f"{where}: {zones} zones, but the address field carries at most "
            f"{bus_mode.MAX_ZONES}"
        )
    if not bus_mode.fits(zones, relays):
        used = bus_mode.payload_used(zones, relays)
        raise ConfigError(
            f"{where}: {zones} zones and {relays} bus relays need {used} bits, "
            f"but a frame carries {bus_mode.PAYLOAD_BITS}. Drop "
            f"{used - bus_mode.PAYLOAD_BITS} relay(s) or a zone."
        )

    # A cue channel that quantises to something other than the 32 steps a
    # symbol holds would be encoded twice, differently.
    for index, channel in enumerate(model.channels):
        if channel.role == "cue" and channel.quantize not in (None, bus_mode.GF_SIZE):
            raise ConfigError(
                f"{where}.channels[{index}]: bus mode carries a cue as one "
                f"{bus_mode.SYMBOL_BITS} bit symbol, so quantize must be "
                f"{bus_mode.GF_SIZE}, not {channel.quantize}"
            )


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

    model.bus = _parse_bus(data.get("bus"), f"{where}.bus")

    occupied = bus_mode.SYMBOLS if model.uses_bus else len(channels)
    if model.tx_offset + occupied > port.nchan:
        what = ("the bus needs eight channels" if model.uses_bus
                else f"channels {model.tx_offset + 1}..{model.tx_offset + occupied}")
        raise ConfigError(
            f"{where}: {what}, which do not fit into port '{port.name}' with "
            f"{port.nchan} channels"
        )
    model.channels = [
        _parse_channel(entry, f"{where}.channels[{index}]", port)
        for index, entry in enumerate(channels)
    ]

    # Both the airborne firmware and the timeline read a zone's four channels by
    # position. Nothing downstream ever looks at `role` again, so a wrong order
    # here is invisible everywhere else -- the model just answers to the wrong
    # channel. Checking it is the only place the mistake can still be caught.
    for index, channel in enumerate(model.channels):
        expected = CHANNEL_ROLES[index % CHANNELS_PER_ZONE]
        if channel.role != expected:
            raise ConfigError(
                f"{where}.channels[{index}]: role '{channel.role}', but position "
                f"{index + 1} of a zone is '{expected}' -- the order "
                f"{', '.join(CHANNEL_ROLES)} is what the firmware decodes"
            )

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

    if model.uses_bus:
        _check_bus(model, port, where)
        for relay in model.bus.relays:
            if relay.cc in seen:
                raise ConfigError(
                    f"{where}: CC {relay.cc} used by both '{seen[relay.cc]}' and "
                    f"bus relay '{relay.name}'"
                )
            seen[relay.cc] = f"bus relay {relay.name}"
    if show.blackout_cc is not None and show.blackout_cc in seen:
        raise ConfigError(
            f"{where}: CC {show.blackout_cc} is reserved as blackout_cc but used by "
            f"'{seen[show.blackout_cc]}'"
        )

    if data.get("plane") is not None:
        if len(model.channels) % CHANNELS_PER_ZONE != 0:
            raise ConfigError(
                f"{where}: a model with a 'plane' section needs channels in "
                f"groups of {CHANNELS_PER_ZONE} (cue, hue, brightness, param) "
                f"-- one group per zone, got {len(model.channels)}"
            )
        model.plane = _parse_plane(data["plane"], f"{where}.plane", model)

    return model


def load(path: str | Path) -> ShowCfg:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    return _build(raw, str(path))


def _build(raw: dict[str, Any], source: str) -> ShowCfg:
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: top level must be a mapping")

    # A missing key keeps the default; an explicit `null` disables the feature.
    blackout = raw.get("blackout_cc", 119)

    show = ShowCfg(
        serial_port=str(raw.get("serial_port", "/dev/ttyACM0")),
        rate_hz=int(raw.get("rate_hz", 100)),
        midi_port_name=str(raw.get("midi_port_name", "lightshow")),
        blackout_cc=None if blackout is None else int(blackout),
        global_offset_ms=int(raw.get("global_offset_ms", 0)),
        bus_latency_limit_ms=int(raw.get("bus_latency_limit_ms", 150)),
    )
    if not 10 <= show.rate_hz <= 500:
        raise ConfigError("rate_hz must be between 10 and 500")
    if show.bus_latency_limit_ms <= 0:
        raise ConfigError("bus_latency_limit_ms must be positive")
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
        # A bus model occupies eight channels however many zones it has, so the
        # block to reserve is the wire block, not the channel list.
        for index in range(model.wire_channels):
            key = (model.tx_port, model.tx_offset + index)
            if key in claimed:
                raise ConfigError(
                    f"tx_port {model.tx_port} channel {model.tx_offset + index + 1} is "
                    f"claimed by both '{claimed[key]}' and '{model.name}'"
                )
            claimed[key] = model.name

    return show


# --------------------------------------------------------------- writing back


def to_dict(show: ShowCfg) -> dict[str, Any]:
    """Plain data, as it is served to the web UI and written back to YAML."""
    data: dict[str, Any] = {
        "serial_port": show.serial_port,
        "rate_hz": show.rate_hz,
        "midi_port_name": show.midi_port_name,
        "blackout_cc": show.blackout_cc,
        "global_offset_ms": show.global_offset_ms,
        "bus_latency_limit_ms": show.bus_latency_limit_ms,
        "tx_ports": [
            {
                "id": port.id,
                "name": port.name,
                "format": port.format,
                "polarity": port.polarity,
                "nchan": port.nchan,
                "frame_us": port.frame_us,
                "sync_us": port.sync_us,
                "min_us": port.min_us,
                "max_us": port.max_us,
            }
            for port in show.ports
        ],
        "models": [],
    }

    for model in show.models:
        entry: dict[str, Any] = {
            "name": model.name,
            "midi_channel": model.midi_channel,
            "tx_port": model.tx_port,
            "tx_offset": model.tx_offset,
            "channels": [],
        }
        for channel in model.channels:
            item: dict[str, Any] = {"role": channel.role, "cc": channel.cc}
            if channel.cc_lsb is not None:
                item["cc_lsb"] = channel.cc_lsb
            if channel.quantize is not None:
                item["quantize"] = channel.quantize
            if channel.invert:
                item["invert"] = True
            item["failsafe"] = channel.failsafe
            entry["channels"].append(item)

        if model.bus is not None:
            entry["bus"] = {
                "enabled": model.bus.enabled,
                "relays": [
                    {"name": relay.name, "cc": relay.cc,
                     "failsafe": relay.failsafe}
                    for relay in model.bus.relays
                ],
            }

        if model.plane is not None:
            plane = model.plane
            entry["plane"] = {
                "board": plane.board,
                "sbus_pin": plane.sbus_pin,
                "max_brightness": plane.max_brightness,
                "render_hz": plane.render_hz,
                "strips": [
                    {
                        "name": strip.name,
                        "pin": strip.pin,
                        "count": strip.count,
                        "zone": strip.zone,
                        "offset": strip.offset,
                        "reverse": strip.reverse,
                    }
                    for strip in plane.strips
                ],
                "relays": [
                    {
                        "name": relay.name,
                        "pin": relay.pin,
                        "zone": relay.zone,
                        "source": relay.source,
                        "arg": relay.arg,
                        "threshold": relay.threshold,
                        "active_low": relay.active_low,
                        "min_on_ms": relay.min_on_ms,
                        "min_off_ms": relay.min_off_ms,
                    }
                    for relay in plane.relays
                ],
                "nav_lights": [
                    {"strip": nav.strip, "index": nav.index, "color": list(nav.color)}
                    for nav in plane.nav_lights
                ],
            }
        data["models"].append(entry)

    return data


HEADER = """\
# Show-Konfiguration fuer die Lightshow-Bridge.
#
# Diese Datei wird von der Web-UI geschrieben. Eigene Kommentare gehen dabei
# verloren -- Notizen also besser in docs/ ablegen.
#
#   python -m lightshow --check     Konfiguration pruefen
#   python -m lightshow --dry-run   ohne Hardware laufen lassen
"""


class _Dumper(yaml.SafeDumper):
    """Keeps short numeric lists on one line, so colours and pin lists stay readable."""


def _represent_list(dumper: yaml.SafeDumper, data: list) -> yaml.Node:
    inline = len(data) <= 8 and all(isinstance(item, int) for item in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=inline)


_Dumper.add_representer(list, _represent_list)


def dump(show: ShowCfg) -> str:
    body = yaml.dump(
        to_dict(show), Dumper=_Dumper, sort_keys=False, allow_unicode=True,
        default_flow_style=False, width=100, indent=2,
    )
    return HEADER + "\n" + body


def load_dict(data: dict[str, Any]) -> ShowCfg:
    """Validates plain data the same way load() validates a file."""
    return _build(data, "<web ui>")


def save(show: ShowCfg, path: str | Path) -> Path:
    """Writes the configuration, keeping the previous version as .bak."""
    path = Path(path)
    text = dump(show)
    # Parse what we are about to write, so a bug here cannot leave an
    # unloadable file behind.
    load_dict(yaml.safe_load(text))

    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_text(path.read_text())
    path.write_text(text)
    return path
