"""Show configuration: loading and validation of ``show.yaml``."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
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
    quantize: int | None = None    # number of discrete steps, for cue channels
    invert: bool = False
    failsafe: int = 1000


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

# A zone is four channels in this order, and both the airborne firmware and the
# project timeline address them by position, not by name. So the order is not a
# convention -- it is the wiring, and a swapped pair means the model reacts to
# the wrong channel without anything looking wrong anywhere.
CHANNEL_ROLES = ("cue", "hue", "brightness", "param")

@dataclass(frozen=True)
class BoardCfg:
    """A ready-made board: which GPIO its connectors actually go to.

    A model built on one of these does not get to choose its pins -- they are
    etched into the copper. Saying which board it is therefore does two things:
    it lets the wizard fill the pins in rather than ask, and it lets the check
    catch a configuration that claims a board and then names a pin the board
    does not bring out anywhere.
    """

    key: str
    name: str
    sbus_pin: int
    led_pins: tuple[int, ...]
    relay_pins: tuple[int, ...]


# `board: pico` means a free build -- a bare Pico wired by hand, where nothing
# below applies and every pin is the builder's choice.
FREE_BOARD = "pico"

BOARDS: dict[str, BoardCfg] = {
    "modell-2led-2relais-v1": BoardCfg(
        key="modell-2led-2relais-v1",
        name="RC-Lightshow Modell-2LED-2Relais-v1",
        sbus_pin=5,
        led_pins=(2, 3),
        relay_pins=(6, 7),
    ),
}

# Boards that were called something else before. Naming the successor beats a
# list of everything that exists, which is what an unknown name would get.
RENAMED_BOARDS = {"modell-v1": "modell-2led-2relais-v1"}

# What the preview draws a model as. Only the ground station cares: the airborne
# config.h has no idea what shape it is bolted into. Names are what goes in
# show.yaml; the sentence is what the interface offers.
AIRFRAMES = {
    "motor": "Motorflugzeug",
    "segler": "Segelflugzeug",
    "quad": "Quadrocopter",
}

MAX_OUTPUTS = 8         # one PIO state machine each
MAX_SEGMENTS = 16
MAX_RELAYS = 8
MAX_ZONE_PIXELS = 256   # longest virtual chain one zone may render
MAX_OUTPUT_PIXELS = 256  # longest physical chain on one GPIO
CHANNELS_PER_ZONE = 4


# The four sides of a model anybody can walk around.
VIEWS = ("top", "bottom", "left", "right")


@dataclass
class PlacementCfg:
    """Where a segment sits on the mockup: a line on one of four views.

    A strip is a line on the airframe, so a line is what this is -- the pixels
    lay themselves along it from `x1,y1` to `x2,y2`. Coordinates are 0..1 across
    the view, so the drawing scales with the window.

    Nothing downstream reads this: not the generator, not the firmware, not the
    wire. It exists so a show can be judged without an aircraft on the bench,
    and it is written back into show.yaml so that judgement survives a restart.
    """

    view: str = "top"
    x1: float = 0.35
    y1: float = 0.5
    x2: float = 0.65
    y2: float = 0.5


@dataclass
class SegmentCfg:
    """A stretch of one physical chain that belongs to one zone.

    The wire is physical and the zone is editorial. Keeping them in one table
    forced a chain to be exactly one zone, which let a soldering decision
    dictate a lighting decision; a segment is where the two meet instead.
    """

    name: str
    start: int             # first pixel of this segment on its chain
    count: int
    zone: int = 0
    offset: int = 0        # position inside the zone's virtual chain
    reverse: bool = False
    # Purely for the preview; absent until somebody places it.
    place: PlacementCfg | None = None

    @property
    def end(self) -> int:
        return self.start + self.count


@dataclass
class OutputCfg:
    """One WS2812 chain: one GPIO, one PIO state machine, N pixels."""

    name: str
    pin: int
    count: int
    segments: list[SegmentCfg] = field(default_factory=list)


@dataclass
class RelayCfg:
    """The board side of one relay: which pin, and how fast it may switch.

    Which relay it *is* comes from its position in the list, which is also its
    bit in the bus frame and its entry in the model's ``bus.relays``. There is
    no slot number to get wrong.
    """

    name: str
    pin: int
    active_low: bool = False
    min_on_ms: int = 0     # 0 for MOSFETs, ~200 for mechanical relays
    min_off_ms: int = 0


@dataclass
class NavLightCfg:
    output: int            # index into PlaneCfg.outputs
    index: int             # absolute pixel on that chain
    color: tuple[int, int, int] = (255, 255, 255)


@dataclass
class PlaneCfg:
    """Everything the airborne controller needs; generated into a config.h."""

    board: str = "pico"
    # What sort of aircraft this is. Nothing airborne reads it -- the generator
    # ignores it and it never goes over the link. It exists so the preview can
    # draw the shape the strips are actually on: a strip along a glider's wing
    # and one along a quadcopter's arm are not the same picture.
    airframe: str = "motor"
    sbus_pin: int = 5
    max_brightness: int = 200
    render_hz: int = 200
    outputs: list[OutputCfg] = field(default_factory=list)
    relays: list[RelayCfg] = field(default_factory=list)
    nav_lights: list[NavLightCfg] = field(default_factory=list)

    @property
    def segments(self) -> list[tuple[int, SegmentCfg]]:
        """Every segment with the index of the chain it sits on, in wire order."""
        return [(index, segment)
                for index, output in enumerate(self.outputs)
                for segment in output.segments]

    def zone_pixels(self, zone: int) -> int:
        """Length of the virtual chain a zone renders.

        As long as the furthest segment reaches, not the pixel counts added up:
        segments sharing an offset mirror each other.
        """
        return max((segment.offset + segment.count
                    for _, segment in self.segments if segment.zone == zone),
                   default=0)


@dataclass
class BusRelayCfg:
    """A relay switched straight over the bus, by one bit of the frame."""

    name: str
    failsafe: bool = False         # state before the show says otherwise


@dataclass
class BusCfg:
    """The model's eight channels carry one addressed data frame.

    This is how every model talks now. The alternative -- four channels being
    one zone, eight being two, full stop -- was dropped: it could not carry more
    zones than channels, it could not switch a relay independently of a zone,
    and it could not tell a foreign frame from a valid one. Keeping both meant
    every rule downstream had two answers.

    Paid for in latency: one zone is refreshed per RC frame.
    """

    relays: list[BusRelayCfg] = field(default_factory=list)

    @property
    def relay_count(self) -> int:
        return len(self.relays)


@dataclass
class ModelCfg:
    name: str
    tx_port: int
    tx_offset: int = 0             # first port channel this model occupies
    channels: list[ChannelCfg] = field(default_factory=list)
    plane: PlaneCfg | None = None
    bus: BusCfg = field(default_factory=BusCfg)

    @property
    def zone_count(self) -> int:
        """One zone per group of four channels."""
        return max(1, len(self.channels) // CHANNELS_PER_ZONE)

    @property
    def wire_channels(self) -> int:
        """How many RC channels the model occupies on its transmitter.

        Always the eight the code needs, however many zones the model has --
        which is the whole point of the bus.
        """
        from .bus import SYMBOLS
        return SYMBOLS

    def zone_base_channel(self, zone: int) -> int:
        """First RC channel of a zone, counted as the transmitter counts.

        No zone owns channels of its own any more; this is what the sweep tool
        drives when it characterises the radio link, and what the measure build
        prints. It is a position on the wire, not a route to a zone.
        """
        return self.tx_offset + zone * CHANNELS_PER_ZONE + 1


@dataclass
class ShowCfg:
    serial_port: str = "/dev/ttyACM0"
    rate_hz: int = 100
    global_offset_ms: int = 0
    # Above this, a bus zone waits so long for its turn that a cue change no
    # longer lands on the beat. Nothing is forbidden -- combinations past it
    # are shown as such, and the choice stays with whoever runs the show.
    bus_latency_limit_ms: int = 150
    ports: list[PortCfg] = field(default_factory=list)
    models: list[ModelCfg] = field(default_factory=list)

    def adopt(self, other: "ShowCfg") -> None:
        """Becomes `other`, in place, keeping this object's identity.

        The bridge hands the same ShowCfg to the mapper, the link, the session,
        the monitor and the web server, and each of them keeps it for as long as
        it runs. Replacing the object would leave every one of those holding the
        old one, and the interface would report a change nobody downstream had
        heard of. Copying the fields across instead means there is exactly one
        configuration in the process, before and after an edit.

        Only what the file describes is copied. Anything derived from it --
        the mapper's slots, the port setup the ground station was given -- has
        to be rebuilt by whoever owns it; see `Server.apply_show`.
        """
        for f in fields(self):
            setattr(self, f.name, getattr(other, f.name))

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
                # A per channel failsafe means nothing here: the eight channels
                # are one code word, and eight independent "sensible" values are
                # not a code word at all. What the ground station must hold is a
                # valid frame saying "off".
                symbols = bus_mode.failsafe_frame(
                    model.zone_count, model.bus.relay_count)
                for index, symbol in enumerate(symbols):
                    failsafe[model.tx_offset + index] = bus_mode.symbol_to_us(
                        symbol, port.min_us, port.max_us)
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
    resting mapper and the project timeline encode through here, and so does
    the link measurement -- a sweep that used its own formula would measure the
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
        quantize=int(data["quantize"]) if data.get("quantize") is not None else None,
        invert=bool(data.get("invert", False)),
        failsafe=int(data.get("failsafe", port.min_us)),
    )
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
        airframe=str(data.get("airframe", "motor")),
        sbus_pin=int(data.get("sbus_pin", 5)),
        max_brightness=int(data.get("max_brightness", 200)),
        render_hz=int(data.get("render_hz", 200)),
    )
    if not 1 <= plane.max_brightness <= 255:
        raise ConfigError(f"{where}: max_brightness must be between 1 and 255")
    if not 30 <= plane.render_hz <= 1000:
        raise ConfigError(f"{where}: render_hz must be between 30 and 1000")
    if plane.airframe not in AIRFRAMES:
        raise ConfigError(
            f"{where}: airframe '{plane.airframe}' is unknown "
            f"(pick one of: {', '.join(AIRFRAMES)})"
        )

    board = BOARDS.get(plane.board)
    if board is None and plane.board != FREE_BOARD:
        if plane.board in RENAMED_BOARDS:
            raise ConfigError(
                f"{where}: board '{plane.board}' is now called "
                f"'{RENAMED_BOARDS[plane.board]}' -- the silkscreen names the "
                f"variant since more boards are coming"
            )
        known = ", ".join([FREE_BOARD, *sorted(BOARDS)])
        raise ConfigError(f"{where}: board '{plane.board}' is unknown -- one of {known}")
    if board is not None and plane.sbus_pin != board.sbus_pin:
        raise ConfigError(
            f"{where}: '{board.name}' wires SBUS to GPIO {board.sbus_pin}, not "
            f"{plane.sbus_pin}. Use board '{FREE_BOARD}' for a hand-wired build"
        )

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

    # A chain used to be a zone, so the key was called `strips`. Refusing the
    # old name is louder than migrating it: the shape below is different enough
    # that a silent guess would put pixels in the wrong place.
    if "strips" in data:
        raise ConfigError(
            f"{where}: 'strips' is now 'outputs' -- a chain is one GPIO, and the "
            f"zones it serves are 'segments' underneath it. A former strip "
            f"becomes an output with one segment covering all its pixels"
        )

    outputs = data.get("outputs") or []
    relays = data.get("relays") or []
    if len(outputs) > MAX_OUTPUTS:
        raise ConfigError(
            f"{where}: {len(outputs)} LED outputs, but only {MAX_OUTPUTS} PIO "
            f"state machines exist"
        )
    if len(relays) > MAX_RELAYS:
        raise ConfigError(f"{where}: at most {MAX_RELAYS} relays, got {len(relays)}")

    zones = model.zone_count
    for index, entry in enumerate(outputs):
        spot = f"{where}.outputs[{index}]"
        output = OutputCfg(
            name=str(entry.get("name", f"output{index}")),
            pin=int(_require(entry, "pin", spot)),
            count=int(_require(entry, "count", spot)),
        )
        _check_gpio(output.pin, spot, "WS2812 data")
        if board is not None and output.pin not in board.led_pins:
            raise ConfigError(
                f"{spot}: '{board.name}' brings its LED connectors out on GPIO "
                f"{', '.join(str(pin) for pin in board.led_pins)}, not "
                f"{output.pin}"
            )
        if output.count < 1:
            raise ConfigError(f"{spot}: count must be at least 1")
        if output.count > MAX_OUTPUT_PIXELS:
            raise ConfigError(
                f"{spot}: {output.count} pixels, the firmware buffers "
                f"{MAX_OUTPUT_PIXELS} per chain"
            )

        entries = entry.get("segments")
        if entries is None:
            # A chain nobody divided is one segment covering all of it. Saying
            # so here keeps the rest of the code free of a special case.
            entries = [{"name": output.name, "start": 0, "count": output.count}]
        if not isinstance(entries, list) or not entries:
            raise ConfigError(f"{spot}.segments: must be a non-empty list")

        cursor = 0
        for si, sub_entry in enumerate(entries):
            sspot = f"{spot}.segments[{si}]"
            if not isinstance(sub_entry, dict):
                raise ConfigError(f"{sspot}: must be a section")
            # `start` is optional: segments given without one simply follow each
            # other along the chain, which is what dividing a strip means.
            start = int(sub_entry.get("start", cursor))
            segment = SegmentCfg(
                name=str(sub_entry.get("name", f"{output.name}{si + 1}")),
                start=start,
                count=int(sub_entry.get("count", output.count - start)),
                zone=int(sub_entry.get("zone", 0)),
                offset=int(sub_entry.get("offset", 0)),
                reverse=bool(sub_entry.get("reverse", False)),
                place=parse_placement(sub_entry.get("place"), f"{sspot}.place"),
            )
            if segment.count < 1:
                raise ConfigError(f"{sspot}: count must be at least 1")
            if segment.start < 0:
                raise ConfigError(f"{sspot}: start cannot be negative")
            if segment.end > output.count:
                raise ConfigError(
                    f"{sspot}: reaches pixel {segment.end} of chain "
                    f"'{output.name}', which has {output.count}"
                )
            for other in output.segments:
                if segment.start < other.end and other.start < segment.end:
                    raise ConfigError(
                        f"{sspot}: pixels {segment.start}..{segment.end - 1} "
                        f"overlap segment '{other.name}' "
                        f"({other.start}..{other.end - 1}) on the same chain"
                    )
            if not 0 <= segment.zone < zones:
                raise ConfigError(
                    f"{sspot}: zone {segment.zone} does not exist, the model has "
                    f"{zones} zone(s) ({len(model.channels)} channels)"
                )
            if segment.offset + segment.count > MAX_ZONE_PIXELS:
                raise ConfigError(
                    f"{sspot}: reaches pixel {segment.offset + segment.count} of "
                    f"its zone, the firmware buffers {MAX_ZONE_PIXELS} per zone"
                )
            output.segments.append(segment)
            cursor = max(cursor, segment.end)

        plane.outputs.append(output)

    total_segments = sum(len(output.segments) for output in plane.outputs)
    if total_segments > MAX_SEGMENTS:
        raise ConfigError(
            f"{where}: {total_segments} segments in total, the firmware holds "
            f"{MAX_SEGMENTS}"
        )

    # A relay used to be able to derive its state on board -- from a pixel, the
    # master dimmer, a cue number or a raw RC channel. Those are gone: a relay
    # is switched over the bus and nowhere else. The old keys are named rather
    # than ignored, because a configuration carrying them describes behaviour
    # this firmware no longer has.
    gone = {
        "source": "a relay is always switched over the bus now",
        "arg": "the position in this list is the bit in the frame",
        "threshold": "there is no level left to compare against",
        "zone": "a relay hangs off no zone at all any more",
    }
    for index, entry in enumerate(relays):
        spot = f"{where}.relays[{index}]"
        for key, why in gone.items():
            if key in entry:
                raise ConfigError(f"{spot}: '{key}' does not exist any more -- {why}")

        relay = RelayCfg(
            name=str(entry.get("name", f"relay{index}")),
            pin=int(_require(entry, "pin", spot)),
            active_low=bool(entry.get("active_low", False)),
            min_on_ms=int(entry.get("min_on_ms", 0)),
            min_off_ms=int(entry.get("min_off_ms", 0)),
        )
        _check_gpio(relay.pin, spot, "relay driver")
        if board is not None and relay.pin not in board.relay_pins:
            raise ConfigError(
                f"{spot}: '{board.name}' brings its switched outputs out on GPIO "
                f"{', '.join(str(pin) for pin in board.relay_pins)}, not "
                f"{relay.pin}"
            )
        if relay.min_on_ms < 0 or relay.min_off_ms < 0:
            raise ConfigError(f"{spot}: minimum times cannot be negative")
        plane.relays.append(relay)

    # The board list and the wire list are two halves of the same relay, paired
    # by position. Different lengths means a reserved bit nothing switches, or a
    # relay nothing can reach; a different name at the same index means the two
    # got out of order, which would switch the wrong device without any of it
    # looking wrong.
    wire = model.bus.relays
    if len(plane.relays) != len(wire):
        raise ConfigError(
            f"{where}: {len(plane.relays)} relay(s) on the board but "
            f"{len(wire)} in bus.relays. Each relay needs both: a bit on the "
            f"wire and a pin to drive"
        )
    for index, (board, air) in enumerate(zip(plane.relays, wire)):
        if board.name != air.name:
            raise ConfigError(
                f"{where}.relays[{index}]: named '{board.name}' here but "
                f"'{air.name}' in bus.relays[{index}]. They are one relay and "
                f"are paired by position, so the two lists must agree"
            )

    for index, entry in enumerate(data.get("nav_lights") or []):
        spot = f"{where}.nav_lights[{index}]"
        colour = entry.get("color", [255, 255, 255])
        if len(colour) != 3 or any(not 0 <= int(c) <= 255 for c in colour):
            raise ConfigError(f"{spot}: color must be three values between 0 and 255")
        if "strip" in entry and "output" not in entry:
            raise ConfigError(
                f"{spot}: 'strip' is now 'output' and counts pixels along the "
                f"whole chain, not within one zone"
            )
        nav = NavLightCfg(
            output=int(_require(entry, "output", spot)),
            index=int(_require(entry, "index", spot)),
            color=(int(colour[0]), int(colour[1]), int(colour[2])),
        )
        if not 0 <= nav.output < len(plane.outputs):
            raise ConfigError(f"{spot}: output {nav.output} does not exist")
        if nav.index >= plane.outputs[nav.output].count:
            raise ConfigError(
                f"{spot}: pixel {nav.index} is beyond chain "
                f"'{plane.outputs[nav.output].name}' with "
                f"{plane.outputs[nav.output].count} pixels"
            )
        plane.nav_lights.append(nav)

    # One pin can only do one job. The UART pins are reserved for the console.
    used: dict[int, str] = {0: "debug UART TX", 1: "debug UART RX",
                            plane.sbus_pin: "SBUS input"}
    for output in plane.outputs:
        if output.pin in used:
            raise ConfigError(
                f"{where}: GPIO {output.pin} is used by both {used[output.pin]} "
                f"and LED output '{output.name}'"
            )
        used[output.pin] = f"LED output '{output.name}'"
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


def parse_placement(data: Any, where: str) -> PlacementCfg | None:
    """Where a segment sits on the mockup. Absent means "not placed yet"."""
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: must be a section")

    view = str(data.get("view", "top")).lower()
    if view not in VIEWS:
        raise ConfigError(f"{where}.view: must be one of {', '.join(VIEWS)}")

    def coord(key: str, fallback: float) -> float:
        value = float(data.get(key, fallback))
        # Clamped rather than refused: this is a drawing, and a point just off
        # the edge is a slip of the mouse, not a configuration error.
        return max(0.0, min(1.0, value))

    return PlacementCfg(
        view=view,
        x1=coord("x1", 0.35), y1=coord("y1", 0.5),
        x2=coord("x2", 0.65), y2=coord("y2", 0.5),
    )


def _parse_bus(data: Any, where: str) -> BusCfg:
    """The `bus` section of a model. Absent means a bus with no relays."""
    if data is None or data is True:
        return BusCfg()
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: must be a section")
    # Bus mode is not optional any more, so a configuration that switches it off
    # is refused rather than quietly ignored -- otherwise someone keeps
    # believing in a mode the firmware no longer builds.
    if data.get("enabled") is False:
        raise ConfigError(
            f"{where}.enabled: bus mode cannot be switched off -- it is the only "
            f"mode the airborne firmware still has. Remove the key"
        )

    bus_cfg = BusCfg()
    entries = data.get("relays") or []
    if not isinstance(entries, list):
        raise ConfigError(f"{where}.relays: must be a list")
    for index, entry in enumerate(entries):
        spot = f"{where}.relays[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{spot}: must be a section")
        bus_cfg.relays.append(BusRelayCfg(
            name=str(entry.get("name", f"relay{index}")),
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
        tx_port=int(_require(data, "tx_port", where)),
        tx_offset=int(data.get("tx_offset", 0)),
    )
    port = show.port_by_id(model.tx_port)
    channels = _require(data, "channels", where)
    if not isinstance(channels, list) or not channels:
        raise ConfigError(f"{where}: 'channels' must be a non-empty list")
    if model.tx_offset < 0:
        raise ConfigError(f"{where}: tx_offset cannot be negative")

    model.bus = _parse_bus(data.get("bus"), f"{where}.bus")

    occupied = bus_mode.SYMBOLS
    if model.tx_offset + occupied > port.nchan:
        raise ConfigError(
            f"{where}: the bus needs eight channels, which do not fit into port "
            f"'{port.name}' with {port.nchan} channels"
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

    _check_bus(model, port, where)

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

    show = ShowCfg(
        serial_port=str(raw.get("serial_port", "/dev/ttyACM0")),
        rate_hz=int(raw.get("rate_hz", 100)),
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

    # No models is the state a fresh installation starts in -- the AppImage
    # ships without any, and the wizard is where they come from. Everything
    # downstream copes: the mapper builds failsafe frames for the jacks, and a
    # project says for itself that it needs a model first.
    show.models = [_parse_model(entry, show) for entry in raw.get("models") or []]

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
            "tx_port": model.tx_port,
            "tx_offset": model.tx_offset,
            "channels": [],
        }
        for channel in model.channels:
            item: dict[str, Any] = {"role": channel.role}
            if channel.quantize is not None:
                item["quantize"] = channel.quantize
            if channel.invert:
                item["invert"] = True
            item["failsafe"] = channel.failsafe
            entry["channels"].append(item)

        if model.bus.relays:
            entry["bus"] = {
                "relays": [
                    {"name": relay.name, "failsafe": relay.failsafe}
                    for relay in model.bus.relays
                ],
            }

        if model.plane is not None:
            plane = model.plane
            entry["plane"] = {
                "board": plane.board,
                "airframe": plane.airframe,
                "sbus_pin": plane.sbus_pin,
                "max_brightness": plane.max_brightness,
                "render_hz": plane.render_hz,
                "outputs": [
                    {
                        "name": output.name,
                        "pin": output.pin,
                        "count": output.count,
                        "segments": [
                            {
                                "name": segment.name,
                                "start": segment.start,
                                "count": segment.count,
                                "zone": segment.zone,
                                "offset": segment.offset,
                                "reverse": segment.reverse,
                                **({"place": {
                                    "view": segment.place.view,
                                    "x1": round(segment.place.x1, 4),
                                    "y1": round(segment.place.y1, 4),
                                    "x2": round(segment.place.x2, 4),
                                    "y2": round(segment.place.y2, 4),
                                }} if segment.place else {}),
                            }
                            for segment in output.segments
                        ],
                    }
                    for output in plane.outputs
                ],
                "relays": [
                    {
                        "name": relay.name,
                        "pin": relay.pin,
                        "active_low": relay.active_low,
                        "min_on_ms": relay.min_on_ms,
                        "min_off_ms": relay.min_off_ms,
                    }
                    for relay in plane.relays
                ],
                "nav_lights": [
                    {"output": nav.output, "index": nav.index,
                     "color": list(nav.color)}
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


# ------------------------------------------------------- one model on its own

MODEL_FILE_KIND = "lightshow-modell"
MODEL_FILE_VERSION = 1


def model_document(show: ShowCfg, name: str) -> dict[str, Any]:
    """One model as a file of its own, carriable to another installation.

    Everything the model needs and nothing it shares: the transmitter's own
    settings come along because a model is meaningless without knowing what
    frame it rides in, but they are advisory -- the importing side keeps its own
    jacks and only reads this to warn when they disagree.
    """
    data = to_dict(show)
    entry = next((m for m in data["models"] if m["name"] == name), None)
    if entry is None:
        raise ConfigError(f"kein Modell '{name}'")
    port = next((p for p in data["tx_ports"] if p["id"] == entry["tx_port"]), None)
    return {
        "kind": MODEL_FILE_KIND,
        "version": MODEL_FILE_VERSION,
        "model": entry,
        # Not imported, only compared: two installations rarely agree on which
        # jack is which, and overwriting a jack that another model rides on
        # would break that one to make room for this.
        "tx_port_was": port,
    }


def read_model_document(data: Any) -> dict[str, Any]:
    """Checks that a file really is one exported model, and hands it back."""
    if not isinstance(data, dict):
        raise ConfigError("Modelldatei: oberste Ebene muss ein Objekt sein")
    if data.get("kind") != MODEL_FILE_KIND:
        raise ConfigError(
            "Das ist keine exportierte Modelldatei — erwartet wird "
            f"kind: {MODEL_FILE_KIND}"
        )
    version = data.get("version")
    if version != MODEL_FILE_VERSION:
        raise ConfigError(
            f"Modelldatei in Fassung {version}, gelesen wird "
            f"{MODEL_FILE_VERSION}"
        )
    model = data.get("model")
    if not isinstance(model, dict) or not model.get("name"):
        raise ConfigError("Modelldatei: 'model' fehlt oder hat keinen Namen")
    return data


def free_name(taken: set[str], wanted: str) -> str:
    """`wanted`, or the first `wanted_2`, `wanted_3`, ... that is free."""
    if wanted not in taken:
        return wanted
    for n in range(2, 1000):
        candidate = f"{wanted}_{n}"
        if candidate not in taken:
            return candidate
    raise ConfigError(f"kein freier Name neben '{wanted}'")


def fit_model(show_data: dict[str, Any], model: dict[str, Any]) -> list[str]:
    """Moves an imported model out of the way of the ones already there.

    Two configurations that never met will collide on nearly everything: both
    put the light on jack 1 from channel 9. So the model is moved rather than
    refused -- and every move is reported, because
    silently renumbering somebody's aircraft is how a model ends up answering to
    a channel nobody expects.

    Changed in place; returns one sentence per move.
    """
    notes: list[str] = []
    others = show_data.get("models") or []

    wanted = str(model["name"])
    name = free_name({str(m["name"]) for m in others}, wanted)
    if name != wanted:
        notes.append(f"Name '{wanted}' war belegt, heißt jetzt '{name}'")
        model["name"] = name

    ports = show_data.get("tx_ports") or []
    block = 8                       # what a bus model occupies, whatever else
    claimed: dict[int, list[tuple[int, int]]] = {}
    for other in others:
        claimed.setdefault(int(other["tx_port"]), []).append(
            (int(other["tx_offset"]), int(other["tx_offset"]) + block))

    def fits(port_id: int, offset: int) -> bool:
        port = next((p for p in ports if p["id"] == port_id), None)
        if port is None or offset + block > int(port["nchan"]):
            return False
        return not any(offset < to and start < offset + block
                       for start, to in claimed.get(port_id, []))

    port_id = int(model.get("tx_port", 0))
    offset = int(model.get("tx_offset", 0))
    if not fits(port_id, offset):
        found = None
        # The jack it came from first, then any other -- a model that fits where
        # it was should stay there, even if it has to move along the frame.
        for candidate in [port_id] + [int(p["id"]) for p in ports]:
            for start in range(0, 17):
                if fits(candidate, start):
                    found = (candidate, start)
                    break
            if found:
                break
        if found is None:
            raise ConfigError(
                "Keine Sender-Buchse hat noch acht freie Kanäle für dieses Modell."
            )
        notes.append(
            f"Kanäle {offset + 1}–{offset + block} auf Buchse {port_id + 1} "
            f"waren belegt, jetzt Buchse {found[0] + 1} ab Kanal {found[1] + 1}"
        )
        model["tx_port"], model["tx_offset"] = found
    return notes


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
