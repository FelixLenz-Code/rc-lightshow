from pathlib import Path

import json

import pytest
import yaml

from lightshow import config as config_module

SHIPPED_CONFIG = Path(__file__).resolve().parents[1] / "config" / "show.yaml"

BASE = """
serial_port: /dev/ttyACM0
tx_ports:
  - {id: 0, name: tx, format: ppm, nchan: 8}
models:
  - name: eule
    midi_channel: 1
    tx_port: 0
    channels:
      - {role: cue, cc: 20, quantize: 32, failsafe: 1000}
      - {role: hue, cc: 21, failsafe: 1500}
      - {role: brightness, cc: 22, failsafe: 1000}
      - {role: param, cc: 23, failsafe: 1500}
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "show.yaml"
    path.write_text(text)
    return path


def test_shipped_config_is_valid():
    show = config_module.load(SHIPPED_CONFIG)
    assert show.ports[0].format == "ppm"
    assert [model.name for model in show.models] == ["eule", "falke"]
    assert show.models[1].tx_offset == 0


def test_every_model_in_the_example_has_its_own_transmitter():
    """One aircraft, one receiver, one transmitter, one jack.

    Sharing a port needs two receivers bound to the same transmitter model,
    which is the exception -- the example must not teach it as the rule.
    """
    show = config_module.load(SHIPPED_CONFIG)
    ports = [model.tx_port for model in show.models]
    assert sorted(ports) == sorted(set(ports)), "zwei Modelle an einer Buchse"
    # Each model's block has to stay inside its own port. Sitting at channel 1
    # is not required -- 'eule' deliberately starts at 9, above the sticks.
    for model in show.models:
        port = show.port_by_id(model.tx_port)
        assert model.tx_offset + model.wire_channels <= port.nchan


def test_wire_ports_fill_failsafe_per_channel():
    """A model's block holds a frame that decodes to off; the rest is minimum.

    Per channel failsafes cannot appear here any more: the eight channels are
    one code word, and eight individually sensible values are not one.
    """
    from lightshow import bus as bus_mode

    show = config_module.load(SHIPPED_CONFIG)
    wires = show.wire_ports()
    for wire in wires:
        assert len(wire.failsafe) == wire.nchan

    for model in show.models:
        wire = wires[model.tx_port]
        first = model.tx_offset
        last = first + bus_mode.SYMBOLS
        block = wire.failsafe[first:last]
        symbols = [bus_mode.us_to_symbol(us, wire.min_us, wire.max_us)
                   for us in block]
        decoded = bus_mode.decode(symbols)
        assert decoded.ok, model.name
        _, state, _ = bus_mode.unpack(
            decoded.data, zones=model.zone_count,
            relays_count=model.bus.relay_count)
        assert bus_mode.is_all_off(state), model.name

        # Everything no model drives holds the port minimum.
        untouched = wire.failsafe[:first] + wire.failsafe[last:]
        assert set(untouched) <= {wire.min_us}, model.name


def test_ppm_frame_must_hold_every_channel(tmp_path):
    text = BASE.replace("nchan: 8", "nchan: 8, frame_us: 15000")
    with pytest.raises(config_module.ConfigError, match="too short"):
        config_module.load(write(tmp_path, text))


def test_channels_must_fit_into_the_port(tmp_path):
    text = BASE.replace("tx_port: 0", "tx_port: 0\n    tx_offset: 7")
    with pytest.raises(config_module.ConfigError, match="do not fit"):
        config_module.load(write(tmp_path, text))


def test_overlapping_models_are_rejected(tmp_path):
    """Two eight channel blocks one channel apart share seven of them."""
    text = BASE.replace("nchan: 8", "nchan: 16, frame_us: 35500") + """
  - name: falke
    midi_channel: 2
    tx_port: 0
    tx_offset: 1
    channels:
      - {role: cue, cc: 30, quantize: 32, failsafe: 1000}
      - {role: hue, cc: 31, failsafe: 1500}
      - {role: brightness, cc: 32, failsafe: 1000}
      - {role: param, cc: 33, failsafe: 1500}
