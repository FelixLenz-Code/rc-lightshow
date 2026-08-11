"""Verifies the serial link's reconnect behaviour.

The interesting part is not sending -- that is covered by test_protocol -- but
who owns the device node. The sending loop reopens the port on its own a hundred
times a second, and flashing the ground station needs it free for long enough to
open it at 1200 baud. Those two have to be told apart.
"""

from __future__ import annotations

import time
import types

import pytest

from lightshow import link as link_module
from lightshow.config import ChannelCfg, ModelCfg, PortCfg, ShowCfg


class FakeSerial:
    """Counts how often the port was opened, which is what the tests are about."""

    opened = 0

    def __init__(self, *args, **kwargs) -> None:
        FakeSerial.opened += 1
        self.in_waiting = 0
        self.closed = False

    def write(self, data):
        return len(data)

    def read(self, count):
        return b""

    def close(self):
        self.closed = True


@pytest.fixture
def wire_ports():
    show = ShowCfg(
        ports=[PortCfg(id=0, name="tx", nchan=8)],
        models=[ModelCfg("eule", 1, 0, channels=[
            ChannelCfg(role="cue", cc=20, quantize=32, failsafe=1000),
        ])],
    )
    return show.wire_ports()


@pytest.fixture
def link(monkeypatch, wire_ports):
    FakeSerial.opened = 0
    monkeypatch.setattr(link_module, "serial",
                        types.SimpleNamespace(Serial=FakeSerial,
                                              SerialException=OSError))
    connection = link_module.PicoLink("/dev/fake", wire_ports)
    connection.poll()
    assert connection.connected
    return connection


def settled(connection) -> None:
    """As if the bridge had been running for a while, not just started."""
    connection._next_attempt = time.monotonic() - 60


def test_a_dropped_port_is_picked_up_again(link):
    """Unplugging and replugging the board must not need a restart."""
    link._drop("unplugged")
    assert not link.connected
    link.poll()
    assert not link.connected, "retried without waiting out the backoff"
    settled(link)                       # backoff elapsed
    link.poll()
    assert link.connected


def test_suspend_keeps_the_port_free_across_polls(link):
    """Flashing needs the device node free; a plain close() lasts one tick."""
    settled(link)
    link.suspend()
    for _ in range(20):
        link.poll()
    assert not link.connected, "der Sendeloop hat den Port zurueckgeholt"


def test_a_suspended_link_sends_nothing(link):
    link.suspend()
    assert link.send(1, [[1000] * 8]) is False


def test_resume_lets_the_board_come_back(link):
    settled(link)
    link.suspend()
    link.poll()
    link.resume()
    # resume() deliberately waits one interval for the board to enumerate.
    link._next_attempt = time.monotonic() - 1
    link.poll()
    assert link.connected


def test_a_dry_run_link_never_touches_the_device(monkeypatch, wire_ports):
    FakeSerial.opened = 0
    monkeypatch.setattr(link_module, "serial",
                        types.SimpleNamespace(Serial=FakeSerial,
                                              SerialException=OSError))
    connection = link_module.PicoLink("/dev/fake", wire_ports, dry_run=True)
    connection.poll()
    assert connection.send(1, [[1000] * 8]) is True
    assert FakeSerial.opened == 0
