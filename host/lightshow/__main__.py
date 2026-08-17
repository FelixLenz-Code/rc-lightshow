"""Entry point: MIDI in, RC channel frames out.

    python -m lightshow --config config/show.yaml
    python -m lightshow --dry-run          # no hardware needed
    python -m lightshow --check            # validate the configuration and exit
"""

from __future__ import annotations

import argparse
import curses
import signal
import sys
import time
from collections import deque
from pathlib import Path

from . import config as config_module
from .link import PicoLink
from .mapping import Mapper
from .monitor import CursesMonitor, PlainMonitor

DEFAULT_CONFIG = Path("config/show.yaml")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="lightshow", description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help=f"show configuration (default: {DEFAULT_CONFIG})")
    parser.add_argument("--serial-port", help="override serial_port from the config")
    parser.add_argument("--dry-run", action="store_true",
                        help="do not open the serial port, just show what would be sent")
    parser.add_argument("--no-tui", action="store_true", help="plain line output")
    parser.add_argument("--check", action="store_true",
                        help="validate the configuration and exit")
    parser.add_argument("--list-midi", action="store_true",
                        help="list available MIDI inputs and exit")
    parser.add_argument("--no-web", action="store_true",
                        help="do not start the web interface")
    parser.add_argument("--web-port", type=int, default=8765,
                        help="port for the web interface (default: 8765)")
    parser.add_argument("--web-host", default="127.0.0.1",
                        help="bind address; 0.0.0.0 opens it to the network "
                             "so a phone can reach it (default: 127.0.0.1)")
    parser.add_argument("--generate", metavar="MODEL",
                        help="write the airborne config.h for a model and exit")

    measure = parser.add_argument_group(
        "link measurement",
        "Characterises what the radio does to a channel. See docs/funkstrecke-messen.md")
    measure.add_argument("--sweep", metavar="MODEL",
                         help="drive a model through known values and record them")
    measure.add_argument("--sweep-zone", type=int, default=0,
                         help="which zone of the model to sweep (default: 0)")
    measure.add_argument("--sweep-dwell", type=float, default=1.0,
                         help="seconds to hold each value (default: 1.0)")
    measure.add_argument("--sweep-log", type=Path, default=Path("sweep.csv"),
                         help="where to record what was sent")
    measure.add_argument("--plane-port", metavar="DEVICE",
                         help="serial port of the aircraft's console, recorded "
                              "alongside the sweep on the same clock")
    measure.add_argument("--plane-log", type=Path, default=Path("meas.csv"),
                         help="where to record what the aircraft saw")
    measure.add_argument("--analyse", nargs=2, metavar=("SWEEP", "MEAS"),
                         help="evaluate two recordings and print the result")
    return parser.parse_args(argv)


def describe(show: config_module.ShowCfg) -> str:
    lines = [f"MIDI port '{show.midi_port_name}', {show.rate_hz} Hz, "
             f"serial {show.serial_port}"]
    if show.global_offset_ms:
        lines.append(f"light delayed by {show.global_offset_ms} ms")
    for port in show.ports:
        lines.append(
            f"  TX{port.id} '{port.name}': {port.format} {port.polarity}, "
            f"{port.nchan} ch, frame {port.frame_us} us, {port.min_us}..{port.max_us} us"
        )
    for model in show.models:
        first = model.tx_offset + 1
        last = model.tx_offset + model.wire_channels
        if model.uses_bus:
            # The channel list is zone values, not wire channels -- printing its
            # length as a channel range would name channels the port has not got.
            lines.append(
                f"  model '{model.name}': MIDI ch {model.midi_channel} -> "
                f"TX{model.tx_port} ch{first}..{last}, Bus mit "
                f"{model.zone_count} Zone(n) und {model.bus.relay_count} Relais"
            )
        else:
            roles = ", ".join(channel.role for channel in model.channels)
            lines.append(
                f"  model '{model.name}': MIDI ch {model.midi_channel} -> "
                f"TX{model.tx_port} ch{first}..{last} ({roles})"
            )
    return "\n".join(lines)


