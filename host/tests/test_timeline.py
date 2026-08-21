"""Verifies the show timeline: blocks, fades and where their values land.

This replaces Ardour as the source of the light values, so the arithmetic here
decides what the aircraft actually do.
"""

from __future__ import annotations

import json

import pytest

from lightshow import project as project_module
from lightshow import timeline as timeline_module
from lightshow.config import ChannelCfg, ModelCfg, PortCfg, ShowCfg

CHANNELS = [
    ChannelCfg(role="cue", quantize=32, failsafe=1000),
    ChannelCfg(role="hue", failsafe=1500),
    ChannelCfg(role="brightness", failsafe=1000),
    ChannelCfg(role="param", failsafe=1500),
]


def make_show(zones: int = 1, offset: int = 0) -> ShowCfg:
    return ShowCfg(
        ports=[PortCfg(id=0, name="tx", nchan=8)],
        models=[ModelCfg("eule", 0, tx_offset=offset,
                         channels=[ChannelCfg(**vars(c)) for c in CHANNELS] * zones)],
    )


def make_project(blocks: list[dict], model: str = "eule", zone: int = 0):
    return project_module.from_dict({
        "name": "test",
        "light_tracks": [{"model": model, "zone": zone, "blocks": blocks}],
    })


def timeline(show, project):
    return timeline_module.Timeline(show, project)


def zone(line, t: float, index: int = 0, model: str = "eule") -> dict:
    """What the timeline put into a zone at time `t`, in the fields it travels.

    The wire carries one zone per frame and rotates on the clock, so reading a
    channel back would ask which zone happened to be in flight. The encoder's
    stored state is the whole picture, and it is what the aircraft holds.

    cue is a step; hue, brightness and param come back as 0..255, coarsened to
    the width each one actually gets on air -- 6, 8 and 5 bits.
    """
    line.frame(t)
    return line.encoders[model].states[index].to_bytes()


# --------------------------------------------------------------------- fades


def test_a_block_without_fades_is_at_full_level_throughout():
    block = project_module.LightBlock(start_s=1, duration_s=4)
    for t in (1.0, 2.5, 4.99):
        assert timeline_module.fade_factor(block, t) == 1.0


def test_fade_in_ramps_from_zero_to_one():
    block = project_module.LightBlock(start_s=0, duration_s=10, fade_in_s=2)
    assert timeline_module.fade_factor(block, 0.0) == 0.0
    assert timeline_module.fade_factor(block, 1.0) == pytest.approx(0.5)
    assert timeline_module.fade_factor(block, 2.0) == 1.0


def test_fade_out_ramps_back_to_zero():
    block = project_module.LightBlock(start_s=0, duration_s=10, fade_out_s=2)
    assert timeline_module.fade_factor(block, 8.0) == 1.0
    assert timeline_module.fade_factor(block, 9.0) == pytest.approx(0.5)
    assert timeline_module.fade_factor(block, 9.999) == pytest.approx(0.0, abs=1e-3)


def test_outside_the_block_the_envelope_is_zero():
    block = project_module.LightBlock(start_s=5, duration_s=2)
    assert timeline_module.fade_factor(block, 4.99) == 0.0
    assert timeline_module.fade_factor(block, 7.0) == 0.0


def test_a_block_shorter_than_its_fades_is_rejected():
    with pytest.raises(project_module.ProjectError, match="passen nicht"):
        make_project([{"start_s": 0, "duration_s": 1, "fade_in_s": 1, "fade_out_s": 1}])


# ------------------------------------------------------------------- frames


def test_nothing_scheduled_means_failsafe():
    """Cue 0 is "everything off", and that is what an empty zone holds."""
    show = make_show()
    line = timeline(show, make_project([]))
    assert zone(line, 5.0) == {"cue": 0, "hue": 0, "brightness": 0, "param": 0}