"""
    with pytest.raises(config_module.ConfigError, match="claimed by both"):
        config_module.load(write(tmp_path, text))


def test_failsafe_outside_the_port_range_is_rejected(tmp_path):
    text = BASE.replace("failsafe: 1500", "failsafe: 2400")
    with pytest.raises(config_module.ConfigError, match="outside the port range"):
        config_module.load(write(tmp_path, text))


def test_port_ids_must_be_consecutive(tmp_path):
    text = BASE.replace("id: 0, name: tx", "id: 1, name: tx").replace("tx_port: 0", "tx_port: 1")
    with pytest.raises(config_module.ConfigError, match="consecutive"):
        config_module.load(write(tmp_path, text))


def test_negative_offset_is_rejected(tmp_path):
    text = "global_offset_ms: -20\n" + BASE
    with pytest.raises(config_module.ConfigError, match="negative"):
        config_module.load(write(tmp_path, text))


def port(**fields) -> str:
    """BASE with one replaced tx_ports line, so port checks can vary a single key."""
    settings = {"id": 0, "name": "tx", "format": "ppm", "nchan": 8, **fields}
    line = ", ".join(f"{key}: {value}" for key, value in settings.items())
    return BASE.replace("{id: 0, name: tx, format: ppm, nchan: 8}", "{" + line + "}")


def test_an_uppercase_format_still_gets_the_ppm_frame_default(tmp_path):
    """`format: PPM` used to pick up the much shorter SBUS default frame."""
    show = config_module.load(write(tmp_path, port(format="PPM")))
    assert show.ports[0].format == "ppm"
    assert show.ports[0].frame_us == 22500


def test_a_sync_pulse_the_firmware_would_refuse_is_caught_here(tmp_path):
    """ports.c accepts 50..800 us and silently drops the rest of the frame."""
    with pytest.raises(config_module.ConfigError, match="sync_us"):
        config_module.load(write(tmp_path, port(sync_us=30)))


def test_a_pulse_range_outside_the_firmware_window_is_rejected(tmp_path):
    with pytest.raises(config_module.ConfigError, match=r"500\.\.2500"):
        config_module.load(write(tmp_path, port(max_us=2600, frame_us=40000)))


# ------------------------------------------------------- airborne pin choices


PLANE = BASE + """
    plane:
      board: pico
      outputs:
        - {name: rumpf, pin: 2, count: 30}
