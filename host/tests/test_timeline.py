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
    ChannelCfg(role="cue", cc=20, quantize=32, failsafe=1000),
    ChannelCfg(role="hue", cc=21, failsafe=1500),
    ChannelCfg(role="brightness", cc=22, failsafe=1000),
    ChannelCfg(role="param", cc=23, failsafe=1500),
]


def make_show(zones: int = 1, offset: int = 0) -> ShowCfg:
    return ShowCfg(
        ports=[PortCfg(id=0, name="tx", nchan=8)],
        models=[ModelCfg("eule", 1, 0, tx_offset=offset,
                         channels=[ChannelCfg(**vars(c)) for c in CHANNELS] * zones)],
    )


def make_project(blocks: list[dict], model: str = "eule", zone: int = 0):
    return project_module.from_dict({
        "name": "test",
        "light_tracks": [{"model": model, "zone": zone, "blocks": blocks}],
    })


def timeline(show, project):
    return timeline_module.Timeline(show, project)


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
    show = make_show()
    line = timeline(show, make_project([]))
    assert line.frame(5.0)[0][:4] == [1000, 1500, 1000, 1500]


def test_a_block_drives_all_four_channels():
    show = make_show()
    line = timeline(show, make_project([
        {"start_s": 0, "duration_s": 10, "cue": 3, "hue": 255,
         "brightness": 255, "param": 0},
    ]))
    frame = line.frame(5.0)[0]
    # cue 3 of 32 steps sits in the middle of its band
    assert frame[0] == 1000 + round(1000 * 3.5 / 32)
    assert frame[1] == 2000      # hue at maximum
    assert frame[2] == 2000      # brightness at maximum
    assert frame[3] == 1000      # param at minimum


def test_brightness_follows_the_fade():
    show = make_show()
    line = timeline(show, make_project([
        {"start_s": 0, "duration_s": 10, "cue": 1, "brightness": 255, "fade_in_s": 4},
    ]))
    assert line.frame(0.0)[0][2] == 1000                    # dark at the start
    assert line.frame(2.0)[0][2] == pytest.approx(1500, abs=3)   # half way up
    assert line.frame(4.0)[0][2] == 2000                    # full
    # and monotonic in between, no steps backwards
    levels = [line.frame(t / 10)[0][2] for t in range(0, 41)]
    assert levels == sorted(levels)


def test_cue_zero_keeps_everything_at_failsafe():
    show = make_show()
    line = timeline(show, make_project([
        {"start_s": 0, "duration_s": 5, "cue": 0, "brightness": 255},
    ]))
    assert line.frame(2.0)[0][:4] == [1000, 1500, 1000, 1500]


def test_gaps_between_blocks_fall_back_to_failsafe():
    show = make_show()
    line = timeline(show, make_project([
        {"start_s": 0, "duration_s": 2, "cue": 1, "brightness": 255},
        {"start_s": 6, "duration_s": 2, "cue": 2, "brightness": 255},
    ]))
    assert line.frame(1.0)[0][2] == 2000
    assert line.frame(4.0)[0][2] == 1000        # the gap
    assert line.frame(7.0)[0][2] == 2000


def test_a_models_channel_offset_is_respected():
    """A model at tx_offset 4 must write channels 5..8, not 1..4."""
    show = make_show(offset=4)
    show.ports[0].nchan = 8
    line = timeline(show, make_project([
        {"start_s": 0, "duration_s": 5, "cue": 1, "brightness": 255},
    ]))
    frame = line.frame(1.0)[0]
    assert frame[6] == 2000                      # brightness of the second block
    assert frame[2] == 1000                      # first block untouched


def test_a_second_zone_writes_the_next_four_channels():
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
    frame = timeline(show, project).frame(1.0)[0]
    assert frame[2] == 2000       # zone 0 brightness up
    assert frame[6] == 1000       # zone 1 brightness down


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


def test_an_inverted_quantised_channel_matches_the_midi_path():
    """The MIDI mapper inverts before quantising; the timeline used to skip it.

    Same channel, same cue -- but a different value depending on whether the
    show ran from the project or from the DAW.
    """
    from lightshow.config import step_us
    from lightshow.mapping import Slot

    show = make_show()
    model = show.models[0]
    port = show.ports[0]
    cue = model.channels[0]
    cue.invert = True

    line = timeline(show, make_project([{"start_s": 0, "duration_s": 4, "cue": 7}]))
    from_timeline = line.frame(1.0)[0][0]

    # What the mapper produces for the same step, driven from the top of the
    # raw range so the inversion has something to mirror.
    slot = Slot(model=model, port=port, channel=cue, port_index=0)
    slot.raw = 7 * (slot.raw_max + 1) // cue.quantize
    from_midi = slot.microseconds()

    assert from_timeline == from_midi
    assert from_timeline == step_us(port, cue.quantize, cue.quantize - 1 - 7)
