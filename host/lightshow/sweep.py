"""Measuring what the radio link really does to a channel.

Everything about the show sits on one unverified number: how far a channel value
drifts on its way from the bridge to the aircraft. The whole design -- 32 cue
steps, quantisation to the middle of a band, the idea of encoding more than one
value per channel -- stands or falls with it. Until now it has been a test
parameter (+/-13 us), not a measurement.

This module turns it into a measurement, in three parts:

  sweep    drives a model's channels through known values and records what was
           sent, using the same encoder a real show uses
  capture  reads the aircraft's debug console and stamps every line with the
           host clock, which is what makes the two recordings comparable
  analyse  lays them on top of each other and answers the only question that
           matters: how many bits does a channel actually carry

Run the sweep over the air and compare against what the ground station was
told to send. The difference between the two is the radio.
"""

from __future__ import annotations

import csv
import math
import re
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import ModelCfg, PortCfg, ShowCfg, level_us, step_us

# Held long enough that a plateau is unmistakable even with a slow link, and
# short enough that a full run stays under two minutes.
DEFAULT_DWELL_S = 1.0

# The aircraft needs a moment to follow, and a plateau's edges are where a
# transition would land. Only the settled middle is measured.
SETTLE_FRACTION = 0.3


@dataclass
class Point:
    """One held value: what was sent, when, and on which channel."""

    phase: str              # "steps" or "ramp"
    channel: int            # 1-based, as the transmitter counts
    intended_us: int
    label: str              # step index, or the target microseconds
    t_start: float = 0.0
    t_end: float = 0.0


def plan(show: ShowCfg, model: ModelCfg, *, zone: int = 0,
         dwell_s: float = DEFAULT_DWELL_S, ramp_step_us: int = 10) -> list[Point]:
    """The list of values a run walks through.

    Two phases, because they answer two different questions. The *steps* phase
    drives the cue channel through every one of its quantisation steps and asks
    "does today's design survive". The *ramp* phase walks a continuous channel
    across the whole range in fine increments and asks "how far off is a
    microsecond value, really" -- and that answer holds for any future encoding,
    not just the current one.
    """
    port = show.port_by_id(model.tx_port)
    base = model.zone_base_channel(zone)
    channels = model.channels[zone * 4:zone * 4 + 4]
    if len(channels) < 4:
        raise ValueError(f"Modell '{model.name}' hat keine Zone {zone}")

    points: list[Point] = []

    cue = channels[0]
    steps = cue.quantize or 32
    for index in range(steps):
        points.append(Point("steps", base, step_us(port, steps, index), str(index)))

    # The second channel of a zone is the hue, which is continuous.
    for microseconds in range(port.min_us, port.max_us + 1, ramp_step_us):
        points.append(Point("ramp", base + 1, microseconds, str(microseconds)))

    for point in points:
        point.dwell_s = dwell_s                     # noqa: B010 - carried along
    return points


def frames_for(show: ShowCfg, model: ModelCfg, point: Point) -> list[list[int]]:
    """A full transmitter frame with one channel of one model set to the point.

    Everything else holds its failsafe, so nothing but the channel under test
    moves -- a neighbour changing at the same time would be indistinguishable
    from crosstalk. That has to include the *other* aircraft: channel numbers
    are per transmitter, so writing the value wherever the number fits would
    also drive the same channel on every other model's transmitter, and a second
    aircraft would visibly follow the measurement.
    """
    values = [[port.min_us] * port.nchan for port in show.ports]
    for other in show.models:
        for offset, channel in enumerate(other.channels):
            values[other.tx_port][other.tx_offset + offset] = channel.failsafe

    first = model.tx_offset + 1
    last = model.tx_offset + len(model.channels)
    if first <= point.channel <= last:
        values[model.tx_port][point.channel - 1] = point.intended_us
    return values


def run(show: ShowCfg, model: ModelCfg, link, points: list[Point], *,
        rate_hz: int = 100, log: Path | None = None,
        progress=None) -> list[Point]:
    """Sends every point for its dwell time, recording host timestamps."""
    period = 1.0 / rate_hz
    seq = 0

    for index, point in enumerate(points):
        frame = frames_for(show, model, point)
        point.t_start = time.monotonic()
        deadline = point.t_start + getattr(point, "dwell_s", DEFAULT_DWELL_S)
        while time.monotonic() < deadline:
            link.poll()
            seq = (seq + 1) & 0xFF
            link.send(seq, frame)
            time.sleep(period)
        point.t_end = time.monotonic()
        if progress:
            progress(index + 1, len(points), point)

    if log is not None:
        write_sweep(points, log)
    return points


