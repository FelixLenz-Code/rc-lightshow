"""Verifies the session: where channel values come from, and project handling.

The session decides whether the aircraft follow the project timeline or the
MIDI input. Getting that wrong means either a dead show or a show that ignores
the editor, so the switch is pinned down here.
"""

from __future__ import annotations

import numpy as np
import pytest
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


# ------------------------------------------------------- live edits


def tone_project(session, tmp_path, *, start_s: float, gain_db: float = 0.0,
                 mute: bool = False) -> dict:
    """A project with one two second tone, as plain data."""
    import numpy as np
    import soundfile as sf

    result = session.new_project("live")
    assert result["ok"], result
    audio = session.project.path / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    rate = 44100
    t = np.arange(int(2 * rate)) / rate
    sf.write(str(audio / "ton.wav"), (0.5 * np.sin(2 * np.pi * 440 * t)).astype("float32"), rate)

    data = project_module.to_dict(session.project)
    data["audio_tracks"][0]["gain_db"] = gain_db
    data["audio_tracks"][0]["mute"] = mute
    data["audio_tracks"][0]["clips"] = [
        {"file": "audio/ton.wav", "start_s": start_s, "duration_s": 2.0}]
    return data


def loud_between(transport) -> tuple[float, float] | None:
    """Where the mix actually carries sound, in seconds."""
    import numpy as np

    mono = np.max(np.abs(transport.mix), axis=1)
    loud = np.nonzero(mono > 0.05)[0]
    if not len(loud):
        return None
    return loud[0] / transport.rate, loud[-1] / transport.rate


def test_moving_a_clip_moves_the_sound(tmp_path):
    """It used to move on screen and keep playing from where it was.

    The mix is built once and the callback only copies a slice out of it, so an
    edit that never reaches the mix is an edit that is never heard.
    """
    session = make_session(tmp_path)
    data = tone_project(session, tmp_path, start_s=0.0)
    assert session.apply_project(data)["ok"]
    assert loud_between(session.transport)[0] == pytest.approx(0.0, abs=0.05)

    data["audio_tracks"][0]["clips"][0]["start_s"] = 5.0
    result = session.apply_project(data)
    assert result["ok"] and result["audio"], "das Audio wurde nicht neu gemischt"

    start, end = loud_between(session.transport)
    assert start == pytest.approx(5.0, abs=0.05), "der Ton liegt noch am alten Platz"
    assert end == pytest.approx(7.0, abs=0.05)
    session.transport.close()


def test_the_track_volume_takes_effect(tmp_path):
    """Turning a track down has to be audible, not only visible."""
    import numpy as np

    session = make_session(tmp_path)
    data = tone_project(session, tmp_path, start_s=0.0)
    assert session.apply_project(data)["ok"]
    full = float(np.max(np.abs(session.transport.mix)))

    data["audio_tracks"][0]["gain_db"] = -20.0
    assert session.apply_project(data)["ok"]
    quiet = float(np.max(np.abs(session.transport.mix)))

    assert quiet == pytest.approx(full * 0.1, rel=0.15), \
        f"-20 dB haben nichts bewirkt: {full:.3f} -> {quiet:.3f}"
    session.transport.close()


def test_muting_a_track_takes_effect(tmp_path):
    import numpy as np

    session = make_session(tmp_path)
    data = tone_project(session, tmp_path, start_s=0.0)
    assert session.apply_project(data)["ok"]

    data["audio_tracks"][0]["mute"] = True
    assert session.apply_project(data)["ok"]
    assert float(np.max(np.abs(session.transport.mix))) == 0.0
    session.transport.close()


def test_a_light_block_alone_does_not_remix_the_audio(tmp_path):
    """Dragging a block must not cost a remix of a five minute song."""
    session = make_session(tmp_path)
    data = tone_project(session, tmp_path, start_s=0.0)
    assert session.apply_project(data)["ok"]

    data["light_tracks"][0]["blocks"] = [
        {"start_s": 0.0, "duration_s": 4.0, "cue": 3, "hue": 10,
         "brightness": 200, "param": 128}]
    result = session.apply_project(data)
    assert result["ok"] and not result["audio"], "das Audio wurde unnötig neu gemischt"
    session.transport.close()


def test_a_light_block_still_moves_the_end_of_the_show(tmp_path):
    """The show ends with the last thing on any track, light included."""
    session = make_session(tmp_path)
    data = tone_project(session, tmp_path, start_s=0.0)
    assert session.apply_project(data)["ok"]
    assert session.transport.duration_s == pytest.approx(2.0, abs=0.05)

    data["light_tracks"][0]["blocks"] = [
        {"start_s": 20.0, "duration_s": 5.0, "cue": 1, "hue": 0,
         "brightness": 255, "param": 128}]
    assert session.apply_project(data)["ok"]

    assert session.transport.duration_s == pytest.approx(25.0, abs=0.05)
    session.transport.seek(24.0)
    assert session.transport.position() == pytest.approx(24.0, abs=0.05), \
        "der Abspielkopf kommt nicht bis zum letzten Block"
    session.transport.close()


def test_applying_does_not_write_to_disk(tmp_path):
    """Live editing is not saving; the file changes only on save."""
    session = make_session(tmp_path)
    data = tone_project(session, tmp_path, start_s=0.0)
    assert session.save_project(data)["ok"]
    on_disk = (session.project.path / project_module.PROJECT_FILE).read_text()

    data["audio_tracks"][0]["clips"][0]["start_s"] = 9.0
    assert session.apply_project(data)["ok"]
    assert (session.project.path / project_module.PROJECT_FILE).read_text() == on_disk

    assert session.save_project(data)["ok"]
    assert (session.project.path / project_module.PROJECT_FILE).read_text() != on_disk
    session.transport.close()
