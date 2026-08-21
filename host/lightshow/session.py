"""Everything a running bridge holds together.

Channel values come from one of two sources: the project timeline while the
transport is playing, and the resting state otherwise. The sending loop asks
the session for a frame and does not care which one produced it.
"""

from __future__ import annotations

import json
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
        # than the mapper's, so they stay truthful whatever the source is.
        self.last_frame: list[list[int]] | None = None

    # ------------------------------------------------------------- failsafe

    def _failsafe_frame(self) -> list[list[int]]:
        values = [[port.min_us] * port.nchan for port in self.show.ports]
        for model in self.show.models:
            # Eight independently "safe" channels are not a valid code word.
            # What belongs here is the one frame that says off, everywhere.
            encoder = self.mapper.bus_encoders.get(model.name)
            if encoder is not None:
                encoder.write_failsafe(values[model.tx_port])
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
        return "idle"

    # ------------------------------------------------------------- projects

    def list_projects(self) -> list[dict]:
        return project_module.list_projects(self.projects_root)

    def _one_per_transmitter(self, chosen: list[str]) -> str | None:
        """Two models on one jack share a transmitter, so a show takes one.

        They may well both exist -- different channel blocks out of the same
        frame is a normal build, and the configuration allows it. But there is
        one set of sticks, and a timeline that drives both would be driving two
        aircraft from it at once. Checked here rather than only in the browser:
        a rule that lives in one dialogue is a rule a hand-edited project.json
        does not have to keep.
        """
        by_port: dict[int, str] = {}
        for model in self.show.models:
            if model.name not in chosen:
                continue
            other = by_port.get(model.tx_port)
            if other is not None:
                return (f"'{other}' und '{model.name}' hängen beide an "
                        f"Sender-Buchse {model.tx_port + 1} — in ein Projekt "
                        f"kommt nur eines von beiden.")
            by_port[model.tx_port] = model.name
        return None

    def new_project(self, name: str, models: list[str] | None = None) -> dict:
        """Lays out a show for the aircraft it is meant for.

        Which ones is a question, not an assumption: a field with four models
        configured rarely flies all four in one show, and a timeline that opens
        with tracks for every zone of every aircraft is one somebody has to
        clear out before starting. `None` still means all of them, which is
        what the older call did.
        """
        directory = self.projects_root / project_module.safe_name(name)
        if directory.exists():
            return {"ok": False, "error": f"'{directory.name}' gibt es schon"}

        known = [model.name for model in self.show.models]
        if models is None:
            chosen = known
        else:
            unknown = [name for name in models if name not in known]
            if unknown:
                return {"ok": False,
                        "error": f"kein Modell '{unknown[0]}' in der Konfiguration"}
            # In configuration order, not in the order they were clicked, so
            # the tracks come out in the same order as everywhere else.
            chosen = [name for name in known if name in set(models)]
        if not chosen:
            return {"ok": False, "error": "Ein Projekt braucht mindestens ein Modell."}
        clash = self._one_per_transmitter(chosen)
        if clash:
            return {"ok": False, "error": clash}

        project = Project(name=name, models=list(chosen))
        # One light track per model and zone, named after the model so the
        # editor is readable from the first second.
        for model in self.show.models:
            if model.name not in project.models:
                continue
            for zone in range(model.zone_count):
                title = model.name if model.zone_count == 1 \
                    else f"{model.name} Zone {zone + 1}"
                project.light_tracks.append(
                    project_module.LightTrack(model=model.name, zone=zone, name=title))
            # And one per relay, named after the relay rather than the bit --
            # "rauch" is what somebody looks for in the timeline, not "Bit 0".
            for index, relay in enumerate(model.bus.relays):
                project.relay_tracks.append(project_module.RelayTrack(
                    model=model.name, relay=index,
                    name=f"{model.name} · {relay.name}"))
        project.audio_tracks.append(project_module.AudioTrack(name="Musik"))
        project.audio_tracks.append(project_module.AudioTrack(name="Effekte"))

        project_module.save(project, directory)
        return self.open_project(directory.name)

    def edit_project(self, name: str, models: list[str] | None,
                     dirname: str | None = None) -> dict:
        """Renames a project and changes which aircraft are in it.

        Works on any project, not only the one that is open: reworking a show
        should not mean loading it first, playing it by accident and losing the
        place in the one that was already there. The open project goes through
        `save_project`, so the bridge hears the change at once; a closed one is
        read, changed and written back without the session noticing.
        """
        with self._lock:
            current = self.project
        open_dir = (current.path.name
                    if current is not None and current.path is not None else None)

        if dirname is None or dirname == open_dir:
            if current is None:
                return {"ok": False, "error": "kein Projekt geöffnet"}
            problem = self._rework(current, name, models)
            if problem:
                return {"ok": False, "error": problem}
            return self.save_project(project_module.to_dict(current))

        directory = self.projects_root / project_module.safe_name(dirname)
        try:
            project = project_module.load(directory)
        except project_module.ProjectError as exc:
            return {"ok": False, "error": str(exc)}
        problem = self._rework(project, name, models)
        if problem:
            return {"ok": False, "error": problem}
        project_module.save(project, directory)
        # No project payload: nothing was opened, and handing one back would
        # invite the interface to draw it as though something had been.
        return {"ok": True, "project": None, "dir": directory.name}

    def _rework(self, project, name: str, models: list[str] | None) -> str | None:
        """Applies a rename and a new model list in place. Returns a complaint.

        Adding a model brings its tracks; removing one takes its tracks away,
        blocks and all. That is destructive, so it is the interface's job to say
        how much before asking -- here it just happens, because a model that is
        not in the project has no business owning a track in it.

        The name is only the label. Moving the folder would break every path
        that points into it for the sake of tidiness.
        """
        if name.strip():
            project.name = name.strip()
        if models is None:
            return None

        known = [model.name for model in self.show.models]
        unknown = [n for n in models if n not in known]
        if unknown:
            return f"kein Modell '{unknown[0]}' in der Konfiguration"
        keep = [n for n in known if n in set(models)]
        if not keep:
            return "Ein Projekt braucht mindestens ein Modell."
        clash = self._one_per_transmitter(keep)
        if clash:
            return clash

        project.models = keep
        project.light_tracks = [t for t in project.light_tracks if t.model in set(keep)]
        project.relay_tracks = [t for t in project.relay_tracks if t.model in set(keep)]
        # And whatever is new gets the tracks it would have got at creation.
        for model in self.show.models:
            if model.name not in project.models:
                continue
            for zone in range(model.zone_count):
                if project.track_for(model.name, zone) is None:
                    title = model.name if model.zone_count == 1 \
                        else f"{model.name} Zone {zone + 1}"
                    project.light_tracks.append(project_module.LightTrack(
                        model=model.name, zone=zone, name=title))
            for index, relay in enumerate(model.bus.relays):
                if project.relay_track_for(model.name, index) is None:
                    project.relay_tracks.append(project_module.RelayTrack(
                        model=model.name, relay=index,
                        name=f"{model.name} · {relay.name}"))
        # Back into configuration order, so a model added later does not sit at
        # the bottom for ever.
        order = {name: i for i, name in enumerate(known)}
        project.light_tracks.sort(key=lambda t: (order.get(t.model, 99), t.zone))
        project.relay_tracks.sort(key=lambda t: (order.get(t.model, 99), t.relay))
        return None

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

    def reload_show(self) -> None:
        """Rebuilds what was derived from the configuration after it was edited.

        The light timeline is built once, out of the configuration and the
        project together -- which zone a track drives is looked up there. Add a
        zone to a model and the timeline in hand still knows the old ones, so it
        is built again. The configuration object itself is the same one the
        session has always held; only its contents changed.
        """
        with self._lock:
            if self.project is not None:
                self.timeline = timeline_module.Timeline(self.show, self.project)

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
        """Writes the project, and takes the audio nobody uses any more with it.

        A clip removed from the timeline used to leave its file behind, so a
        project grew by forty megabytes every time a song was swapped for
        another one. Now a file goes when the last clip pointing at it goes.

        Deliberately only *those* files: what falls out of use between this save
        and the one before it. A sweep of everything unreferenced would also
        take a file somebody copied into the folder to use in a minute, and an
        automatic save runs a second after every edit -- that is no moment to be
        deleting things nobody asked about. Whatever was already lying around
        stays until it is asked for by name; see `sweep_audio`.

        "Before" is read off the **disk**, not out of the project in hand. An
        edit reaches the session a good half second before it reaches the file,
        so by save time the clip is already gone from memory and the two sets
        would agree -- and nothing would ever be deleted. The last document
        written is what the folder was stocked for, so that is what to compare
        against.
        """
        with self._lock:
            current = self.project
        before = self._audio_written(current.path if current is not None else None)

        result = self.apply_project(data)
        if not result.get("ok"):
            return result

        with self._lock:
            current = self.project
        project_module.save(current, current.path)

        dropped = project_module.drop_audio(
            current.path, sorted(before - project_module.audio_in_use(current)))
        return {"ok": True, "project": self.project_payload(),
                "removed_audio": dropped}

    @staticmethod
    def _audio_written(directory) -> set[str]:
        """Which audio files the document *on disk* points at."""
        if directory is None:
            return set()
        file = Path(directory) / project_module.PROJECT_FILE
        try:
            document = json.loads(file.read_text())
        except (OSError, ValueError):
            return set()
        return {str(clip["file"])
                for track in (document.get("audio_tracks") or [])
                for clip in (track.get("clips") or []) if clip.get("file")}

    def audio_leftovers(self, dirname: str) -> dict:
        """What lies in a project's audio folder that no clip points at."""
        directory = self.projects_root / project_module.safe_name(dirname)
        try:
            project = project_module.load(directory)
        except project_module.ProjectError as exc:
            return {"ok": False, "error": str(exc)}
        names = sorted(set(project_module.audio_on_disk(directory))
                       - project_module.audio_in_use(project))
        return {"ok": True, "files": names,
                "bytes": project_module.audio_bytes(directory, names)}

    def sweep_audio(self, dirname: str) -> dict:
        """Deletes exactly the files `audio_leftovers` just listed.

        Asked for by name rather than done on every save: these are files that
        were never in use as far as this bridge can tell, which is not the same
        as files that are rubbish.
        """
        found = self.audio_leftovers(dirname)
        if not found.get("ok"):
            return found
        directory = self.projects_root / project_module.safe_name(dirname)
        freed = found["bytes"]
        gone = project_module.drop_audio(directory, found["files"])
        return {"ok": True, "files": gone, "bytes": freed}

    def export_project(self, dirname: str) -> tuple[bytes, str] | dict:
        """One project as a zip, ready to hand over. Errors come back as dicts."""
        directory = self.projects_root / project_module.safe_name(dirname)
        try:
            return project_module.export_zip(directory), directory.name
        except project_module.ProjectError as exc:
            return {"ok": False, "error": str(exc)}

    def import_project(self, data: bytes, wanted: str = "") -> dict:
        """Unpacks a project someone else exported, without opening it.

        Not opened on purpose: importing is a filing action, and taking the show
        on screen away to put up one that has just arrived is not what was
        asked. It appears in the list, and Öffnen is right next to it.
        """
        try:
            directory, notes = project_module.import_zip(
                data, self.projects_root, wanted)
        except project_module.ProjectError as exc:
            return {"ok": False, "error": str(exc)}

        project = project_module.load(directory)
        known = {model.name for model in self.show.models}
        missing = [name for name in project.models if name not in known]
        if missing:
            notes.append(
                "Für " + ", ".join(f"'{n}'" for n in missing)
                + (" gibt es hier kein Modell" if len(missing) == 1
                   else " gibt es hier keine Modelle")
                + " — die Spuren bleiben stumm, bis eines dieses Namens "
                  "eingerichtet ist."
            )
        return {"ok": True, "dir": directory.name, "name": project.name,
                "notes": notes}

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