"""


@pytest.mark.parametrize("kind", sorted(config_module.AIRFRAMES))
def test_every_offered_airframe_survives_the_file(tmp_path, kind):
    """The word the wizard writes has to come back as the word the preview reads."""
    text = PLANE.replace("board: pico", f"board: pico\n      airframe: {kind}")
    show = config_module.load(write(tmp_path, text))
    assert show.models[0].plane.airframe == kind


def test_a_model_that_says_nothing_is_an_aeroplane(tmp_path):
    """Every configuration written before there was a choice is a Motorflugzeug."""
    show = config_module.load(write(tmp_path, PLANE))
    assert show.models[0].plane.airframe == "motor"


def test_an_unknown_airframe_is_rejected_by_name(tmp_path):
    """A typo would otherwise be drawn as an aeroplane and never mentioned."""
    text = PLANE.replace("board: pico", "board: pico\n      airframe: helikopter")
    with pytest.raises(config_module.ConfigError, match="helikopter"):
        config_module.load(write(tmp_path, text))


def test_an_sbus_pin_uart1_cannot_reach_is_rejected(tmp_path):
    """The image would build, boot and never receive a frame.

    SBUS runs on uart1, and its RX line only comes out on a few pins. Any other
    pin gets funcsel UART and lands on TX or a flow control line instead.
    """
    text = PLANE.replace("board: pico", "board: pico\n      sbus_pin: 4")
    with pytest.raises(config_module.ConfigError, match="cannot receive SBUS"):
        config_module.load(write(tmp_path, text))


@pytest.mark.parametrize("pin", sorted(config_module.PICO_UART1_RX_GPIO))
def test_the_pins_uart1_does_reach_are_accepted(tmp_path, pin):
    text = PLANE.replace("board: pico", f"board: pico\n      sbus_pin: {pin}")
    show = config_module.load(write(tmp_path, text))
    assert show.models[0].plane.sbus_pin == pin


def test_pwm_pins_are_rejected_now_that_the_receiver_is_sbus_only(tmp_path):
    """Eine alte Konfiguration soll auffallen, nicht stillschweigend wirkungslos
    werden -- sonst glaubt jemand weiter an einen Rueckfallpfad."""
    text = PLANE.replace("board: pico", "board: pico\n      pwm_pins: [10, 11, 12, 13]")
    with pytest.raises(config_module.ConfigError, match="pwm_pins does not exist"):
        config_module.load(write(tmp_path, text))


def test_gpio_10_to_13_are_free_for_strips_now(tmp_path):
    """Was frueher PWM belegte, steht jetzt fuer Ausgaenge zur Verfuegung."""
    text = PLANE.replace(
        "- {name: rumpf, pin: 2, count: 30}",
        "- {name: rumpf, pin: 2, count: 30}\n"
        "        - {name: fluegel, pin: 10, count: 20}")
    show = config_module.load(write(tmp_path, text))
    assert [o.pin for o in show.models[0].plane.outputs] == [2, 10]


def test_swapped_channel_roles_are_rejected(tmp_path):
    """Nothing downstream reads `role`; the firmware decodes by position."""
    text = BASE.replace("- {role: cue, cc: 20, quantize: 32, failsafe: 1000}\n"
                        "      - {role: hue, cc: 21, failsafe: 1500}",
                        "- {role: hue, cc: 21, failsafe: 1500}\n"
                        "      - {role: cue, cc: 20, quantize: 32, failsafe: 1000}")
    with pytest.raises(config_module.ConfigError, match="position 1 of a zone"):
        config_module.load(write(tmp_path, text))


def test_an_invented_role_name_is_rejected(tmp_path):
    text = BASE.replace("role: hue", "role: banane")
    with pytest.raises(config_module.ConfigError, match="banane"):
        config_module.load(write(tmp_path, text))


def test_a_second_zone_repeats_the_same_four_roles(tmp_path):
    text = BASE + """
      - {role: cue, cc: 24, quantize: 32, failsafe: 1000}
      - {role: hue, cc: 25, failsafe: 1500}
      - {role: brightness, cc: 26, failsafe: 1000}
      - {role: param, cc: 27, failsafe: 1500}
"""
    show = config_module.load(write(tmp_path, text))
    assert show.models[0].zone_count == 2


# ---------------------------------------------------------------- relay pixels


def test_segments_sharing_an_offset_mirror_each_other(tmp_path):
    """A zone is as long as its furthest segment reaches, not the sum.

    Two segments at offset 0 are two views of one 30 pixel chain -- a chase
    runs across 30 positions, not 60.
    """
    text = PLANE + """
        - name: flaeche
          pin: 3
          count: 30
          segments: [{name: a, start: 0, count: 30, offset: 0}]
"""
    plane = config_module.load(write(tmp_path, text)).models[0].plane
    assert plane.zone_pixels(0) == 30


def test_strips_laid_end_to_end_do_make_a_longer_chain(tmp_path):
    """Offsets in sequence, on the other hand, really do add up."""
    text = PLANE + """
        - name: flaeche
          pin: 3
          count: 30
          segments: [{name: a, start: 0, count: 30, offset: 30}]
"""
    plane = config_module.load(write(tmp_path, text)).models[0].plane
    assert plane.zone_pixels(0) == 60


# ------------------------------------------------------------------ bus mode

# Built by substitution rather than str.format -- the template is YAML and is
# full of braces of its own.
BUS_BASE = """
serial_port: /dev/ttyACM0
tx_ports:
  - {id: 0, name: tx, format: ppm, nchan: 16, frame_us: 35500}
models:
  - name: eule
    midi_channel: 1
    tx_port: 0
    tx_offset: 8
    bus:
      relays:
#RELAYS#
    channels:
#CHANNELS#
    plane:
      board: pico
      outputs:
        - {name: rumpf, pin: 2, count: 30}
      relays:
#BOARD#
"""


def bus_text(zones: int, relays: int) -> str:
    channels = ""
    for zone in range(zones):
        first = 20 + zone * 4
        channels += (
            f"      - {{role: cue, cc: {first}, quantize: 32, failsafe: 1000}}\n"
            f"      - {{role: hue, cc: {first + 1}, failsafe: 1500}}\n"
            f"      - {{role: brightness, cc: {first + 2}, failsafe: 1000}}\n"
            f"      - {{role: param, cc: {first + 3}, failsafe: 1500}}\n")
    relay_lines = "".join(
        f"        - {{name: r{i}, cc: {100 + i}}}\n" for i in range(relays)
    ) or "        []\n"
    # Same relays, same order, seen from the board.
    board_lines = "".join(
        f"        - {{name: r{i}, pin: {6 + i}}}\n" for i in range(relays)
    ) or "        []\n"
    return (BUS_BASE.replace("#CHANNELS#\n", channels)
                    .replace("#RELAYS#\n", relay_lines)
                    .replace("#BOARD#\n", board_lines))


def test_a_bus_model_occupies_eight_channels_whatever_its_zones(tmp_path):
    """Six zones would be 24 channels laid out one per value -- on the bus they
    are eight, which is the entire point of the mode."""
    show = config_module.load(write(tmp_path, bus_text(zones=6, relays=0)))
    model = show.models[0]
    assert model.zone_count == 6
    assert model.wire_channels == 8


def test_too_many_relays_for_the_zones_is_refused_with_the_arithmetic(tmp_path):
    """Five relays plus a two bit address plus the zone state is 31 bits."""
    with pytest.raises(config_module.ConfigError, match="30"):
        config_module.load(write(tmp_path, bus_text(zones=4, relays=5)))


def test_the_bus_failsafe_is_a_code_word_not_eight_safe_channels(tmp_path):
    """Eight individually sensible values are not a valid frame at all."""
    from lightshow import bus as bus_mode

    show = config_module.load(write(tmp_path, bus_text(zones=4, relays=2)))
    model = show.models[0]
    wire = show.wire_ports()[0]
    block = wire.failsafe[model.tx_offset:model.tx_offset + bus_mode.SYMBOLS]
    symbols = [bus_mode.us_to_symbol(us, 1000, 2000) for us in block]

    decoded = bus_mode.decode(symbols)
    assert decoded.ok and decoded.corrected is None
    _, state, relays = bus_mode.unpack(decoded.data, zones=4, relays_count=2)
    assert bus_mode.is_all_off(state)
    assert state.brightness == 0
    assert relays == [False, False]


def test_a_relay_on_the_board_without_a_bit_is_refused(tmp_path):
    """A pin nothing can reach: the wire list is what reserves the bits."""
    text = bus_text(zones=2, relays=1).replace(
        "        - {name: r0, pin: 6}",
        "        - {name: r0, pin: 6}\n"
        "        - {name: rauch, pin: 7}")
    with pytest.raises(config_module.ConfigError, match="2 relay\\(s\\) on the board"):
        config_module.load(write(tmp_path, text))


def test_a_reserved_bit_without_a_relay_is_refused(tmp_path):
    """The other way round: a bit paid for out of the payload that switches
    nothing at all."""
    text = bus_text(zones=2, relays=2).replace(
        "        - {name: r1, pin: 7}\n", "")
    with pytest.raises(config_module.ConfigError, match="1 relay\\(s\\) on the board"):
        config_module.load(write(tmp_path, text))


def test_the_two_relay_lists_must_be_in_the_same_order(tmp_path):
    """Position is the whole mapping, so a swap would switch the wrong device
    while every line still reads as plausible."""
    text = bus_text(zones=2, relays=2).replace(
        "        - {name: r0, pin: 6}\n        - {name: r1, pin: 7}\n",
        "        - {name: r1, pin: 7}\n        - {name: r0, pin: 6}\n")
    with pytest.raises(config_module.ConfigError, match="paired by position"):
        config_module.load(write(tmp_path, text))


def test_bus_survives_the_round_trip_through_yaml(tmp_path):
    """The web UI writes the config back; a dropped bus section would silently
    turn a six zone aircraft back into a two zone one."""
    show = config_module.load(write(tmp_path, bus_text(zones=4, relays=2)))
    again = config_module.load_dict(config_module.to_dict(show))
    assert again.models[0].bus.relay_count == 2
    assert [r.name for r in again.models[0].bus.relays] == ["r0", "r1"]


# ------------------------------------------------------- outputs and segments


TWO_ZONES = BASE + """
      - {role: cue, cc: 24, quantize: 32, failsafe: 1000}
      - {role: hue, cc: 25, failsafe: 1500}
      - {role: brightness, cc: 26, failsafe: 1000}
      - {role: param, cc: 27, failsafe: 1500}
    plane:
      board: pico
      outputs:
"""


def test_one_chain_can_serve_two_zones(tmp_path):
    """The point of splitting outputs from zones: a 60 pixel strip soldered to
    one GPIO can be a wing in front and a fuselage behind."""
    text = TWO_ZONES + """
        - name: rumpf
          pin: 2
          count: 60
          segments:
            - {name: vorn,   start: 0,  count: 30, zone: 0}
            - {name: hinten, start: 30, count: 30, zone: 1}
"""
    plane = config_module.load(write(tmp_path, text)).models[0].plane
    assert len(plane.outputs) == 1
    assert [s.zone for _, s in plane.segments] == [0, 1]
    # Each zone renders only as far as its own segment reaches.
    assert plane.zone_pixels(0) == 30 and plane.zone_pixels(1) == 30


def test_segments_without_a_start_simply_follow_each_other(tmp_path):
    """Dividing a chain is the common case; saying where each piece begins
    twice over is not."""
    text = TWO_ZONES + """
        - name: rumpf
          pin: 2
          count: 60
          segments:
            - {name: vorn,   count: 20, zone: 0}
            - {name: hinten, count: 40, zone: 1}
"""
    plane = config_module.load(write(tmp_path, text)).models[0].plane
    assert [(s.start, s.count) for _, s in plane.segments] == [(0, 20), (20, 40)]


def test_a_chain_nobody_divided_is_one_segment(tmp_path):
    text = TWO_ZONES + """
        - {name: rumpf, pin: 2, count: 40}
"""
    plane = config_module.load(write(tmp_path, text)).models[0].plane
    segment = plane.outputs[0].segments[0]
    assert (segment.start, segment.count, segment.zone) == (0, 40, 0)


def test_overlapping_segments_are_rejected(tmp_path):
    """Two zones writing the same pixel is a race, not a mix."""
    text = TWO_ZONES + """
        - name: rumpf
          pin: 2
          count: 60
          segments:
            - {name: vorn,   start: 0,  count: 40, zone: 0}
            - {name: hinten, start: 30, count: 30, zone: 1}
"""
    with pytest.raises(config_module.ConfigError, match="overlap segment"):
        config_module.load(write(tmp_path, text))


def test_a_segment_may_not_reach_past_its_chain(tmp_path):
    text = TWO_ZONES + """
        - name: rumpf
          pin: 2
          count: 30
          segments:
            - {name: zuviel, start: 0, count: 40, zone: 0}
"""
    with pytest.raises(config_module.ConfigError, match="which has 30"):
        config_module.load(write(tmp_path, text))


def test_the_old_strips_key_is_named_rather_than_guessed_at(tmp_path):
    text = BASE + """
    plane:
      board: pico
      strips:
        - {name: rumpf, pin: 2, count: 30, zone: 0}
"""
    with pytest.raises(config_module.ConfigError, match="'strips' is now 'outputs'"):
        config_module.load(write(tmp_path, text))


def test_a_nav_light_counts_along_the_whole_chain(tmp_path):
    """It is a lamp at a wingtip; which zone covers that pixel is irrelevant."""
    text = TWO_ZONES + """
        - name: rumpf
          pin: 2
          count: 60
          segments:
            - {name: vorn,   start: 0,  count: 30, zone: 0}
            - {name: hinten, start: 30, count: 30, zone: 1}
      nav_lights:
        - {output: 0, index: 59, color: [255, 255, 255]}
