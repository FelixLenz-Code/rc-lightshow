"""Verifies the generator that turns a model definition into the plane's config.h.

The generated header is compiled into the airborne firmware, so a mistake here
ends up flying. These tests pin down the parts that carry meaning: the channel
block a model reads, the relay source macros, and the fact that a configuration
survives a round trip through YAML unchanged.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from lightshow import config as config_module
from lightshow import planegen

SHIPPED = Path(__file__).resolve().parents[1] / "config" / "show.yaml"
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def show() -> config_module.ShowCfg:
    return config_module.load(SHIPPED)


def model(show: config_module.ShowCfg, name: str) -> config_module.ModelCfg:
    return next(m for m in show.models if m.name == name)


def defines(header: str) -> dict[str, str]:
    """Single-line #defines only; multi-line tables are checked in the raw text."""
    out = {}
    for line in header.splitlines():
        if line.startswith("#define ") and not line.rstrip().endswith("\\"):
            parts = line[len("#define "):].split(None, 1)
            out[parts[0]] = parts[1].strip() if len(parts) > 1 else ""
    return out


# ----------------------------------------------------------------- generator


def test_a_model_reads_the_channel_block_its_offset_names(show):
    """Where a model reads follows tx_offset, and nothing else.

    'falke' sits at the bottom of its transmitter, 'eule' starts at channel 9
    so the sticks keep 1..8 -- both have to come out of the generator right.
    """
    for name in ("eule", "falke"):
        entry = model(show, name)
        if entry.uses_bus:
            continue          # no zone owns channels there; see the bus tests
        header = planegen.generate(show, entry)
        first = entry.tx_offset + 1
        assert f"{{{first}}}," in header
        assert f"Kanaele {first}..{first + 3}" in header


def test_zone_base_channel_follows_the_transmitter_offset(show):
    """The exception: a model pushed up the frame must read 5..8, not 1..4.

    That happens when a model has a second zone, and when two receivers are
    deliberately bound to one transmitter.
    """
    shifted = model(show, "falke")
    shifted.tx_offset = 4
    header = planegen.generate(show, shifted)
    shifted.tx_offset = 0                       # the fixture is module scoped
    assert "{5}," in header and "Kanaele 5..8" in header


def test_a_second_zone_takes_the_next_four_channels(show):
    """Zones are what tx_offset normally has to make room for."""
    two = model(show, "falke")                  # sits at offset 0, one zone
    original = list(two.channels)
    two.channels = original + original          # eight channels, two zones
    header = planegen.generate(show, two)
    two.channels = original
    assert "#define ZONE_COUNT 2" in header
    assert "{1}," in header and "{5}," in header


def test_strip_table_matches_the_configuration(show):
    header = planegen.generate(show, model(show, "eule"))
    assert defines(header)["STRIP_COUNT"] == "2"
    assert "{2, 30, 0, 0, false}" in header    # linke Fläche
    assert "{3, 30, 0, 0, true}" in header     # rechte, gespiegelt


def test_relay_sources_use_the_firmware_macros(show):
    """Every configured source has to reach the header as its macro."""
    for name in ("eule", "falke"):
        entry = model(show, name)
        header = planegen.generate(show, entry)
        assert defines(header)["RELAY_COUNT"] == str(len(entry.plane.relays))
        for relay in entry.plane.relays:
            assert planegen.SOURCE_MACRO[relay.source] in header


def test_cue_steps_follow_the_quantize_setting(show):
    assert defines(planegen.generate(show, model(show, "eule")))["CUE_STEPS"] == "32"


def test_each_image_carries_its_own_model_name(show):
    """The board reports this at boot, so a wrongly flashed image shows up."""
    for name in ("eule", "falke"):
        header = defines(planegen.generate(show, model(show, name)))
        assert header["PLANE_MODEL_NAME"] == f'"{name}"'


def test_models_really_differ_in_the_generated_output(show):
    """Two aircraft with different lights must not produce the same header."""
    eule = planegen.generate(show, model(show, "eule"))
    falke = planegen.generate(show, model(show, "falke"))
    assert eule != falke
    assert defines(eule)["STRIP_COUNT"] != defines(falke)["STRIP_COUNT"]


def test_generated_guard_does_not_clash_with_config_h(show):
    """config.h includes the generated file, so the guards must differ."""
    header = planegen.generate(show, model(show, "eule"))
    assert "PLANE_MODEL_CONFIG_H" in header
    assert "#define PLANE_CONFIG_H" not in header


