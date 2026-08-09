"""Show projects: audio tracks, light tracks and how they are stored.

A project is a directory so it can be copied to another machine in one piece:

    projects/nachtflug/
        project.json
        audio/musik.mp3

Audio files dragged into the editor are copied into ``audio/`` rather than
referenced where they happen to lie, so a project does not fall apart when the
Downloads folder is tidied up.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_FILE = "project.json"
AUDIO_DIR = "audio"
VERSION = 1

# Effects the airborne firmware implements; the editor offers these by name.
CUE_NAMES = [
    "aus", "Dauerlicht", "Atmen", "Strobe", "Doppelstrobe", "Lauflicht",
    "Komet", "Funkeln", "Regenbogen", "Polizei", "Theater-Chase",
]


class ProjectError(Exception):
    """Raised with a message naming the offending part of the project."""


def safe_name(name: str) -> str:
    """A file system friendly directory name, without surprises."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip()).strip("._")
    return cleaned or "projekt"


@dataclass
class AudioClip:
    file: str                 # relative to the project directory
    start_s: float = 0.0      # position on the timeline
    offset_s: float = 0.0     # where playback starts inside the file
    duration_s: float = 0.0   # 0 means "to the end of the file"
    gain_db: float = 0.0
    fade_in_s: float = 0.0
    fade_out_s: float = 0.0

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s


@dataclass
class AudioTrack:
    name: str = "Audio"
    gain_db: float = 0.0
    mute: bool = False
    clips: list[AudioClip] = field(default_factory=list)


@dataclass
class LightBlock:
    """One effect on one zone, for a stretch of time."""

    start_s: float
    duration_s: float
    cue: int = 1              # effect index, 0 = off
    hue: int = 0              # 0..255
    brightness: int = 255     # 0..255, before the fades
    param: int = 128          # speed / second parameter
    fade_in_s: float = 0.0
    fade_out_s: float = 0.0
    label: str = ""

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s


@dataclass
class LightTrack:
    model: str
    zone: int = 0
    name: str = ""
    blocks: list[LightBlock] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.name or f"{self.model} Zone {self.zone}"


@dataclass
class Project:
    name: str = "unbenannt"
    path: Path | None = None
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    light_tracks: list[LightTrack] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        ends = [clip.end_s for track in self.audio_tracks for clip in track.clips]
        ends += [block.end_s for track in self.light_tracks for block in track.blocks]
        return max(ends) if ends else 0.0

    def track_for(self, model: str, zone: int) -> LightTrack | None:
        for track in self.light_tracks:
            if track.model == model and track.zone == zone:
                return track
        return None


# ------------------------------------------------------------------ parsing


