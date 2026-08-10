"""Verifies the audio engine and, more importantly, the clock it provides.

The transport is the time reference for the whole show: the light values are
evaluated at the position it reports. If it drifts, jumps on pause or keeps
running past the end, the lights do the same.
"""

from __future__ import annotations

import time

import numpy as np
import pytest
import soundfile as sf

from lightshow import project as project_module
from lightshow.audio import Transport, db_to_gain


def write_tone(path, seconds=2.0, rate=48000, freq=440.0, channels=2):
    frames = int(seconds * rate)
    t = np.arange(frames) / rate
    wave = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    data = np.repeat(wave[:, None], channels, axis=1)
    sf.write(str(path), data, rate)
    return path


@pytest.fixture
def project_with_tone(tmp_path):
    project = project_module.from_dict({"name": "t"})
    project_module.save(project, tmp_path)
    write_tone(tmp_path / "audio" / "ton.wav", seconds=2.0)
    project = project_module.from_dict({
        "name": "t",
        "audio_tracks": [{"name": "Musik", "clips": [
            {"file": "audio/ton.wav", "start_s": 1.0, "duration_s": 2.0}]}],
    }, tmp_path)
    return project


def silent(transport: Transport, monkeypatch) -> Transport:
    """Forces the no-device path, which must still keep time."""
    monkeypatch.setattr(transport, "_open", lambda: False)
    return transport


# -------------------------------------------------------------------- mixing


def test_a_clip_lands_at_its_start_time(project_with_tone):
    transport = Transport()
    transport.load(project_with_tone)

    rate = transport.rate
    assert np.max(np.abs(transport.mix[: int(0.9 * rate)])) == 0.0   # silence before
    assert np.max(np.abs(transport.mix[int(1.1 * rate): int(2.9 * rate)])) > 0.1


def test_duration_covers_the_last_clip(project_with_tone):
    transport = Transport()
    transport.load(project_with_tone)
    assert transport.duration_s == pytest.approx(3.0, abs=1.1)


def test_a_missing_file_is_reported_and_does_not_crash(tmp_path):
    project = project_module.from_dict({
        "name": "t",
        "audio_tracks": [{"name": "x", "clips": [{"file": "audio/weg.wav"}]}],
    }, tmp_path)
    transport = Transport()
    transport.load(project)
    assert any("weg.wav" in message for message in transport.messages)
    assert transport.clips[0].error


def test_muting_a_track_removes_it_from_the_mix(tmp_path, project_with_tone):
    project_with_tone.audio_tracks[0].mute = True
    transport = Transport()
    transport.load(project_with_tone)
    assert float(np.max(np.abs(transport.mix))) == 0.0


def test_clip_gain_is_applied(tmp_path, project_with_tone):
    loud = Transport()
    loud.load(project_with_tone)
    reference = float(np.max(np.abs(loud.mix)))

    project_with_tone.audio_tracks[0].clips[0].gain_db = -6.0
    quiet = Transport()
    quiet.load(project_with_tone)
    assert float(np.max(np.abs(quiet.mix))) == pytest.approx(
        reference * db_to_gain(-6.0), rel=0.02)


def test_a_fade_in_starts_from_silence(tmp_path, project_with_tone):
    project_with_tone.audio_tracks[0].clips[0].fade_in_s = 1.0
    transport = Transport()
    transport.load(project_with_tone)
    rate = transport.rate
    start = int(1.0 * rate)
    assert float(np.max(np.abs(transport.mix[start:start + 100]))) < 0.01
    assert float(np.max(np.abs(transport.mix[start + rate - 100:start + rate]))) > 0.1


def test_an_overloaded_mix_is_normalised_and_says_so(tmp_path):
    project = project_module.from_dict({"name": "t"})
    project_module.save(project, tmp_path)
    write_tone(tmp_path / "audio" / "a.wav", seconds=1.0)
    clips = [{"file": "audio/a.wav", "start_s": 0, "duration_s": 1.0, "gain_db": 6.0}]
    project = project_module.from_dict({
        "name": "t",
        "audio_tracks": [{"name": "1", "clips": clips}, {"name": "2", "clips": clips}],
    }, tmp_path)

    transport = Transport()
    transport.load(project)
    assert float(np.max(np.abs(transport.mix))) <= 1.0 + 1e-6
    assert any("normalisiert" in message for message in transport.messages)


