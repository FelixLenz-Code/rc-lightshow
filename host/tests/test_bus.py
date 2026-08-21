"""Verifies bus mode -- the eight light channels as one addressed data frame.

Two things have to hold before a model flies on this. The code must repair
exactly the damage it claims to repair, and the two implementations must agree:
the ground station encodes in Python, the aircraft decodes in C, and there is
no way to renegotiate in the air. So the arithmetic is checked exhaustively
here, and every frame is then pushed through the firmware's own decoder.
"""

from __future__ import annotations

import random
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from lightshow import bus

REPO = Path(__file__).resolve().parents[2]
CTEST = REPO / "tools" / "ctest"


@pytest.fixture(scope="session")
def bus_decoder() -> Path:
    if shutil.which("make") is None or shutil.which("cc") is None:
        pytest.skip("make/cc not available")
    subprocess.run(["make", "-s"], cwd=CTEST, check=True)
    return CTEST / "build" / "bus_decoder"


def ask(binary: Path, lines: list[str]) -> list[str]:
    result = subprocess.run([str(binary)], input="\n".join(lines) + "\n",
                            capture_output=True, text=True, check=True)
    return result.stdout.splitlines()


# ------------------------------------------------------------------- the field


def test_field_is_primitive():
    # Every non zero element exactly once: that is what makes the log table
    # usable at all.
    assert sorted(bus.GF_EXP[:31]) == list(range(1, 32))


def test_multiplication_has_an_inverse():
    for a in range(1, 32):
        for b in range(1, 32):
            assert bus.gf_div(bus.gf_mul(a, b), b) == a


# -------------------------------------------------------------------- the code


def test_clean_codeword_survives():
    data = [1, 2, 3, 4, 5, 6]
    result = bus.decode(bus.encode(data))
    assert result.ok and result.corrected is None and result.data == data


def test_every_single_symbol_error_is_caught():
    """One wrong channel, at every position, with every possible magnitude.

    By default the code detects rather than repairs, so a damaged frame is
    rejected outright -- the aircraft then holds its last good state.
    """
    random.seed(11)
    for _ in range(20):
        data = [random.randrange(32) for _ in range(bus.DATA_SYMBOLS)]
        code = bus.encode(data)
        for position in range(bus.SYMBOLS):
            for magnitude in range(1, 32):
                broken = list(code)
                broken[position] ^= magnitude
                assert not bus.decode(broken).ok, (data, position, magnitude)


def test_the_repair_still_works_when_it_is_asked_for():
    """The correction is not gone, only off by default."""
    random.seed(11)
    for _ in range(20):
        data = [random.randrange(32) for _ in range(bus.DATA_SYMBOLS)]
        code = bus.encode(data)
        for position in range(bus.SYMBOLS):
            for magnitude in range(1, 32):
                broken = list(code)
                broken[position] ^= magnitude
                result = bus.decode(broken, correct=True)
                assert result.ok and result.data == data
                assert result.corrected == position


def test_detecting_is_far_stricter_than_repairing():
    """The number that decided the default.

    Repairing accepts everything within distance one of a code word; detecting
    accepts code words only. Measured against random frames, the difference is
    more than two orders of magnitude -- and foreign frames are exactly what
    this wire carries.
    """
    random.seed(99)
    trials = 20000
    accepted_repair = 0
    accepted_detect = 0
    for _ in range(trials):
        noise = [random.randrange(32) for _ in range(bus.SYMBOLS)]
        if bus.decode(noise, correct=True).ok:
            accepted_repair += 1
        if bus.decode(noise).ok:
            accepted_detect += 1
    # Roughly 249/1024 against 1/1024.
    assert 0.15 < accepted_repair / trials < 0.35
    assert accepted_detect / trials < 0.01
    assert accepted_repair > accepted_detect * 20