def write_sweep(points: list[Point], path: Path) -> Path:
    path = Path(path)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["phase", "channel", "intended_us", "label",
                         "t_start", "t_end"])
        for point in points:
            writer.writerow([point.phase, point.channel, point.intended_us,
                             point.label, f"{point.t_start:.4f}",
                             f"{point.t_end:.4f}"])
    return path


def read_sweep(path: Path) -> list[Point]:
    out = []
    with Path(path).open(newline="") as handle:
        for row in csv.DictReader(handle):
            point = Point(row["phase"], int(row["channel"]), int(row["intended_us"]),
                          row["label"], float(row["t_start"]), float(row["t_end"]))
            out.append(point)
    return out


# ------------------------------------------------------------------- capture


# What the measurement build of the airborne firmware prints per RC frame:
#   MEAS ms=12345 seq=678 src=1 c9=1487 c10=1502 c11=1000 c12=1500 step=15
MEAS_LINE = re.compile(r"\bMEAS\b(?P<body>.*)")
FIELD = re.compile(r"(\w+)=(-?\d+)")


@dataclass
class Sample:
    t: float                       # host clock, from the capture
    fields: dict[str, int] = field(default_factory=dict)

    def channel_us(self, channel: int) -> int | None:
        return self.fields.get(f"c{channel}")


def parse_meas(line: str, t: float) -> Sample | None:
    match = MEAS_LINE.search(line)
    if match is None:
        return None
    fields = {key: int(value) for key, value in FIELD.findall(match.group("body"))}
    return Sample(t, fields) if fields else None


def capture(device: str, path: Path, *, baud: int = 115200,
            seconds: float | None = None, echo=None) -> Path:
    """Records the aircraft's console, stamping each line with the host clock.

    The aircraft counts milliseconds since its own boot and the bridge counts
    from its own start; neither can be compared with the other. Stamping here,
    on the machine that also ran the sweep, is what ties the two recordings
    together.
    """
    import serial

    path = Path(path)
    deadline = None if seconds is None else time.monotonic() + seconds

    with serial.Serial(device, baudrate=baud, timeout=0.2) as port, \
            path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["t", "line"])
        buffer = b""
        while deadline is None or time.monotonic() < deadline:
            chunk = port.read(256)
            if not chunk:
                continue
            buffer += chunk
            while b"\n" in buffer:
                raw, _, buffer = buffer.partition(b"\n")
                text = raw.decode("utf-8", "replace").strip()
                if not text:
                    continue
                stamp = time.monotonic()
                writer.writerow([f"{stamp:.4f}", text])
                handle.flush()
                if echo:
                    echo(text)
    return path


def read_capture(path: Path) -> list[Sample]:
    out = []
    with Path(path).open(newline="") as handle:
        for row in csv.DictReader(handle):
            sample = parse_meas(row["line"], float(row["t"]))
            if sample is not None:
                out.append(sample)
    return out


# ------------------------------------------------------------------ analysis


@dataclass
class Result:
    point: Point
    samples: int
    mean_us: float
    min_us: int
    max_us: int
    error_us: float                # mean minus intended: the systematic part
    spread_us: int                 # max minus min: the random part
    worst_us: float                # largest deviation of any single sample

    @property
    def ok(self) -> bool:
        return self.samples > 0


