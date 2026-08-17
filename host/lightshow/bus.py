"""Bus mode: the eight light channels carry one data frame instead of one zone.

The classic layout spends four RC channels on a single zone -- cue, hue,
brightness, param -- so eight channels are two zones and that is the end of it.
Bus mode reads the same eight channels as eight 5 bit symbols and puts a small
addressed frame in them, so a model can have more zones than it has channels.
The price is latency: one zone is refreshed per RC frame, so eight zones mean
eight frames until the same zone comes round again.

Why 5 bits: that is what the radio link was measured to carry per channel, and
it is exactly the quantisation the firmware already applies for cue steps. A
symbol is a cue step -- nothing new has to survive the air that did not have to
survive it before.

Why Reed-Solomon over GF(32): the errors this link makes are not scattered bit
flips, they are whole channels landing one step off. A symbol oriented code
matches that, and GF(32) holds 5 bit symbols exactly. RS(8,6) leaves 30 bits of
payload. What the two parity symbols are spent on -- repairing one symbol or
detecting two -- is decided in `decode`, and the answer came from a bench
measurement rather than from taste.

The layout, most significant bit first:

    [ magic: 2 ][ relays: R ][ zone address: A ][ cue: 5 ][ hue: 6 ]
    [ brightness: 8 ][ param: 5 ][ spare: 30 - 2 - R - A - 24 ]

Relays sit in every frame, so they switch at the full frame rate no matter
which zone is being addressed. That is deliberate: a relay is a discrete event
and waiting eight frames for it would be visible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# --- the field ---------------------------------------------------------------
# GF(2^5) with x^5 + x^2 + 1, the usual primitive polynomial for five bits.
GF_POLY = 0b100101
GF_SIZE = 32
SYMBOL_BITS = 5
SYMBOL_MAX = GF_SIZE - 1

# --- the code ----------------------------------------------------------------
SYMBOLS = 8             # channels on the wire
DATA_SYMBOLS = 6        # RS(8,6)
PARITY_SYMBOLS = SYMBOLS - DATA_SYMBOLS
PAYLOAD_BITS = DATA_SYMBOLS * SYMBOL_BITS      # 30

# --- the payload -------------------------------------------------------------
# Field widths of one zone's state. cue keeps the 32 steps of the cue list,
# brightness keeps eight bits so a fade stays smooth, hue gets six because a
# colour wheel in 64 steps is not visibly stepped, param gets five.
ZONE_FIELDS = (("cue", 5), ("hue", 6), ("brightness", 8), ("param", 5))
ZONE_STATE_BITS = sum(width for _, width in ZONE_FIELDS)   # 24

# A fixed pattern at the front of every frame, checked before anything else.
#
# The parity alone is not enough to tell our frames from somebody else's. One
# random frame in 1024 is a valid code word, which sounds rare until the source
# repeats: a transmitter that drops its trainer input substitutes the same
# channel values over and over, and on the bench that fixed pattern *was* a
# valid code word. It passed every time and overwrote a zone.
#
# Two bits cost one relay slot in the tighter configurations and turn three out
# of four foreign frames away on top of the parity check. They cannot make the
# wire safe on their own -- nothing can, against a determined coincidence --
# but they move it from "every seventh frame" to "every few thousand".
MAGIC_BITS = 2
MAGIC = 0b10

MAX_ZONES = 8           # what three address bits carry, and MAX_STRIPS
MAX_RELAYS = 8

# A frame addresses one zone, so a static failsafe frame could only ever turn
# one zone off and would leave the rest of the model lit if the host died while
# the ground station kept transmitting. This cue value means "everything off,
# every zone" and is reserved on the wire. docs/cues.md keeps steps 11..31 free
# as spare effects, so spending the last one costs nothing.
CUE_ALL_OFF = 31

# ... but the cue value alone is not enough to say it with.
#
# RS(8,6) carries ten bits of redundancy, so a frame from somewhere else passes
# as valid about once in a thousand tries -- and a *repeating* foreign frame
# either always passes or never does. On the bench a transmitter that dropped
# the trainer input substituted its own channels, and that fixed pattern decoded
# cleanly to zone 0 with every payload bit zero. Cue 31 out of all-zero bits is
# exactly what rubbish hits most easily, and the model went dark for it.
#
# So "everything off" has to be *said*, not merely landed on: cue at 31 and hue
# and param at their maxima as well. Sixteen specific bits on top of the code's
# own check, and no real zone state can collide with it because cue 31 is
# reserved anyway.
HUE_ALL_OFF = 63        # (1 << 6) - 1
PARAM_ALL_OFF = 31      # (1 << 5) - 1


def _build_tables() -> tuple[list[int], list[int]]:
    exp = [0] * (2 * GF_SIZE)
    log = [0] * GF_SIZE
    value = 1
    for power in range(GF_SIZE - 1):
        exp[power] = value
        log[value] = power
        value <<= 1
        if value & GF_SIZE:
            value ^= GF_POLY
    # Second lap, so a product of two logs can be looked up without a modulo.
    for power in range(GF_SIZE - 1, 2 * (GF_SIZE - 1)):
        exp[power] = exp[power - (GF_SIZE - 1)]
    return exp, log


GF_EXP, GF_LOG = _build_tables()


def gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return GF_EXP[GF_LOG[a] + GF_LOG[b]]


def gf_div(a: int, b: int) -> int:
    if b == 0:
        raise ZeroDivisionError("division by zero in GF(32)")
    if a == 0:
        return 0
    return GF_EXP[(GF_LOG[a] - GF_LOG[b]) % (GF_SIZE - 1)]


# g(x) = (x + a^0)(x + a^1); in GF(2) addition and subtraction are the same.
_G1 = GF_EXP[0] ^ GF_EXP[1]
_G0 = gf_mul(GF_EXP[0], GF_EXP[1])


def encode(data: list[int]) -> list[int]:
    """Six data symbols in, eight code symbols out, systematic."""
    if len(data) != DATA_SYMBOLS:
        raise ValueError(f"needs {DATA_SYMBOLS} symbols, got {len(data)}")
    if any(not 0 <= s <= SYMBOL_MAX for s in data):
        raise ValueError("symbols must fit in five bits")

    # Long division of data * x^2 by g(x); the remainder is the parity.
    r0 = r1 = 0
    for symbol in data:
        feedback = symbol ^ r0
        r0 = r1 ^ gf_mul(_G1, feedback)
        r1 = gf_mul(_G0, feedback)
    return list(data) + [r0, r1]


class ForeignFrame(Exception):
    """Raised by `unpack` for a frame that is not one of ours."""


@dataclass
class Decoded:
    data: list[int]
    corrected: int | None      # index of the repaired symbol, None if clean
    ok: bool                   # False when the damage is beyond repair


def decode(code: list[int], *, correct: bool = False) -> Decoded:
    """Eight symbols in, six out.

    Two parity symbols buy *either* the repair of one wrong symbol *or* the
    detection of two -- not both. Which one to take is not a matter of taste
    here, it was measured on 17.08.2026:

    Repairing accepts everything within distance one of a code word, and that
    is 8*31+1 = 249 words per code word: **24 % of all possible frames pass**.
    Detecting only accepts code words themselves, one in 1024. The difference
    matters because this wire carries frames from somewhere else -- a
    transmitter that drops its trainer input substitutes its own channels, and
    those frames must not be mistaken for ours.

    What repairing would buy: one single-symbol error was seen in 1233 frames.
    A tenth of a percent of throughput, against a factor of 249 in false
    acceptance. So detection is the default, and a rejected frame simply leaves
    the last good state standing.

    `correct=True` restores the repair for a link where symbol errors are the
    real problem and nothing foreign can reach the wire.
    """
    if len(code) != SYMBOLS:
        raise ValueError(f"needs {SYMBOLS} symbols, got {len(code)}")

    # Syndromes: the codeword evaluated at a^0 and a^1, both zero when clean.
    s0 = 0
    s1 = 0
    for index, symbol in enumerate(code):
        s0 ^= symbol
        s1 ^= gf_mul(symbol, GF_EXP[(SYMBOLS - 1 - index) % (GF_SIZE - 1)])

    if s0 == 0 and s1 == 0:
        return Decoded(list(code[:DATA_SYMBOLS]), None, True)

    if not correct:
        # Anything that is not a code word is somebody else's frame or a broken
        # one; either way the last good state is the better answer.
        return Decoded(list(code[:DATA_SYMBOLS]), None, False)

    if s0 == 0:
        # A magnitude of zero is no error at all, so this cannot be a single
        # symbol fault -- something worse happened.
        return Decoded(list(code[:DATA_SYMBOLS]), None, False)

    position = GF_LOG[gf_div(s1, s0)]
    index = SYMBOLS - 1 - position
    if not 0 <= index < SYMBOLS:
        return Decoded(list(code[:DATA_SYMBOLS]), None, False)

    repaired = list(code)
    repaired[index] ^= s0
    return Decoded(repaired[:DATA_SYMBOLS], index, True)


# ----------------------------------------------------------------- the payload


def address_bits(zones: int) -> int:
    """Bits needed to address `zones` zones -- none at all when there is one."""
    if zones <= 1:
        return 0
    return (zones - 1).bit_length()


def payload_used(zones: int, relays: int) -> int:
    return MAGIC_BITS + relays + address_bits(zones) + ZONE_STATE_BITS


def spare_bits(zones: int, relays: int) -> int:
    return PAYLOAD_BITS - payload_used(zones, relays)


def fits(zones: int, relays: int) -> bool:
    return (1 <= zones <= MAX_ZONES and 0 <= relays <= MAX_RELAYS
            and spare_bits(zones, relays) >= 0)


def latency_ms(zones: int, frame_us: int) -> float:
    """How long until the same zone is addressed again."""
    return zones * frame_us / 1000.0


@dataclass
class Combination:
    zones: int
    relays: int
    latency_ms: float
    spare_bits: int
    within_budget: bool        # latency at or below the configured limit


def combinations(frame_us: int, *, limit_ms: float | None = None,
                 max_zones: int = MAX_ZONES,
                 max_relays: int = MAX_RELAYS) -> list[Combination]:
    """Every zone/relay pair the frame can hold, worst latency first.

    `limit_ms` does not remove anything -- it marks what stays inside the
    budget, so the interface can show the rest greyed out rather than
    pretending it does not exist.
    """
    out = []
    for zones in range(1, min(max_zones, MAX_ZONES) + 1):
        for relays in range(0, min(max_relays, MAX_RELAYS) + 1):
            if not fits(zones, relays):
                continue
            lag = latency_ms(zones, frame_us)
            out.append(Combination(
                zones=zones,
                relays=relays,
                latency_ms=lag,
                spare_bits=spare_bits(zones, relays),
                within_budget=limit_ms is None or lag <= limit_ms + 1e-9,
            ))
    out.sort(key=lambda c: (c.zones, c.relays))
    return out


def narrow(value: int, bits: int) -> int:
    """A 0..255 value down to `bits`, the way the ground station sends it."""
    top = (1 << bits) - 1
    return max(0, min(top, (value * top) // 255))


def widen(value: int, bits: int) -> int:
    """Back to 0..255, the way the firmware reads it.

    The full value has to map back to 255: a hue of 63 that widened to 252
    would put full saturation out of reach.
    """
    top = (1 << bits) - 1
    return (value * 255) // top if top else 0


@dataclass
class ZoneState:
    """One zone as it travels: every field already at its on-air width."""
    cue: int = 0            # 0..31, a cue step
    hue: int = 0            # 0..63
    brightness: int = 0     # 0..255
    param: int = 0          # 0..31

    def as_fields(self) -> dict[str, int]:
        return {"cue": self.cue, "hue": self.hue,
                "brightness": self.brightness, "param": self.param}

    @classmethod
    def from_bytes(cls, cue: int, hue: int, brightness: int, param: int
                   ) -> "ZoneState":
        """From what MIDI produces -- cue as a step, the rest 0..255."""
        widths = dict(ZONE_FIELDS)
        return cls(
            cue=max(0, min((1 << widths["cue"]) - 1, cue)),
            hue=narrow(hue, widths["hue"]),
            brightness=narrow(brightness, widths["brightness"]),
            param=narrow(param, widths["param"]),
        )

    def to_bytes(self) -> dict[str, int]:
        """What the firmware hands the effects: cue as a step, the rest 0..255."""
        widths = dict(ZONE_FIELDS)
        return {
            "cue": self.cue,
            "hue": widen(self.hue, widths["hue"]),
            "brightness": widen(self.brightness, widths["brightness"]),
            "param": widen(self.param, widths["param"]),
        }


def pack(zone_index: int, state: ZoneState, relays: list[bool], *,
         zones: int, relays_count: int) -> list[int]:
    """One zone's state plus every relay, as six data symbols."""
    if not fits(zones, relays_count):
        raise ValueError(f"{zones} zones and {relays_count} relays do not fit "
                         f"into {PAYLOAD_BITS} bits")
    if not 0 <= zone_index < zones:
        raise ValueError(f"zone {zone_index} outside 0..{zones - 1}")
    if len(relays) != relays_count:
        raise ValueError(f"needs {relays_count} relay states, got {len(relays)}")

    bits = 0
    width = 0

    def push(value: int, size: int) -> None:
        nonlocal bits, width
        if size == 0:
            return
        if not 0 <= value < (1 << size):
            raise ValueError(f"value {value} does not fit in {size} bits")
        bits = (bits << size) | value
        width += size

    push(MAGIC, MAGIC_BITS)

    relay_word = 0
    for index, on in enumerate(relays):
        if on:
            relay_word |= 1 << (relays_count - 1 - index)
    push(relay_word, relays_count)
    push(zone_index, address_bits(zones))

    values = state.as_fields()
    for name, size in ZONE_FIELDS:
        # Every field is already at its on-air width -- ZoneState.from_bytes
        # does the scaling, so a value too large here is a real mistake.
        push(values[name], size)

    push(0, PAYLOAD_BITS - width)      # spare, reserved, always zero

    symbols = []
    for shift in range(DATA_SYMBOLS - 1, -1, -1):
        symbols.append((bits >> (shift * SYMBOL_BITS)) & SYMBOL_MAX)
    return symbols


