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

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .project import AudioClip, Project

DEFAULT_RATE = 48000
BLOCKSIZE = 1024
PEAKS_PER_CLIP = 800


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
        self._loaded_duration = 0.0

    # ------------------------------------------------------------- loading

    def load(self, project: Project) -> None:
        """Mixes the project down. Playback stops while this happens."""
        self.stop()
        messages: list[str] = []
        clips: list[ClipInfo] = []

        import soundfile as sf

        rates: list[int] = []
        for track in project.audio_tracks:
            for clip in track.clips:
                path = self._resolve(project, clip)
                if path is None:
                    continue
                try:
                    rates.append(sf.info(str(path)).samplerate)
                except Exception:       # noqa: BLE001 - unreadable file, reported later
                    continue
        # Mixing at the rate most files already use avoids resampling entirely
        # in the common case of one album and a few effects.
        self.rate = max(set(rates), key=rates.count) if rates else DEFAULT_RATE

        total = project.duration_s
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
        return max(self._loaded_duration, self.mix.shape[0] / self.rate
                   if self.rate else 0.0)

    def position(self) -> float:
        """Play head in seconds, interpolated between audio callbacks.

        The callback only fires every few milliseconds, which would be a coarse
        clock for the light. Adding the time since the last callback -- minus
        the output latency, so it matches what is actually audible -- gives a
        smooth position.
        """
        with self._lock:
            base = self._frame / self.rate
            if not self._playing:
                return base
            elapsed = time.monotonic() - self._frame_at
            return max(0.0, base + elapsed - self._latency)

    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ARG002
        with self._lock:
            start = self._frame
            end = min(start + frames, self.mix.shape[0])
            count = max(0, end - start)
            if count:
                outdata[:count] = self.mix[start:end]
            if count < frames:
                outdata[count:] = 0
            self._frame = end
            self._frame_at = time.monotonic()
            if end >= self.mix.shape[0]:
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
                if self.mix.shape[0] and self._frame >= self.mix.shape[0]:
                    self._playing = False
                    return

    def pause(self) -> None:
        with self._lock:
            if self._playing:
                # Fold the interpolated part back in so pausing does not jump.
                self._frame += int((time.monotonic() - self._frame_at) * self.rate)
                self._frame = max(0, min(self._frame, max(0, self.mix.shape[0])))
            self._playing = False
            self._frame_at = time.monotonic()

    def stop(self) -> None:
        # Close the stream first: a callback still in flight would otherwise
        # advance the play head again right after it was reset.
        self.pause()
        with self._device_lock:
            stream, self._stream = self._stream, None
            if stream is not None:
                self._discard(stream)
        with self._lock:
            self._frame = 0
            self._frame_at = time.monotonic()

    def seek(self, seconds: float) -> None:
        with self._lock:
            limit = max(0, self.mix.shape[0])
            self._frame = max(0, min(int(seconds * self.rate), limit))
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
