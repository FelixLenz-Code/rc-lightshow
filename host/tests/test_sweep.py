"""Verifies the link measurement.

The measurement exists to answer one number: how many bits a channel carries.
That answer decides whether the current 32 cue steps are safe and whether a
denser encoding is worth building, so the arithmetic behind it has to be right
before anyone reads a result off a bench.

Every test here feeds synthetic recordings with a known error and checks that
the report says what it must -- no radio, no hardware.
"""

from __future__ import annotations

import random
import re

import pytest

from lightshow import sweep
from lightshow.config import ChannelCfg, ModelCfg, PortCfg, ShowCfg, step_us


def make_show(min_us: int = 1000, max_us: int = 2000) -> ShowCfg:
    return ShowCfg(
        ports=[PortCfg(id=0, name="tx", nchan=8, min_us=min_us, max_us=max_us)],
        models=[
            ModelCfg("eule", 0, tx_offset=0, channels=[
                ChannelCfg(role="cue", quantize=32, failsafe=min_us),
                ChannelCfg(role="hue", failsafe=1500),
                ChannelCfg(role="brightness", failsafe=min_us),
                ChannelCfg(role="param", failsafe=1500),
            ]),
        ],
    )


def timed(points: list[sweep.Point], dwell: float = 1.0) -> list[sweep.Point]:
    """Gives every point a plausible start and end on the host clock."""
    clock = 100.0
    for point in points:
        point.t_start = clock
        point.t_end = clock + dwell
        clock += dwell
    return points


def recording(points: list[sweep.Point], error, *, per_point: int = 40
              ) -> list[sweep.Sample]:
    """Synthesises what the aircraft would have reported.

    ``error`` returns the deviation in microseconds for one sample.
    """
    samples: list[sweep.Sample] = []
    for point in points:
        span = point.t_end - point.t_start
        for index in range(per_point):
            t = point.t_start + span * (index + 0.5) / per_point
            value = point.intended_us + error(point, index)
            samples.append(sweep.Sample(t, {f"c{point.channel}": round(value)}))
    return samples


# ------------------------------------------------------------------ planning


def test_the_plan_covers_every_cue_step_and_the_whole_range():
    show = make_show()
    points = sweep.plan(show, show.models[0], dwell_s=0.5, ramp_step_us=50)

    steps = [p for p in points if p.phase == "steps"]
    ramp = [p for p in points if p.phase == "ramp"]

    assert len(steps) == 32, "nicht jede Cue-Stufe wird angefahren"
    assert ramp[0].intended_us == 1000 and ramp[-1].intended_us == 2000
    assert steps[0].channel == 1 and ramp[0].channel == 2


def test_the_sweep_sends_exactly_what_a_show_would_send():
    """A sweep with its own encoder would measure the wrong thing."""
    show = make_show()
    model = show.models[0]
    points = [p for p in sweep.plan(show, model) if p.phase == "steps"]
    port = show.port_by_id(model.tx_port)

    for index, point in enumerate(points):
        assert point.intended_us == step_us(port, 32, index)


def test_only_the_channel_under_test_moves():
    """A neighbour moving at the same time would look like crosstalk."""
    show = make_show()
    model = show.models[0]
    points = sweep.plan(show, model)
    frame = sweep.frames_for(show, model, points[5])[0]

    assert frame[0] == points[5].intended_us
    for index, channel in enumerate(model.channels[1:], start=1):
        assert frame[index] == channel.failsafe


# ------------------------------------------------------------------ parsing


def test_a_measurement_line_is_read():
    line = "MEAS ms=12345 seq=678 src=1 c9=1487 c10=1502 c11=1000 c12=1500 step=15"
    sample = sweep.parse_meas(line, 42.0)
    assert sample is not None
    assert sample.t == 42.0
    assert sample.channel_us(9) == 1487
    assert sample.fields["step"] == 15
    assert sample.fields["seq"] == 678


def test_ordinary_console_chatter_is_ignored():
    for line in ("lightshow plane: model=eule zones=1 strips=2 relays=2",
                 "eule src=1 cue=0 hue=128 bri=0 param=128 frames=12",
                 ""):
        assert sweep.parse_meas(line, 1.0) is None


