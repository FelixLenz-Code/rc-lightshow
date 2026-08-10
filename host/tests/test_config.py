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
    assert all(model.tx_offset == 0 for model in show.models)


def test_wire_ports_fill_failsafe_per_channel():
    show = config_module.load(SHIPPED_CONFIG)
    for index, wire in enumerate(show.wire_ports()):
        assert len(wire.failsafe) == wire.nchan
        # Each model sits at the start of its own port.
        assert wire.failsafe[:4] == [1000, 1500, 1000, 1500]
        # Nothing drives the rest, so they hold the port minimum.
        assert set(wire.failsafe[4:]) == {1000}, f"Port {index}"


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