def unpack(symbols: list[int], *, zones: int, relays_count: int
           ) -> tuple[int, ZoneState, list[bool]]:
    """The inverse of `pack`, for tests and for reading a capture back."""
    if len(symbols) != DATA_SYMBOLS:
        raise ValueError(f"needs {DATA_SYMBOLS} symbols, got {len(symbols)}")

    bits = 0
    for symbol in symbols:
        bits = (bits << SYMBOL_BITS) | symbol

    offset = PAYLOAD_BITS

    def pull(size: int) -> int:
        nonlocal offset
        if size == 0:
            return 0
        offset -= size
        return (bits >> offset) & ((1 << size) - 1)

    magic = pull(MAGIC_BITS)
    relay_word = pull(relays_count)
    relays = [bool(relay_word & (1 << (relays_count - 1 - i)))
              for i in range(relays_count)]
    zone_index = pull(address_bits(zones))
    state = ZoneState(**{name: pull(size) for name, size in ZONE_FIELDS})
    if magic != MAGIC:
        raise ForeignFrame(f"Erkennungsmuster {magic:0{MAGIC_BITS}b} statt "
                           f"{MAGIC:0{MAGIC_BITS}b}")
    return zone_index, state, relays


def frame(zone_index: int, state: ZoneState, relays: list[bool], *,
          zones: int, relays_count: int) -> list[int]:
    """Everything at once: state in, eight channel symbols out."""
    return encode(pack(zone_index, state, relays,
                       zones=zones, relays_count=relays_count))