# ----------------------------------------------------------------- analysis


def test_a_perfect_link_reports_the_full_resolution():
    show = make_show()
    points = timed(sweep.plan(show, show.models[0], ramp_step_us=100))
    report = sweep.analyse(points, recording(points, lambda p, i: 0))

    assert report.gaps == 0
    assert report.worst_deviation_us == 0
    assert report.usable_bits(1000) == 8


@pytest.mark.parametrize("jitter,expected", [
    (13, 5),      # what the cross-check assumes today -> 32 steps
    (30, 4),      # a noisier link -> 16 steps
    (5, 6),       # a clean one -> 64 steps
])
def test_the_bit_budget_follows_the_measured_noise(jitter, expected):
    """A step survives only while the value stays inside its own half band."""
    show = make_show()
    points = timed(sweep.plan(show, show.models[0], ramp_step_us=100))
    random.seed(1)
    samples = recording(points, lambda p, i: random.choice((-jitter, jitter)))

    report = sweep.analyse(points, samples)
    assert report.usable_bits(1000) == expected
    assert report.safe_steps(1000) == 2 ** expected


def test_a_constant_offset_does_not_cost_resolution():
    """A fixed shift is correctable, so it must not be counted as noise."""
    show = make_show()
    points = timed(sweep.plan(show, show.models[0], ramp_step_us=100))
    clean = sweep.analyse(points, recording(points, lambda p, i: 0))
    shifted = sweep.analyse(points, recording(points, lambda p, i: 40))

    assert shifted.systematic_us == pytest.approx(40, abs=0.5)
    assert shifted.usable_bits(1000) == clean.usable_bits(1000)


def test_a_dropout_is_reported_rather_than_averaged_away():
    """Silence must never look like a clean measurement."""
    show = make_show()
    points = timed(sweep.plan(show, show.models[0], ramp_step_us=100))
    samples = recording(points, lambda p, i: 0)
    dead = [points[3], points[9]]
    samples = [s for s in samples
               if not any(p.t_start <= s.t <= p.t_end for p in dead)]

    report = sweep.analyse(points, samples)
    assert report.gaps == 2
    assert len(report.measured) == len(points) - 2


def test_the_settling_time_is_left_out():
    """The first moments of a plateau still carry the previous value."""
    show = make_show()
    points = timed(sweep.plan(show, show.models[0], ramp_step_us=100))

    def stale_at_first(point, index):
        return -500 if index < 8 else 0     # a fifth of each plateau is stale

    report = sweep.analyse(points, recording(points, stale_at_first))
    assert report.worst_deviation_us == 0, "der Einschwingteil wurde mitgemessen"


def test_the_frame_rate_is_reported():
    show = make_show()
    points = timed(sweep.plan(show, show.models[0], ramp_step_us=100), dwell=1.0)
    report = sweep.analyse(points, recording(points, lambda p, i: 0, per_point=45))
    assert report.frames_per_second == pytest.approx(45, rel=0.05)


def test_the_report_names_the_answer():
    show = make_show()
    points = timed(sweep.plan(show, show.models[0], ramp_step_us=200))
    random.seed(2)
    report = sweep.analyse(points, recording(points,
                                             lambda p, i: random.choice((-13, 13))))
    text = sweep.format_report(report, 1000)

    assert "5 Bit je Kanal" in text
    assert "32 Stufen" in text
    assert "Frames am Modell" in text


def test_an_empty_recording_says_so_instead_of_pretending():
    show = make_show()
    points = timed(sweep.plan(show, show.models[0]))
    text = sweep.format_report(sweep.analyse(points, []), 1000)
    assert "Keine Messwerte" in text
    assert "MEASURE" in text


# ------------------------------------------------------------- round trip


def test_a_recording_survives_being_written_and_read(tmp_path):
    show = make_show()
    points = timed(sweep.plan(show, show.models[0], ramp_step_us=250))
    path = sweep.write_sweep(points, tmp_path / "sweep.csv")

    again = sweep.read_sweep(path)
    assert len(again) == len(points)
    assert [p.intended_us for p in again] == [p.intended_us for p in points]
    assert again[0].t_start == pytest.approx(points[0].t_start)


