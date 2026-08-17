"""Generates the airborne controller's config.h from a model definition.

The plane cannot be configured over the air -- the only link to it is the RC
channels. So the model definition in show.yaml is the single source, and this
module turns it into the header the firmware is compiled with. The wiring
overview falls out of the same data, which is what keeps the documentation and
the firmware from drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import bus as bus_mode
from .config import (
    PICO_PHYSICAL_PIN,
    ModelCfg,
    PlaneCfg,
    ShowCfg,
)

SOURCE_MACRO = {
    "pixel": "RELAY_SRC_PIXEL",
    "brightness": "RELAY_SRC_BRIGHTNESS",
    "cue": "RELAY_SRC_CUE",
    "channel": "RELAY_SRC_CHANNEL",
    "bus": "RELAY_SRC_BUS",
}


@dataclass
class WiringRow:
    gpio: int
    physical: str      # physical pin on the header, or "-"
    role: str
    detail: str
    note: str


def _pin_label(gpio: int) -> str:
    pin = PICO_PHYSICAL_PIN.get(gpio)
    return f"Pin {pin}" if pin else "-"


def wiring(model: ModelCfg) -> list[WiringRow]:
    """Everything that has to be soldered to the Pico in this model."""
    plane = model.plane
    if plane is None:
        return []

    rows = [
        WiringRow(0, _pin_label(0), "Debug-UART TX", "Konsole",
                  "nur zur Fehlersuche, kann frei bleiben"),
        WiringRow(1, _pin_label(1), "Debug-UART RX", "Konsole",
                  "nur zur Fehlersuche, kann frei bleiben"),
        WiringRow(plane.sbus_pin, _pin_label(plane.sbus_pin), "SBUS-Eingang",
                  "SBUS-Ausgang des Empfaengers",
                  "bevorzugter Weg: eine Leitung, alle 16 Kanaele"),
    ]

    for index, pin in enumerate(plane.pwm_pins):
        rows.append(WiringRow(
            pin, _pin_label(pin), f"PWM-Eingang {index + 1}",
            f"Empfaengerkanal {index + 1}",
            "nur noetig, wenn der Empfaenger kein SBUS hat"))

    for index, strip in enumerate(plane.strips):
        rows.append(WiringRow(
            strip.pin, _pin_label(strip.pin), f"LED-Strip {index}: {strip.name}",
            f"{strip.count} Pixel, Zone {strip.zone}, Offset {strip.offset}"
            + (", rueckwaerts" if strip.reverse else ""),
            "ueber 74AHCT125 und 330 Ohm an DIN"))

    for index, relay in enumerate(plane.relays):
        rows.append(WiringRow(
            relay.pin, _pin_label(relay.pin), f"Relais {index}: {relay.name}",
            describe_relay(relay),
            "Relaismodul, schaltet bei LOW" if relay.active_low
            else "MOSFET-Gate ueber 100 Ohm, 100k gegen Masse"))

    rows.append(WiringRow(-1, "Pin 39", "VSYS", "5 V vom UBEC",
                          "nicht an VBUS, und Masse an Pin 38"))
    rows.append(WiringRow(-1, "Pin 38", "GND", "Masse",
                          "gemeinsam mit Empfaenger und LED-Versorgung"))
    return rows


def describe_relay(relay) -> str:
    speed = ("MOSFET, folgt jedem Muster" if relay.min_on_ms == 0 and relay.min_off_ms == 0
             else f"mechanisch, min {relay.min_on_ms}/{relay.min_off_ms} ms")
    if relay.source == "pixel":
        what = f"folgt Pixel {relay.arg} ab Helligkeit {relay.threshold}"
    elif relay.source == "brightness":
        what = f"an ab Master-Dimmer {relay.threshold}"
    elif relay.source == "cue":
        what = f"an ab Cue {relay.arg}"
    elif relay.source == "bus":
        what = f"direkt geschaltet, Bus-Steckplatz {relay.arg}"
    else:
        what = f"an ab RC-Kanal {relay.arg} ueber {relay.threshold}"
    return f"{what}; {speed}"


def power_estimate(plane: PlaneCfg) -> dict[str, float]:
    """Rough current draw of the LED strips, in ampere."""
    pixels = sum(strip.count for strip in plane.strips)
    worst = pixels * 0.06
    typical = worst * (plane.max_brightness / 255.0) / 3.0
    return {"pixels": pixels, "worst_a": round(worst, 2), "typical_a": round(typical, 2)}


def generate(show: ShowCfg, model: ModelCfg) -> str:
    """Renders the config.h for one model."""
    plane = model.plane
    if plane is None:
        raise ValueError(f"model '{model.name}' has no plane configuration")

    port = show.port_by_id(model.tx_port)
    zones = model.zone_count
    cue_steps = 32
    for channel in model.channels:
        if channel.role == "cue" and channel.quantize:
            cue_steps = channel.quantize
            break

    out: list[str] = []
    add = out.append

    add(f"// Generated from show.yaml for model '{model.name}'. Do not edit by hand --")
    add("// change the model in the web UI or in show.yaml and regenerate.")
    add("")
    add("#ifndef PLANE_MODEL_CONFIG_H")
    add("#define PLANE_MODEL_CONFIG_H")
    add("")
    add('#include "outputs.h"')
    add("")
    add("// Reported on the debug console at boot, so a board can be asked which")
    add("// model it is configured for -- the pin assignment differs per model.")
    add(f'#define PLANE_MODEL_NAME "{model.name}"')
    add("")
    add(f"#define RENDER_HZ {plane.render_hz}")
    add(f"#define MAX_BRIGHTNESS {plane.max_brightness}")
    add("")
    add("#define SBUS_UART   uart1")
    add(f"#define SBUS_RX_PIN {plane.sbus_pin}")
    add("#define PWM_PINS  {" + ", ".join(str(p) for p in plane.pwm_pins) + "}")
    add(f"#define PWM_COUNT {len(plane.pwm_pins)}")
    add("")
    add(f"#define RC_MIN_US {port.min_us}")
    add(f"#define RC_MAX_US {port.max_us}")
    add(f"#define CUE_STEPS {cue_steps}")
    add("#define RC_TIMEOUT_MS 500")
    add("")

    if model.uses_bus:
        first = model.tx_offset + 1
        add(f"// Bus mode: channels {first}..{first + bus_mode.SYMBOLS - 1} carry "
            f"one RS(8,6) coded frame,")
        add(f"// {zones} zone(s) taking turns, one per RC frame.")
        add("#define BUS_MODE 1")
        add(f"#define BUS_FIRST_CHANNEL {first}")
        add(f"#define BUS_ZONES {zones}")
        add(f"#define BUS_RELAY_COUNT {model.bus.relay_count}")
        if model.bus.relays:
            add("// Slot order is the wire order; a relay refers to it by index.")
            for index, relay in enumerate(model.bus.relays):
                add(f"//   {index}: {relay.name}")
        # The all-off command is a property of the wire, not of this model --
        # bus.h owns it, and the cross-check keeps both sides in step.
        add("")
        add(f"#define ZONE_COUNT {zones}")
        # A zone owns no channels here, but the rest of the firmware still asks
        # for a base channel; the bus decoder is what actually feeds the zones.
        add("#define ZONES { \\")
        for zone in range(zones):
            add(f"    {{{first}}},  /* Zone {zone}: aus dem Bus */ \\")
        add("}")
        add("")
    else:
        add("#define BUS_MODE 0")
        add(f"// {zones} zone(s); this model sits on transmitter channels "
            f"{model.tx_offset + 1}..{model.tx_offset + len(model.channels)}.")
        add(f"#define ZONE_COUNT {zones}")
        add("#define ZONES { \\")
        for zone in range(zones):
            add(f"    {{{model.zone_base_channel(zone)}}},  /* Zone {zone}: Kanaele "
                f"{model.zone_base_channel(zone)}.."
                f"{model.zone_base_channel(zone) + 3} */ \\")
        add("}")
        add("")

    add(f"#define STRIP_COUNT {len(plane.strips)}")
    if plane.strips:
        add("#define STRIPS { \\")
        for strip in plane.strips:
            add(f"    {{{strip.pin}, {strip.count}, {strip.zone}, {strip.offset}, "
                f"{'true' if strip.reverse else 'false'}}},  /* {strip.name} */ \\")
        add("}")
    else:
        add("#define STRIPS {}")
    add("")

    add(f"#define RELAY_COUNT {len(plane.relays)}")
    if plane.relays:
        add("#define RELAYS { \\")
        for relay in plane.relays:
            add(f"    {{{relay.pin}, {relay.zone}, {SOURCE_MACRO[relay.source]}, "
                f"{relay.arg}, {relay.threshold}, "
                f"{'true' if relay.active_low else 'false'}, "
                f"{relay.min_on_ms}, {relay.min_off_ms}}},  /* {relay.name} */ \\")
        add("}")
    else:
        add("#define RELAYS {}")
    add("")

    add(f"#define NAV_COUNT {len(plane.nav_lights)}")
    if plane.nav_lights:
        add("#define NAV_LIGHTS { \\")
        for nav in plane.nav_lights:
            r, g, b = nav.color
            strip_name = plane.strips[nav.strip].name
            add(f"    {{{nav.strip}, {nav.index}, {r}, {g}, {b}}},"
                f"  /* {strip_name} Pixel {nav.index} */ \\")
        add("}")
    else:
        add("#define NAV_LIGHTS {}")
    add("")
    add("#endif // PLANE_MODEL_CONFIG_H")
    return "\n".join(out) + "\n"
