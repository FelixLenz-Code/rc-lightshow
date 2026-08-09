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
        roles = ", ".join(channel.role for channel in model.channels)
        lines.append(
            f"  model '{model.name}': MIDI ch {model.midi_channel} -> TX{model.tx_port} "
            f"ch{model.tx_offset + 1}..{model.tx_offset + len(model.channels)} ({roles})"
        )
    return "\n".join(lines)


def run(show: config_module.ShowCfg, mapper: Mapper, link: PicoLink, monitor) -> None:
    period = 1.0 / show.rate_hz
    delay_frames = round(show.global_offset_ms / 1000.0 * show.rate_hz)
    history: deque[list[list[int]]] = deque()
    seq = 0

    stopping = False

    def request_stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    next_tick = time.monotonic()
    while not stopping:
        link.poll()

        history.append(mapper.frame())
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

    print(describe(show))
    if args.check:
        print("configuration ok")
        return 0

    from .midi import MidiInput  # imported late so --check works without rtmidi

    mapper = Mapper(show)
    link = PicoLink(show.serial_port, show.wire_ports(), dry_run=args.dry_run)

    use_tui = not args.no_tui and sys.stdout.isatty()
    try:
        with MidiInput(show.midi_port_name, mapper):
            if use_tui:
                def wrapped(screen: "curses._CursesWindow") -> None:
                    run(show, mapper, link, CursesMonitor(screen, show, mapper, link))

                curses.wrapper(wrapped)
            else:
                run(show, mapper, link, PlainMonitor(show, mapper, link))
    except OSError as exc:
        print(f"MIDI error: {exc}", file=sys.stderr)
        return 1
    finally:
        link.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