def test_a_block_drives_all_four_values():
    show = make_show()
    line = timeline(show, make_project([
        {"start_s": 0, "duration_s": 10, "cue": 3, "hue": 255,
         "brightness": 255, "param": 0},
    ]))
    state = zone(line, 5.0)
    assert state["cue"] == 3
    assert state["hue"] == 255           # at maximum
    assert state["brightness"] == 255    # at maximum
    assert state["param"] == 0           # at minimum


def test_brightness_follows_the_fade():
    show = make_show()
    line = timeline(show, make_project([
        {"start_s": 0, "duration_s": 10, "cue": 1, "brightness": 255, "fade_in_s": 4},
    ]))
    assert zone(line, 0.0)["brightness"] == 0               # dark at the start
    assert zone(line, 2.0)["brightness"] == pytest.approx(128, abs=2)  # half way
    assert zone(line, 4.0)["brightness"] == 255             # full
    # and monotonic in between, no steps backwards
    levels = [zone(line, t / 10)["brightness"] for t in range(0, 41)]
    assert levels == sorted(levels)


def test_cue_zero_keeps_everything_at_failsafe():
    show = make_show()
    line = timeline(show, make_project([
        {"start_s": 0, "duration_s": 5, "cue": 0, "brightness": 255},
    ]))
    assert zone(line, 2.0) == {"cue": 0, "hue": 0, "brightness": 0, "param": 0}


def test_gaps_between_blocks_fall_back_to_failsafe():
    show = make_show()
    line = timeline(show, make_project([
        {"start_s": 0, "duration_s": 2, "cue": 1, "brightness": 255},
        {"start_s": 6, "duration_s": 2, "cue": 2, "brightness": 255},
    ]))
    assert zone(line, 1.0)["brightness"] == 255
    assert zone(line, 4.0)["brightness"] == 0        # the gap
    assert zone(line, 7.0)["brightness"] == 255


def test_a_models_channel_offset_is_respected():
    """A model at tx_offset 8 must write channels 9..16, not 1..8."""
    show = make_show(offset=8)
    show.ports[0].nchan = 16
    show.ports[0].frame_us = 35500
    line = timeline(show, make_project([
        {"start_s": 0, "duration_s": 5, "cue": 1, "brightness": 255},
    ]))
    frame = line.frame(1.0)[0]
    # The coded block sits in the model's own eight channels; the sticks below
    # it are never written and keep the port minimum.
    assert set(frame[:8]) == {show.ports[0].min_us}
    assert frame[8:] != [show.ports[0].min_us] * 8


def test_a_second_zone_keeps_its_own_state():
    """Two zones, one eight channel block -- they take turns, they do not
    take four channels each."""
    show = make_show(zones=2)
    project = project_module.from_dict({
        "name": "test",
        "light_tracks": [
            {"model": "eule", "zone": 0,
             "blocks": [{"start_s": 0, "duration_s": 5, "cue": 1, "brightness": 255}]},
            {"model": "eule", "zone": 1,
             "blocks": [{"start_s": 0, "duration_s": 5, "cue": 1, "brightness": 0}]},
        ],
    })
    line = timeline(show, project)
    assert zone(line, 1.0, 0)["brightness"] == 255      # zone 0 up
    assert zone(line, 1.0, 1)["brightness"] == 0        # zone 1 down
    assert line.encoders["eule"].zones == 2


# ----------------------------------------------------------------- warnings


def test_an_unknown_model_is_reported_instead_of_crashing():
    line = timeline(make_show(), make_project([], model="gibtsnicht"))
    assert line.bindings == []
    assert any("gibtsnicht" in w for w in line.warnings)


def test_a_missing_zone_is_reported():
    line = timeline(make_show(zones=1), make_project([], zone=1))
    assert line.bindings == []
    assert any("Zone 1" in w for w in line.warnings)


# -------------------------------------------------------------- project i/o


def test_overlapping_blocks_are_refused():
    with pytest.raises(project_module.ProjectError, match="ueberlappen"):
        make_project([
            {"start_s": 0, "duration_s": 5, "cue": 1},
            {"start_s": 3, "duration_s": 5, "cue": 2},
        ])


