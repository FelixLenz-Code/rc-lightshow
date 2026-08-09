"""Terminal monitor: channel bars, link state and firmware status lines."""

from __future__ import annotations

import curses
import time

from .config import ShowCfg
from .link import PicoLink
from .mapping import Mapper

BAR_WIDTH = 20


def _bar(value_us: int, min_us: int, max_us: int) -> str:
    span = max(1, max_us - min_us)
    filled = round(BAR_WIDTH * (value_us - min_us) / span)
    filled = max(0, min(BAR_WIDTH, filled))
    return "#" * filled + "-" * (BAR_WIDTH - filled)


class CursesMonitor:
    """Returns 'quit' or 'blackout' from poll_key(), None otherwise."""

    def __init__(self, screen: "curses._CursesWindow", show: ShowCfg,
                 mapper: Mapper, link: PicoLink) -> None:
        self.screen = screen
        self.show = show
        self.mapper = mapper
        self.link = link
        self._last_draw = 0.0

        curses.curs_set(0)
        screen.nodelay(True)

    def poll_key(self) -> str | None:
        try:
            key = self.screen.getch()
        except curses.error:
            return None
        if key in (ord("q"), ord("Q")):
            return "quit"
        if key in (ord("b"), ord("B")):
            return "blackout"
        return None

    def draw(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_draw < 0.05:
            return
        self._last_draw = now

        blackout, messages, slots = self.mapper.snapshot()
        screen = self.screen
        height, width = screen.getmaxyx()
        screen.erase()

        if self.link.dry_run:
            link_text = "dry-run"
        elif self.link.connected:
            link_text = f"{self.link.device} ok"
        else:
            link_text = f"{self.link.device} DOWN ({self.link.last_error or 'not open'})"

        rows: list[tuple[str, int]] = [
            (
                f" lightshow   midi:{self.show.midi_port_name}   link:{link_text}"
                f"   {self.show.rate_hz} Hz   frames:{self.link.frames_sent}"
                f"   midi msgs:{messages}",
                curses.A_REVERSE,
            ),
            ("", 0),
        ]

        current_model = None
        for slot, value_us in slots:
            if slot.model is not current_model:
                current_model = slot.model
                rows.append(
                    (
                        f" {slot.model.name}  (MIDI ch {slot.model.midi_channel} "
                        f"-> TX{slot.model.tx_port})",
                        curses.A_BOLD,
                    )
                )
            bar = _bar(value_us, slot.port.min_us, slot.port.max_us)
            extra = ""
            if slot.channel.quantize:
                span = max(1, slot.port.max_us - slot.port.min_us)
                step = min(
                    slot.channel.quantize - 1,
                    int((value_us - slot.port.min_us) * slot.channel.quantize / span),
                )
                extra = f" step {step}/{slot.channel.quantize - 1}"
            elif slot.raw is None:
                extra = " (failsafe)"
            rows.append(
                (
                    f"   ch{slot.port_index + 1:<2} {slot.channel.role:<12}"
                    f" cc{slot.channel.cc:<4}{value_us:5d} us [{bar}]{extra}",
                    0,
                )
            )

        rows.append(("", 0))
        rows.append(
            (
                " *** BLACKOUT ***" if blackout else " running",
                curses.A_REVERSE if blackout else 0,
            )
        )
        for line in list(self.link.status_lines)[-3:]:
            rows.append((f"   {line}", curses.A_DIM))
        rows.append((" [b] blackout   [q] quit", curses.A_DIM))

        for index, (text, attr) in enumerate(rows):
            if index >= height:
                break
            try:
                screen.addnstr(index, 0, text.ljust(width - 1)[: width - 1], width - 1, attr)
            except curses.error:
                pass
        screen.refresh()


class PlainMonitor:
    """Fallback for non-interactive terminals: one summary line per second."""

    def __init__(self, show: ShowCfg, mapper: Mapper, link: PicoLink) -> None:
        self.show = show
        self.mapper = mapper
        self.link = link
        self._last = 0.0

    def poll_key(self) -> str | None:
        return None

    def draw(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last < 1.0:
            return
        self._last = now

        blackout, messages, slots = self.mapper.snapshot()
        values = " ".join(
            f"{slot.model.name}.{slot.channel.role}={value}" for slot, value in slots
        )
        state = "BLACKOUT" if blackout else ("ok" if self.link.connected else "link down")
        print(f"[{state}] frames={self.link.frames_sent} midi={messages} {values}", flush=True)
