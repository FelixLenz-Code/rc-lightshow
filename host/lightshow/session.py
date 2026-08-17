"""Everything a running bridge holds together.

Channel values come from one of two sources: the project timeline while the
transport is playing, and the MIDI input otherwise. The sending loop asks the
session for a frame and does not care which one produced it, so a running show
and live poking from a DAW can coexist without a mode switch.
"""

from __future__ import annotations

import threading
from pathlib import Path

from . import project as project_module
from . import timeline as timeline_module
from .audio import Transport
from .config import ShowCfg
from .project import Project

PROJECTS_DIR = "projects"


class Session:
    def __init__(self, show: ShowCfg, mapper, link, projects_root: Path) -> None:
        self.show = show
        self.mapper = mapper
        self.link = link
        self.projects_root = Path(projects_root)
        self.transport = Transport()

        self._lock = threading.Lock()
        self.project: Project | None = None
        self.timeline: timeline_module.Timeline | None = None
        # What the sending loop last produced. The monitors show this rather
        # than the MIDI state, so they stay truthful whatever the source is.
        self.last_frame: list[list[int]] | None = None

    # ------------------------------------------------------------- failsafe

    def _failsafe_frame(self) -> list[list[int]]:
        values = [[port.min_us] * port.nchan for port in self.show.ports]
        for model in self.show.models:
            if model.uses_bus:
                # Eight independently "safe" channels are not a valid code word.
                # What belongs here is the one frame that says off, everywhere.
                encoder = self.mapper.bus_encoders.get(model.name)
                if encoder is not None:
                    encoder.write_failsafe(values[model.tx_port])
                continue
            for offset, channel in enumerate(model.channels):
                values[model.tx_port][model.tx_offset + offset] = channel.failsafe
        return values

    # --------------------------------------------------------------- frames

    def frame(self) -> list[list[int]]:
        values = self._compute_frame()
        self.last_frame = values
        return values

    def _compute_frame(self) -> list[list[int]]:
        if self.mapper.blackout:
            return self._failsafe_frame()
        with self._lock:
            line = self.timeline
        if line is not None and self.transport.playing:
            return line.frame(self.transport.position())
        return self.mapper.frame()

    @property
    def source(self) -> str:
        if self.timeline is not None and self.transport.playing:
            return "timeline"
        return "midi"

    # ------------------------------------------------------------- projects

    def list_projects(self) -> list[dict]:
        return project_module.list_projects(self.projects_root)

    def new_project(self, name: str) -> dict:
        directory = self.projects_root / project_module.safe_name(name)
        if directory.exists():
            return {"ok": False, "error": f"'{directory.name}' gibt es schon"}

        project = Project(name=name)
        # One light track per model and zone, named after the model so the
        # editor is readable from the first second.
        for model in self.show.models:
            for zone in range(model.zone_count):
                title = model.name if model.zone_count == 1 \
                    else f"{model.name} Zone {zone + 1}"
                project.light_tracks.append(
                    project_module.LightTrack(model=model.name, zone=zone, name=title))
        project.audio_tracks.append(project_module.AudioTrack(name="Musik"))
        project.audio_tracks.append(project_module.AudioTrack(name="Effekte"))

        project_module.save(project, directory)
        return self.open_project(directory.name)

    def open_project(self, dirname: str) -> dict:
        directory = self.projects_root / project_module.safe_name(dirname)
        try:
            project = project_module.load(directory)
        except project_module.ProjectError as exc:
            return {"ok": False, "error": str(exc)}

        self.transport.stop()
        self.transport.load(project)
        line = timeline_module.Timeline(self.show, project)
        with self._lock:
            self.project = project
            self.timeline = line
        return {"ok": True, "project": self.project_payload()}

    def apply_project(self, data: dict) -> dict:
        """Makes an edit audible and visible, without writing it to disk.

        The mix is built once when a project loads, and the light timeline is
        built with it. Without this, a clip dragged to a new place stayed where
        it was until someone pressed save -- it moved on screen and played from
        its old position, which is the worst kind of wrong.

        The audio is only remixed when the audio actually changed. Dragging a
        light block must not cost a remix of a five minute song.
        """
        with self._lock:
            current = self.project
        if current is None or current.path is None:
            return {"ok": False, "error": "kein Projekt geöffnet"}

        try:
            updated = project_module.from_dict(data, current.path)
        except project_module.ProjectError as exc:
            return {"ok": False, "error": str(exc)}

        audio_changed = (project_module.to_dict(updated)["audio_tracks"]
                         != project_module.to_dict(current)["audio_tracks"])

        line = timeline_module.Timeline(self.show, updated)
        with self._lock:
            self.project = updated
            self.timeline = line

        if audio_changed:
            was_playing = self.transport.playing
            position = self.transport.position()
            self.transport.load(updated)
            # Editing during playback should not throw you back to the start.
            self.transport.seek(position)
            if was_playing:
                self.transport.play()
        else:
            # No audio touched, but a light block may still have moved the end
            # of the show -- and the transport stops at that end.
            self.transport.set_duration(updated.duration_s)

        return {"ok": True, "audio": audio_changed,
                "warnings": list(line.warnings)}

    def save_project(self, data: dict) -> dict:
        result = self.apply_project(data)
        if not result.get("ok"):
            return result

        with self._lock:
            current = self.project
        project_module.save(current, current.path)
        return {"ok": True, "project": self.project_payload()}

    def close_project(self) -> None:
        self.transport.close()
        with self._lock:
            self.project = None
            self.timeline = None

    def import_audio(self, filename: str, data: bytes) -> dict:
        with self._lock:
            current = self.project
        if current is None or current.path is None:
            return {"ok": False, "error": "kein Projekt geöffnet"}

        directory = current.path / project_module.AUDIO_DIR
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / project_module.safe_name(Path(filename).name)
        stem, suffix = target.stem, target.suffix
        counter = 1
        while target.exists():
            target = directory / f"{stem}_{counter}{suffix}"
            counter += 1
        target.write_bytes(data)

        try:
            import soundfile as sf

            info = sf.info(str(target))
            duration = round(info.frames / info.samplerate, 3)
        except Exception as exc:            # noqa: BLE001 - not an audio file
            target.unlink(missing_ok=True)
            return {"ok": False, "error": f"{filename} ist keine lesbare Audiodatei ({exc})"}

        return {"ok": True,
                "file": f"{project_module.AUDIO_DIR}/{target.name}",
                "duration_s": duration}

    # ----------------------------------------------------------------- state

    def project_payload(self) -> dict | None:
        with self._lock:
            current = self.project
            line = self.timeline
        if current is None:
            return None
        return {
            "name": current.name,
            "dir": current.path.name if current.path else "",
            "data": project_module.to_dict(current),
            "duration": round(current.duration_s, 3),
            "peaks": self.transport.clip_peaks(),
            "warnings": list(line.warnings) if line else [],
            "audio_messages": list(self.transport.messages),
            "cue_names": project_module.CUE_NAMES,
        }

    def transport_state(self) -> dict:
        state = self.transport.state()
        state["source"] = self.source
        state["project"] = self.project.name if self.project else None
        if self.timeline is not None:
            state["tracks"] = self.timeline.describe(self.transport.position())
        return state
