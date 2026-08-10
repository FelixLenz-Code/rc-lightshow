"""Audio playback and the transport clock of a show.

The bridge plays the music itself, which makes it the clock: the light values
are evaluated at the position this transport reports, so sound and light come
from the same process and cannot drift apart.

The whole project is mixed down once when it is loaded, rather than decoded in
the audio callback. A few minutes of stereo cost a hundred megabytes or so and
buy a callback that only copies a slice -- no glitches, and seeking is free.

Without a usable output device the transport still runs on the wall clock. The
lights then work exactly as they would with sound, which is what makes the show
testable on a machine that has no audio at all.
"""

from __future__ import annotations

import atexit
import threading
import time
import weakref
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .project import AudioClip, Project

DEFAULT_RATE = 48000
BLOCKSIZE = 1024
PEAKS_PER_CLIP = 800


# Every transport that still holds a device. Now that stop() keeps the stream
# open, something has to hand it back when the process ends -- PortAudio calling
# into a half torn down interpreter is a crash, not a warning.
_LIVE: weakref.WeakSet = weakref.WeakSet()


@atexit.register
def _release_devices() -> None:
    for transport in list(_LIVE):
        try:
            transport.close()
        except Exception:               # noqa: BLE001 - shutdown, report nothing
            pass


def db_to_gain(db: float) -> float:
    return float(10.0 ** (db / 20.0))


@dataclass
class ClipInfo:
    track: int
    clip: int
    file: str
    start_s: float
    duration_s: float
    peaks: list[float] = field(default_factory=list)
    error: str = ""