"""
    plane = config_module.load(write(tmp_path, text)).models[0].plane
    assert plane.nav_lights[0].index == 59


def test_a_nav_light_beyond_the_chain_is_rejected(tmp_path):
    text = TWO_ZONES + """
        - {name: rumpf, pin: 2, count: 30}
      nav_lights:
        - {output: 0, index: 30, color: [255, 255, 255]}
"""
    with pytest.raises(config_module.ConfigError, match="beyond chain"):
        config_module.load(write(tmp_path, text))


@pytest.mark.parametrize("key,value", [
    ("source", "pixel"), ("arg", "0"), ("threshold", "64"), ("zone", "1"),
])
def test_the_old_relay_keys_are_named_rather_than_ignored(tmp_path, key, value):
    """A relay is switched over the bus and nowhere else now.

    Leaving one of these in would describe behaviour the firmware no longer
    has, and it would be silently ignored rather than refused.
    """
    text = bus_text(zones=2, relays=1).replace(
        "        - {name: r0, pin: 6}",
        f"        - {{name: r0, pin: 6, {key}: {value}}}")
    with pytest.raises(config_module.ConfigError, match=f"'{key}' does not exist"):
        config_module.load(write(tmp_path, text))


def test_a_relay_is_paired_with_its_bit_by_position(tmp_path):
    """The board half and the wire half of the same relay, in step."""
    show = config_module.load(write(tmp_path, bus_text(zones=2, relays=2)))
    model = show.models[0]
    assert [r.name for r in model.plane.relays] == ["r0", "r1"]
    assert [r.name for r in model.bus.relays] == ["r0", "r1"]
    assert [r.pin for r in model.plane.relays] == [6, 7]


# ----------------------------------------------------------------- die Platine


def board_text(board: str = "modell-2led-2relais-v1", led_pin: int = 2,
               relay_pin: int = 6,
               sbus_pin: int = 5) -> str:
    return bus_text(zones=1, relays=1) \
        .replace("      board: pico", f"      board: {board}\n      sbus_pin: {sbus_pin}") \
        .replace("- {name: rumpf, pin: 2, count: 30}",
                 f"- {{name: rumpf, pin: {led_pin}, count: 30}}") \
        .replace("- {name: r0, pin: 6}", f"- {{name: r0, pin: {relay_pin}}}")


def test_a_model_may_name_the_board_it_is_built_on(tmp_path):
    show = config_module.load(write(tmp_path, board_text()))
    assert show.models[0].plane.board == "modell-2led-2relais-v1"


def test_a_board_that_does_not_exist_is_refused(tmp_path):
    """Silently treating it as a free build would drop every check below."""
    with pytest.raises(config_module.ConfigError, match="is unknown"):
        config_module.load(write(tmp_path, board_text(board="modell-v9")))


def test_a_board_decides_where_its_led_connectors_go(tmp_path):
    """GP9 is a fine pin on a bare Pico, and nowhere on this board."""
    with pytest.raises(config_module.ConfigError, match="LED connectors"):
        config_module.load(write(tmp_path, board_text(led_pin=9)))


def test_a_board_decides_where_its_switched_outputs_go(tmp_path):
    with pytest.raises(config_module.ConfigError, match="switched outputs"):
        config_module.load(write(tmp_path, board_text(relay_pin=9)))


def test_a_board_decides_where_sbus_comes_in(tmp_path):
    """GP9 does reach uart1, so only the board rules this one out."""
    assert 9 in config_module.PICO_UART1_RX_GPIO
    with pytest.raises(config_module.ConfigError, match="wires SBUS to GPIO 5"):
        config_module.load(write(tmp_path, board_text(sbus_pin=9)))


def test_the_free_build_keeps_every_pin_open(tmp_path):
    """`board: pico` is the way out -- hand-wired, so nothing above applies."""
    show = config_module.load(write(tmp_path, board_text(
        board="pico", led_pin=9, relay_pin=14, sbus_pin=21)))
    plane = show.models[0].plane
    assert plane.outputs[0].pin == 9 and plane.relays[0].pin == 14


def test_the_two_relay_connectors_may_be_swapped(tmp_path):
    """Which device hangs on which connector is a soldering decision, so the
    board fixes the set of pins but not their order."""
    show = config_module.load(write(tmp_path, board_text(relay_pin=7)))
    assert show.models[0].plane.relays[0].pin == 7


def test_the_shipped_config_has_one_of_each(tmp_path):
    """The example teaches both ways: a ready-made board and a free build."""
    show = config_module.load(SHIPPED_CONFIG)
    boards = {model.name: model.plane.board for model in show.models}
    assert boards == {"eule": "pico", "falke": "modell-2led-2relais-v1"}


def test_the_boards_old_name_says_what_it_is_called_now(tmp_path):
    """The silkscreen names the variant since more boards are coming, so the
    key moved with it. A bare 'unknown' would leave somebody guessing which of
    the listed names used to be theirs."""
    with pytest.raises(config_module.ConfigError,
                       match="now called 'modell-2led-2relais-v1'"):
        config_module.load(write(tmp_path, board_text(board="modell-v1")))


# --------------------------------------------------------- die Platzierung


def test_a_segment_may_carry_where_it_sits_on_the_mockup(tmp_path):
    text = TWO_ZONES + """
        - name: rumpf
          pin: 2
          count: 30
          segments:
            - {name: ganz, start: 0, count: 30, zone: 0,
               place: {view: left, x1: 0.2, y1: 0.4, x2: 0.8, y2: 0.45}}