def all_off_state() -> ZoneState:
    """The one zone state that means "everything off, every zone"."""
    return ZoneState(cue=CUE_ALL_OFF, hue=HUE_ALL_OFF, brightness=0,
                     param=PARAM_ALL_OFF)


def is_all_off(state: ZoneState) -> bool:
    """Whether a decoded state is the all-off command rather than a zone."""
    return (state.cue == CUE_ALL_OFF and state.hue == HUE_ALL_OFF
            and state.param == PARAM_ALL_OFF)


def failsafe_frame(zones: int, relays_count: int) -> list[int]:
    """What the ground station holds when the host stops feeding it.

    Carries the all-off command, so a single repeated frame darkens every zone
    rather than only the one it addresses.
    """
    return frame(0, all_off_state(), [False] * relays_count,
                 zones=zones, relays_count=relays_count)


def symbol_to_us(symbol: int, min_us: int, max_us: int) -> int:
    """Puts a symbol in the middle of its band.

    Deliberately the same arithmetic as `config.step_us` with 32 steps -- a
    symbol *is* a cue step as far as the wire is concerned, and rounding it
    differently would give away a microsecond of margin for nothing.
    """
    span = max_us - min_us
    symbol = max(0, min(SYMBOL_MAX, symbol))
    return min_us + round(span * (symbol + 0.5) / GF_SIZE)