def test_blocks_are_sorted_even_if_the_file_is_not():
    project = make_project([
        {"start_s": 10, "duration_s": 2, "cue": 2},
        {"start_s": 0, "duration_s": 2, "cue": 1},
    ])
    assert [b.start_s for b in project.light_tracks[0].blocks] == [0, 10]


def test_duration_covers_audio_and_light():
    project = project_module.from_dict({
        "name": "t",
        "audio_tracks": [{"name": "Musik", "clips": [
            {"file": "audio/a.wav", "start_s": 0, "duration_s": 30}]}],
        "light_tracks": [{"model": "eule", "blocks": [
            {"start_s": 40, "duration_s": 5, "cue": 1}]}],
    })
    assert project.duration_s == 45


def test_audio_paths_may_not_escape_the_project():
    with pytest.raises(project_module.ProjectError, match="innerhalb"):
        project_module.from_dict({"name": "t", "audio_tracks": [
            {"name": "x", "clips": [{"file": "../../etc/passwd"}]}]})


def test_round_trip_keeps_everything(tmp_path):
    original = project_module.from_dict({
        "name": "nachtflug",
        "audio_tracks": [{"name": "Musik", "gain_db": -3.0, "clips": [
            {"file": "audio/m.wav", "start_s": 1.5, "duration_s": 60,
             "fade_out_s": 2.0}]}],
        "light_tracks": [{"model": "eule", "zone": 0, "name": "Flächen", "blocks": [
            {"start_s": 2, "duration_s": 8, "cue": 3, "hue": 40, "brightness": 200,
             "param": 90, "fade_in_s": 1, "label": "Strobe rot"}]}],
    })
    project_module.save(original, tmp_path)
    again = project_module.load(tmp_path)

    assert project_module.to_dict(again) == project_module.to_dict(original)
    assert again.light_tracks[0].blocks[0].label == "Strobe rot"
    assert (tmp_path / "project.json").is_file()


def test_saving_twice_keeps_a_backup(tmp_path):
    project = project_module.from_dict({"name": "a"})
    project_module.save(project, tmp_path)
    project.name = "b"
    project_module.save(project, tmp_path)
    assert json.loads((tmp_path / "project.json.bak").read_text())["name"] == "a"


def test_importing_audio_copies_it_into_the_project(tmp_path):
    source = tmp_path / "Downloads" / "Mein Lied.wav"
    source.parent.mkdir()
    source.write_bytes(b"RIFF")

    project = project_module.from_dict({"name": "t"})
    project_module.save(project, tmp_path / "projekt")
    relative = project_module.import_audio(project, source)

    assert relative == "audio/Mein_Lied.wav"
    assert (tmp_path / "projekt" / relative).read_bytes() == b"RIFF"


def test_listing_finds_saved_projects(tmp_path):
    for name in ("eins", "zwei"):
        project_module.save(project_module.from_dict({"name": name}), tmp_path / name)
    assert [p["name"] for p in project_module.list_projects(tmp_path)] == ["eins", "zwei"]


def test_an_inverted_quantised_channel_mirrors_the_step():
    """Inverting has to mirror the step index, not the microseconds.

    A channel wired the other way round is corrected here, on the way out --
    the airborne decoder knows nothing about it and reads the step it is given.
    """
    show = make_show()
    cue = show.models[0].channels[0]
    cue.invert = True

    line = timeline(show, make_project([{"start_s": 0, "duration_s": 4, "cue": 7}]))
    assert zone(line, 1.0)["cue"] == cue.quantize - 1 - 7


# ------------------------------------------------------------------- relays


