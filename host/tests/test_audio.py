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
    transport.stop()
    assert opened[0].closed


def test_stopping_closes_the_stream_exactly_once(project_with_tone, monkeypatch):
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
        transport.stop()

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
    transport.stop()
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