def _resample(data: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Linear resampling; only used when a file's rate differs from the mix."""
    if source_rate == target_rate or data.size == 0:
        return data
    count = int(round(data.shape[0] * target_rate / source_rate))
    source_index = np.linspace(0.0, data.shape[0] - 1, count)
    out = np.empty((count, data.shape[1]), dtype=np.float32)
    grid = np.arange(data.shape[0])
    for channel in range(data.shape[1]):
        out[:, channel] = np.interp(source_index, grid, data[:, channel])
    return out


def _apply_fades(data: np.ndarray, rate: int, clip: AudioClip) -> None:
    frames = data.shape[0]
    fade_in = min(int(clip.fade_in_s * rate), frames)
    if fade_in > 0:
        data[:fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32)[:, None]
    fade_out = min(int(clip.fade_out_s * rate), frames)
    if fade_out > 0:
        data[frames - fade_out:] *= np.linspace(
            1.0, 0.0, fade_out, dtype=np.float32)[:, None]


class Transport:
    """Owns playback and the clock. Thread safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Guards the stream's life cycle. Every web request runs in its own
        # thread, so two quick clicks on play used to open two PortAudio
        # streams; the one that lost the race was garbage collected while its
        # audio thread was still calling into it, and PortAudio then jumped
        # into freed memory. Opening, closing and starting are serialised here.
        self._device_lock = threading.RLock()
        # Streams that could not be closed cleanly are kept alive rather than
        # collected -- a freed callback is a segfault, a leaked one is not.
        self._retired: list = []
        self._clock_thread: threading.Thread | None = None
        self.rate = DEFAULT_RATE
        self.mix: np.ndarray = np.zeros((0, 2), dtype=np.float32)
        self.clips: list[ClipInfo] = []
        self.messages: list[str] = []
        self.device_error: str = ""

        self._stream = None
        self._playing = False
        self._frame = 0                 # play head in frames
        self._frame_at = time.monotonic()
        self._latency = 0.0
        self.device_name = ""
        self._loaded_duration = 0.0
        _LIVE.add(self)

    # ------------------------------------------------------------- loading

    def load(self, project: Project) -> None:
        """Mixes the project down. Playback stops while this happens."""
        self.pause()
        messages: list[str] = []
        clips: list[ClipInfo] = []

        import soundfile as sf

        # Probe every clip once: it settles the mix rate, and for clips that
        # run "to the end of the file" it is the only place their real length
        # is known.
        rates: list[int] = []
        lengths: dict[tuple[int, int], float] = {}
        for track_index, track in enumerate(project.audio_tracks):
            for clip_index, clip in enumerate(track.clips):
                path = self._resolve(project, clip)
                if path is None:
                    continue
                try:
                    info = sf.info(str(path))
                except Exception:       # noqa: BLE001 - unreadable file, reported later
                    continue
                rates.append(info.samplerate)
                lengths[(track_index, clip_index)] = max(
                    0.0, info.frames / info.samplerate - clip.offset_s)
        # Mixing at the rate most files already use avoids resampling entirely
        # in the common case of one album and a few effects.
        new_rate = max(set(rates), key=rates.count) if rates else DEFAULT_RATE

        # Only hand the device back when the rate actually changes. Editing a
        # clip remixes the project, and reopening the output for every drag
        # would cost a second or more each time.
        if new_rate != self.rate:
            self.close()
        self.rate = new_rate

        # duration_s of 0 means "play to the end of the file", which the project
        # itself cannot resolve -- without this the mix would be cut short.
        total = project.duration_s
        for (track_index, clip_index), length in lengths.items():
            clip = project.audio_tracks[track_index].clips[clip_index]
            if clip.duration_s <= 0:
                total = max(total, clip.start_s + length)

        frames = int(total * self.rate) + self.rate     # a second of tail
        mix = np.zeros((max(frames, 1), 2), dtype=np.float32)

        for track_index, track in enumerate(project.audio_tracks):
            track_gain = 0.0 if track.mute else db_to_gain(track.gain_db)
            for clip_index, clip in enumerate(track.clips):
                info = ClipInfo(track=track_index, clip=clip_index, file=clip.file,
                                start_s=clip.start_s, duration_s=clip.duration_s)
                clips.append(info)

                path = self._resolve(project, clip)
                if path is None:
                    info.error = f"{clip.file} nicht gefunden"
                    messages.append(info.error)
                    continue

                try:
                    data, source_rate = self._read(sf, path, clip)
                except Exception as exc:        # noqa: BLE001
                    info.error = f"{clip.file}: {exc}"
                    messages.append(info.error)
                    continue

                data = _resample(data, source_rate, self.rate)
                if clip.duration_s <= 0:
                    info.duration_s = data.shape[0] / self.rate
                _apply_fades(data, self.rate, clip)
                info.peaks = self._peaks(data)

                data = data * (track_gain * db_to_gain(clip.gain_db))
                start = int(clip.start_s * self.rate)
                end = min(start + data.shape[0], mix.shape[0])
                if end > start:
                    mix[start:end] += data[:end - start]

        peak = float(np.max(np.abs(mix))) if mix.size else 0.0
        if peak > 1.0:
            mix /= peak
            messages.append(f"Summe war {peak:.1f}x zu laut und wurde normalisiert "
                            f"— besser die Clip-Lautstärken senken")

        with self._lock:
            self.mix = mix
            self.clips = clips
            self.messages = messages
            self._frame = 0
            self._frame_at = time.monotonic()
            self._loaded_duration = total


    @staticmethod
    def _resolve(project: Project, clip: AudioClip) -> Path | None:
        if project.path is None:
            return None
        path = project.path / clip.file
        return path if path.is_file() else None

    def _read(self, sf, path: Path, clip: AudioClip) -> tuple[np.ndarray, int]:
        info = sf.info(str(path))
        start = int(clip.offset_s * info.samplerate)
        stop = None
        if clip.duration_s > 0:
            stop = start + int(clip.duration_s * info.samplerate)
        data, rate = sf.read(str(path), start=start, stop=stop,
                             dtype="float32", always_2d=True)
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2]
        return np.ascontiguousarray(data), rate

    @staticmethod
    def _peaks(data: np.ndarray) -> list[float]:
        if data.shape[0] == 0:
            return []
        mono = np.max(np.abs(data), axis=1)
        buckets = min(PEAKS_PER_CLIP, mono.shape[0])
        edges = np.linspace(0, mono.shape[0], buckets + 1).astype(int)
        return [float(mono[a:b].max()) if b > a else 0.0
                for a, b in zip(edges, edges[1:])]

    # ----------------------------------------------------------- transport

    @property
    def duration_s(self) -> float:
        """Length of the show.

        The mix buffer carries a second of padding behind it so a clip that
        ends on a rounded frame is never clipped. That padding is not part of
        the show, and reporting it would put the end marker in the editor a
        second past the last note.
        """
        return self._loaded_duration

    def set_duration(self, seconds: float) -> None:
        """Moves the end of the show without remixing a single sample.

        A show is as long as the last thing on any track, and light blocks
        count towards that. Placing one past the end of the music has to extend
        the show -- but it does not change the audio, so the buffer is padded
        with silence instead of every file being read again.
        """
        with self._lock:
            self._loaded_duration = max(0.0, seconds)
            needed = int(self._loaded_duration * self.rate) + self.rate
            if needed > self.mix.shape[0]:
                grown = np.zeros((needed, 2), dtype=np.float32)
                grown[:self.mix.shape[0]] = self.mix
                self.mix = grown

    def _limit(self) -> int:
        """Last frame the play head may reach. The caller holds ``_lock``."""
        return min(self.mix.shape[0], max(0, round(self._loaded_duration * self.rate)))

    def position(self) -> float:
        """Play head in seconds, interpolated between audio callbacks.

        The callback only fires every few milliseconds, which would be a coarse
        clock for the light. Adding the time since the last callback -- minus
        the output latency, so it matches what is actually audible -- gives a
        smooth position.
        """
        with self._lock:
            return self._position_locked()

    def _position_locked(self) -> float:
        """``position()`` for callers that already hold ``_lock``."""
        base = self._frame / self.rate
        if not self._playing:
            return base
        elapsed = time.monotonic() - self._frame_at
        return max(0.0, base + elapsed - self._latency)

    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ARG002
        with self._lock:
            # A paused transport keeps the device open but feeds it silence.
            # Draining the mix here instead would keep the music running after
            # pause, which is what it used to do.
            if not self._playing:
                outdata[:] = 0
                return

            limit = self._limit()
            start = self._frame
            end = min(start + frames, limit)
            count = max(0, end - start)
            if count:
                outdata[:count] = self.mix[start:end]
            if count < frames:
                outdata[count:] = 0
            self._frame = max(start, end)
            self._frame_at = time.monotonic()
            if end >= limit:
                self._playing = False

    def _open(self) -> bool:
        with self._device_lock:
            if self._stream is not None:
                return True
            stream = None
            try:
                import sounddevice as sd

                stream = sd.OutputStream(samplerate=self.rate, channels=2,
                                         dtype="float32", blocksize=BLOCKSIZE,
                                         callback=self._callback)
                stream.start()
            except Exception as exc:    # noqa: BLE001 - no device, busy, no PortAudio
                self.device_error = str(exc)
                if stream is not None:
                    # Constructed but not started: close it here, otherwise the
                    # callback would be freed while PortAudio may still hold it.
                    self._discard(stream)
                return False

            self._stream = stream
            try:
                import sounddevice as sd

                self.device_name = str(sd.query_devices(stream.device)["name"])
            except Exception:               # noqa: BLE001 - only a label
                self.device_name = ""
            latency = getattr(stream, "latency", 0.0)
            self._latency = float(latency[0] if isinstance(latency, (tuple, list))
                                  else latency or 0.0)
            self.device_error = ""
            return True

    def _discard(self, stream) -> None:
        """Closes a stream, keeping it referenced if closing failed."""
        try:
            stream.abort()
            stream.close()
        except Exception:               # noqa: BLE001
            self._retired.append(stream)

    def play(self, at: float | None = None) -> None:
        if at is not None:
            self.seek(at)
        else:
            with self._lock:
                # Pressing play at the end means play it again. Without this the
                # transport starts and the next callback stops it in the same
                # breath, so the button looks broken once a show has run out.
                limit = self._limit()
                if limit and self._frame >= limit:
                    self._frame = 0
                    self._frame_at = time.monotonic()

        with self._device_lock:
            has_device = self._open()
            with self._lock:
                self._playing = True
                self._frame_at = time.monotonic()
            if not has_device:
                # Silent transport: the clock still runs so the lights do too.
                # Only ever one clock thread, or time would run at double speed.
                if self._clock_thread is None or not self._clock_thread.is_alive():
                    self._clock_thread = threading.Thread(
                        target=self._silent_clock, daemon=True, name="silent-clock")
                    self._clock_thread.start()

    def _silent_clock(self) -> None:
        while True:
            time.sleep(0.05)
            with self._lock:
                if not self._playing or self._stream is not None:
                    return
                now = time.monotonic()
                self._frame += int((now - self._frame_at) * self.rate)
                self._frame_at = now
                limit = self._limit()
                if self._frame >= limit:
                    self._frame = limit
                    self._playing = False
                    return

    def pause(self) -> None:
        with self._lock:
            if self._playing:
                # Stop exactly where it sounded like it stopped, latency and
                # all, so resuming does not jump.
                self._frame = max(0, min(int(self._position_locked() * self.rate),
                                         self._limit()))
            self._playing = False
            self._frame_at = time.monotonic()

    def stop(self) -> None:
        """Back to the start. The device stays open.

        Opening an output stream costs a second or two here and much more on a
        device that has to wake up first. Doing that on every press of play put
        the whole show behind the button; keeping the stream and feeding it
        silence makes play instant.
        """
        self.pause()
        with self._lock:
            self._frame = 0
            self._frame_at = time.monotonic()

    def close(self) -> None:
        """Releases the audio device. The stream is closed exactly once."""
        self.pause()
        with self._device_lock:
            stream, self._stream = self._stream, None
            if stream is not None:
                self._discard(stream)
        with self._lock:
            self._frame_at = time.monotonic()

    def seek(self, seconds: float) -> None:
        with self._lock:
            self._frame = max(0, min(int(seconds * self.rate), self._limit()))
            self._frame_at = time.monotonic()

    @property
    def playing(self) -> bool:
        with self._lock:
            return self._playing

    def state(self) -> dict:
        return {
            "playing": self.playing,
            "position": round(self.position(), 3),
            "duration": round(self.duration_s, 3),
            "rate": self.rate,
            "device": self._stream is not None,
            "device_name": self.device_name,
            # What the output buffer costs. The position is corrected by it,
            # but if sound still arrives late this is the number to look at.
            "latency_ms": round(self._latency * 1000, 1),
            "device_error": self.device_error,
            "messages": list(self.messages),
        }

    def clip_peaks(self) -> list[dict]:
        return [
            {"track": info.track, "clip": info.clip, "file": info.file,
             "start_s": info.start_s, "duration_s": round(info.duration_s, 3),
             "peaks": [round(value, 3) for value in info.peaks],
             "error": info.error}
            for info in self.clips
        ]
