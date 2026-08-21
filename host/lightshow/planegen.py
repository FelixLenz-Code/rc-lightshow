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
                  "der einzige Weg: eine Leitung, alle 16 Kanaele"),
    ]

    for index, output in enumerate(plane.outputs):
        # One line per chain -- that is what gets soldered. Which zones ride on
        # it is a property of the chain, so it goes in the same line.
        parts = []
        for segment in output.segments:
            span = (f"{segment.start}..{segment.end - 1}" if segment.count > 1
                    else str(segment.start))
            # One based, as every zone label in the interface is.
            parts.append(f"Pixel {span} -> Zone {segment.zone + 1}"
                         + (f" ab {segment.offset}" if segment.offset else "")
                         + (", rueckwaerts" if segment.reverse else ""))
        rows.append(WiringRow(
            output.pin, _pin_label(output.pin),
            f"LED-Strip {index}: {output.name}",
            f"{output.count} Pixel; " + "; ".join(parts),
            "ueber 74AHCT125 und 330 Ohm an DIN"))

    for index, relay in enumerate(plane.relays):
        rows.append(WiringRow(
            relay.pin, _pin_label(relay.pin), f"Relais {index}: {relay.name}",
            describe_relay(relay, index),
            "Relaismodul, schaltet bei LOW" if relay.active_low
            else "MOSFET-Gate ueber 100 Ohm, 100k gegen Masse"))

    rows.append(WiringRow(-1, "Pin 39", "VSYS", "5 V vom UBEC",
                          "nicht an VBUS, und Masse an Pin 38"))
    rows.append(WiringRow(-1, "Pin 38", "GND", "Masse",
                          "gemeinsam mit Empfaenger und LED-Versorgung"))
    return rows


def describe_relay(relay, slot: int | None = None) -> str:
    speed = ("MOSFET, folgt jedem Muster" if relay.min_on_ms == 0 and relay.min_off_ms == 0
             else f"mechanisch, min {relay.min_on_ms}/{relay.min_off_ms} ms")
    what = "direkt geschaltet" + (f", Bus-Bit {slot}" if slot is not None else "")
    return f"{what}; {speed}"


def power_estimate(plane: PlaneCfg) -> dict[str, float]:
    """Rough current draw of the LED strips, in ampere."""
    pixels = sum(output.count for output in plane.outputs)
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
    add("")
    add(f"#define RC_MIN_US {port.min_us}")
    add(f"#define RC_MAX_US {port.max_us}")
    add(f"#define CUE_STEPS {cue_steps}")
    add("#define RC_TIMEOUT_MS 500")
    add("")

    first = model.tx_offset + 1
    add(f"// Bus: channels {first}..{first + bus_mode.SYMBOLS - 1} carry "
        f"one RS(8,6) coded frame,")
    add(f"// {zones} zone(s) taking turns, one per RC frame.")
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

    segments = plane.segments
    add(f"#define OUTPUT_COUNT {len(plane.outputs)}")
    add(f"#define SEGMENT_COUNT {len(segments)}")
    # Every chain lives in one flat frame buffer; this is how long it has to be.
    add(f"#define OUTPUT_PIXEL_TOTAL "
        f"{sum(output.count for output in plane.outputs)}")
    if plane.outputs:
        add("// The physical chains: pin, pixels, and where they start in the")
        add("// shared frame buffer.")
        add("#define OUTPUTS { \\")
        cursor = 0
        for output in plane.outputs:
            add(f"    {{{output.pin}, {output.count}, {cursor}}},"
                f"  /* {output.name} */ \\")
            cursor += output.count
        add("}")
        add("")
        add("// How those chains are divided between the zones.")
        add("#define SEGMENTS { \\")
        for index, segment in segments:
            add(f"    {{{index}, {segment.start}, {segment.count}, {segment.zone}, "
                f"{segment.offset}, {'true' if segment.reverse else 'false'}}},"
                f"  /* {plane.outputs[index].name}: {segment.name} */ \\")
        add("}")
    else:
        add("#define OUTPUTS {}")
        add("#define SEGMENTS {}")
    add("")

    add(f"#define RELAY_COUNT {len(plane.relays)}")
    if plane.relays:
        add("// Position is the bit in the bus frame -- there is no slot field.")
        add("#define RELAYS { \\")
        for index, relay in enumerate(plane.relays):
            add(f"    {{{relay.pin}, {'true' if relay.active_low else 'false'}, "
                f"{relay.min_on_ms}, {relay.min_off_ms}}},"
                f"  /* Bit {index}: {relay.name} */ \\")
        add("}")
    else:
        add("#define RELAYS {}")
    add("")

    add(f"#define NAV_COUNT {len(plane.nav_lights)}")
    if plane.nav_lights:
        add("#define NAV_LIGHTS { \\")
        for nav in plane.nav_lights:
            r, g, b = nav.color
            output_name = plane.outputs[nav.output].name
            add(f"    {{{nav.output}, {nav.index}, {r}, {g}, {b}}},"
                f"  /* {output_name} Pixel {nav.index} */ \\")
        add("}")
    else:
        add("#define NAV_LIGHTS {}")
    add("")
    add("#endif // PLANE_MODEL_CONFIG_H")
    return "\n".join(out) + "\n"