def test_model_without_plane_section_is_refused():
    show = config_module.ShowCfg(
        ports=[config_module.PortCfg(id=0, name="tx")],
        models=[config_module.ModelCfg("x", 1, 0)],
    )
    with pytest.raises(ValueError, match="no plane configuration"):
        planegen.generate(show, show.models[0])


# -------------------------------------------------------------------- wiring


def test_wiring_names_the_physical_pin(show):
    rows = planegen.wiring(model(show, "eule"))
    by_role = {row.role: row for row in rows}
    # GP2 is physical pin 4 on the Pico header.
    strip = next(row for row in rows if row.role.startswith("LED-Strip 0"))
    assert strip.gpio == 2 and strip.physical == "Pin 4"
    assert by_role["SBUS-Eingang"].physical == "Pin 7"
    assert by_role["VSYS"].physical == "Pin 39"


def test_wiring_covers_every_configured_output(show):
    eule = model(show, "eule")
    rows = planegen.wiring(eule)
    pins = {row.gpio for row in rows}
    for strip in eule.plane.strips:
        assert strip.pin in pins
    for relay in eule.plane.relays:
        assert relay.pin in pins


def test_wiring_distinguishes_mosfet_from_relay_board(show):
    rows = planegen.wiring(model(show, "eule"))
    mosfet = next(r for r in rows if "scheinwerfer" in r.role)
    board = next(r for r in rows if "rauch" in r.role)
    assert "MOSFET" in mosfet.note
    assert "LOW" in board.note


def test_power_estimate_counts_every_pixel(show):
    estimate = planegen.power_estimate(model(show, "eule").plane)
    assert estimate["pixels"] == 60
    assert estimate["worst_a"] == pytest.approx(3.6, abs=0.01)
    assert estimate["typical_a"] < estimate["worst_a"]


# --------------------------------------------------------------- round trip


def test_configuration_survives_a_round_trip(show):
    """What the UI saves must load back identical -- otherwise editing loses data."""
    text = config_module.dump(show)
    again = config_module.load_dict(yaml.safe_load(text))
    assert config_module.to_dict(again) == config_module.to_dict(show)


def test_generated_header_is_stable_across_a_round_trip(show):
    again = config_module.load_dict(yaml.safe_load(config_module.dump(show)))
    for name in ("eule", "falke"):
        assert planegen.generate(again, model(again, name)) == \
               planegen.generate(show, model(show, name))


def test_save_keeps_a_backup_and_refuses_to_write_garbage(tmp_path, show):
    path = tmp_path / "show.yaml"
    path.write_text("serial_port: /dev/null\n")
    config_module.save(show, path)
    assert (tmp_path / "show.yaml.bak").read_text() == "serial_port: /dev/null\n"
    assert config_module.load(path).models[0].name == "eule"


# --------------------------------------------------------- firmware compiles


def test_generated_header_compiles_against_the_firmware(show, tmp_path):
    """The strongest check: the C preprocessor has to accept what we emit."""
    if shutil.which("cc") is None:
        pytest.skip("cc not available")

    src = REPO / "firmware" / "plane" / "src"
    header = tmp_path / "model.h"
    header.write_text(planegen.generate(show, model(show, "eule")))

    probe = tmp_path / "probe.c"
    probe.write_text(
        '#include "config.h"\n'
        "static const strip_cfg_t strips[] = STRIPS;\n"
        "static const relay_cfg_t relays[] = RELAYS;\n"
        "static const zone_cfg_t zones[] = ZONES;\n"
        "static const nav_light_t navs[] = NAV_LIGHTS;\n"
        "int main(void) {\n"
        "  return (int)(sizeof(strips) + sizeof(relays) + sizeof(zones) + sizeof(navs)\n"
        "               + STRIP_COUNT + RELAY_COUNT + ZONE_COUNT + NAV_COUNT);\n"
        "}\n"
    )
    result = subprocess.run(
        ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fsyntax-only",
         f"-I{src}", f'-DPLANE_CONFIG_HEADER="{header}"', str(probe)],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


# ------------------------------------------------------------------ bus mode