def _num(value: Any, name: str, where: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ProjectError(f"{where}: '{name}' ist keine Zahl") from None
    if not low <= number <= high:
        raise ProjectError(f"{where}: '{name}' muss zwischen {low} und {high} liegen")
    return number


def _clip_from(data: dict, where: str) -> AudioClip:
    if not data.get("file"):
        raise ProjectError(f"{where}: 'file' fehlt")
    clip = AudioClip(
        file=str(data["file"]),
        start_s=_num(data.get("start_s", 0), "start_s", where, 0, 86400),
        offset_s=_num(data.get("offset_s", 0), "offset_s", where, 0, 86400),
        duration_s=_num(data.get("duration_s", 0), "duration_s", where, 0, 86400),
        gain_db=_num(data.get("gain_db", 0), "gain_db", where, -60, 12),
        fade_in_s=_num(data.get("fade_in_s", 0), "fade_in_s", where, 0, 3600),
        fade_out_s=_num(data.get("fade_out_s", 0), "fade_out_s", where, 0, 3600),
    )
    if ".." in clip.file or Path(clip.file).is_absolute():
        raise ProjectError(f"{where}: 'file' muss innerhalb des Projekts liegen")
    return clip


def _block_from(data: dict, where: str) -> LightBlock:
    block = LightBlock(
        start_s=_num(data.get("start_s", 0), "start_s", where, 0, 86400),
        duration_s=_num(data.get("duration_s", 1), "duration_s", where, 0.01, 86400),
        cue=int(_num(data.get("cue", 1), "cue", where, 0, 31)),
        hue=int(_num(data.get("hue", 0), "hue", where, 0, 255)),
        brightness=int(_num(data.get("brightness", 255), "brightness", where, 0, 255)),
        param=int(_num(data.get("param", 128), "param", where, 0, 255)),
        fade_in_s=_num(data.get("fade_in_s", 0), "fade_in_s", where, 0, 3600),
        fade_out_s=_num(data.get("fade_out_s", 0), "fade_out_s", where, 0, 3600),
        label=str(data.get("label", "")),
    )
    if block.fade_in_s + block.fade_out_s > block.duration_s:
        raise ProjectError(
            f"{where}: Ein- und Ausblendung ({block.fade_in_s} + {block.fade_out_s} s) "
            f"passen nicht in {block.duration_s} s"
        )
    return block


def from_dict(data: dict, path: Path | None = None) -> Project:
    if not isinstance(data, dict):
        raise ProjectError("Projekt: oberste Ebene muss ein Objekt sein")

    project = Project(name=str(data.get("name", "unbenannt")), path=path)

    for index, entry in enumerate(data.get("audio_tracks") or []):
        where = f"audio_tracks[{index}]"
        track = AudioTrack(
            name=str(entry.get("name", f"Audio {index + 1}")),
            gain_db=_num(entry.get("gain_db", 0), "gain_db", where, -60, 12),
            mute=bool(entry.get("mute", False)),
        )
        track.clips = [_clip_from(clip, f"{where}.clips[{i}]")
                       for i, clip in enumerate(entry.get("clips") or [])]
        project.audio_tracks.append(track)

    seen: set[tuple[str, int]] = set()
    for index, entry in enumerate(data.get("light_tracks") or []):
        where = f"light_tracks[{index}]"
        if not entry.get("model"):
            raise ProjectError(f"{where}: 'model' fehlt")
        track = LightTrack(
            model=str(entry["model"]),
            zone=int(_num(entry.get("zone", 0), "zone", where, 0, 3)),
            name=str(entry.get("name", "")),
        )
        key = (track.model, track.zone)
        if key in seen:
            raise ProjectError(f"{where}: {track.model} Zone {track.zone} gibt es doppelt")
        seen.add(key)

        track.blocks = [_block_from(block, f"{where}.blocks[{i}]")
                        for i, block in enumerate(entry.get("blocks") or [])]
        track.blocks.sort(key=lambda block: block.start_s)

        # One zone shows one effect at a time, so overlapping blocks would be
        # ambiguous rather than a crossfade.
        for earlier, later in zip(track.blocks, track.blocks[1:]):
            if later.start_s < earlier.end_s - 1e-6:
                raise ProjectError(
                    f"{where}: Bloecke ueberlappen bei {later.start_s:.2f} s "
                    f"('{earlier.label or earlier.cue}' und '{later.label or later.cue}') "
                    f"-- eine Zone zeigt immer nur einen Effekt"
                )
        project.light_tracks.append(track)

    return project


def to_dict(project: Project) -> dict:
    return {
        "version": VERSION,
        "name": project.name,
        "audio_tracks": [
            {
                "name": track.name,
                "gain_db": track.gain_db,
                "mute": track.mute,
                "clips": [
                    {
                        "file": clip.file,
                        "start_s": clip.start_s,
                        "offset_s": clip.offset_s,
                        "duration_s": clip.duration_s,
                        "gain_db": clip.gain_db,
                        "fade_in_s": clip.fade_in_s,
                        "fade_out_s": clip.fade_out_s,
                    }
                    for clip in track.clips
                ],
            }
            for track in project.audio_tracks
        ],
        "light_tracks": [
            {
                "model": track.model,
                "zone": track.zone,
                "name": track.name,
                "blocks": [
                    {
                        "start_s": block.start_s,
                        "duration_s": block.duration_s,
                        "cue": block.cue,
                        "hue": block.hue,
                        "brightness": block.brightness,
                        "param": block.param,
                        "fade_in_s": block.fade_in_s,
                        "fade_out_s": block.fade_out_s,
                        "label": block.label,
                    }
                    for block in track.blocks
                ],
            }
            for track in project.light_tracks
        ],
    }


# ------------------------------------------------------------ disk handling


def load(path: str | Path) -> Project:
    path = Path(path)
    directory = path.parent if path.name == PROJECT_FILE else path
    file = directory / PROJECT_FILE
    try:
        data = json.loads(file.read_text())
    except FileNotFoundError:
        raise ProjectError(f"{file} gibt es nicht") from None
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{file}: {exc}") from exc
    return from_dict(data, directory)


def save(project: Project, path: str | Path | None = None) -> Path:
    directory = Path(path) if path is not None else project.path
    if directory is None:
        raise ProjectError("Projekt hat keinen Speicherort")
    directory = Path(directory)
    (directory / AUDIO_DIR).mkdir(parents=True, exist_ok=True)

    text = json.dumps(to_dict(project), indent=2, ensure_ascii=False)
    from_dict(json.loads(text))     # never leave an unloadable project behind

    file = directory / PROJECT_FILE
    if file.exists():
        (directory / (PROJECT_FILE + ".bak")).write_text(file.read_text())
    file.write_text(text)
    project.path = directory
    return file


def import_audio(project: Project, source: str | Path) -> str:
    """Copies a file into the project and returns its relative path."""
    if project.path is None:
        raise ProjectError("Projekt muss erst gespeichert werden")
    source = Path(source)
    if not source.is_file():
        raise ProjectError(f"{source} gibt es nicht")

    target_dir = project.path / AUDIO_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_name(source.name)
    if target.resolve() != source.resolve():
        stem, suffix = target.stem, target.suffix
        counter = 1
        while target.exists():
            target = target_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        shutil.copyfile(source, target)
    return f"{AUDIO_DIR}/{target.name}"


def list_projects(root: str | Path) -> list[dict]:
    root = Path(root)
    found = []
    if not root.is_dir():
        return found
    for entry in sorted(root.iterdir()):
        file = entry / PROJECT_FILE
        if file.is_file():
            try:
                data = json.loads(file.read_text())
                name = str(data.get("name", entry.name))
            except (OSError, json.JSONDecodeError):
                name = entry.name
            found.append({"dir": entry.name, "name": name})
    return found
