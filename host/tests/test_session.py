"""Verifies the session: where channel values come from, and project handling.

The session decides whether the aircraft follow the project timeline or the
MIDI input. Getting that wrong means either a dead show or a show that ignores
the editor, so the switch is pinned down here.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile as sf

from lightshow import bus as bus_mode
from lightshow import project as project_module
from lightshow.config import ChannelCfg, ModelCfg, PortCfg, ShowCfg
from lightshow.mapping import Mapper
from lightshow.session import Session


def zone_channels(first_cc: int) -> list[ChannelCfg]:
    return [
        ChannelCfg(role="cue", quantize=32, failsafe=1000),
        ChannelCfg(role="hue", failsafe=1500),
        ChannelCfg(role="brightness", failsafe=1000),
        ChannelCfg(role="param", failsafe=1500),
    ]


def make_show(models: int = 1, one_jack: bool = False) -> ShowCfg:
    """One aircraft, or two.

    `one_jack` puts them both on the same transmitter, a block apart -- which is
    a legal build, and the case a project may take only one of.
    """
    ports = [PortCfg(id=0, name="tx", nchan=8 if models == 1 else 16)]
    if models > 1 and not one_jack:
        ports.append(PortCfg(id=1, name="tx2", nchan=8))
    return ShowCfg(
        ports=ports,
        models=[
            ModelCfg("eule", 0, tx_offset=0, channels=zone_channels(20)),
            *([ModelCfg("falke", 0 if one_jack else 1,
                        tx_offset=8 if one_jack else 0,
                        channels=zone_channels(30))]
              if models > 1 else []),
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


def state(session: Session) -> dict:
    """What the session actually put on the wire, decoded back out of it.

    The eight channels are one RS(8,6) frame, so nothing can be read off a
    channel directly. With a single zone the frame always addresses that zone,
    which makes this deterministic.
    """
    port = session.show.ports[0]
    block = session.frame()[0][:bus_mode.SYMBOLS]
    symbols = [bus_mode.us_to_symbol(us, port.min_us, port.max_us)
               for us in block]
    decoded = bus_mode.decode(symbols)
    assert decoded.ok, "the ground station put a frame on the wire that is none"
    _, zone, _ = bus_mode.unpack(decoded.data, zones=1, relays_count=0)
    return {"all_off": bus_mode.is_all_off(zone), **zone.to_bytes()}


def with_block(session: Session, **block) -> None:
    """Loads a project with a single block covering 0..10 s."""
    result = session.new_project("test")
    assert result["ok"], result
    data = result["project"]["data"]
    data["light_tracks"][0]["blocks"] = [
        {"start_s": 0, "duration_s": 10, "cue": 1, "brightness": 255, **block}]
    assert session.save_project(data)["ok"]


# ------------------------------------------------------------------ sources


def test_without_a_project_everything_rests(tmp_path):
    """No project, no transport: the failsafe values and nothing else."""
    session = make_session(tmp_path)
    assert state(session)["cue"] == 0


def test_a_stopped_transport_leaves_the_show_at_rest(tmp_path):
    """A block on the timeline does not light anything until it is played."""
    session = make_session(tmp_path)
    with_block(session, hue=255)

    assert not session.transport.playing
    # Cue 0 is "dark"; hue rests wherever its failsafe puts it and does not
    # matter while nothing is lit.
    assert state(session)["cue"] == 0
    assert session.source == "idle"


def test_while_playing_the_timeline_takes_over(tmp_path, monkeypatch):
    session = make_session(tmp_path)
    with_block(session, hue=200)

    monkeypatch.setattr(session.transport, "_open", lambda: False)
    session.transport.play()
    try:
        assert session.source == "timeline"
        # Six bits on the wire, so the value comes back rounded to its band.
        assert abs(state(session)["hue"] - 200) <= 4
    finally:
        session.transport.pause()


def test_blackout_beats_both_sources(tmp_path, monkeypatch):
    session = make_session(tmp_path)
    with_block(session, brightness=255)
    monkeypatch.setattr(session.transport, "_open", lambda: False)
    session.transport.play()
    session.mapper.set_blackout(True)
    try:
        # One frame that says off everywhere, not four individually safe values.
        assert state(session)["all_off"]
        assert state(session)["brightness"] == 0
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


# ------------------------------------- a project is for the aircraft it is for


def two_model_session(tmp_path) -> Session:
    show = make_show(models=2)
    return Session(show, Mapper(show), FakeLink(), projects_root=tmp_path / "projects")


def test_a_project_is_laid_out_only_for_the_models_it_was_given(tmp_path):
    """A field with four aircraft configured rarely flies all four in one show.

    Opening on tracks for every zone of every model is a timeline somebody has
    to clear out before they can start.
    """
    session = two_model_session(tmp_path)
    data = session.new_project("Nachtflug", ["falke"])["project"]["data"]
    assert data["models"] == ["falke"]
    assert [t["model"] for t in data["light_tracks"]] == ["falke"]


def test_leaving_the_models_out_still_means_all_of_them(tmp_path):
    """The call that existed before the question did."""
    session = two_model_session(tmp_path)
    data = session.new_project("Alles")["project"]["data"]
    assert data["models"] == ["eule", "falke"]


def test_the_tracks_come_out_in_configuration_order(tmp_path):
    """Not in the order the boxes happened to be ticked."""
    session = two_model_session(tmp_path)
    data = session.new_project("Reihenfolge", ["falke", "eule"])["project"]["data"]
    assert data["models"] == ["eule", "falke"]


def test_a_project_for_nothing_is_refused(tmp_path):
    session = two_model_session(tmp_path)
    answer = session.new_project("Leer", [])
    assert not answer["ok"] and "mindestens ein Modell" in answer["error"]


def test_a_model_that_is_not_configured_is_refused_by_name(tmp_path):
    """Silently dropping it would produce a show for nothing, and say nothing."""
    session = two_model_session(tmp_path)
    answer = session.new_project("Tippfehler", ["eule", "eulle"])
    assert not answer["ok"] and "eulle" in answer["error"]


def test_an_older_project_says_which_models_it_is_for(tmp_path):
    """Written before the field existed, so it is read back off the tracks."""
    session = two_model_session(tmp_path)
    session.new_project("Alt", ["falke"])
    directory = tmp_path / "projects" / "Alt"
    data = json.loads((directory / "project.json").read_text())
    del data["models"]
    (directory / "project.json").write_text(json.dumps(data))
    assert project_module.load(directory).models == ["falke"]


def one_jack_session(tmp_path) -> Session:
    show = make_show(models=2, one_jack=True)
    return Session(show, Mapper(show), FakeLink(), projects_root=tmp_path / "projects")


def test_two_models_on_one_transmitter_cannot_share_a_project(tmp_path):
    """They may both exist -- one set of sticks cannot fly both at once."""
    session = one_jack_session(tmp_path)
    answer = session.new_project("Beide", ["eule", "falke"])
    assert not answer["ok"]
    assert "Sender-Buchse 1" in answer["error"]


def test_either_of_them_alone_is_fine(tmp_path):
    session = one_jack_session(tmp_path)
    assert session.new_project("Eins", ["eule"])["ok"]
    assert session.new_project("Zwei", ["falke"])["ok"]


# ---------------------------------------------------------- reworking a project


def test_a_project_can_be_renamed_without_moving_its_folder(tmp_path):
    """Every path that points into it would break for the sake of tidiness."""
    session = two_model_session(tmp_path)
    session.new_project("Nachtflug", ["eule"])
    answer = session.edit_project("Morgenflug", None)
    assert answer["ok"]
    assert answer["project"]["data"]["name"] == "Morgenflug"
    assert (tmp_path / "projects" / "Nachtflug" / "project.json").is_file()


def test_adding_a_model_brings_its_tracks(tmp_path):
    session = two_model_session(tmp_path)
    session.new_project("Nachtflug", ["eule"])
    data = session.edit_project("", ["eule", "falke"])["project"]["data"]
    assert [t["model"] for t in data["light_tracks"]] == ["eule", "falke"]


def test_removing_a_model_takes_its_tracks_with_it(tmp_path):
    """Blocks and all -- a model that is not in the project owns nothing in it."""
    session = two_model_session(tmp_path)
    session.new_project("Nachtflug", ["eule", "falke"])
    data = session.edit_project("", ["falke"])["project"]["data"]
    assert data["models"] == ["falke"]
    assert [t["model"] for t in data["light_tracks"]] == ["falke"]


def test_what_stays_keeps_what_is_on_it(tmp_path):
    """Reworking the model list must not quietly clear the timeline."""
    session = two_model_session(tmp_path)
    made = session.new_project("Nachtflug", ["eule", "falke"])["project"]["data"]
    made["light_tracks"][0]["blocks"] = [
        {"start_s": 1, "duration_s": 2, "cue": 3, "brightness": 200}]
    assert session.save_project(made)["ok"]
    data = session.edit_project("", ["eule"])["project"]["data"]
    assert len(data["light_tracks"][0]["blocks"]) == 1


def test_editing_without_a_project_says_so(tmp_path):
    session = two_model_session(tmp_path)
    assert not session.edit_project("Egal", ["eule"])["ok"]


def test_a_project_that_is_not_open_can_be_reworked(tmp_path):
    """Loading one first would mean playing it by accident, to rename it."""
    session = two_model_session(tmp_path)
    session.new_project("Erstes", ["eule"])
    session.new_project("Zweites", ["falke"])          # this one is now open

    answer = session.edit_project("Umbenannt", ["eule", "falke"], "Erstes")
    assert answer["ok"]
    # Nothing was opened, so nothing is handed back to draw.
    assert answer["project"] is None

    # The open project is untouched...
    assert session.project.name == "Zweites"
    assert session.project.models == ["falke"]
    # ...and the closed one is changed on disk.
    reread = project_module.load(tmp_path / "projects" / "Erstes")
    assert reread.name == "Umbenannt"
    assert reread.models == ["eule", "falke"]


def test_reworking_a_project_that_is_not_there_says_so(tmp_path):
    session = two_model_session(tmp_path)
    session.new_project("Da", ["eule"])
    assert not session.edit_project("Egal", ["eule"], "Nichtda")["ok"]


def test_naming_the_open_project_explicitly_still_goes_through_the_session(tmp_path):
    """Same folder, so the editor and the bridge have to hear about it."""
    session = two_model_session(tmp_path)
    session.new_project("Offen", ["eule"])
    answer = session.edit_project("Anders", None, "Offen")
    assert answer["ok"] and answer["project"] is not None
    assert session.project.name == "Anders"


def test_closing_a_project_hands_the_lights_back_to_midi(tmp_path):
    session = two_model_session(tmp_path)
    session.new_project("Nachtflug", ["eule"])
    assert session.project is not None
    session.close_project()
    assert session.project is None and session.timeline is None


# ------------------------------------------------ carrying a project around


def test_a_project_survives_being_zipped_and_unzipped(tmp_path):
    """A project is a folder on purpose, so carrying it is zipping it."""
    session = two_model_session(tmp_path)
    made = session.new_project("Nachtflug", ["eule"])["project"]["data"]
    made["light_tracks"][0]["blocks"] = [
        {"start_s": 1, "duration_s": 2, "cue": 3, "brightness": 200}]
    assert session.save_project(made)["ok"]

    data = project_module.export_zip(tmp_path / "projects" / "Nachtflug")
    answer = session.import_project(data, "Nachtflug")

    assert answer["ok"]
    # The folder was taken, so it landed beside it and said so.
    assert answer["dir"] == "Nachtflug_2"
    assert any("gibt es schon" in n for n in answer["notes"])
    copy = project_module.load(tmp_path / "projects" / "Nachtflug_2")
    assert copy.name == "Nachtflug"
    assert copy.models == ["eule"]
    assert len(copy.light_tracks[0].blocks) == 1


def test_importing_does_not_take_the_open_show_away(tmp_path):
    """Filing something is not the same as putting it on screen."""
    session = two_model_session(tmp_path)
    session.new_project("Erstes", ["eule"])
    session.new_project("Offen", ["falke"])
    data = project_module.export_zip(tmp_path / "projects" / "Erstes")

    assert session.import_project(data, "Erstes")["ok"]
    assert session.project.name == "Offen"


def test_a_project_for_models_that_are_not_here_says_so(tmp_path):
    """Its tracks would be silent, and silence explains nothing by itself."""
    session = two_model_session(tmp_path)
    session.new_project("Fremd", ["falke"])
    directory = tmp_path / "projects" / "Fremd"
    document = json.loads((directory / "project.json").read_text())
    document["models"] = ["seeadler"]
    document["light_tracks"][0]["model"] = "seeadler"
    (directory / "project.json").write_text(json.dumps(document))

    answer = session.import_project(project_module.export_zip(directory), "Fremd")
    assert answer["ok"]
    assert any("seeadler" in n for n in answer["notes"])


def test_something_that_is_not_a_project_is_refused(tmp_path):
    session = two_model_session(tmp_path)
    answer = session.import_project(b"das ist keine zip-datei", "x")
    assert not answer["ok"] and "Zip" in answer["error"]


def test_an_archive_that_writes_outside_its_folder_is_refused(tmp_path):
    """A zip may name `../../anywhere`, and unpacking one blind obeys it."""
    import io as _io
    import zipfile

    buffer = _io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("project.json", json.dumps(
            {"name": "boese", "audio_tracks": [], "light_tracks": [],
             "relay_tracks": []}))
        archive.writestr("../../entkommen.txt", "hier soll nichts landen")

    session = two_model_session(tmp_path)
    answer = session.import_project(buffer.getvalue(), "boese")
    assert not answer["ok"] and "entkommen.txt" in answer["error"]
    assert not (tmp_path / "entkommen.txt").exists()
    assert not (tmp_path / "projects" / "boese").exists()


# ------------------------------------------------- the audio folder tidying


def with_audio(session, name: str, files: list[str]) -> tuple[dict, object]:
    """A project with `files` on disk, the first of them used by a clip."""
    made = session.new_project(name, ["eule"])["project"]["data"]
    directory = session.projects_root / name
    (directory / "audio").mkdir(parents=True, exist_ok=True)
    for file in files:
        (directory / "audio" / file).write_bytes(b"nicht wirklich ton")
    made["audio_tracks"][0]["clips"] = [
        {"file": f"audio/{files[0]}", "start_s": 0, "offset_s": 0,
         "duration_s": 5}]
    assert session.save_project(made)["ok"]
    return made, directory


def test_the_file_goes_when_the_last_clip_using_it_goes(tmp_path):
    """A song swapped for another one used to leave forty megabytes behind."""
    session = two_model_session(tmp_path)
    made, directory = with_audio(session, "Ton", ["lied.wav"])

    made["audio_tracks"][0]["clips"] = []
    answer = session.save_project(made)

    assert answer["removed_audio"] == ["audio/lied.wav"]
    assert not (directory / "audio" / "lied.wav").exists()


def test_a_file_two_clips_share_stays_until_both_are_gone(tmp_path):
    session = two_model_session(tmp_path)
    made, directory = with_audio(session, "Zweimal", ["lied.wav"])
    clip = made["audio_tracks"][0]["clips"][0]
    made["audio_tracks"][0]["clips"] = [clip, {**clip, "start_s": 10}]
    assert session.save_project(made)["ok"]

    made["audio_tracks"][0]["clips"] = [clip]
    assert session.save_project(made)["removed_audio"] == []
    assert (directory / "audio" / "lied.wav").is_file()

    made["audio_tracks"][0]["clips"] = []
    assert session.save_project(made)["removed_audio"] == ["audio/lied.wav"]
    assert not (directory / "audio" / "lied.wav").exists()


def test_deleting_the_whole_track_takes_its_files_too(tmp_path):
    session = two_model_session(tmp_path)
    made, directory = with_audio(session, "Spurweg", ["lied.wav"])
    made["audio_tracks"] = made["audio_tracks"][1:]
    assert session.save_project(made)["removed_audio"] == ["audio/lied.wav"]
    assert not (directory / "audio" / "lied.wav").exists()


def test_a_file_nobody_ever_used_is_left_where_it_is(tmp_path):
    """An automatic save runs a second after every edit -- no moment to be
    deleting a file somebody copied in to use in a minute."""
    session = two_model_session(tmp_path)
    made, directory = with_audio(session, "Fremd", ["lied.wav", "spaeter.wav"])

    made["audio_tracks"][0]["clips"] = []
    assert session.save_project(made)["removed_audio"] == ["audio/lied.wav"]
    assert (directory / "audio" / "spaeter.wav").is_file()


def test_the_leftovers_are_counted_and_can_be_asked_for_by_name(tmp_path):
    session = two_model_session(tmp_path)
    _, directory = with_audio(session, "Reste", ["lied.wav", "alt.wav"])

    found = session.audio_leftovers("Reste")
    assert found["files"] == ["audio/alt.wav"] and found["bytes"] > 0

    swept = session.sweep_audio("Reste")
    assert swept["files"] == ["audio/alt.wav"]
    assert not (directory / "audio" / "alt.wav").exists()
    # The one in use is untouched.
    assert (directory / "audio" / "lied.wav").is_file()


def test_a_document_cannot_point_a_delete_out_of_the_project(tmp_path):
    """The names come from a file a person may have edited."""
    session = two_model_session(tmp_path)
    _, directory = with_audio(session, "Boese", ["lied.wav"])
    outside = tmp_path / "nicht-anfassen.txt"
    outside.write_text("bleibt")

    gone = project_module.drop_audio(directory, ["../../nicht-anfassen.txt"])
    assert gone == [] and outside.is_file()


def test_the_live_edit_arriving_first_does_not_hide_the_deletion(tmp_path):
    """The editor pushes an edit long before it saves it.

    Three hundred milliseconds to be heard, nine hundred to be written -- so by
    the time the save runs, the clip is already gone from the project in hand.
    Comparing against that would find nothing removed and delete nothing, which
    is exactly what happened the first time.
    """
    session = two_model_session(tmp_path)
    made, directory = with_audio(session, "Reihenfolge", ["lied.wav"])

    made["audio_tracks"][0]["clips"] = []
    assert session.apply_project(made)["ok"]        # what pushEdit does
    answer = session.save_project(made)             # and what the timer does

    assert answer["removed_audio"] == ["audio/lied.wav"]
    assert not (directory / "audio" / "lied.wav").exists()