def us_to_symbol(microseconds: int, min_us: int, max_us: int) -> int:
    span = max_us - min_us
    if span <= 0:
        return 0
    index = ((microseconds - min_us) * GF_SIZE) // span
    return max(0, min(SYMBOL_MAX, index))


def us_to_level(microseconds: int, min_us: int, max_us: int) -> int:
    """The inverse of `config.level_us`: microseconds back to 0..255."""
    span = max_us - min_us
    if span <= 0:
        return 0
    return max(0, min(255, round((microseconds - min_us) * 255 / span)))


class Encoder:
    """Holds a bus model's logical state and hands out the eight wire values.

    Three places produce frames -- the MIDI mapper, the project timeline and
    the session's failsafe -- and all three used to write straight into channel
    positions. In bus mode there are no channel positions to write into, so all
    three feed an encoder instead and it decides what goes on the wire.

    It takes plain numbers rather than a ModelCfg so that `config` can keep
    importing this module and not the other way round.
    """

    def __init__(self, *, zones: int, relays_count: int, tx_offset: int,
                 min_us: int, max_us: int, frame_us: int) -> None:
        if not fits(zones, relays_count):
            raise ValueError(f"{zones} zones and {relays_count} relays do not fit")
        self.zones = zones
        self.relays_count = relays_count
        self.tx_offset = tx_offset
        self.min_us = min_us
        self.max_us = max_us
        self.frame_us = frame_us

        self.states = [ZoneState() for _ in range(zones)]
        self.relays = [False] * relays_count
        self._zone = 0
        self._due: float | None = None

    # ---------------------------------------------------------------- input

    def set_zone(self, zone: int, state: ZoneState) -> None:
        if 0 <= zone < self.zones:
            self.states[zone] = state

    def set_zone_us(self, zone: int, cue_us: int, hue_us: int,
                    brightness_us: int, param_us: int) -> None:
        """From what the other producers already compute: microseconds."""
        self.set_zone(zone, ZoneState.from_bytes(
            cue=us_to_symbol(cue_us, self.min_us, self.max_us),
            hue=us_to_level(hue_us, self.min_us, self.max_us),
            brightness=us_to_level(brightness_us, self.min_us, self.max_us),
            param=us_to_level(param_us, self.min_us, self.max_us),
        ))

    def set_relay(self, index: int, on: bool) -> None:
        if 0 <= index < self.relays_count:
            self.relays[index] = bool(on)

    # --------------------------------------------------------------- output

    def _advance(self, now: float) -> None:
        """One zone per RC frame -- faster would send frames the air never carries."""
        period = self.frame_us / 1_000_000.0
        if self._due is None:
            self._due = now + period
            return
        while now >= self._due:
            self._zone = (self._zone + 1) % self.zones
            self._due += period
            # A long stall must not make it race through the zones catching up.
            if now - self._due > period * self.zones:
                self._due = now + period
                break

    @property
    def zone_in_flight(self) -> int:
        return self._zone

    def symbols(self, now: float) -> list[int]:
        self._advance(now)
        return frame(self._zone, self.states[self._zone], self.relays,
                     zones=self.zones, relays_count=self.relays_count)

    def write(self, channel_values: list[int], now: float) -> None:
        """Puts the eight wire values into a port's channel list, in place."""
        for index, symbol in enumerate(self.symbols(now)):
            position = self.tx_offset + index
            if position < len(channel_values):
                channel_values[position] = symbol_to_us(
                    symbol, self.min_us, self.max_us)

    def write_failsafe(self, channel_values: list[int]) -> None:
        """The one frame that means "off" everywhere, without rotating."""
        for index, symbol in enumerate(failsafe_frame(self.zones,
                                                      self.relays_count)):
            position = self.tx_offset + index
            if position < len(channel_values):
                channel_values[position] = symbol_to_us(
                    symbol, self.min_us, self.max_us)


def describe(zones: int, relays: int, frame_us: int) -> str:
    """One line for a log or a report."""
    lag = latency_ms(zones, frame_us)
    return (f"{zones} Zonen, {relays} Relais: {lag:.0f} ms je Zone, "
            f"{spare_bits(zones, relays)} Bit frei")