def test_a_console_recording_survives_being_read(tmp_path):
    path = tmp_path / "meas.csv"
    path.write_text(
        "t,line\n"
        "100.5,MEAS ms=1 seq=1 src=1 c1=1015 c2=1500 c3=1000 c4=1500 step=0\n"
        "100.6,lightshow plane: model=eule\n"
        "100.7,MEAS ms=23 seq=2 src=1 c1=1047 c2=1500 c3=1000 c4=1500 step=1\n"
    )
    samples = sweep.read_capture(path)
    assert len(samples) == 2, "die Statuszeile wurde nicht aussortiert"
    assert samples[0].channel_us(1) == 1015
    assert samples[1].fields["step"] == 1


# ------------------------------------------------- against the real firmware


FIRMWARE_MAIN = (
    __import__("pathlib").Path(__file__).resolve().parents[2]
    / "firmware" / "plane" / "src" / "main.c"
)


def measure_format() -> str:
    """The MEAS format string as it stands in the airborne firmware."""
    text = FIRMWARE_MAIN.read_text()
    start = text.index('"MEAS ')
    end = text.index('\\n"', start) + len('\\n"')
    # A C string literal may be split across lines; join the pieces.
    pieces = re.findall(r'"([^"]*)"', text[start:end])
    return "".join(pieces)


def test_the_parser_understands_what_the_firmware_prints():
    """The firmware prints it, the bridge parses it -- two files, one format.

    Nothing links them, so a changed printf would simply stop being understood
    and every measurement would come out empty. This is the seam.
    """
    fmt = measure_format()
    assert fmt.startswith("MEAS "), fmt

    # Fill the conversions in order with values a real frame would carry.
    values = iter([12345, 678, 1, 9, 1487, 10, 1502, 11, 1000, 12, 1500, 15])
    line = re.sub(r"%l?[uid]", lambda _: str(next(values)), fmt).strip()

    sample = sweep.parse_meas(line, 1.0)
    assert sample is not None, f"der Parser versteht die Zeile nicht: {line!r}"
    assert sample.channel_us(9) == 1487
    assert sample.channel_us(12) == 1500
    assert sample.fields["step"] == 15
    assert sample.fields["seq"] == 678


def test_the_firmware_only_prints_on_a_new_frame():
    """A held value must not look like fresh reception.

    The receiver repeats its last frame when the link drops. Printing every
    render pass instead of every RC frame would turn a dropout into a clean
    measurement -- the one error this whole exercise cannot survive.
    """
    text = FIRMWARE_MAIN.read_text()
    assert "rc.frames != last_frames" in text, \
        "die MEAS-Ausgabe hängt nicht mehr am Frame-Zähler"


def two_model_show() -> ShowCfg:
    """Two aircraft, two transmitters -- the normal case, and the risky one.

    Channel numbers are counted per transmitter, so both models own a channel 1.
    """
    channels = lambda: [                                        # noqa: E731
        ChannelCfg(role="cue", quantize=32, failsafe=1000),
        ChannelCfg(role="hue", failsafe=1500),
        ChannelCfg(role="brightness", failsafe=1000),
        ChannelCfg(role="param", failsafe=1500),
    ]
    return ShowCfg(
        ports=[PortCfg(id=0, name="eule_tx", nchan=8),
               PortCfg(id=1, name="falke_tx", nchan=8)],
        models=[ModelCfg("eule", 0, tx_offset=0, channels=channels()),
                ModelCfg("falke", 1, tx_offset=0, channels=channels())],
    )


def test_the_other_aircraft_holds_its_failsafe_during_a_sweep():
    """Its transmitter used to follow along, because channel 1 exists twice."""
    show = two_model_show()
    eule, falke = show.models
    point = next(p for p in sweep.plan(show, eule) if p.phase == "steps")
    frames = sweep.frames_for(show, eule, point)

    assert frames[eule.tx_port][0] == point.intended_us
    assert frames[falke.tx_port][0] == falke.channels[0].failsafe
    assert frames[falke.tx_port][:4] == [c.failsafe for c in falke.channels]
