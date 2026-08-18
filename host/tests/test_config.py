from pathlib import Path

import pytest

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
    show = config_module.load(SHIPPED_CONFIG)
    wires = show.wire_ports()
    for wire in wires:
        assert len(wire.failsafe) == wire.nchan

    for model in show.models:
        wire = wires[model.tx_port]
        first = model.tx_offset
        if model.uses_bus:
            # A bus model's block is one code word, checked in test_bus.py --
            # per channel failsafes mean nothing there.
            continue
        last = first + len(model.channels)
        # A model's own block carries the failsafe its channels declare ...
        assert wire.failsafe[first:last] == [c.failsafe for c in model.channels]
        # ... and everything nothing drives holds the port minimum.
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
    text = BASE + """
  - name: falke
    midi_channel: 2
    tx_port: 0
    tx_offset: 1
    channels:
      - {role: cue, cc: 20, failsafe: 1000}
"""
    with pytest.raises(config_module.ConfigError, match="claimed by both"):
        config_module.load(write(tmp_path, text))


def test_duplicate_cc_on_the_same_midi_channel_is_rejected(tmp_path):
    text = BASE.replace("- {role: hue, cc: 21", "- {role: hue, cc: 20")
    with pytest.raises(config_module.ConfigError, match="CC 20"):
        config_module.load(write(tmp_path, text))


def test_blackout_cc_cannot_be_reused(tmp_path):
    text = BASE.replace("cc: 21", "cc: 119")
    with pytest.raises(config_module.ConfigError, match="blackout_cc"):
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
      - {role: brightness, cc: 22, failsafe: 1000}
      - {role: param, cc: 23, failsafe: 1500}
    plane:
      board: pico
      strips:
        - {name: rumpf, pin: 2, count: 30}
"""


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
    assert [s.pin for s in show.models[0].plane.strips] == [2, 10]


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
      - {role: brightness, cc: 22, failsafe: 1000}
      - {role: param, cc: 23, failsafe: 1500}
      - {role: cue, cc: 24, quantize: 32, failsafe: 1000}
      - {role: hue, cc: 25, failsafe: 1500}
      - {role: brightness, cc: 26, failsafe: 1000}
      - {role: param, cc: 27, failsafe: 1500}
"""
    show = config_module.load(write(tmp_path, text))
    assert show.models[0].zone_count == 2


# ---------------------------------------------------------------- relay pixels


def test_a_relay_may_not_follow_a_pixel_beyond_the_zones_chain(tmp_path):
    """Mirrored strips share a chain, so the zone is as long as one of them.

    Adding the pixel counts up would accept an index the firmware reads as out
    of range -- and the relay would then simply never switch.
    """
    text = PLANE + """
        - {name: flaeche, pin: 3, count: 30, offset: 0}
      relays:
        - {name: licht, pin: 6, source: pixel, arg: 45}
"""
    with pytest.raises(config_module.ConfigError, match="only has 30"):
        config_module.load(write(tmp_path, text))


def test_strips_laid_end_to_end_do_make_a_longer_chain(tmp_path):
    text = PLANE + """
        - {name: flaeche, pin: 3, count: 30, offset: 30}
      relays:
        - {name: licht, pin: 6, source: pixel, arg: 45}
"""
    show = config_module.load(write(tmp_path, text))
    assert show.models[0].plane.relays[0].arg == 45


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
      enabled: true
      relays:
#RELAYS#
    channels:
#CHANNELS#
    plane:
      board: pico
      strips:
        - {name: rumpf, pin: 2, count: 30}
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
    return (BUS_BASE.replace("#CHANNELS#\n", channels)
                    .replace("#RELAYS#\n", relay_lines))


def test_a_bus_model_occupies_eight_channels_whatever_its_zones(tmp_path):
    """Six zones would be 24 channels laid out one per value -- on the bus they
    are eight, which is the entire point of the mode."""
    show = config_module.load(write(tmp_path, bus_text(zones=6, relays=0)))
    model = show.models[0]
    assert model.uses_bus
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


def test_a_relay_cannot_point_at_a_bus_slot_that_does_not_exist(tmp_path):
    text = bus_text(zones=2, relays=1).replace(
        "        - {name: rumpf, pin: 2, count: 30}",
        "        - {name: rumpf, pin: 2, count: 30}\n"
        "      relays:\n"
        "        - {name: rauch, pin: 6, source: bus, arg: 3}")
    with pytest.raises(config_module.ConfigError, match="bus relay 3"):
        config_module.load(write(tmp_path, text))


def test_source_bus_without_bus_mode_is_refused(tmp_path):
    text = PLANE + """
      relays:
        - {name: rauch, pin: 6, source: bus, arg: 0}
"""
    with pytest.raises(config_module.ConfigError, match="bus mode"):
        config_module.load(write(tmp_path, text))


def test_a_bus_relay_may_not_share_a_control_change(tmp_path):
    text = bus_text(zones=2, relays=1).replace("cc: 100", "cc: 21")
    with pytest.raises(config_module.ConfigError, match="CC 21"):
        config_module.load(write(tmp_path, text))


def test_bus_survives_the_round_trip_through_yaml(tmp_path):
    """The web UI writes the config back; a dropped bus section would silently
    turn a six zone aircraft back into a two zone one."""
    show = config_module.load(write(tmp_path, bus_text(zones=4, relays=2)))
    again = config_module.load_dict(config_module.to_dict(show))
    assert again.models[0].uses_bus
    assert again.models[0].bus.relay_count == 2
    assert [r.cc for r in again.models[0].bus.relays] == [100, 101]
