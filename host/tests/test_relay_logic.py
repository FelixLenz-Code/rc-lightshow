"""Verifies the airborne relay logic.

Two things are worth getting right before a relay hangs in an aircraft: that a
mechanical one is never switched faster than it can move, and that a lost link
really means everything off. Both are checked here against the firmware's own
code, compiled for the host.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CTEST = REPO / "tools" / "ctest"

@pytest.fixture(scope="session")
def relay_sim() -> Path:
    if shutil.which("make") is None or shutil.which("cc") is None:
        pytest.skip("make/cc not available")
    subprocess.run(["make", "-s"], cwd=CTEST, check=True)
    return CTEST / "build" / "relay_sim"


def step(relay_sim: Path, min_on: int, min_off: int,
         samples: list[tuple[int, int]]) -> list[tuple[int, int]]:
    text = "\n".join(f"{t} {want}" for t, want in samples) + "\n"
    result = subprocess.run(
        [str(relay_sim), "step", str(min_on), str(min_off)],
        input=text.encode(), capture_output=True, check=True,
    )
    out = []
    for line in result.stdout.decode().splitlines():
        t, state = line.split()
        out.append((int(t), int(state)))
    return out


def wants(relay_sim: Path, rows: list[tuple[int, int]]) -> list[int]:
    """rows are (bus_on, all_off) -- the only two inputs a relay still has."""
    text = "\n".join(" ".join(str(v) for v in row) for row in rows) + "\n"
    result = subprocess.run(
        [str(relay_sim), "want"],
        input=text.encode(), capture_output=True, check=True,
    )
    return [int(line) for line in result.stdout.decode().splitlines()]


def strobe(period_ms: int, duty_ms: int, duration_ms: int,
           tick_ms: int = 5) -> list[tuple[int, int]]:
    return [(t, 1 if t % period_ms < duty_ms else 0)
            for t in range(0, duration_ms, tick_ms)]


# ------------------------------------------------------------------- timing --


def test_mosfet_follows_the_effect_exactly(relay_sim):
    """min_on = min_off = 0 must reproduce the input one to one."""
    samples = strobe(period_ms=50, duty_ms=25, duration_ms=1000)
    result = step(relay_sim, 0, 0, samples)
    assert [state for _, state in result] == [want for _, want in samples]


def test_mechanical_relay_never_switches_faster_than_allowed(relay_sim):
    min_on = min_off = 50
    result = step(relay_sim, min_on, min_off,
                  strobe(period_ms=50, duty_ms=25, duration_ms=3000))

    changes = [t for index, (t, state) in enumerate(result)
               if index > 0 and state != result[index - 1][1]]
    gaps = [b - a for a, b in zip(changes, changes[1:])]
    assert gaps, "the relay should still switch, just more slowly"
    assert min(gaps) >= min(min_on, min_off), f"switched after only {min(gaps)} ms"


def test_a_slow_relay_still_switches_during_a_fast_strobe(relay_sim):
    """It must not lock up in one state -- it should blink, just slower."""
    result = step(relay_sim, 50, 50, strobe(50, 25, 3000))
    states = {state for _, state in result}
    assert states == {0, 1}


def test_minimum_on_time_is_honoured_for_a_single_short_pulse(relay_sim):
    samples = [(0, 0), (10, 1), (20, 0)] + [(t, 0) for t in range(30, 400, 10)]
    result = step(relay_sim, 200, 0, samples)
    on = [t for t, state in result if state == 1]
    assert on, "relay never switched on"
    assert max(on) - min(on) >= 190, "dropped out before the minimum on time"


def test_no_change_is_queued_while_the_minimum_time_runs(relay_sim):
    """A blip that is over before the relay may move must be ignored entirely."""
    samples = [(0, 1)] + [(t, 1) for t in range(10, 100, 10)]
    samples += [(100, 0), (110, 1)]                    # 10 ms dropout
    samples += [(t, 1) for t in range(120, 400, 10)]
    result = step(relay_sim, 200, 200, samples)
    assert all(state == 1 for _, state in result), "the blip made it through"


def test_first_sample_adopts_the_requested_state_immediately(relay_sim):
    assert step(relay_sim, 500, 500, [(0, 1), (10, 1)])[0][1] == 1
    assert step(relay_sim, 500, 500, [(0, 0), (10, 0)])[0][1] == 0


# ------------------------------------------------------------------ sources --


def test_a_relay_follows_its_bit_and_nothing_else(relay_sim):
    """One input, one answer. There is no second way to switch a relay."""
    assert wants(relay_sim, [(0, 0), (1, 0)]) == [0, 1]


def test_all_off_beats_a_set_bit(relay_sim):
    """Failsafe, blackout or a frame saying so -- none of it is negotiable.

    Getting this the wrong way round would leave a smoke system running on a
    model that has lost its link.
    """
    assert wants(relay_sim, [(1, 1), (0, 1)]) == [0, 0]


def pin_levels(relay_sim: Path, active_low: bool, states: list[int]) -> list[int]:
    text = "\n".join(str(s) for s in states) + "\n"
    result = subprocess.run(
        [str(relay_sim), "pin", "1" if active_low else "0"],
        input=text.encode(), capture_output=True, check=True,
    )
    return [int(line) for line in result.stdout.decode().splitlines()]


def test_mosfet_boards_are_driven_directly(relay_sim):
    assert pin_levels(relay_sim, active_low=False, states=[0, 1]) == [0, 1]


def test_active_low_boards_get_the_inverted_pin_level(relay_sim):
    """The usual opto-isolated boards switch on when pulled low."""
    assert pin_levels(relay_sim, active_low=True, states=[0, 1]) == [1, 0]