def test_files_with_another_sample_rate_are_resampled(tmp_path):
    project = project_module.from_dict({"name": "t"})
    project_module.save(project, tmp_path)
    write_tone(tmp_path / "audio" / "a.wav", seconds=1.0, rate=48000)
    write_tone(tmp_path / "audio" / "b.wav", seconds=1.0, rate=22050)
    project = project_module.from_dict({
        "name": "t",
        "audio_tracks": [{"name": "1", "clips": [
            {"file": "audio/a.wav", "start_s": 0, "duration_s": 1.0},
            {"file": "audio/b.wav", "start_s": 2.0, "duration_s": 1.0}]}],
    }, tmp_path)

    transport = Transport()
    transport.load(project)
    assert transport.rate == 48000                  # the majority rate wins
    rate = transport.rate
    # The 22 kHz clip still occupies one second on the timeline, not half of one.
    tail = transport.mix[int(2.8 * rate): int(3.0 * rate)]
    assert float(np.max(np.abs(tail))) > 0.1


def test_waveform_peaks_are_produced_per_clip(project_with_tone):
    transport = Transport()
    transport.load(project_with_tone)
    peaks = transport.clip_peaks()
    assert len(peaks) == 1
    assert len(peaks[0]["peaks"]) > 100
    assert max(peaks[0]["peaks"]) > 0.4


# ------------------------------------------------------------------- clock


def test_the_clock_runs_without_an_audio_device(project_with_tone, monkeypatch):
    transport = silent(Transport(), monkeypatch)
    transport.load(project_with_tone)

    transport.play()
    time.sleep(0.4)
    position = transport.position()
    transport.pause()

    assert 0.2 < position < 0.8, f"Uhr lief mit {position} s statt etwa 0,4 s"


def test_pausing_holds_the_position(project_with_tone, monkeypatch):
    transport = silent(Transport(), monkeypatch)
    transport.load(project_with_tone)

    transport.play()
    time.sleep(0.3)
    transport.pause()
    first = transport.position()
    time.sleep(0.3)

    assert transport.position() == pytest.approx(first, abs=0.01)


def test_resuming_continues_where_it_stopped(project_with_tone, monkeypatch):
    transport = silent(Transport(), monkeypatch)
    transport.load(project_with_tone)

    transport.play()
    time.sleep(0.3)
    transport.pause()
    paused = transport.position()
    transport.play()
    time.sleep(0.2)
    transport.pause()

    assert transport.position() > paused


def test_seeking_moves_the_play_head(project_with_tone, monkeypatch):
    transport = silent(Transport(), monkeypatch)
    transport.load(project_with_tone)
    transport.seek(1.5)
    assert transport.position() == pytest.approx(1.5, abs=0.01)


def test_seeking_cannot_run_off_either_end(project_with_tone, monkeypatch):
    transport = silent(Transport(), monkeypatch)
    transport.load(project_with_tone)

    transport.seek(-10)
    assert transport.position() == 0.0
    transport.seek(9999)
    assert transport.position() <= transport.duration_s + 0.01


def test_stop_rewinds(project_with_tone, monkeypatch):
    transport = silent(Transport(), monkeypatch)
    transport.load(project_with_tone)
    transport.seek(1.0)
    transport.stop()
    assert transport.position() == 0.0
    assert not transport.playing


def test_playback_ends_by_itself_at_the_end(project_with_tone, monkeypatch):
    transport = silent(Transport(), monkeypatch)
    transport.load(project_with_tone)
    transport.seek(transport.duration_s - 0.2)
    transport.play()

    for _ in range(40):
        time.sleep(0.05)
        if not transport.playing:
            break
    assert not transport.playing, "Transport lief über das Ende hinaus weiter"


def test_stop_rewinds_with_a_real_device_too(project_with_tone):
    """Regression: a callback in flight used to move the head after the reset."""
    transport = Transport()
    transport.load(project_with_tone)
    transport.play()
    time.sleep(0.2)
    if transport.state()["device"] is False:
        transport.stop()
        pytest.skip("kein Audiogerät verfügbar")

    transport.stop()
    assert transport.position() == 0.0
    assert not transport.playing
    transport.close()


