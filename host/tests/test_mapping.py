import pytest

from lightshow.config import ChannelCfg, ModelCfg, PortCfg, ShowCfg
from lightshow.mapping import Mapper


def make_show(**channel_kwargs) -> ShowCfg:
    port = PortCfg(id=0, name="tx", nchan=4)
    channels = [
        ChannelCfg(role="cue", cc=20, quantize=32, failsafe=1000),
        ChannelCfg(role="hue", cc=21, failsafe=1500),
        ChannelCfg(role="brightness", cc=22, cc_lsb=54, failsafe=1000, **channel_kwargs),
        ChannelCfg(role="param", cc=23, failsafe=1500),
    ]
    model = ModelCfg(name="eule", midi_channel=1, tx_port=0, channels=channels)
    return ShowCfg(ports=[port], models=[model])


def test_untouched_channels_report_failsafe():
    mapper = Mapper(make_show())
    assert mapper.frame() == [[1000, 1500, 1000, 1500]]


def test_seven_bit_cc_spans_the_full_range():
    mapper = Mapper(make_show())
    mapper.handle_control_change(1, 21, 0)
    assert mapper.frame()[0][1] == 1000
    mapper.handle_control_change(1, 21, 127)
    assert mapper.frame()[0][1] == 2000
    mapper.handle_control_change(1, 21, 64)
    assert mapper.frame()[0][1] == pytest.approx(1504, abs=1)


def test_fourteen_bit_pair_gives_finer_steps():
    mapper = Mapper(make_show())
    mapper.handle_control_change(1, 22, 64)      # MSB alone already moves
    coarse = mapper.frame()[0][2]
    mapper.handle_control_change(1, 54, 1)       # LSB refines
    assert mapper.frame()[0][2] >= coarse
    mapper.handle_control_change(1, 22, 127)
    mapper.handle_control_change(1, 54, 127)
    assert mapper.frame()[0][2] == 2000


def test_inverted_channel_flips_the_range():
    mapper = Mapper(make_show(invert=True))
    mapper.handle_control_change(1, 22, 127)
    mapper.handle_control_change(1, 54, 127)
    assert mapper.frame()[0][2] == 1000


def test_quantized_values_sit_in_the_middle_of_their_step():
    mapper = Mapper(make_show())
    span, steps = 1000, 32
    for value in range(128):
        mapper.handle_control_change(1, 20, value)
        us = mapper.frame()[0][0]
        index = value * steps // 128
        assert us == 1000 + round(span * (index + 0.5) / steps)
        # Decoding the way the airborne firmware does must give the step back.
        decoded = min(steps - 1, int((us - 1000) * steps / span))
        assert decoded == index


def test_blackout_forces_failsafe_and_releases():
    mapper = Mapper(make_show())
    mapper.handle_control_change(1, 21, 127)
    mapper.handle_control_change(1, 119, 127)
    assert mapper.frame() == [[1000, 1500, 1000, 1500]]
    mapper.handle_control_change(1, 119, 0)
    assert mapper.frame()[0][1] == 2000


def test_all_notes_off_resets_that_midi_channel():
    mapper = Mapper(make_show())
    mapper.handle_control_change(1, 21, 127)
    mapper.handle_control_change(1, 123, 0)
    assert mapper.frame()[0][1] == 1500


def test_messages_on_other_channels_are_ignored():
    mapper = Mapper(make_show())
    mapper.handle_control_change(2, 21, 127)
    assert mapper.frame()[0][1] == 1500


def test_models_sharing_a_port_land_in_their_own_block():
    port = PortCfg(id=0, name="tx", nchan=8)
    def channels():
        return [
            ChannelCfg(role="cue", cc=20, failsafe=1000),
            ChannelCfg(role="hue", cc=21, failsafe=1500),
        ]
    show = ShowCfg(
        ports=[port],
        models=[
            ModelCfg("a", 1, 0, tx_offset=0, channels=channels()),
            ModelCfg("b", 2, 0, tx_offset=4, channels=channels()),
        ],
    )
    mapper = Mapper(show)
    mapper.handle_control_change(2, 20, 127)
    frame = mapper.frame()[0]
    assert frame[0] == 1000      # model a untouched
    assert frame[4] == 2000      # model b, first channel of its block