def relay_show(relays: int = 2) -> ShowCfg:
    """A one zone model with `relays` bits, and a board relay for each."""
    from lightshow.config import BusCfg, BusRelayCfg, PlaneCfg, RelayCfg

    show = make_show()
    model = show.models[0]
    model.bus = BusCfg(relays=[BusRelayCfg(f"r{i}", 100 + i) for i in range(relays)])
    model.plane = PlaneCfg(relays=[RelayCfg(f"r{i}", 6 + i) for i in range(relays)])
    return show


def relay_project(blocks: list[dict], relay: int = 0, model: str = "eule"):
    return project_module.from_dict({
        "name": "test",
        "relay_tracks": [{"model": model, "relay": relay, "blocks": blocks}],
    })


def relay_bits(line, t: float, model: str = "eule") -> list[bool]:
    line.frame(t)
    return list(line.encoders[model].relays)


def test_a_relay_block_closes_its_bit_and_only_its_bit():
    show = relay_show()
    line = timeline(show, relay_project([{"start_s": 2, "duration_s": 3}], relay=1))
    assert relay_bits(line, 3.0) == [False, True]


def test_a_relay_is_off_before_and_after_its_block():
    show = relay_show(relays=1)
    line = timeline(show, relay_project([{"start_s": 2, "duration_s": 3}]))
    assert relay_bits(line, 1.9) == [False]
    assert relay_bits(line, 2.0) == [True]
    assert relay_bits(line, 4.99) == [True]
    assert relay_bits(line, 5.0) == [False]


def test_a_relay_nobody_scheduled_is_cleared_every_frame():
    """The encoder holds its last state, so silence has to mean off.

    Without this a smoke system would keep running from whatever the previous
    project left in the encoder.
    """
    show = relay_show(relays=1)
    line = timeline(show, relay_project([{"start_s": 0, "duration_s": 1}]))
    line.encoders["eule"].set_relay(0, True)
    assert relay_bits(line, 5.0) == [False]


def test_a_relay_track_naming_a_bit_that_does_not_exist_is_reported():
    show = relay_show(relays=1)
    line = timeline(show, relay_project([], relay=3))
    assert line.relay_bindings == []
    assert any("Relais 4" in warning for warning in line.warnings)


def test_a_relay_track_on_an_unknown_model_is_reported():
    line = timeline(relay_show(), relay_project([], model="gibtsnicht"))
    assert line.relay_bindings == []
    assert any("gibtsnicht" in warning for warning in line.warnings)


def test_overlapping_relay_blocks_are_refused():
    """An is an is: two blocks saying it would make the gap the only content."""
    with pytest.raises(project_module.ProjectError, match="an oder aus"):
        relay_project([{"start_s": 0, "duration_s": 5},
                       {"start_s": 3, "duration_s": 5}])


def test_relay_tracks_survive_the_round_trip_through_json():
    project = relay_project([{"start_s": 1, "duration_s": 2, "label": "Rauch an"}])
    again = project_module.from_dict(project_module.to_dict(project))
    assert len(again.relay_tracks) == 1
    assert again.relay_tracks[0].blocks[0].label == "Rauch an"
    assert again.relay_tracks[0].relay == 0


def test_the_project_length_counts_relay_blocks_too():
    """Otherwise a show ending on a smoke burst would be cut short."""
    project = relay_project([{"start_s": 10, "duration_s": 5}])
    assert project.duration_s == 15


def test_a_relay_reaches_the_wire_as_a_decodable_frame():
    """The whole path: block on the timeline, bit in the RS(8,6) frame."""
    from lightshow import bus as bus_mode

    show = relay_show(relays=2)
    show.ports[0].nchan = 8
    line = timeline(show, relay_project([{"start_s": 0, "duration_s": 5}], relay=1))
    port = show.ports[0]
    block = line.frame(2.0)[0][:bus_mode.SYMBOLS]
    symbols = [bus_mode.us_to_symbol(us, port.min_us, port.max_us) for us in block]
    decoded = bus_mode.decode(symbols)
    assert decoded.ok
    _, _, relays = bus_mode.unpack(decoded.data, zones=1, relays_count=2)
    assert relays == [False, True]
