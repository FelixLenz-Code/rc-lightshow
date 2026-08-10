"""Checks the browser's effect preview against the airborne firmware.

The interface draws the pattern a model is about to fly, which is only worth
anything if it is really the same pattern. `web/effects.js` is a hand port of
`firmware/plane/src/effects.c`, so it is exactly the kind of copy that drifts.

These tests compile the real C, run the real JavaScript, and compare the two
pixel for pixel. They skip where node is not installed rather than failing --
node is a convenience for this check, not a dependency of the bridge.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CTEST = REPO / "tools" / "ctest"
EFFECTS_JS = REPO / "host" / "lightshow" / "web" / "effects.js"

# The ceiling the example config.h compiles in; effect_dump reports through it.
MAX_BRIGHTNESS = 200

# Cue, hue, brightness, param, time, pixel count. Chosen to hit each effect and
# the awkward edges: hue on a sector boundary, phase near a strobe edge, pixel
# counts that do and do not divide evenly.
CASES = [
    (cue, hue, brightness, param, now, count)
    for cue in range(0, 12)
    for hue, brightness, param, now, count in (
        (0, 255, 128, 0, 30),
        (85, 200, 0, 137, 30),
        (128, 255, 255, 512, 16),
        (170, 64, 64, 1999, 7),
        (255, 255, 200, 4321, 60),
        (43, 128, 255, 99, 3),
    )
]


@pytest.fixture(scope="session")
def dump_tool() -> Path:
    if shutil.which("make") is None or shutil.which("cc") is None:
        pytest.skip("make/cc not available")
    subprocess.run(["make", "-s"], cwd=CTEST, check=True)
    return CTEST / "build" / "effect_dump"


@pytest.fixture(scope="session")
def node() -> str:
    found = shutil.which("node")
    if found is None:
        pytest.skip("node not available")
    return found


def firmware_pixels(tool: Path, *args: object) -> list[tuple[int, int, int]]:
    result = subprocess.run([str(tool), *(str(a) for a in args)],
                            capture_output=True, check=True, text=True)
    return [tuple(int(v) for v in line.split())
            for line in result.stdout.splitlines() if line.strip()]


def browser_pixels(node: str, script: str) -> list[list[int]]:
    """Runs effects.js in node and returns whatever `script` prints."""
    program = f"""
const fs = require('fs');
const vm = require('vm');
const context = {{console, Math, Uint8ClampedArray, Uint8Array}};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(EFFECTS_JS))}, 'utf8'), context);
vm.runInContext({json.dumps(script)}, context);
"""
    result = subprocess.run([node, "-e", program],
                            capture_output=True, check=True, text=True)
    return json.loads(result.stdout)


def to_triples(flat: list[int]) -> list[tuple[int, int, int]]:
    return [tuple(flat[i:i + 3]) for i in range(0, len(flat), 3)]


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"cue{c[0]}_hue{c[1]}_n{c[5]}")
def test_the_preview_renders_what_the_firmware_renders(dump_tool, node, case):
    cue, hue, brightness, param, now, count = case

    expected = firmware_pixels(dump_tool, cue, hue, brightness, param, now, count)

    # resetRandom keeps the sparkle sequence in step: the C starts from a fresh
    # static seed in every process, so the port has to start there too.
    script = f"""
resetRandom();
const pixels = renderEffect(
  {{cue: {cue}, hue: {hue}, brightness: {brightness}, param: {param}}},
  {now}, {count}, {{max: {MAX_BRIGHTNESS}, gamma: true}});
console.log(JSON.stringify(Array.from(pixels)));
"""
    actual = to_triples(browser_pixels(node, script))

    assert len(actual) == count
    assert actual == expected, (
        f"cue {cue}, hue {hue}, brightness {brightness}, param {param}, "
        f"t={now} ms, {count} Pixel: die Vorschau im Browser weicht von der "
        f"Bordfirmware ab"
    )


@pytest.mark.parametrize("now,count", [(0, 20), (500, 20), (1000, 8), (1750, 40)])
def test_the_failsafe_pulse_matches_too(dump_tool, node, now, count):
    """The amber pulse is what says "this model lost its link" -- it has to look
    the same on screen as in the air, or the preview teaches the wrong colour."""
    expected = firmware_pixels(dump_tool, "failsafe", now, count)

    script = f"""
const pixels = renderFailsafe({now}, {count}, {{max: {MAX_BRIGHTNESS}, gamma: true}});
console.log(JSON.stringify(Array.from(pixels)));
"""
    assert to_triples(browser_pixels(node, script)) == expected


def test_an_unknown_cue_falls_back_to_steady_light(dump_tool, node):
    """Cues 11..31 are reserved. They must show light, not darkness -- a typo in
    the automation must never black out a model in flight."""
    expected = firmware_pixels(dump_tool, 20, 90, 255, 128, 250, 12)
    assert any(any(pixel) for pixel in expected), "Reserve-Cue wurde dunkel"

    script = """
resetRandom();
const pixels = renderEffect({cue: 20, hue: 90, brightness: 255, param: 128},
  250, 12, {max: 200, gamma: true});
console.log(JSON.stringify(Array.from(pixels)));
"""
    assert to_triples(browser_pixels(node, script)) == expected