def run(show: config_module.ShowCfg, mapper: Mapper, link: PicoLink, monitor,
        session=None) -> None:
    period = 1.0 / show.rate_hz
    delay_frames = round(show.global_offset_ms / 1000.0 * show.rate_hz)
    history: deque[list[list[int]]] = deque()
    seq = 0
    # With a project loaded the values come from its timeline while the
    # transport runs, and from MIDI the rest of the time.
    source = session.frame if session is not None else mapper.frame

    stopping = False

    def request_stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    next_tick = time.monotonic()
    while not stopping:
        link.poll()

        history.append(source())
        if len(history) > delay_frames:
            seq = (seq + 1) & 0xFF
            link.send(seq, history.popleft())

        action = monitor.poll_key()
        if action == "quit":
            break
        if action == "blackout":
            mapper.set_blackout(not mapper.blackout)
        monitor.draw()

        next_tick += period
        sleep = next_tick - time.monotonic()
        if sleep > 0:
            time.sleep(sleep)
        else:
            # Fell behind (e.g. the machine was busy) -- give up on catching up
            # rather than sending a burst of stale frames.
            next_tick = time.monotonic()

    # Leave the field dark: hold the failsafe values for a few frames so they
    # definitely make it out before the port closes.
    mapper.set_blackout(True)
    for _ in range(5):
        seq = (seq + 1) & 0xFF
        link.send(seq, mapper.frame())
        time.sleep(period)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list_midi:
        from .midi import list_inputs

        for name in list_inputs():
            print(name)
        return 0

    try:
        show = config_module.load(args.config)
    except config_module.ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"cannot read {args.config}: {exc}", file=sys.stderr)
        return 2

    if args.serial_port:
        show.serial_port = args.serial_port

    if args.analyse:
        return run_analysis(show, Path(args.analyse[0]), Path(args.analyse[1]))

    if args.generate:
        return generate_plane_header(show, args.config, args.generate)

    if args.sweep:
        return run_sweep(show, args)

    print(describe(show))
    if args.check:
        print("configuration ok")
        return 0

    from .midi import MidiInput  # imported late so --check works without rtmidi

    mapper = Mapper(show)
    link = PicoLink(show.serial_port, show.wire_ports(), dry_run=args.dry_run)

    from .session import PROJECTS_DIR, Session

    root = repo_root(args.config)
    session = Session(show, mapper, link, projects_root=root / PROJECTS_DIR)

    web = None
    if not args.no_web:
        from .webui import Server

        web = Server(show, mapper, link, config_path=args.config,
                     repo_root=root, session=session,
                     host=args.web_host, port=args.web_port)
        try:
            print(f"web interface: {web.start()}")
        except OSError as exc:
            print(f"web interface not started: {exc}", file=sys.stderr)
            web = None

    use_tui = not args.no_tui and sys.stdout.isatty()
    try:
        with MidiInput(show.midi_port_name, mapper):
            if use_tui:
                def wrapped(screen: "curses._CursesWindow") -> None:
                    run(show, mapper, link,
                        CursesMonitor(screen, show, mapper, link, session), session)

                curses.wrapper(wrapped)
            else:
                run(show, mapper, link, PlainMonitor(show, mapper, link, session), session)
    except OSError as exc:
        print(f"MIDI error: {exc}", file=sys.stderr)
        return 1
    finally:
        if web is not None:
            web.stop()
        session.close_project()      # hand the audio device back
        link.close()

    return 0


def run_sweep(show: config_module.ShowCfg, args: argparse.Namespace) -> int:
    """Drives known values out and records what the aircraft made of them."""
    import threading

    from . import sweep as sweep_module
    from .link import PicoLink

    model = next((m for m in show.models if m.name == args.sweep), None)
    if model is None:
        available = ", ".join(m.name for m in show.models)
        print(f"no model '{args.sweep}' -- available: {available}", file=sys.stderr)
        return 2

    try:
        points = sweep_module.plan(show, model, zone=args.sweep_zone,
                                   dwell_s=args.sweep_dwell)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    port = show.port_by_id(model.tx_port)
    total_s = sum(getattr(p, "dwell_s", 1.0) for p in points)
    print(f"Sweep '{model.name}' Zone {args.sweep_zone}: {len(points)} Punkte, "
          f"{total_s:.0f} s, {sweep_module.baseline_note(port)}")

    link = PicoLink(show.serial_port, show.wire_ports(), dry_run=args.dry_run)
    capture_thread = None
    if args.plane_port:
        print(f"Konsole des Modells: {args.plane_port} -> {args.plane_log}")
        capture_thread = threading.Thread(
            target=sweep_module.capture, daemon=True,
            args=(args.plane_port, args.plane_log),
            kwargs={"seconds": total_s + 3.0})
        capture_thread.start()
        time.sleep(0.5)             # let the port settle before the first value
    else:
        print("Kein --plane-port angegeben: es wird nur aufgezeichnet, was "
              "gesendet wurde.")

    def progress(done: int, count: int, point) -> None:
        print(f"\r  {done:>4}/{count}  {point.phase:<6} "
              f"{point.intended_us:>5} us  ", end="", flush=True)

    try:
        sweep_module.run(show, model, link, points, rate_hz=show.rate_hz,
                         log=args.sweep_log, progress=progress)
    finally:
        link.close()
    print(f"\nGesendetes aufgezeichnet: {args.sweep_log}")

    if capture_thread is not None:
        capture_thread.join(timeout=5.0)
        return run_analysis(show, args.sweep_log, args.plane_log)
    return 0


def run_analysis(show: config_module.ShowCfg, sweep_log: Path,
                 plane_log: Path) -> int:
    from . import sweep as sweep_module

    try:
        points = sweep_module.read_sweep(sweep_log)
        samples = sweep_module.read_capture(plane_log)
    except OSError as exc:
        print(f"cannot read the recordings: {exc}", file=sys.stderr)
        return 2

    print(f"{len(points)} gesendete Punkte, {len(samples)} Messzeilen")
    report = sweep_module.analyse(points, samples)
    span = show.ports[0].max_us - show.ports[0].min_us
    print(sweep_module.format_report(report, span))
    return 0


def repo_root(config_path: Path) -> Path:
    """Walks up from the configuration until the repository root shows up."""
    for candidate in [Path.cwd(), *Path(config_path).resolve().parents]:
        if (candidate / "firmware").is_dir() and (candidate / "host").is_dir():
            return candidate
    return Path.cwd()


def generate_plane_header(show: config_module.ShowCfg, config_path: Path,
                          name: str) -> int:
    from . import planegen

    model = next((m for m in show.models if m.name == name), None)
    if model is None:
        available = ", ".join(m.name for m in show.models)
        print(f"no model '{name}' -- available: {available}", file=sys.stderr)
        return 2
    if model.plane is None:
        print(f"model '{name}' has no 'plane' section in the configuration",
              file=sys.stderr)
        return 2

    target = repo_root(config_path) / "firmware" / "plane" / "generated" / f"{name}.h"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(planegen.generate(show, model))
    print(f"wrote {target}")
    print(f"cmake -S firmware/plane -B build/plane-{name} "
          f"-DPLANE_CONFIG=generated/{name}.h")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