@dataclass
class Report:
    results: list[Result]
    frames_per_second: float
    gaps: int                      # plateaus that received nothing at all

    @property
    def measured(self) -> list[Result]:
        return [r for r in self.results if r.ok]

    @property
    def worst_deviation_us(self) -> float:
        return max((r.worst_us for r in self.measured), default=0.0)

    @property
    def systematic_us(self) -> float:
        """Mean error across all points -- a constant offset, correctable."""
        errors = [r.error_us for r in self.measured]
        return statistics.fmean(errors) if errors else 0.0

    def usable_bits(self, span_us: int) -> int:
        """How many bits a channel carries, given what was measured.

        A step survives when it is wider than twice the worst deviation: the
        value has to stay inside its own half band. The systematic part is taken
        out first, because a constant offset can simply be subtracted -- what is
        left is the noise that cannot.
        """
        residual = max(
            (abs(r.worst_us - self.systematic_us) for r in self.measured),
            default=0.0)
        if residual <= 0:
            return 8                                # cleaner than we can resolve
        steps = span_us / (2.0 * residual)
        return max(0, min(8, int(math.floor(math.log2(steps))))) if steps >= 1 else 0

    def safe_steps(self, span_us: int) -> int:
        return 2 ** self.usable_bits(span_us)


def analyse(points: list[Point], samples: list[Sample], *,
            settle: float = SETTLE_FRACTION) -> Report:
    """Lays the two recordings on top of each other."""
    results: list[Result] = []
    gaps = 0

    for point in points:
        length = point.t_end - point.t_start
        start = point.t_start + length * settle
        window = [s for s in samples if start <= s.t <= point.t_end]
        values = [s.channel_us(point.channel) for s in window]
        values = [v for v in values if v is not None]

        if not values:
            gaps += 1
            results.append(Result(point, 0, 0.0, 0, 0, 0.0, 0, 0.0))
            continue

        mean = statistics.fmean(values)
        results.append(Result(
            point=point,
            samples=len(values),
            mean_us=mean,
            min_us=min(values),
            max_us=max(values),
            error_us=mean - point.intended_us,
            spread_us=max(values) - min(values),
            worst_us=max(abs(v - point.intended_us) for v in values),
        ))

    span = (points[-1].t_end - points[0].t_start) if points else 0.0
    rate = len(samples) / span if span > 0 else 0.0
    return Report(results, rate, gaps)


def format_report(report: Report, span_us: int) -> str:
    """The table the measurement exists to produce."""
    lines: list[str] = []
    measured = report.measured

    if not measured:
        return ("Keine Messwerte. Kam etwas auf der Konsole an? "
                "Ist der Messmodus geflasht (-DMEASURE=1)?")

    for phase in ("steps", "ramp"):
        rows = [r for r in measured if r.point.phase == phase]
        if not rows:
            continue
        title = {"steps": "Cue-Stufen", "ramp": "Feiner Durchlauf"}[phase]
        lines.append(f"\n{title} — {len(rows)} Punkte")
        lines.append(f"{'soll':>8} {'ist':>9} {'Fehler':>8} {'Streuung':>9} "
                     f"{'schlimmster':>12} {'n':>5}")
        for result in rows:
            lines.append(
                f"{result.point.intended_us:>8} {result.mean_us:>9.1f} "
                f"{result.error_us:>+8.1f} {result.spread_us:>9} "
                f"{result.worst_us:>12.1f} {result.samples:>5}"
            )

    bits = report.usable_bits(span_us)
    lines.append("")
    lines.append(f"Frames am Modell:      {report.frames_per_second:.1f}/s")
    if report.gaps:
        lines.append(f"Punkte ohne Empfang:   {report.gaps}  <-- Aussetzer!")
    lines.append(f"Systematischer Versatz: {report.systematic_us:+.1f} us "
                 f"(konstant, herausrechenbar)")
    lines.append(f"Schlimmste Abweichung:  {report.worst_deviation_us:.1f} us")
    lines.append("")
    lines.append(f"=> sicher sind {bits} Bit je Kanal "
                 f"({report.safe_steps(span_us)} Stufen)")

    if bits >= 6:
        lines.append("   Das trägt den Bus-Modus mit voller Breite.")
    elif bits == 5:
        lines.append("   Genau das, womit heute gerechnet wird — der Bus-Modus")
        lines.append("   rechnet sich wie vorgerechnet.")
    else:
        lines.append("   Weniger als angenommen. Erst die Ursache suchen:")
        lines.append("   Masse gemeinsam? Pegel ausreichend? polarity richtig?")
    return "\n".join(lines)


def baseline_note(port: PortCfg) -> str:
    return (f"Kanalhub {port.max_us - port.min_us} us "
            f"({port.min_us}..{port.max_us})")
