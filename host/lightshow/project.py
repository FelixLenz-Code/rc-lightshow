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

import io
import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Iterable
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
class RelayBlock:
    """A stretch of time in which one relay is on.

    A relay has no level, no colour and no fades -- it is a switch. So a block
    carries nothing but where it starts, how long it lasts, and a name for the
    person reading the timeline.
    """

    start_s: float
    duration_s: float
    label: str = ""

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s


@dataclass
class RelayTrack:
    """One relay of one model, addressed by its bit -- the same index the
    board's relay table and ``bus.relays`` are ordered by."""

    model: str
    relay: int = 0
    name: str = ""
    blocks: list[RelayBlock] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.name or f"{self.model} Relais {self.relay + 1}"


@dataclass
class Project:
    name: str = "unbenannt"
    path: Path | None = None
    # Which aircraft this show is for. Kept as its own list rather than read
    # back off the tracks: it is the question asked when a project is created,
    # and it stays true after somebody has emptied every track of a model. The
    # list of projects can also answer "what is this for" without opening one.
    models: list[str] = field(default_factory=list)
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    light_tracks: list[LightTrack] = field(default_factory=list)
    relay_tracks: list[RelayTrack] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        ends = [clip.end_s for track in self.audio_tracks for clip in track.clips]
        ends += [block.end_s for track in self.light_tracks for block in track.blocks]
        ends += [block.end_s for track in self.relay_tracks for block in track.blocks]
        return max(ends) if ends else 0.0

    def track_for(self, model: str, zone: int) -> LightTrack | None:
        for track in self.light_tracks:
            if track.model == model and track.zone == zone:
                return track
        return None

    def relay_track_for(self, model: str, relay: int) -> RelayTrack | None:
        for track in self.relay_tracks:
            if track.model == model and track.relay == relay:
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


def _relay_block_from(data: dict, where: str) -> RelayBlock:
    return RelayBlock(
        start_s=_num(data.get("start_s", 0), "start_s", where, 0, 86400),
        duration_s=_num(data.get("duration_s", 1), "duration_s", where, 0.01, 86400),
        label=str(data.get("label", "")),
    )


def from_dict(data: dict, path: Path | None = None) -> Project:
    if not isinstance(data, dict):
        raise ProjectError("Projekt: oberste Ebene muss ein Objekt sein")

    project = Project(name=str(data.get("name", "unbenannt")), path=path)
    project.models = [str(name) for name in (data.get("models") or [])]

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

    seen_relays: set[tuple[str, int]] = set()
    for index, entry in enumerate(data.get("relay_tracks") or []):
        where = f"relay_tracks[{index}]"
        if not entry.get("model"):
            raise ProjectError(f"{where}: 'model' fehlt")
        track = RelayTrack(
            model=str(entry["model"]),
            relay=int(_num(entry.get("relay", 0), "relay", where, 0, 7)),
            name=str(entry.get("name", "")),
        )
        key = (track.model, track.relay)
        if key in seen_relays:
            raise ProjectError(
                f"{where}: {track.model} Relais {track.relay} gibt es doppelt")
        seen_relays.add(key)

        track.blocks = [_relay_block_from(block, f"{where}.blocks[{i}]")
                        for i, block in enumerate(entry.get("blocks") or [])]
        track.blocks.sort(key=lambda block: block.start_s)

        # Two overlapping "on" blocks say the same thing twice, and the gap
        # between them would be the only thing that mattered. Merging them
        # silently would move an edge somebody dragged deliberately.
        for earlier, later in zip(track.blocks, track.blocks[1:]):
            if later.start_s < earlier.end_s - 1e-6:
                raise ProjectError(
                    f"{where}: Bloecke ueberlappen bei {later.start_s:.2f} s "
                    f"-- ein Relais ist an oder aus, zweimal an gibt es nicht"
                )
        project.relay_tracks.append(track)

    # Written since the project tab exists; anything older says which aircraft
    # it is for by having tracks for them.
    if not project.models:
        project.models = list(dict.fromkeys(
            [track.model for track in project.light_tracks]
            + [track.model for track in project.relay_tracks]))

    return project


