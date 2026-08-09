"""Verifies the session: where channel values come from, and project handling.

The session decides whether the aircraft follow the project timeline or the
MIDI input. Getting that wrong means either a dead show or a show that ignores
the editor, so the switch is pinned down here.
"""

from __future__ import annotations

import numpy as np
import soundfile as sf

from lightshow import project as project_module
from lightshow.config import ChannelCfg, ModelCfg, PortCfg, ShowCfg
from lightshow.mapping import Mapper
from lightshow.session import Session


def make_show() -> ShowCfg:
    return ShowCfg(
        ports=[PortCfg(id=0, name="tx", nchan=8)],
        models=[
            ModelCfg("eule", 1, 0, tx_offset=0, channels=[
                ChannelCfg(role="cue", cc=20, quantize=32, failsafe=1000),
                ChannelCfg(role="hue", cc=21, failsafe=1500),
                ChannelCfg(role="brightness", cc=22, failsafe=1000),
                ChannelCfg(role="param", cc=23, failsafe=1500),
            ]),
        ],
    )


class FakeLink:
    device = "dry"
    dry_run = True
    connected = True
    frames_sent = 0
    last_error = None
    status_lines: list[str] = []


def make_session(tmp_path) -> Session:
    show = make_show()
    return Session(show, Mapper(show), FakeLink(), projects_root=tmp_path / "projects")


def with_block(session: Session, **block) -> None:
    """Loads a project with a single block covering 0..10 s."""
    result = session.new_project("test")
    assert result["ok"], result
    data = result["project"]["data"]
    data["light_tracks"][0]["blocks"] = [
        {"start_s": 0, "duration_s": 10, "cue": 1, "brightness": 255, **block}]
    assert session.save_project(data)["ok"]


# ------------------------------------------------------------------ sources


def test_without_a_project_the_values_come_from_midi(tmp_path):
    session = make_session(tmp_path)
    session.mapper.handle_control_change(1, 21, 127)
    assert session.frame()[0][1] == 2000


def test_a_stopped_transport_still_leaves_midi_in_charge(tmp_path):
    session = make_session(tmp_path)
    with_block(session)
    session.mapper.handle_control_change(1, 21, 127)

    assert not session.transport.playing
    assert session.frame()[0][1] == 2000
    assert session.source == "midi"


def test_while_playing_the_timeline_takes_over(tmp_path, monkeypatch):
    session = make_session(tmp_path)
    with_block(session, hue=0)
    session.mapper.handle_control_change(1, 21, 127)      # MIDI says maximum

    monkeypatch.setattr(session.transport, "_open", lambda: False)
    session.transport.play()
    try:
        assert session.source == "timeline"
        assert session.frame()[0][1] == 1000              # timeline says minimum
    finally:
        session.transport.pause()


def test_blackout_beats_both_sources(tmp_path, monkeypatch):
    session = make_session(tmp_path)
    with_block(session, brightness=255)
    monkeypatch.setattr(session.transport, "_open", lambda: False)
    session.transport.play()
    session.mapper.set_blackout(True)
    try:
        assert session.frame()[0][:4] == [1000, 1500, 1000, 1500]
    finally:
        session.transport.pause()


def test_the_last_frame_is_kept_for_the_monitors(tmp_path):
    session = make_session(tmp_path)
    assert session.last_frame is None
    frame = session.frame()
    assert session.last_frame == frame


# ----------------------------------------------------------------- projects


def test_a_new_project_gets_a_track_per_model_and_zone(tmp_path):
    session = make_session(tmp_path)
    result = session.new_project("Nachtflug")
    assert result["ok"]
    tracks = result["project"]["data"]["light_tracks"]
    assert [t["model"] for t in tracks] == ["eule"]
    assert [t["name"] for t in result["project"]["data"]["audio_tracks"]] == \
        ["Musik", "Effekte"]


def test_creating_the_same_project_twice_is_refused(tmp_path):
    session = make_session(tmp_path)
    assert session.new_project("Show")["ok"]
    assert not session.new_project("Show")["ok"]


def test_a_project_can_be_reopened(tmp_path):
    session = make_session(tmp_path)
    with_block(session, cue=5, label="Strobe")
    session.close_project()
    assert session.project is None

    assert session.open_project("test")["ok"]
    assert session.project.light_tracks[0].blocks[0].label == "Strobe"


def test_opening_something_that_is_not_a_project_reports_it(tmp_path):
    session = make_session(tmp_path)
    assert not session.open_project("gibtsnicht")["ok"]


def test_saving_an_invalid_project_changes_nothing(tmp_path):
    session = make_session(tmp_path)
    with_block(session, cue=1)
    before = project_module.to_dict(session.project)

    broken = project_module.to_dict(session.project)
    broken["light_tracks"][0]["blocks"] = [
        {"start_s": 0, "duration_s": 5, "cue": 1},
        {"start_s": 2, "duration_s": 5, "cue": 2},          # overlapping
    ]
    result = session.save_project(broken)

    assert not result["ok"] and "ueberlappen" in result["error"]
    assert project_module.to_dict(session.project) == before


def test_editing_during_playback_keeps_the_position(tmp_path, monkeypatch):
    session = make_session(tmp_path)
    with_block(session)
    monkeypatch.setattr(session.transport, "_open", lambda: False)

    session.transport.seek(3.0)
    session.transport.play()
    data = project_module.to_dict(session.project)
    data["light_tracks"][0]["blocks"][0]["hue"] = 200
    assert session.save_project(data)["ok"]

    try:
        assert session.transport.playing
        assert session.transport.position() >= 3.0
    finally:
        session.transport.pause()


def test_importing_audio_rejects_a_file_that_is_not_audio(tmp_path):
    session = make_session(tmp_path)
    session.new_project("test")
    result = session.import_audio("notiz.txt", b"kein Audio")
    assert not result["ok"]
    # and nothing is left lying around in the project
    assert not (session.project.path / "audio" / "notiz.txt").exists()


def test_importing_audio_stores_it_and_reports_the_length(tmp_path):
    session = make_session(tmp_path)
    session.new_project("test")

    wav = tmp_path / "ton.wav"
    sf.write(str(wav), np.zeros((44100, 2), dtype="float32"), 44100)
    result = session.import_audio("ton.wav", wav.read_bytes())

    assert result["ok"] and result["duration_s"] == 1.0
    assert (session.project.path / result["file"]).is_file()


def test_a_second_upload_of_the_same_name_does_not_overwrite(tmp_path):
    session = make_session(tmp_path)
    session.new_project("test")
    wav = tmp_path / "ton.wav"
    sf.write(str(wav), np.zeros((4410, 2), dtype="float32"), 44100)

    first = session.import_audio("ton.wav", wav.read_bytes())
    second = session.import_audio("ton.wav", wav.read_bytes())
    assert first["file"] != second["file"]
