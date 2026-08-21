"""Verifies the frame the bridge sends when no show is running.

There used to be a MIDI input here and most of this file was about it. What is
left of the mapper is the resting state: every zone at its failsafe value,
every relay where the configuration put it, and the blackout switch on top.
That frame goes out a hundred times a second whenever the timeline is not
driving, so it has to be a valid code word rather than eight separately
harmless numbers.
"""

from lightshow import bus as bus_mode
from lightshow.config import ChannelCfg, ModelCfg, PortCfg, ShowCfg
from lightshow.mapping import Mapper


def values(mapper: Mapper) -> list[int]:
    """What each channel holds, one entry per channel.

    Deliberately not read off the wire: a model's eight channels are the code
    symbols of one RS(8,6) frame, so channel n is not value n.
    """
    _, slots = mapper.snapshot()
    return [us for _, us in slots]


def channels() -> list[ChannelCfg]:
    return [
        ChannelCfg(role="cue", quantize=32, failsafe=1000),
        ChannelCfg(role="hue", failsafe=1500),
        ChannelCfg(role="brightness", failsafe=1000),
        ChannelCfg(role="param", failsafe=1500),
    ]


def make_show(**channel_kwargs) -> ShowCfg:
    port = PortCfg(id=0, name="tx", nchan=8)
    listed = channels()
    if channel_kwargs:
        listed[2] = ChannelCfg(role="brightness", failsafe=1000, **channel_kwargs)
    model = ModelCfg(name="eule", tx_port=0, channels=listed)
    return ShowCfg(ports=[port], models=[model])


def cue_at(mapper: Mapper, port: PortCfg, offset: int) -> int:
    """Decodes one model's block back off the wire, the way the aircraft does."""
    block = mapper.frame()[0][offset:offset + bus_mode.SYMBOLS]
    symbols = [bus_mode.us_to_symbol(us, port.min_us, port.max_us) for us in block]
    decoded = bus_mode.decode(symbols)
    assert decoded.ok
    _, state, _ = bus_mode.unpack(decoded.data, zones=1, relays_count=0)
    return state.cue


def test_the_resting_frame_is_every_channel_at_failsafe():
    assert values(Mapper(make_show())) == [1000, 1500, 1000, 1500]


def test_the_resting_frame_decodes_to_cue_zero():
    """Dark, and provably so -- not merely 'some numbers nobody set'."""
    show = make_show()
    assert cue_at(Mapper(show), show.ports[0], 0) == 0


def test_blackout_holds_failsafe_and_lets_go_again():
    mapper = Mapper(make_show())
    mapper.set_blackout(True)
    assert values(mapper) == [1000, 1500, 1000, 1500]
    mapper.set_blackout(False)
    assert values(mapper) == [1000, 1500, 1000, 1500]


def test_blackout_darkens_the_wire_in_one_frame():
    """Not zone by zone over a full rotation -- one frame says off everywhere."""
    show = make_show()
    mapper = Mapper(show)
    mapper.set_blackout(True)
    assert cue_at(mapper, show.ports[0], 0) == bus_mode.CUE_ALL_OFF


def test_models_sharing_a_port_land_in_their_own_block():
    """Two aircraft on one transmitter: eight coded channels each, side by side.

    Reading the wire back is the only way to see this, so the blocks are
    decoded rather than compared as numbers.
    """
    port = PortCfg(id=0, name="tx", nchan=16, frame_us=35500)
    show = ShowCfg(
        ports=[port],
        models=[
            ModelCfg("a", 0, tx_offset=0, channels=channels()),
            ModelCfg("b", 0, tx_offset=8, channels=channels()),
        ],
    )
    mapper = Mapper(show)

    assert cue_at(mapper, port, 0) == 0
    assert cue_at(mapper, port, 8) == 0
    # Each block has to be a code word of its own, not a slice of one big frame.
    assert len(mapper.frame()[0]) == 16


def test_a_relay_rests_where_the_configuration_put_it():
    from lightshow.config import BusCfg, BusRelayCfg

    port = PortCfg(id=0, name="tx", nchan=8)
    model = ModelCfg("eule", 0, channels=channels(),
                     bus=BusCfg(relays=[BusRelayCfg(name="rauch", failsafe=True)]))
    mapper = Mapper(ShowCfg(ports=[port], models=[model]))

    encoder = mapper.bus_encoders["eule"]
    assert encoder.relays[0] is True


def test_reload_drops_slots_that_no_longer_exist():
    """A model that lost a zone must not leave a slot driving a channel."""
    mapper = Mapper(make_show())
    assert len(mapper.slots) == 4

    port = PortCfg(id=0, name="tx", nchan=8)
    mapper.reload(ShowCfg(ports=[port], models=[]))
    assert mapper.slots == []
    assert mapper.bus_encoders == {}