def test_two_wrong_symbols_do_not_pass_as_clean():
    """The code cannot repair two, so it must not claim an untouched frame.

    Some double faults are indistinguishable from a single one -- that is a
    property of the code, not a defect. What must never happen is a frame
    reported as clean when it is not.
    """
    random.seed(12)
    undetected = 0
    trials = 400
    for _ in range(trials):
        data = [random.randrange(32) for _ in range(bus.DATA_SYMBOLS)]
        code = bus.encode(data)
        first, second = random.sample(range(bus.SYMBOLS), 2)
        broken = list(code)
        broken[first] ^= random.randrange(1, 32)
        broken[second] ^= random.randrange(1, 32)
        result = bus.decode(broken)
        assert not (result.ok and result.corrected is None and result.data == data) \
            or broken == code
        if result.ok and result.data == data:
            undetected += 1
    # It may mis-repair, but it must not silently pass most of them through.
    assert undetected < trials // 2


# ----------------------------------------------------------------- the payload


def test_address_bits():
    assert bus.address_bits(1) == 0
    assert bus.address_bits(2) == 1
    assert bus.address_bits(4) == 2
    assert bus.address_bits(5) == 3
    assert bus.address_bits(8) == 3


def test_budget_arithmetic():
    # 30 bits of payload: 2 magic, 24 zone state, the rest address and relays.
    assert bus.PAYLOAD_BITS == 30
    assert bus.ZONE_STATE_BITS == 24
    assert bus.MAGIC_BITS == 2
    assert bus.spare_bits(4, 2) == 30 - 2 - 2 - 2 - 24
    assert bus.fits(4, 2)
    assert not bus.fits(4, 3)       # magic + 3 relays + 2 address + 24 is 31
    assert bus.fits(1, 4)           # no address bits, so four relays fit
    assert not bus.fits(9, 0)       # beyond the address space


@pytest.mark.parametrize("zones,relays", [(1, 4), (2, 3), (3, 2), (4, 2),
                                          (6, 1), (8, 1)])
def test_pack_unpack_round_trip(zones, relays):
    random.seed(13)
    for _ in range(200):
        zone = random.randrange(zones)
        state = bus.ZoneState(cue=random.randrange(32), hue=random.randrange(64),
                              brightness=random.randrange(256),
                              param=random.randrange(32))
        switches = [random.random() < 0.5 for _ in range(relays)]
        symbols = bus.pack(zone, state, switches, zones=zones, relays_count=relays)
        assert len(symbols) == bus.DATA_SYMBOLS
        assert all(0 <= s <= 31 for s in symbols)
        assert bus.unpack(symbols, zones=zones, relays_count=relays) == \
            (zone, state, switches)


def test_pack_refuses_what_does_not_fit():
    with pytest.raises(ValueError):
        bus.pack(0, bus.ZoneState(), [True] * 3, zones=4, relays_count=3)
    with pytest.raises(ValueError):
        bus.pack(4, bus.ZoneState(), [], zones=4, relays_count=0)


def test_scaling_reaches_both_ends():
    """A full value must widen back to full, or saturation is unreachable."""
    for bits in (5, 6, 8):
        assert bus.widen(bus.narrow(255, bits), bits) == 255
        assert bus.widen(bus.narrow(0, bits), bits) == 0


# ------------------------------------------------------------- the combinations


def test_combinations_marks_rather_than_hides():
    listed = bus.combinations(35500, limit_ms=150)
    pairs = {(c.zones, c.relays): c for c in listed}
    # Both of the combinations the brief named are present ...
    assert (4, 2) in pairs and (6, 0) in pairs
    # ... but only one of them is inside the latency budget at 35,5 ms.
    assert pairs[(4, 2)].within_budget
    assert not pairs[(6, 0)].within_budget
    assert pairs[(4, 2)].latency_ms == pytest.approx(142.0)


def test_a_shorter_frame_buys_zones():
    """Light on channels 1..8 means 22,5 ms, and six zones fit the budget."""
    pairs = {(c.zones, c.relays): c for c in bus.combinations(22500, limit_ms=150)}
    assert pairs[(6, 0)].within_budget
    assert pairs[(6, 0)].latency_ms == pytest.approx(135.0)


def test_every_listed_combination_actually_fits():
    for combination in bus.combinations(22500):
        assert bus.fits(combination.zones, combination.relays)
        assert combination.spare_bits >= 0


# ------------------------------------------------------ symbols and microseconds


def test_symbol_lands_in_the_middle_of_its_band():
    for symbol in range(32):
        microseconds = bus.symbol_to_us(symbol, 1000, 2000)
        assert bus.us_to_symbol(microseconds, 1000, 2000) == symbol


