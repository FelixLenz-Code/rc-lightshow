"""Checks the firmware C code against the Python ground station.

Both sides implement the same protocol and the same channel quantisation. These
tests compile the SDK-independent firmware sources for the host and compare the
two implementations directly, so a change on one side cannot silently drift
away from the other.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lightshow.config import ChannelCfg, ModelCfg, PortCfg, ShowCfg
from lightshow.mapping import Mapper
from lightshow.protocol import PortWire, build_channels, build_config

REPO = Path(__file__).resolve().parents[2]
CTEST = REPO / "tools" / "ctest"
BUILD = CTEST / "build"


@pytest.fixture(scope="session")
def binaries() -> Path:
    if shutil.which("make") is None or shutil.which("cc") is None:
        pytest.skip("make/cc not available")
    subprocess.run(["make", "-s"], cwd=CTEST, check=True)
    return BUILD


def run_decoder(binaries: Path, data: bytes) -> list[str]:
    result = subprocess.run(
        [str(binaries / "frame_decoder")], input=data,
        capture_output=True, check=True,
    )
    return result.stdout.decode().splitlines()


PORTS = [
    PortWire("frsky", "ppm", "normal", 4, 22500, 400, 1000, 2000, [1000, 1500, 1000, 1500]),
    PortWire("alt", "ppm", "inverted", 2, 20000, 300, 1100, 1900, [1100, 1900]),
]


def test_firmware_reads_back_the_config_the_host_sent(binaries):
    lines = run_decoder(binaries, build_config(PORTS))
    assert lines[0] == "CONFIG nports=2"
    assert lines[1] == (
        "PORT 0 fmt=1 flags=0 nchan=4 frame=22500 sync=400 min=1000 max=2000 "
        "fs=1000,1500,1000,1500"
    )
    assert lines[2] == (
        "PORT 1 fmt=1 flags=1 nchan=2 frame=20000 sync=300 min=1100 max=1900 fs=1100,1900"
    )
    assert lines[-1].startswith("STATS ok=1 crc_err=0 bad=0")


def test_firmware_reads_back_the_channel_values(binaries):
    stream = build_config(PORTS) + build_channels(1, [[1000, 1234, 1750, 2000], [1500, 1600]])
    lines = run_decoder(binaries, stream)
    assert "CH 0 1000,1234,1750,2000" in lines
    assert "CH 1 1500,1600" in lines
    assert "FRAME" in lines


def test_channel_frames_before_a_config_are_rejected(binaries):
    lines = run_decoder(binaries, build_channels(1, [[1500] * 4]))
    assert not any(line.startswith("CH ") for line in lines)
    assert "bad=1" in lines[-1]


def test_values_outside_the_port_range_are_clamped(binaries):
    stream = build_config(PORTS) + build_channels(1, [[500, 2500, 1500, 1500], [1500, 1500]])
    lines = run_decoder(binaries, stream)
    assert "CH 0 1000,2000,1500,1500" in lines


def test_a_corrupted_byte_is_caught_by_the_crc(binaries):
    frame = bytearray(build_config(PORTS))
    frame[10] ^= 0xFF
    lines = run_decoder(binaries, bytes(frame))
    assert not any(line.startswith("CONFIG") for line in lines)
    assert "crc_err=1" in lines[-1]


def test_parser_resynchronises_after_garbage(binaries):
    stream = b"\xa5\xa5\x00\xff\xa5" + build_config(PORTS) + build_channels(9, [[1500] * 4, [1500] * 2])
    lines = run_decoder(binaries, stream)
    assert "CH 0 1500,1500,1500,1500" in lines


def test_sequence_gaps_are_reported(binaries):
    stream = build_config(PORTS)
    for seq in (1, 2, 7):
        stream += build_channels(seq, [[1500] * 4, [1500] * 2])
    lines = run_decoder(binaries, stream)
    assert "gaps=1" in lines[-1]


def test_sequence_number_wraps_without_a_false_gap(binaries):
    stream = build_config(PORTS)
    for seq in (254, 255, 0, 1):
        stream += build_channels(seq, [[1500] * 4, [1500] * 2])
    lines = run_decoder(binaries, stream)
    assert "gaps=0" in lines[-1]


# --------------------------------------------------------------- quantisation


def decode_table(binaries: Path, args: list[str]) -> dict[int, int]:
    result = subprocess.run(
        [str(binaries / "rc_decoder"), *args], capture_output=True, check=True
    )
    table = {}
    for line in result.stdout.decode().splitlines():
        us, value = line.split()
        table[int(us)] = int(value)
    return table


@pytest.mark.parametrize("steps", [2, 8, 32, 128])
def test_every_cue_step_survives_the_round_trip(binaries, steps):
    """What the ground station encodes must decode to the same step on board."""
    port = PortCfg(id=0, name="tx", nchan=1)
    channel = ChannelCfg(role="cue", cc=20, quantize=steps, failsafe=1000)
    show = ShowCfg(
        ports=[port],
        models=[ModelCfg("m", 1, 0, channels=[channel])],
    )
    mapper = Mapper(show)
    table = decode_table(binaries, ["step", str(steps), "1000", "2000"])

    for raw in range(128):
        mapper.handle_control_change(1, 20, raw)
        us = mapper.frame()[0][0]
        expected = min(steps - 1, raw * steps // 128)
        assert table[us] == expected, f"raw {raw} -> {us} us decoded as {table[us]}"


def test_quantised_values_keep_a_safety_margin(binaries):
    """Each encoded value must stay clear of its neighbours' bands."""
    steps = 32
    table = decode_table(binaries, ["step", str(steps), "1000", "2000"])
    port = PortCfg(id=0, name="tx", nchan=1)
    channel = ChannelCfg(role="cue", cc=20, quantize=steps, failsafe=1000)
    mapper = Mapper(
        ShowCfg(ports=[port], models=[ModelCfg("m", 1, 0, channels=[channel])])
    )

    for raw in range(0, 128, 4):
        mapper.handle_control_change(1, 20, raw)
        us = mapper.frame()[0][0]
        expected = table[us]
        # A whole PPM frame's worth of jitter must not change the step.
        for jitter in (-13, -8, 8, 13):
            assert table[us + jitter] == expected


def test_continuous_channels_agree_at_the_ends_and_middle(binaries):
    table = decode_table(binaries, ["u8", "1000", "2000"])
    assert table[1000] == 0
    assert table[2000] == 255
    assert table[1500] == 127
    assert sorted(table.values()) == list(table.values())  # monotonic