"""
    plane = config_module.load(write(tmp_path, text)).models[0].plane
    place = plane.outputs[0].segments[0].place
    assert (place.view, place.x1, place.y2) == ("left", 0.2, 0.45)


def test_a_segment_without_a_placement_simply_has_none(tmp_path):
    """It is a drawing, not a requirement -- a model works unplaced."""
    text = TWO_ZONES + """
        - {name: rumpf, pin: 2, count: 30}
"""
    plane = config_module.load(write(tmp_path, text)).models[0].plane
    assert plane.outputs[0].segments[0].place is None


def test_a_view_that_does_not_exist_is_refused(tmp_path):
    text = TWO_ZONES + """
        - name: rumpf
          pin: 2
          count: 30
          segments:
            - {name: ganz, start: 0, count: 30, zone: 0, place: {view: vorne}}
"""
    with pytest.raises(config_module.ConfigError, match="must be one of"):
        config_module.load(write(tmp_path, text))


def test_a_point_off_the_edge_is_pulled_back_rather_than_refused(tmp_path):
    """A slip of the mouse is not a broken configuration."""
    text = TWO_ZONES + """
        - name: rumpf
          pin: 2
          count: 30
          segments:
            - {name: ganz, start: 0, count: 30, zone: 0,
               place: {view: top, x1: -0.4, y1: 1.9, x2: 0.5, y2: 0.5}}
"""
    place = config_module.load(write(tmp_path, text)).models[0].plane \
        .outputs[0].segments[0].place
    assert (place.x1, place.y1) == (0.0, 1.0)


def test_a_placement_survives_the_round_trip_through_yaml(tmp_path):
    """It is written back into show.yaml, so it has to come out again."""
    text = TWO_ZONES + """
        - name: rumpf
          pin: 2
          count: 30
          segments:
            - {name: ganz, start: 0, count: 30, zone: 0,
               place: {view: bottom, x1: 0.1, y1: 0.2, x2: 0.3, y2: 0.4}}
"""
    show = config_module.load(write(tmp_path, text))
    again = config_module.load_dict(config_module.to_dict(show))
    place = again.models[0].plane.outputs[0].segments[0].place
    assert (place.view, place.x1, place.y2) == ("bottom", 0.1, 0.4)


def test_the_generator_never_sees_a_placement(tmp_path):
    """It is a drawing. Nothing about it may reach the aircraft."""
    from lightshow import planegen

    text = TWO_ZONES + """
        - name: rumpf
          pin: 2
          count: 30
          segments:
            - {name: ganz, start: 0, count: 30, zone: 0,
               place: {view: right, x1: 0.1, y1: 0.2, x2: 0.3, y2: 0.4}}