def test_concurrent_play_opens_only_one_stream(project_with_tone, monkeypatch):
    """Regression: every web request is its own thread.

    Two quick clicks on play used to open two PortAudio streams. The one that
    lost the race was garbage collected while its audio thread was still
    calling into it, and PortAudio then jumped into freed memory -- a segfault
    a few seconds later, far away from the cause.
    """
    import threading as th

    transport = Transport()
    transport.load(project_with_tone)

    opened = []

    class FakeStream:
        latency = 0.01

        def __init__(self, **kwargs):
            # Opening a real PortAudio stream takes milliseconds; without that
            # delay the GIL hides the race the test is about.
            time.sleep(0.02)
            opened.append(self)
            self.closed = False

        def start(self):
            pass

        def abort(self):
            pass

        def close(self):
            self.closed = True

    fake_sd = type("sd", (), {"OutputStream": FakeStream})
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", fake_sd)

    barrier = th.Barrier(8)

    def hammer():
        barrier.wait()
        transport.play()

    threads = [th.Thread(target=hammer) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(opened) == 1, f"{len(opened)} Streams geöffnet statt einem"
    transport.close()
    assert opened[0].closed


def test_closing_closes_the_stream_exactly_once(project_with_tone, monkeypatch):
    """Six threads, one close. A double close used to free a live callback."""
    import threading as th

    transport = Transport()
    transport.load(project_with_tone)

    closes = []

    class FakeStream:
        latency = 0.0

        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def abort(self):
            time.sleep(0.02)

        def close(self):
            closes.append(1)

    monkeypatch.setitem(__import__("sys").modules, "sounddevice",
                        type("sd", (), {"OutputStream": FakeStream}))
    transport.play()

    barrier = th.Barrier(6)

    def hammer():
        barrier.wait()
        transport.close()

    threads = [th.Thread(target=hammer) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(closes) == 1, f"{len(closes)}x geschlossen statt einmal"


def test_a_stream_that_will_not_close_is_kept_alive(project_with_tone, monkeypatch):
    """Better a leaked callback than a freed one -- freed means segfault."""
    transport = Transport()
    transport.load(project_with_tone)

    class StubbornStream:
        latency = 0.0

        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def abort(self):
            raise RuntimeError("PortAudio mag nicht")

        def close(self):
            raise RuntimeError("PortAudio mag nicht")

    monkeypatch.setitem(__import__("sys").modules, "sounddevice",
                        type("sd", (), {"OutputStream": StubbornStream}))
    transport.play()
    transport.close()
    assert len(transport._retired) == 1


def test_repeated_play_does_not_stack_up_clock_threads(project_with_tone, monkeypatch):
    """A second silent clock would make time run at double speed."""
    monkeypatch.setattr(Transport, "_open", lambda self: False)
    transport = Transport()
    transport.load(project_with_tone)

    for _ in range(5):
        transport.play()
    time.sleep(0.4)
    position = transport.position()
    transport.pause()

    assert 0.2 < position < 0.8, f"Uhr lief mit {position} s -- mehrere Clock-Threads?"


def test_state_reports_a_missing_device_instead_of_pretending(project_with_tone,
                                                              monkeypatch):
    transport = Transport()
    transport.load(project_with_tone)
    monkeypatch.setattr(transport, "_open", lambda: False)
    transport.play()
    state = transport.state()
    assert state["playing"] and not state["device"]
    transport.pause()


# ------------------------------------------------------- length of the show


def test_duration_is_the_show_not_the_padding(project_with_tone):
    """The mix carries a second of tail; the show does not.

    Reporting the padded length put the end marker in the editor a second
    behind the last note and let the play head wander into silence.
    """
    transport = Transport()
    transport.load(project_with_tone)
    assert transport.duration_s == pytest.approx(3.0, abs=0.01)
    assert transport.mix.shape[0] > transport.duration_s * transport.rate


def test_seeking_past_the_end_stops_at_the_end(project_with_tone, monkeypatch):
    transport = silent(Transport(), monkeypatch)
    transport.load(project_with_tone)
    transport.seek(9999)
    assert transport.position() == pytest.approx(transport.duration_s, abs=0.01)


def test_a_clip_without_a_length_plays_to_the_end_of_the_file(tmp_path):
    """duration_s of 0 means "to the end of the file".

    Only the file knows how long that is, so a project whose clips all say 0
    used to be mixed down to a single second of tail.
    """
    project = project_module.from_dict({"name": "t"})
    project_module.save(project, tmp_path)
    write_tone(tmp_path / "audio" / "lang.wav", seconds=4.0)

    project = project_module.from_dict({
        "name": "t",
        "audio_tracks": [{"name": "Musik", "clips": [
            {"file": "audio/lang.wav", "start_s": 2.0, "duration_s": 0}]}],
    }, tmp_path)

    transport = Transport()
    transport.load(project)

    assert transport.duration_s == pytest.approx(6.0, abs=0.05)
    rate = transport.rate
    assert np.max(np.abs(transport.mix[int(5.0 * rate):int(5.9 * rate)])) > 0.1


def test_an_offset_shortens_what_is_left_of_the_file(tmp_path):
    project = project_module.from_dict({"name": "t"})
    project_module.save(project, tmp_path)
    write_tone(tmp_path / "audio" / "lang.wav", seconds=4.0)

    project = project_module.from_dict({
        "name": "t",
        "audio_tracks": [{"name": "Musik", "clips": [
            {"file": "audio/lang.wav", "start_s": 0, "offset_s": 3.0, "duration_s": 0}]}],
    }, tmp_path)

    transport = Transport()
    transport.load(project)
    assert transport.duration_s == pytest.approx(1.0, abs=0.05)


# ------------------------------------------------------------ pause and device


def test_pausing_actually_silences_the_output(project_with_tone):
    """Pause used to leave the stream running, so the music played on.

    The play head froze while the audio kept draining the mix, which is the
    worst of both: the show says it stopped and the field still hears music.
    """
    transport = Transport()
    transport.load(project_with_tone)

    calls = []
    real = transport._callback

    def spy(outdata, frames, time_info, status):
        real(outdata, frames, time_info, status)
        calls.append(float(np.max(np.abs(outdata))))

    # The stream captures the callback when it opens, so the spy goes in first.
    transport._callback = spy
    transport.play()
    time.sleep(0.25)
    if not transport.state()["device"]:
        transport.close()
        pytest.skip("kein Audiogerät verfügbar")

    transport.pause()
    head = transport.position()
    calls.clear()
    time.sleep(0.4)

    assert calls, "der Stream läuft nicht mehr — der Test misst nichts"
    assert max(calls) == 0.0, "nach pause() kam noch Ton aus dem Puffer"
    assert transport.position() == pytest.approx(head, abs=0.01), \
        "der Abspielkopf ist nach pause() weitergelaufen"
    transport.close()


def test_stop_keeps_the_device_so_the_next_play_is_immediate(project_with_tone):
    """Opening a stream costs a second or more; a show cannot pay that on play."""
    transport = Transport()
    transport.load(project_with_tone)
    transport.play()
    time.sleep(0.2)
    if not transport.state()["device"]:
        transport.close()
        pytest.skip("kein Audiogerät verfügbar")

    transport.stop()
    assert transport.position() == 0.0
    assert transport.state()["device"], "stop() hat das Gerät wieder hergegeben"

    started = time.monotonic()
    transport.play()
    assert time.monotonic() - started < 0.25, "play() musste das Gerät erst öffnen"
    transport.close()
    assert not transport.state()["device"]


def test_the_reported_latency_is_visible(project_with_tone):
    """If sound still arrives late, this is the number to look at."""
    transport = Transport()
    transport.load(project_with_tone)
    state = transport.state()
    assert "latency_ms" in state and state["latency_ms"] >= 0
    transport.close()


def test_play_at_the_end_starts_over(project_with_tone, monkeypatch):
    """A transport parked at the end used to swallow every press of play.

    play() set the flag, the next callback saw the head past the limit and
    cleared it again -- so the button, and the space bar, did nothing at all
    once a show had run out.
    """
    transport = silent(Transport(), monkeypatch)
    transport.load(project_with_tone)
    transport.seek(transport.duration_s)
    assert transport.position() == pytest.approx(transport.duration_s, abs=0.01)

    transport.play()
    assert transport.playing, "play() am Ende hat nichts getan"
    assert transport.position() < 0.5, "es wurde nicht an den Anfang gesprungen"
    transport.close()


def test_play_from_a_given_position_does_not_rewind(project_with_tone, monkeypatch):
    """Only the bare play() restarts; seeking somewhere explicit still wins."""
    transport = silent(Transport(), monkeypatch)
    transport.load(project_with_tone)
    transport.seek(transport.duration_s)
    transport.play(1.0)
    assert transport.position() == pytest.approx(1.0, abs=0.05)
    transport.close()
