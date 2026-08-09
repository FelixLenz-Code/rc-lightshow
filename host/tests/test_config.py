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
    assert show.models[1].tx_offset == 4


def test_wire_ports_fill_failsafe_per_channel():
    show = config_module.load(SHIPPED_CONFIG)
    wire = show.wire_ports()[0]
    assert len(wire.failsafe) == wire.nchan
    assert wire.failsafe[:4] == [1000, 1500, 1000, 1500]
    assert wire.failsafe[4:] == [1000, 1500, 1000, 1500]


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