def to_dict(project: Project) -> dict:
    return {
        "version": VERSION,
        "name": project.name,
        "models": list(project.models),
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
        "relay_tracks": [
            {
                "model": track.model,
                "relay": track.relay,
                "name": track.name,
                "blocks": [
                    {
                        "start_s": block.start_s,
                        "duration_s": block.duration_s,
                        "label": block.label,
                    }
                    for block in track.blocks
                ],
            }
            for track in project.relay_tracks
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


def audio_in_use(project: Project) -> set[str]:
    """Every audio file some clip still points at, as a relative path."""
    return {clip.file for track in project.audio_tracks for clip in track.clips}


def audio_on_disk(directory: str | Path) -> list[str]:
    """Every file lying in the project's audio folder, as a relative path."""
    folder = Path(directory) / AUDIO_DIR
    if not folder.is_dir():
        return []
    return sorted(f"{AUDIO_DIR}/{path.name}"
                  for path in folder.iterdir() if path.is_file())


def audio_bytes(directory: str | Path, names: Iterable[str]) -> int:
    total = 0
    for name in names:
        path = Path(directory) / name
        if path.is_file():
            total += path.stat().st_size
    return total


def drop_audio(directory: str | Path, names: Iterable[str]) -> list[str]:
    """Deletes named audio files from a project. Returns what actually went.

    Only inside the project's own audio folder, and only plain files -- the
    names come out of a document that a person may have edited, and a delete
    that follows `../` wherever it points is a delete nobody can take back.
    """
    directory = Path(directory).resolve()
    folder = (directory / AUDIO_DIR).resolve()
    gone: list[str] = []
    for name in names:
        path = (directory / name).resolve()
        if path.parent != folder or not path.is_file():
            continue
        path.unlink()
        gone.append(name)
    return gone


def list_projects(root: str | Path) -> list[dict]:
    root = Path(root)
    found = []
    if not root.is_dir():
        return found
    for entry in sorted(root.iterdir()):
        file = entry / PROJECT_FILE
        if file.is_file():
            # Read straight out of the file rather than through `load`: the
            # list has to survive a project that no longer parses, and say so
            # by the little it can still read.
            models: list[str] = []
            tracks = 0
            try:
                data = json.loads(file.read_text())
                name = str(data.get("name", entry.name))
                models = [str(m) for m in (data.get("models") or [])]
                if not models:
                    models = list(dict.fromkeys(
                        str(t.get("model")) for kind in ("light_tracks", "relay_tracks")
                        for t in (data.get(kind) or []) if t.get("model")))
                tracks = sum(len(data.get(kind) or []) for kind in
                             ("audio_tracks", "light_tracks", "relay_tracks"))
            except (OSError, json.JSONDecodeError):
                name = entry.name
                data = {}
            leftovers = sorted(set(audio_on_disk(entry)) - {
                str(c.get("file")) for t in (data.get("audio_tracks") or [])
                for c in (t.get("clips") or []) if c.get("file")})
            found.append({"dir": entry.name, "name": name,
                          "models": models, "tracks": tracks,
                          # What lies in the audio folder that nothing points
                          # at. Not deleted here -- only counted, so the tab can
                          # offer to.
                          "spare_audio": len(leftovers),
                          "spare_bytes": audio_bytes(entry, leftovers)})
    return found


# ------------------------------------------------------ carrying one project


def export_zip(directory: str | Path) -> bytes:
    """A project folder as a zip: the document and the audio beside it.

    A project is a folder on purpose -- the audio is copied in rather than
    linked, so the folder is the whole show. Carrying it is therefore zipping
    it, and nothing has to be reassembled at the other end.
    """
    directory = Path(directory)
    if not (directory / PROJECT_FILE).is_file():
        raise ProjectError(f"{directory} ist kein Projektordner")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.name != PROJECT_FILE + ".bak":
                archive.write(path, path.relative_to(directory).as_posix())
    return buffer.getvalue()


def import_zip(data: bytes, root: str | Path, wanted: str) -> tuple[Path, list[str]]:
    """Unpacks an exported project into `root`, under a free folder name.

    Returns the folder and whatever is worth saying about it. Refuses anything
    that is not a project, and anything whose entries point outside the folder
    they are supposed to land in -- a zip can name `../../etc/whatever`, and
    unpacking one blind is how an archive writes wherever it likes.
    """
    root = Path(root)
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ProjectError(f"keine lesbare Zip-Datei: {exc}") from exc

    names = archive.namelist()
    if PROJECT_FILE not in names:
        raise ProjectError(
            f"Im Archiv liegt keine {PROJECT_FILE} — das ist kein Projekt."
        )
    for name in names:
        target = (root / "x" / name).resolve()
        if not str(target).startswith(str((root / "x").resolve()) + "/") \
                and target != (root / "x").resolve():
            raise ProjectError(f"Das Archiv will nach '{name}' schreiben.")

    try:
        document = json.loads(archive.read(PROJECT_FILE))
    except (json.JSONDecodeError, KeyError) as exc:
        raise ProjectError(f"{PROJECT_FILE} im Archiv: {exc}") from exc
    # Loaded before anything is written, so a broken archive leaves no folder.
    project = from_dict(document)

    name = safe_name(wanted or project.name)
    directory = root / name
    counter = 2
    while directory.exists():
        directory = root / f"{name}_{counter}"
        counter += 1

    directory.mkdir(parents=True)
    archive.extractall(directory)
    project.path = directory
    save(project, directory)

    notes: list[str] = []
    if directory.name != name:
        notes.append(f"Ordner '{name}' gibt es schon, liegt jetzt in "
                     f"'{directory.name}'")
    return directory, notes