def test_symbol_survives_half_a_band_of_error():
    """A band is 31,25 us wide, so 15 us either way must still land right.

    The measured worst case on the radio was 13,1 us. That is the whole margin
    this mode has per symbol -- and the reason RS(8,6) is not decoration.
    """
    for symbol in range(32):
        centre = bus.symbol_to_us(symbol, 1000, 2000)
        for error in (-15, -13, 0, 13, 15):
            assert bus.us_to_symbol(centre + error, 1000, 2000) == symbol


def test_symbol_placement_matches_a_cue_step():
    """The wire must not learn a second rounding rule."""
    from lightshow.config import PortCfg, step_us
    port = PortCfg(id=0, name="t", nchan=16, min_us=1000, max_us=2000)
    for symbol in range(32):
        assert bus.symbol_to_us(symbol, 1000, 2000) == step_us(port, 32, symbol)


# ------------------------------------------------------- against the real thing


def test_firmware_decodes_what_python_encodes(bus_decoder):
    random.seed(14)
    cases = []
    lines = []
    for _ in range(400):
        zones = random.choice([1, 2, 3, 4, 6, 8])
        relays = random.randrange(0, bus.PAYLOAD_BITS - bus.ZONE_STATE_BITS
                                  - bus.MAGIC_BITS - bus.address_bits(zones) + 1)
        zone = random.randrange(zones)
        state = bus.ZoneState(cue=random.randrange(32), hue=random.randrange(64),
                              brightness=random.randrange(256),
                              param=random.randrange(32))
        switches = [random.random() < 0.5 for _ in range(relays)]
        wire = bus.frame(zone, state, switches, zones=zones, relays_count=relays)
        cases.append((zones, relays, zone, state, switches))
        lines.append("frame " + " ".join(str(v) for v in
                                         [zones, relays, *wire]))

    out = ask(bus_decoder, lines)
    assert len(out) == len(cases)

    for (zones, relays, zone, state, switches), answer in zip(cases, out):
        assert answer.startswith("ok "), (zones, relays, answer)
        _, got_zone, cue, hue, brightness, param, relay_word, corrected = \
            answer.split()
        expected = state.to_bytes()
        assert int(got_zone) == zone
        assert int(cue) == expected["cue"]
        assert int(hue) == expected["hue"]
        assert int(brightness) == expected["brightness"]
        assert int(param) == expected["param"]
        assert int(corrected) == -1
        for index, on in enumerate(switches):
            assert bool(int(relay_word) & (1 << index)) == on


def test_firmware_rejects_a_broken_channel(bus_decoder):
    """One channel lands anywhere -- the frame is dropped, not guessed at."""
    random.seed(15)
    cases, lines = [], []
    for _ in range(300):
        zones, relays = 4, 2
        zone = random.randrange(zones)
        state = bus.ZoneState(cue=random.randrange(32), hue=random.randrange(64),
                              brightness=random.randrange(256),
                              param=random.randrange(32))
        switches = [random.random() < 0.5 for _ in range(relays)]
        wire = bus.frame(zone, state, switches, zones=zones, relays_count=relays)
        position = random.randrange(bus.SYMBOLS)
        wire[position] = (wire[position] + random.randrange(1, 32)) % 32
        cases.append((zone, state, switches))
        lines.append("frame " + " ".join(str(v) for v in [zones, relays, *wire]))

    out = ask(bus_decoder, lines)
    assert all(answer == "reject" for answer in out), \
        "ein beschaedigter Rahmen darf nicht als gueltig durchgehen"


def test_firmware_rejects_an_impossible_address(bus_decoder):
    """A frame claiming zone 5 of four is not this model's frame."""
    # Build a payload by hand with an address the configuration cannot hold.
    zones, relays = 4, 0
    symbols = bus.pack(3, bus.ZoneState(cue=1), [], zones=8, relays_count=0)
    wire = bus.encode(symbols)
    out = ask(bus_decoder, ["frame " + " ".join(str(v) for v in
                                                [zones, relays, *wire])])
    # Either the address is out of range and it says so, or it decodes to a
    # zone the model has -- what it must never do is invent a fifth zone.
    if out[0] != "reject":
        assert int(out[0].split()[1]) < zones