"""
    show = config_module.load(write(tmp_path, text))
    header = planegen.generate(show, show.models[0])
    for word in ("place", "view", "right", "0.1"):
        assert word not in header, word


# ------------------------------------------------- carrying one model around


def test_an_exported_model_names_what_it_is(tmp_path):
    """A file that could be anything is a file nobody can refuse politely."""
    show = config_module.load(write(tmp_path, PLANE))
    document = config_module.model_document(show, "eule")
    assert document["kind"] == config_module.MODEL_FILE_KIND
    assert document["model"]["name"] == "eule"
    # The transmitter comes along so the other side can say when it disagrees.
    assert document["tx_port_was"]["id"] == show.models[0].tx_port


def test_a_file_that_is_not_a_model_is_refused(tmp_path):
    with pytest.raises(config_module.ConfigError, match="keine exportierte"):
        config_module.read_model_document({"hallo": "welt"})


def test_a_model_file_from_a_later_version_is_refused():
    with pytest.raises(config_module.ConfigError, match="Fassung"):
        config_module.read_model_document(
            {"kind": config_module.MODEL_FILE_KIND, "version": 99, "model": {"name": "x"}})


# One jack wide enough for two models, which is what an import needs -- and a
# frame long enough to carry them.
ROOMY = PLANE.replace("nchan: 8", "nchan: 16, frame_us: 35500")


def test_importing_a_model_beside_itself_moves_it_out_of_the_way(tmp_path):
    """Two configurations that never met collide on nearly everything."""
    show = config_module.load(write(tmp_path, ROOMY))
    data = config_module.to_dict(show)
    incoming = json.loads(json.dumps(data["models"][0]))

    notes = config_module.fit_model(data, incoming)

    assert incoming["name"] != data["models"][0]["name"]
    assert incoming["tx_offset"] != data["models"][0]["tx_offset"]
    # Every move is reported -- silently moving an aircraft is how it ends up
    # on a jack nobody expects.
    assert len(notes) >= 2
    data["models"].append(incoming)
    config_module.load_dict(data)      # and the result is a valid show


def test_a_model_that_fits_is_left_exactly_where_it_is(tmp_path):
    show = config_module.load(write(tmp_path, ROOMY))
    data = config_module.to_dict(show)
    incoming = json.loads(json.dumps(data["models"][0]))
    incoming["name"] = "zweiter"
    incoming["tx_offset"] = 8
    before = json.loads(json.dumps(incoming))

    assert config_module.fit_model(data, incoming) == []
    assert incoming == before


# ---------------------------------------------------- the empty first start


STARTER = Path(__file__).resolve().parents[2] / "packaging" / "appimage" / "show.yaml"


def test_a_show_without_models_is_allowed(tmp_path):
    """That is what a fresh installation looks like.

    The AppImage ships without models, and the wizard is where they come from.
    Refusing to start would leave a new user at a configuration error before
    they ever saw the interface.
    """
    text = board_text()
    document = yaml.safe_load(text)
    document["models"] = []
    show = config_module.load(write(tmp_path, yaml.safe_dump(document, sort_keys=False)))

    assert show.models == []
    assert show.ports, "die Buchsen bleiben, nur die Modelle fehlen"


def test_the_starter_config_ships_empty():
    """What the AppImage puts into a new workspace."""
    show = config_module.load(STARTER)

    assert show.models == [], "das AppImage liefert keine Modelle mit"
    assert len(show.ports) == 8
    assert all(port.format == "off" for port in show.ports), \
        "jede Buchse ist frei, der Assistent schaltet die ein, die benutzt wird"
    assert all(port.name == f"buchse{index + 1}" for index, port in enumerate(show.ports)), \
        "keine Namen aus einer fremden Beispielshow"


def test_the_starter_config_is_what_the_writer_produces():
    """Byte for byte, so the shipped file cannot drift away from the schema.

    The interface rewrites it on the first edit anyway; if the two ever differ,
    the difference is a bug in one of them.
    """
    show = config_module.load(STARTER)
    assert config_module.dump(show) == STARTER.read_text()
