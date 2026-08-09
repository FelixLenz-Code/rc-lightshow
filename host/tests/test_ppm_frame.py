"""Verifies the PPM frame timing the firmware generates.

The PIO program costs three fixed cycles per half period, so the buffer holds
`duration - 3`. If that compensation were wrong every channel would be off by
the same few microseconds -- visible in the transmitter as a trim error and
tedious to chase with an oscilloscope. These tests reconstruct the real pulse
timing from the firmware's own frame builder.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CTEST = REPO / "tools" / "ctest"


@pytest.fixture(scope="session")
def ppm_dump() -> Path:
    if shutil.which("make") is None or shutil.which("cc") is None:
        pytest.skip("make/cc not available")
    subprocess.run(["make", "-s"], cwd=CTEST, check=True)
    return CTEST / "build" / "ppm_dump"


def frame(ppm_dump: Path, sync_us: int, frame_us: int, values: list[int],
          min_us: int = 1000, max_us: int = 2000) -> list[tuple[str, int]]:
    result = subprocess.run(
        [str(ppm_dump), str(sync_us), str(frame_us), str(min_us), str(max_us),
         *[str(v) for v in values]],
        capture_output=True, check=True,
    )
    pulses = []
    for line in result.stdout.decode().splitlines():
        kind, duration = line.split()
        pulses.append((kind, int(duration)))
    return pulses


def channel_slots(pulses: list[tuple[str, int]]) -> list[int]:
    """Time from one rising edge to the next -- what a receiver measures."""
    slots = []
    for index in range(0, len(pulses) - 2, 2):
        slots.append(pulses[index][1] + pulses[index + 1][1])
    return slots


def test_channel_slots_match_the_requested_values(ppm_dump):
    values = [1000, 1250, 1500, 1750, 2000, 1100, 1900, 1500]
    pulses = frame(ppm_dump, 400, 22500, values)
    assert channel_slots(pulses) == values


def test_every_mark_is_the_configured_sync_width(ppm_dump):
    pulses = frame(ppm_dump, 400, 22500, [1500] * 8)
    assert [duration for kind, duration in pulses if kind == "mark"] == [400] * 9


def test_total_frame_length_is_exact(ppm_dump):
    for frame_us in (20000, 22500, 25000):
        pulses = frame(ppm_dump, 400, frame_us, [1500] * 8)
        assert sum(duration for _, duration in pulses) == frame_us


def test_frame_stays_valid_with_all_channels_at_maximum(ppm_dump):
    # 8 x 2000 + 400 sync = 16400 us, so 22.5 ms still leaves a long gap.
    pulses = frame(ppm_dump, 400, 22500, [2000] * 8)
    assert channel_slots(pulses) == [2000] * 8
    assert pulses[-1][1] >= 3000
    assert sum(duration for _, duration in pulses) == 22500


def test_sync_gap_is_never_shorter_than_three_milliseconds(ppm_dump):
    # A frame that is too short for its channels must grow rather than produce
    # an unrecognisable sync pulse.
    pulses = frame(ppm_dump, 400, 10000, [2000] * 8)
    assert pulses[-1][1] >= 3000
    assert channel_slots(pulses) == [2000] * 8


def test_values_are_clamped_to_the_port_range(ppm_dump):
    pulses = frame(ppm_dump, 400, 22500, [500, 3000, 1500, 1500],
                   min_us=1100, max_us=1900)
    assert channel_slots(pulses) == [1100, 1900, 1500, 1500]


def test_alternative_sync_width_still_adds_up(ppm_dump):
    pulses = frame(ppm_dump, 300, 22500, [1234] * 8)
    assert channel_slots(pulses) == [1234] * 8
    assert [duration for kind, duration in pulses if kind == "mark"] == [300] * 9
    assert sum(duration for _, duration in pulses) == 22500


@pytest.mark.parametrize("nchan", [4, 6, 8, 12, 16])
def test_buffer_holds_one_pair_per_channel_plus_the_sync_pair(ppm_dump, nchan):
    pulses = frame(ppm_dump, 400, 40000, [1500] * nchan)
    assert len(pulses) == 2 * (nchan + 1)