def bus_show(zones: int = 4, relays: int = 2):
    """A show whose single model runs on the bus, built the way YAML would."""
    from lightshow import config as config_module

    channels = []
    for _ in range(zones):
        channels.append(config_module.ChannelCfg("cue", quantize=32, failsafe=1000))
        channels.append(config_module.ChannelCfg("hue", failsafe=1500))
        channels.append(config_module.ChannelCfg("brightness", failsafe=1000))
        channels.append(config_module.ChannelCfg("param", failsafe=1500))

    model = config_module.ModelCfg(
        name="bus_test", tx_port=0, tx_offset=8,
        channels=channels,
        bus=config_module.BusCfg(
            relays=[config_module.BusRelayCfg(f"r{i}", 100 + i)
                    for i in range(relays)]),
    )
    port = config_module.PortCfg(id=0, name="tx", nchan=16, frame_us=35500)
    return config_module.ShowCfg(ports=[port], models=[model]), model, port


def wire_symbols(values, model, port):
    """The eight channels of a frame, back as symbols the aircraft would read."""
    block = values[model.tx_port][model.tx_offset:model.tx_offset + bus.SYMBOLS]
    return [bus.us_to_symbol(us, port.min_us, port.max_us) for us in block]


def test_a_scheduled_value_reaches_the_firmware_unharmed(bus_decoder):
    """The whole host path: a block on the timeline, decoded zone state out.

    Every other test here checks one link of the chain. This one runs the real
    timeline, puts its frame through the microsecond quantisation the radio
    imposes, and hands the result to the decoder that actually flies.
    """
    from lightshow import project as project_module
    from lightshow import timeline as timeline_module

    show, model, port = bus_show(zones=4, relays=2)
    # Zone 2: cue step 7 of 32, a hue, half brightness, some tempo. The editor
    # works in 0..255 for everything but the cue, which is a step index.
    project = project_module.from_dict({
        "name": "test",
        "light_tracks": [{"model": "bus_test", "zone": 2, "blocks": [
            {"start_s": 0, "duration_s": 10, "cue": 7, "hue": 201,
             "brightness": 129, "param": 201},
        ]}],
        "relay_tracks": [
            {"model": "bus_test", "relay": 0,
             "blocks": [{"start_s": 0, "duration_s": 10}]},
            {"model": "bus_test", "relay": 1, "blocks": []},
        ],
    })
    line = timeline_module.Timeline(show, project)

    # The encoder sends one zone per RC frame, so keep asking until zone 2 flies.
    seen = {}
    for _ in range(40):
        symbols = wire_symbols(line.frame(1.0), model, port)
        answer = ask(bus_decoder, ["frame 4 2 " + " ".join(str(s) for s in symbols)])[0]
        assert answer.startswith("ok "), answer
        parts = answer.split()
        seen[int(parts[1])] = parts
        if len(seen) == 4:
            break
        time.sleep(port.frame_us / 1_000_000.0)

    assert set(seen) == {0, 1, 2, 3}, f"nicht jede Zone kam dran: {sorted(seen)}"

    zone2 = seen[2]
    assert int(zone2[2]) == 7                       # cue step survived exactly
    assert abs(int(zone2[3]) - 201) <= 5            # hue, six bits: 4 per step
    assert abs(int(zone2[4]) - 129) <= 2            # brightness, eight bits
    assert abs(int(zone2[5]) - 201) <= 9            # param, five bits: 8 per step
    assert int(zone2[6]) & 1                        # relay 0 on
    assert not (int(zone2[6]) & 2)                  # relay 1 off

    # Zones nobody addressed hold their failsafe, which is "off".
    assert int(seen[0][2]) == 0


def test_blackout_darkens_every_zone_in_one_frame(bus_decoder):
    """A rotation takes four frames; a blackout may not take four frames."""
    from lightshow.mapping import Mapper

    show, model, port = bus_show(zones=4, relays=2)
    mapper = Mapper(show)
    mapper.set_blackout(True)

    symbols = wire_symbols(mapper.frame(), model, port)
    answer = ask(bus_decoder, ["frame 4 2 " + " ".join(str(s) for s in symbols)])[0]
    assert answer.startswith("ok "), answer
    parts = answer.split()
    # The all-off command, which takes three fields to say.
    assert int(parts[2]) == bus.CUE_ALL_OFF
    assert int(parts[3]) == 255                     # hue at its maximum
    assert int(parts[5]) == 255                     # param at its maximum
    assert int(parts[6]) == 0                       # and no relay survives it


