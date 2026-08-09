"""MIDI input.

Opens a virtual ALSA sequencer port that Ardour (or any other sequencer) can
connect its tracks to. Messages are delivered on the rtmidi callback thread and
handed straight to the Mapper, which is thread safe.
"""

from __future__ import annotations

from typing import Callable

import mido

from .mapping import Mapper


class MidiInput:
    def __init__(self, name: str, mapper: Mapper,
                 on_message: Callable[[mido.Message], None] | None = None) -> None:
        self.name = name
        self._mapper = mapper
        self._on_message = on_message
        self._port: mido.ports.BaseInput | None = None

    def open(self) -> None:
        # A virtual port shows up in Ardour's routing grid without needing an
        # existing hardware device.
        self._port = mido.open_input(self.name, virtual=True, callback=self._callback)

    def _callback(self, message: mido.Message) -> None:
        if message.type == "control_change":
            self._mapper.handle_control_change(
                message.channel + 1, message.control, message.value
            )
        if self._on_message is not None:
            self._on_message(message)

    def close(self) -> None:
        if self._port is not None:
            self._port.close()
            self._port = None

    def __enter__(self) -> "MidiInput":
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def list_inputs() -> list[str]:
    return list(mido.get_input_names())