def bus_model(show, zones=4, relays=2):
    """The shipped 'eule' turned into a bus model with `zones` zones."""
    from lightshow import config as config_module

    entry = model(show, "eule")
    base = list(entry.channels[:4])
    entry.channels = []
    for zone in range(zones):
        for offset, channel in enumerate(base):
            entry.channels.append(config_module.ChannelCfg(
                role=channel.role, cc=20 + zone * 4 + offset,
                quantize=channel.quantize, failsafe=channel.failsafe))
    entry.bus = config_module.BusCfg(
        enabled=True,
        relays=[config_module.BusRelayCfg(f"r{i}", 100 + i) for i in range(relays)])
    return entry


def test_a_bus_model_declares_the_frame_the_firmware_has_to_decode(show):
    entry = model(show, "eule")
    keep = (list(entry.channels), entry.bus)
    try:
        header = planegen.generate(show, bus_model(show, zones=6, relays=1))
        table = defines(header)
        assert table["BUS_MODE"] == "1"
        assert table["BUS_ZONES"] == "6"
        assert table["BUS_RELAY_COUNT"] == "1"
        assert table["ZONE_COUNT"] == "6"
        # Where on the transmitter the eight coded channels start.
        assert table["BUS_FIRST_CHANNEL"] == str(entry.tx_offset + 1)
        # The all-off command belongs to bus.h, not to a model's header.
        assert "BUS_CUE_ALL_OFF" not in table
    finally:
        entry.channels, entry.bus = keep


def test_a_classic_model_says_so_rather_than_leaving_it_open(show):
    """`#if BUS_MODE` on a missing macro is silently false -- but a header that
    states it can be read by a human without knowing that rule."""
    assert defines(planegen.generate(show, model(show, "falke")))["BUS_MODE"] == "0"


def test_the_bus_relay_slots_are_named_in_the_header(show):
    """Which bit means which relay is otherwise invisible on the aircraft."""
    entry = model(show, "eule")
    keep = (list(entry.channels), entry.bus)
    try:
        header = planegen.generate(show, bus_model(show, zones=2, relays=2))
        assert "0: r0" in header and "1: r1" in header
    finally:
        entry.channels, entry.bus = keep


def test_a_bus_header_compiles_and_matches_the_decoder(show, tmp_path):
    """The generated bus macros have to line up with bus.h, or the aircraft
    would decode a frame the ground station never sends."""
    if shutil.which("cc") is None:
        pytest.skip("cc not available")

    entry = model(show, "eule")
    keep = (list(entry.channels), entry.bus)
    try:
        header = tmp_path / "model.h"
        header.write_text(planegen.generate(show, bus_model(show, zones=6, relays=2)))

        src = REPO / "firmware" / "plane" / "src"
        probe = tmp_path / "probe.c"
        probe.write_text(
            '#include "config.h"\n'
            '#include "bus.h"\n'
            "static const zone_cfg_t zones[] = ZONES;\n"
            # The header's idea of the frame has to be the decoder's idea of it.
            "_Static_assert(BUS_ZONES <= BUS_MAX_ZONES, \"zu viele Zonen\");\n"
            "_Static_assert(BUS_RELAY_COUNT <= BUS_MAX_RELAYS, \"zu viele Relais\");\n"
            "_Static_assert(BUS_ZONES == ZONE_COUNT, \"Zonenzahl uneinig\");\n"
            "int main(void) {\n"
            "  return (int)(sizeof(zones) + BUS_MODE + BUS_FIRST_CHANNEL\n"
            "               + BUS_CUE_ALL_OFF + bus_address_bits(BUS_ZONES));\n"
            "}\n"
        )
        result = subprocess.run(
            ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fsyntax-only",
             f"-I{src}", f'-DPLANE_CONFIG_HEADER="{header}"', str(probe)],
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr.decode()
    finally:
        entry.channels, entry.bus = keep


def test_the_generated_budget_is_one_the_frame_can_carry(show):
    """planegen must not emit a combination the encoder would refuse."""
    from lightshow import bus as bus_mode

    entry = model(show, "eule")
    keep = (list(entry.channels), entry.bus)
    try:
        for zones, relays in ((1, 4), (4, 2), (6, 1), (8, 1)):
            built = bus_model(show, zones=zones, relays=relays)
            table = defines(planegen.generate(show, built))
            assert bus_mode.fits(int(table["BUS_ZONES"]),
                                 int(table["BUS_RELAY_COUNT"]))
    finally:
        entry.channels, entry.bus = keep