def test_the_failsafe_the_ground_station_holds_is_a_valid_frame(bus_decoder):
    """If the host dies the ground station repeats this for ever -- it has to
    decode, and it has to mean off."""
    show, model, port = bus_show(zones=4, relays=2)
    wire = show.wire_ports()[0]
    block = wire.failsafe[model.tx_offset:model.tx_offset + bus.SYMBOLS]
    symbols = [bus.us_to_symbol(us, port.min_us, port.max_us) for us in block]

    answer = ask(bus_decoder, ["frame 4 2 " + " ".join(str(s) for s in symbols)])[0]
    assert answer.startswith("ok "), answer
    parts = answer.split()
    assert int(parts[2]) == bus.CUE_ALL_OFF
    assert int(parts[3]) == 255                     # hue at its maximum
    assert int(parts[4]) == 0                       # brightness
    assert int(parts[5]) == 255                     # param at its maximum
    assert int(parts[6]) == 0                       # relays


def test_microsecond_conversion_agrees_with_the_firmware(bus_decoder):
    lines, expected = [], []
    for symbol in range(32):
        microseconds = bus.symbol_to_us(symbol, 1000, 2000)
        for error in (-15, -8, 0, 8, 15):
            value = microseconds + error
            lines.append(f"us {value} 1000 2000")
            expected.append(bus.us_to_symbol(value, 1000, 2000))
    out = ask(bus_decoder, lines)
    for answer, want in zip(out, expected):
        assert int(answer.split()[1]) == want


def test_both_sides_agree_on_the_wire_constants(bus_decoder):
    """bus.h owns them, bus.py repeats them -- and there is no way to
    renegotiate once an aircraft is flashed."""
    answer = ask(bus_decoder, ["consts"])[0].split()
    assert int(answer[1]) == bus.SYMBOLS
    assert int(answer[2]) == bus.DATA_SYMBOLS
    assert int(answer[3]) == bus.PAYLOAD_BITS
    assert int(answer[4]) == bus.CUE_ALL_OFF
    assert int(answer[5]) == bus.HUE_ALL_OFF
    assert int(answer[6]) == bus.PARAM_ALL_OFF


def test_a_foreign_frame_cannot_blank_the_model(bus_decoder):
    """Measured on the bench, 17.08.2026.

    When the transmitter drops its trainer input it substitutes its own channel
    values. That fixed pattern decodes as a valid code word -- ten bits of
    parity let roughly one frame in a thousand through, and a *repeating*
    pattern either always passes or never does. This one always did, and its
    payload was cue 31 out of all-zero bits: the model went dark for it.

    Saying "everything off" now takes three fields, so the pattern cannot mean
    it by accident any more.
    """
    # The values the FrSky X14 substituted, in microseconds.
    foreign = [1057, 1941, 1027, 1027, 1027, 1027, 1637, 1362]
    symbols = [bus.us_to_symbol(us, 1000, 2000) for us in foreign]

    # It is a valid code word -- the parity cannot tell it apart, not even with
    # the correction switched off. That is exactly why the magic exists.
    assert bus.decode(symbols).ok, "der Rahmen ist ein gueltiges Codewort"

    # But it does not carry our pattern, so unpacking refuses it ...
    with pytest.raises(bus.ForeignFrame):
        bus.unpack(bus.decode(symbols).data, zones=4, relays_count=2)

    # ... and so does the firmware.
    answer = ask(bus_decoder,
                 ["frame 4 2 " + " ".join(str(s) for s in symbols)])[0]
    assert answer == "reject", answer


def test_the_all_off_command_still_works_when_it_is_meant(bus_decoder):
    state = bus.all_off_state()
    assert bus.is_all_off(state)
    wire = bus.frame(0, state, [False, False], zones=4, relays_count=2)
    parts = ask(bus_decoder, ["frame 4 2 " + " ".join(str(s) for s in wire)])[0].split()
    assert parts[0] == "ok"
    assert int(parts[2]) == bus.CUE_ALL_OFF
    assert int(parts[3]) == 255 and int(parts[5]) == 255
