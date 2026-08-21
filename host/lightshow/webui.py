"""Local web interface for the bridge.

Runs a small HTTP server in a background thread, using nothing but the standard
library. It shows whether the ground Pico is connected, what is going out on
each channel, lets you edit the per-model output configuration and generates
the airborne controller's header plus its wiring list.

Configuration cannot be edited while a show is running: while the transport
plays, the editor is locked so a mapping cannot change mid-show.
"""

from __future__ import annotations

import json
import os
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import bus as bus_mode
from . import config as config_module
from . import flasher
from . import planegen

WEB_ROOT = Path(__file__).parent / "web"

# The interface is three files in one flat directory -- no bundler, no
# dependencies. Anything not listed here is not served.
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}

# Loopback, in every shape the socket layer reports it. Requests from anywhere
# else may look but not build, flash or write into the repository.
LOCAL_ADDRESSES = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})

GENERATED_DIR = "firmware/plane/generated"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

# Long enough for the answer to be on the wire before the process goes away,
# short enough that nobody wonders whether the button did anything.
QUIT_DELAY_S = 0.25

# How long the bridge waits after its last window went away before it follows.
# A reload drops the event stream too, but the browser is back in well under a
# second -- this is the margin that tells the two apart.
IDLE_QUIT_S = 3.0


def stop_process() -> None:
    """Ends the bridge the way Ctrl-C would.

    Deliberately not sys.exit() from this thread: the main loop's signal
    handler is the one path that leaves the field dark, sends the failsafe
    frames out and gives the serial port and the audio device back. Anything
    else would drop the aircraft into failsafe by cutting the link instead of
    by telling it to.
    """
    os.kill(os.getpid(), signal.SIGTERM)


def zone_outputs(model: config_module.ModelCfg) -> list[dict]:
    """Which lamps each zone of a model actually drives.

    A light track in the editor addresses a zone, and a zone is only a number
    until you know what hangs on it. This is what lets the editor say "this
    effect runs on flaeche_links and flaeche_rechts, 60 pixels" instead of
    "Zone 1".

    Relays are deliberately not here. They are switched over the bus, each on
    its own bit and its own control change, and belong to no zone at all.
    """
    out: list[dict] = []
    plane = model.plane

    for zone in range(model.zone_count):
        segments = ([(index, seg) for index, seg in plane.segments
                     if seg.zone == zone] if plane else [])
        out.append({
            "zone": zone,
            # The virtual chain a chase runs across is as long as the furthest
            # segment reaches, not the sum of their pixel counts -- segments
            # that share an offset are mirrors of each other.
            "pixels": plane.zone_pixels(zone) if plane else 0,
            "strips": [{"name": seg.name, "output": plane.outputs[index].name,
                        "pin": plane.outputs[index].pin, "count": seg.count,
                        "start": seg.start, "offset": seg.offset,
                        "reverse": seg.reverse} for index, seg in segments],
        })
    return out


def model_chains(model: config_module.ModelCfg) -> list[dict]:
    """The physical view: every WS2812 chain with the segments cut out of it.

    ``zone_outputs`` answers "what does this zone drive"; this answers "what
    does this chain show", which is what somebody looking at the aircraft sees
    and what the preview window has to draw. Same data, the other way round.
    """
    plane = model.plane
    if plane is None:
        return []
    return [
        {
            "name": output.name,
            "pin": output.pin,
            "count": output.count,
            "segments": [
                {"name": segment.name, "start": segment.start,
                 "count": segment.count, "zone": segment.zone,
                 "offset": segment.offset, "reverse": segment.reverse,
                 "place": (None if segment.place is None else {
                     "view": segment.place.view,
                     "x1": segment.place.x1, "y1": segment.place.y1,
                     "x2": segment.place.x2, "y2": segment.place.y2})}
                for segment in output.segments
            ],
            # Stamped on top of everything, at an absolute index on this chain.
            "nav_lights": [
                {"index": nav.index, "color": list(nav.color)}
                for nav in plane.nav_lights if nav.output == index
            ],
        }
        for index, output in enumerate(plane.outputs)
    ]


def model_relays(model: config_module.ModelCfg) -> list[dict]:
    """The model's relays: one bit on the wire, one pin on the board."""
    board = model.plane.relays if model.plane else []
    return [
        {"slot": index, "name": air.name,
         "pin": board[index].pin if index < len(board) else None,
         "active_low": board[index].active_low if index < len(board) else None,
         "min_on_ms": board[index].min_on_ms if index < len(board) else None,
         "min_off_ms": board[index].min_off_ms if index < len(board) else None}
        for index, air in enumerate(model.bus.relays)
    ]


class Server:
    def __init__(self, show: config_module.ShowCfg, mapper, link, config_path: Path,
                 repo_root: Path, session=None, host: str = "127.0.0.1",
                 port: int = 8765) -> None:
        self.show = show
        self.mapper = mapper
        self.link = link
        self.session = session
        self.config_path = Path(config_path)
        self.repo_root = Path(repo_root)
        self.host = host
        self.port = port

        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Set from outside once an application window has been opened. Closing
        # that window is then the way out, and the bridge follows it down --
        # otherwise it would keep the serial port with no window left to
        # say so.
        self.quit_when_idle = False
        self._watchers = 0
        self._seen_a_watcher = False
        self._idle_timer: threading.Timer | None = None
        self._watch_lock = threading.Lock()

        self._job: flasher.Job | None = None

    # ------------------------------------------------------------------ state

    def show_running(self) -> bool:
        """A show is running while the transport plays."""
        return self.session is not None and self.session.transport.playing

    def active_encoders(self) -> dict:
        """The bus encoders that are driving the wire at this moment.

        Two things can hold a model's zone state: the resting mapper, or the
        project timeline while it plays. Both keep it in a ``bus.Encoder``, so
        asking the right one is the whole job.
        """
        if (self.session is not None and self.session.source == "timeline"
                and self.session.timeline is not None):
            return self.session.timeline.encoders
        return self.mapper.bus_encoders

    def zone_states(self, model: config_module.ModelCfg,
                    blackout: bool) -> list[dict]:
        """What each zone of a model currently holds, in 0..255.

        Deliberately *not* read back off the wire. Those eight channels carry
        the symbols of one RS(8,6) code word, and a symbol is not the value it
        helps encode -- reading them as channel values is how this used to show
        an effect number where a failsafe was. The encoder holds the real thing.
        """
        encoder = self.active_encoders().get(model.name)
        out = []
        for zone in range(model.zone_count):
            if blackout or encoder is None or zone >= len(encoder.states):
                out.append({"cue": 0, "hue": 0, "brightness": 0, "param": 128})
                continue
            out.append(encoder.states[zone].to_bytes())
        return out

    def state(self) -> dict:
        blackout, slots = self.mapper.snapshot()

        models: list[dict] = []
        for model in self.show.models:
            entries = []
            for slot, snapshot_us in slots:
                if slot.model is not model:
                    continue
                value_us = snapshot_us
                span = max(1, slot.port.max_us - slot.port.min_us)
                fraction = (value_us - slot.port.min_us) / span
                decoded = f"{round(fraction * 100)} %"
                step = None
                if slot.channel.quantize:
                    step = min(slot.channel.quantize - 1,
                               int(fraction * slot.channel.quantize))
                    decoded = f"Stufe {step}"
                entries.append({
                    "role": slot.channel.role,
                    "us": value_us,
                    "fraction": round(fraction, 4),
                    "decoded": decoded,
                    # What the airborne firmware will decode this to: a step
                    # index for quantised channels, 0..255 otherwise. The
                    # interface previews the effect from these, so it must not
                    # have to parse `decoded` back apart.
                    "step": step,
                    "level": round(fraction * 255),
                    "live": value_us != slot.channel.failsafe,
                })
            models.append({
                "name": model.name,
                "tx_port": model.tx_port,
                "tx_offset": model.tx_offset,
                # The eight coded channels the whole model rides on -- shared by
                # every zone, not divided between them.
                "first_channel": model.tx_offset + 1,
                "last_channel": model.tx_offset + model.wire_channels,
                "zones": model.zone_count,
                "has_plane": model.plane is not None,
                # The interface previews the effect this model will show, and
                # the ceiling is part of what it looks like.
                "max_brightness": model.plane.max_brightness if model.plane else 255,
                # Which shape the preview draws the strips on.
                "airframe": model.plane.airframe if model.plane else "motor",
                "outputs": zone_outputs(model),
                # What every zone actually holds right now, from whichever
                # encoder is driving. This is what the previews render.
                "zone_states": self.zone_states(model, blackout),
                "chains": model_chains(model),
                "relays": model_relays(model),
                "channels": entries,
            })

        return {
            "pico": {
                "device": self.link.device,
                "dry_run": self.link.dry_run,
                "connected": self.link.connected,
                "frames": self.link.frames_sent,
                "error": self.link.last_error,
                "status": list(self.link.status_lines)[-4:],
            },
            "blackout": blackout,
            "rate_hz": self.show.rate_hz,
            "locked": self.show_running(),
            "models": models,
            "transport": self.session.transport_state() if self.session else None,
        }

    # ----------------------------------------------------------------- config

    def save_placement(self, data: dict) -> dict:
        """Moves one segment on the mockup and writes only that.

        Deliberately not "save the whole configuration": the preview is a second
        window, and the models view may be open in the first one with unsaved
        edits. Sending the whole document from here would quietly undo them.
        This touches one segment's drawing coordinates and nothing else -- and
        because they are only coordinates on a drawing, it stays allowed while a
        show runs, unlike every other write.
        """
        name = str(data.get("model", ""))
        try:
            output_at = int(data.get("output", -1))
            segment_at = int(data.get("segment", -1))
        except (TypeError, ValueError):
            return {"ok": False, "error": "output/segment müssen Zahlen sein"}

        model = self.model_by_name(name)
        if model is None or model.plane is None:
            return {"ok": False,
                    "error": f"kein Modell '{name}' mit Bordkonfiguration"}
        outputs = model.plane.outputs
        if not 0 <= output_at < len(outputs):
            return {"ok": False, "error": f"Ausgang {output_at} gibt es nicht"}
        segments = outputs[output_at].segments
        if not 0 <= segment_at < len(segments):
            return {"ok": False, "error": f"Abschnitt {segment_at} gibt es nicht"}

        try:
            place = config_module.parse_placement(data.get("place"), "place")
        except config_module.ConfigError as exc:
            return {"ok": False, "error": str(exc)}

        with self._lock:
            segments[segment_at].place = place
            config_module.save(self.show, self.config_path)
        return {"ok": True}

    def save_config(self, data: dict) -> dict:
        if self.show_running():
            return {"ok": False, "error":
                    "Es läuft eine Show. Zum Bearbeiten die Wiedergabe stoppen."}
        try:
            new_show = config_module.load_dict(data)
        except config_module.ConfigError as exc:
            return {"ok": False, "error": str(exc)}
        except (TypeError, ValueError, KeyError) as exc:
            return {"ok": False, "error": f"ungültige Eingabe: {exc}"}

        with self._lock:
            config_module.save(new_show, self.config_path)
            self.apply_show(new_show)
        return {"ok": True,
                "note": "Gespeichert und übernommen. Die Bordkonfiguration "
                        "muss noch neu generiert und geflasht werden."}

    def apply_show(self, new_show: config_module.ShowCfg) -> None:
        """Puts an edited configuration to work without restarting the bridge.

        Saving used to mean "the next start will do this", which is a strange
        thing for a live instrument to say: the model list was already showing
        the new zones while the frames on the wire were still the old ones, and
        nothing on screen said which of the two was true.

        Three things have to happen, in this order. The configuration takes on
        the new contents in place, so that everything holding it -- mapper,
        session, monitor, this server -- sees the change rather than a stale
        copy. Then the mapper rebuilds the slots and bus encoders it derived
        from it. Then the ground station is told the new port setup, because it
        was given the old one when it connected and has no other way to hear.

        Safe to do here because `save_config` has already refused if a show is
        running: the transport is stopped, so no frame
        is being built out of the tables while they are replaced.
        """
        self.show.adopt(new_show)
        self.mapper.reload(self.show)
        self.link.reconfigure(self.show.serial_port, self.show.wire_ports())
        if self.session is not None:
            self.session.reload_show()

    def export_model(self, name: str) -> dict:
        """One model as a document, for carrying to another installation."""
        try:
            return {"ok": True,
                    "document": config_module.model_document(self.show, name)}
        except config_module.ConfigError as exc:
            return {"ok": False, "error": str(exc)}

    def import_model(self, document: dict) -> dict:
        """Takes a model out of an exported file and into this configuration.

        Written through the same door as every other configuration change, so
        the same validation runs and the bridge picks it up on the spot: what
        comes back out of `fit_model` is added to the current document and the
        whole thing is saved, exactly as the model editor would.
        """
        if self.show_running():
            return {"ok": False, "error":
                    "Es läuft eine Show. Zum Importieren die Wiedergabe stoppen."}
        try:
            checked = config_module.read_model_document(document)
            data = config_module.to_dict(self.show)
            model = json.loads(json.dumps(checked["model"]))   # a copy to move
            notes = config_module.fit_model(data, model)
            data.setdefault("models", []).append(model)
            new_show = config_module.load_dict(data)
        except config_module.ConfigError as exc:
            return {"ok": False, "error": str(exc)}
        except (TypeError, ValueError, KeyError) as exc:
            return {"ok": False, "error": f"ungültige Eingabe: {exc}"}

        # What the file says about its transmitter is advisory: this
        # installation keeps its own jacks. Saying so beats a model that quietly
        # rides in a frame of a different length than it was built for.
        was = checked.get("tx_port_was") or {}
        here = next((p for p in data["tx_ports"]
                     if p["id"] == model["tx_port"]), {})
        for key, label in (("format", "Format"), ("nchan", "Kanäle"),
                           ("frame_us", "Rahmenlänge")):
            if was.get(key) is not None and was.get(key) != here.get(key):
                notes.append(f"{label} der Buchse: exportiert mit "
                             f"{was[key]}, hier {here.get(key)}")

        with self._lock:
            config_module.save(new_show, self.config_path)
            self.apply_show(new_show)
        return {"ok": True, "name": model["name"], "notes": notes}

    def model_by_name(self, name: str) -> config_module.ModelCfg | None:
        for model in self.show.models:
            if model.name == name:
                return model
        return None

    def bus_options(self, frame_us: int | None = None) -> dict:
        """Which zone/relay pairs each transmitter can carry, and how fast.

        The arithmetic lives in `bus`, not in the browser: the frame the
        aircraft decodes and the table the interface draws have to come from
        one place, or they will disagree the moment one of them is edited.
        `frame_us` lets the wizard ask about a transmitter it has not saved
        yet, for the same reason -- so it does not have to know the rules.
        """
        limit = self.show.bus_latency_limit_ms

        def table(length_us: int) -> list[dict]:
            return [
                {"zones": c.zones, "relays": c.relays,
                 "latency_ms": round(c.latency_ms, 1),
                 "spare_bits": c.spare_bits,
                 "within_budget": c.within_budget}
                for c in bus_mode.combinations(length_us, limit_ms=limit)
            ]

        ports = {}
        for port in self.show.ports:
            ports[str(port.id)] = {
                "frame_us": port.frame_us,
                "nchan": port.nchan,
                "combinations": table(port.frame_us),
            }
        if frame_us:
            ports["asked"] = {
                "frame_us": frame_us,
                "nchan": None,
                "combinations": table(frame_us),
            }

        models = {}
        for model in self.show.models:
            port = self.show.port_by_id(model.tx_port)
            relays = model.bus.relay_count
            models[model.name] = {
                "zones": model.zone_count,
                "relays": relays,
                "latency_ms": round(
                    bus_mode.latency_ms(model.zone_count, port.frame_us), 1),
                "fits": bus_mode.fits(model.zone_count, relays),
                "wire_channels": model.wire_channels,
            }

        # What a PPM frame has to be at least, per channel count, so the wizard
        # can propose one without knowing the rule.
        ppm_minimum = {str(n): config_module.ppm_frame_minimum(n)
                       for n in (4, 6, 8, 10, 12, 14, 16)}

        return {
            "limit_ms": limit,
            "ppm_frame_minimum": ppm_minimum,
            "channels_per_zone": config_module.CHANNELS_PER_ZONE,
            "payload_bits": bus_mode.PAYLOAD_BITS,
            "zone_state_bits": bus_mode.ZONE_STATE_BITS,
            "max_zones": bus_mode.MAX_ZONES,
            "symbols": bus_mode.SYMBOLS,
            "ports": ports,
            "models": models,
        }

    def plane_payload(self, name: str) -> dict:
        model = self.model_by_name(name)
        if model is None:
            return {"ok": False, "error": f"kein Modell '{name}'"}
        if model.plane is None:
            return {"ok": False, "error":
                    f"Modell '{name}' hat noch keine Bordkonfiguration"}

        header = planegen.generate(self.show, model)
        rows = [row.__dict__ for row in planegen.wiring(model)]
        target = f"{GENERATED_DIR}/{model.name}.h"
        return {
            "ok": True,
            "header": header,
            "wiring": rows,
            "power": planegen.power_estimate(model.plane),
            "target": target,
            "build": (f"cmake -S firmware/plane -B build/plane-{model.name} "
                      f"-DPLANE_CONFIG=generated/{model.name}.h\n"
                      f"cmake --build build/plane-{model.name} -j4"),
        }

    def write_plane_header(self, name: str) -> dict:
        payload = self.plane_payload(name)
        if not payload.get("ok"):
            return payload
        path = self.repo_root / payload["target"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload["header"])
        return {"ok": True, "path": str(path)}

    # --------------------------------------------------------------- windows

    def watcher_arrived(self) -> None:
        """A window opened the event stream."""
        with self._watch_lock:
            self._watchers += 1
            self._seen_a_watcher = True
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None

    def watcher_left(self) -> None:
        """A window went away -- the last one takes the bridge with it."""
        with self._watch_lock:
            self._watchers = max(0, self._watchers - 1)
            # Never before the first window: the browser needs a moment to
            # start, and an empty count until then means nothing.
            if not (self.quit_when_idle and self._seen_a_watcher):
                return
            if self._watchers or self._idle_timer is not None:
                return
            self._idle_timer = threading.Timer(IDLE_QUIT_S, self._quit_if_idle)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def _quit_if_idle(self) -> None:
        with self._watch_lock:
            self._idle_timer = None
            if self._watchers:
                return          # somebody came back, most likely a reload
        stop_process()

    # ------------------------------------------------------------------- quit

    def request_quit(self) -> dict:
        """Stops the bridge, but not before this answer has left the socket."""
        def fire() -> None:
            time.sleep(QUIT_DELAY_S)
            stop_process()

        threading.Thread(target=fire, daemon=True, name="quit").start()
        return {"ok": True}

    # -------------------------------------------------------------- transport

    def transport_command(self, body: dict) -> dict:
        if self.session is None:
            return {"ok": False, "error": "keine Session aktiv"}
        if self.session.project is None:
            return {"ok": False, "error": "kein Projekt geöffnet"}

        action = str(body.get("action", ""))
        transport = self.session.transport
        if action == "play":
            transport.play(body.get("position"))
        elif action == "toggle":
            # The space bar asks for this rather than deciding for itself. The
            # interface hears that the show is running from a status frame five
            # times a second, so a second press inside those 200 ms would send
            # "play" again and feel like a key that did not work.
            transport.pause() if transport.playing else transport.play()
        elif action == "pause":
            transport.pause()
        elif action == "stop":
            transport.stop()
        elif action == "seek":
            transport.seek(float(body.get("position", 0)))
        else:
            return {"ok": False, "error": f"unbekannte Aktion '{action}'"}
        return {"ok": True, "transport": self.session.transport_state()}

    # ------------------------------------------------------- build and flash

    def job_state(self) -> dict:
        if self._job is None:
            return {"idle": True}
        state = self._job.snapshot()
        state["idle"] = False
        return state

    def start_job(self, kind: str, model: str | None) -> dict:
        if self._job is not None and not self._job.done:
            return {"ok": False, "error": "Es läuft bereits ein Vorgang."}
        if kind in ("build-plane", "flash-plane") and not model:
            return {"ok": False, "error": "kein Modell angegeben"}

        if kind == "build-plane":
            job = flasher.Job(f"Bordfirmware bauen: {model}")
            target = lambda: flasher.build_plane(job, self.repo_root, model)  # noqa: E731
        elif kind == "build-ground":
            job = flasher.Job("Bodenstation bauen")
            target = lambda: flasher.build_ground(job, self.repo_root)  # noqa: E731
        elif kind == "flash-plane":
            job = flasher.Job(f"Bordfirmware aufspielen: {model}")
            uf2 = flasher.plane_image(self.repo_root, model)
            if uf2 is None:
                return {"ok": False,
                        "error": f"Für '{model}' ist noch keine Firmware gebaut."}
            job.log(f"Modell '{model}': {uf2.name}")
            # The airborne board has no USB stdio, so it cannot be reset from here.
            target = lambda: flasher.flash(job, uf2, None)  # noqa: E731
        elif kind == "flash-ground":
            job = flasher.Job("Bodenstation aufspielen")
            uf2 = self.repo_root / "build/pico" / "lightshow_tx.uf2"
            device = None if self.link.dry_run else self.link.device
            if device:
                # Keep the port released for the whole job: the sending loop
                # keeps polling and would otherwise reclaim it between here and
                # the 1200 baud reset.
                self.link.suspend()

            def target() -> None:
                try:
                    flasher.flash(job, uf2, device)
                finally:
                    if device:
                        self.link.resume()
        else:
            return {"ok": False, "error": f"unbekannter Vorgang '{kind}'"}

        self._job = job
        threading.Thread(target=target, daemon=True, name="firmware").start()
        return {"ok": True, "name": job.name}

    # ------------------------------------------------------------------ serve

    def start(self) -> str:
        handler = _make_handler(self)
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True, name="webui")
        self._thread.start()
        return f"http://{self.host}:{self._httpd.server_port}/"

    def stop(self) -> None:
        # First the timer: a server that is going down must not still be armed
        # to stop the process a few seconds from now.
        with self._watch_lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


def _make_handler(server: Server):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        REMOTE_DENIED = ("Das geht nur direkt am Rechner, auf dem die Bridge "
                         "läuft — nicht über das Netzwerk.")

        # Filled by `_take_body` at the start of every POST that carries JSON.
        _body: bytes = b""

        def log_message(self, *args) -> None:  # keep the TUI clean
            pass

        # -------------------------------------------------------- helpers ---

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict, code: int = 200) -> None:
            self._send(code, json.dumps(payload).encode(), "application/json")

        def _read_json(self) -> dict:
            return json.loads(self._body or b"{}")

        def _take_body(self) -> None:
            """Reads the request body, whether the handler wants it or not.

            The connection is keep-alive, so a body left sitting in the socket
            is not discarded -- it becomes the first bytes of the *next*
            request, which then arrives as a method called `{}GET`. That is one
            forgotten `_read_json()` away in any branch, so it is taken here
            once instead of trusted to every one of them.
            """
            length = int(self.headers.get("Content-Length", "0"))
            self._body = self.rfile.read(length) if length > 0 else b""

        # ------------------------------------------------------------ GET ---

        def do_GET(self) -> None:
            path = urlparse(self.path).path

            if path == "/" or not path.startswith("/api/"):
                self._static(path)
            elif path == "/api/state":
                self._json(server.state())
            elif path == "/api/config":
                self._json({"config": config_module.to_dict(server.show),
                            # The boards and their pins come from the server so
                            # the wizard does not carry a second copy that can
                            # drift out of step with the one that validates.
                            "boards": [
                                {"key": board.key, "name": board.name,
                                 "sbus_pin": board.sbus_pin,
                                 "led_pins": list(board.led_pins),
                                 "relay_pins": list(board.relay_pins)}
                                for board in config_module.BOARDS.values()
                            ],
                            "free_board": config_module.FREE_BOARD,
                            "locked": server.show_running(),
                            "path": str(server.config_path)})
            elif path.startswith("/api/model/export/"):
                self._json(server.export_model(
                    unquote(path.split("/api/model/export/")[1])))
            elif path.startswith("/api/project/export/"):
                self._project_zip(unquote(path.split("/api/project/export/")[1]))
            elif path.startswith("/api/plane/"):
                self._json(server.plane_payload(unquote(path.split("/api/plane/")[1])))
            elif path == "/api/bus":
                asked = parse_qs(urlparse(self.path).query).get("frame_us")
                try:
                    frame_us = int(asked[0]) if asked else None
                except ValueError:
                    frame_us = None
                self._json(server.bus_options(frame_us))
            elif path == "/api/toolchain":
                payload = flasher.toolchain_status()
                payload["bootsel"] = flasher.find_bootsel()
                payload["local"] = self._is_local()
                self._json(payload)
            elif path == "/api/job":
                self._json(server.job_state())
            elif path == "/api/projects":
                # Which one is open belongs here rather than in a second call:
                # the list is drawn once and has to mark it straight away.
                open_dir = None
                if server.session and server.session.project is not None \
                        and server.session.project.path is not None:
                    open_dir = server.session.project.path.name
                self._json({"projects": server.session.list_projects()
                            if server.session else [],
                            "open": open_dir,
                            # A project is created for models, so the tab that
                            # creates one needs to know what there is.
                            "models": [
                                {"name": model.name,
                                 "zones": model.zone_count,
                                 "relays": model.bus.relay_count,
                                 "airframe": (model.plane.airframe
                                              if model.plane else "motor"),
                                 # Two models on one jack share a transmitter,
                                 # so a show takes one of them or the other.
                                 # The rule is the server's; the dialogue only
                                 # has to draw it.
                                 "tx_port": model.tx_port,
                                 "has_plane": model.plane is not None}
                                for model in server.show.models
                            ]})
            elif path == "/api/project":
                self._json({"project": server.session.project_payload()
                            if server.session else None})
            elif path == "/api/events":
                self._events()
            else:
                self._json({"error": "not found"}, 404)

        def _static(self, path: str) -> None:
            """Serves the interface out of ``web/``, which is one flat folder.

            Rejecting every path with a slash in it is what keeps this from
            being a directory traversal -- there are no subdirectories to
            reach, so no name that contains a separator can ever be valid.
            """
            name = path.lstrip("/") or "index.html"
            suffix = Path(name).suffix
            file = WEB_ROOT / name
            if "/" in name or suffix not in STATIC_TYPES or not file.is_file():
                self._json({"error": "not found"}, 404)
                return
            self._send(200, file.read_bytes(), STATIC_TYPES[suffix])

        def _is_local(self) -> bool:
            """Building and flashing run commands, so only the local machine may.

            With --web-host 0.0.0.0 the UI is reachable from the network, and
            nobody there should be able to start a compiler or overwrite a
            board's firmware.
            """
            return self.client_address[0] in LOCAL_ADDRESSES

        def _events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            server.watcher_arrived()
            try:
                while True:
                    payload = json.dumps(server.state())
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(0.2)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # browser navigated away
            finally:
                server.watcher_left()

        # ----------------------------------------------------------- POST ---

        # Everything only the machine itself may do. Almost all of it leaves
        # something behind on disk; closing a project does not, but it takes the
        # show away from everybody, which is no business of a phone in a field.
        # Blackout and the transport only move the running show, so those stay
        # reachable from one.
        # Switching the bridge off writes nothing, but it takes the show away
        # from everybody and puts every aircraft into failsafe. That is a
        # decision for whoever sits at the machine, not for a phone in a field.
        STOPS_THE_BRIDGE = ("/api/quit",)

        WRITES_TO_DISK = ("/api/config", "/api/placement", "/api/plane/",
                          "/api/project",
                          "/api/project/new", "/api/project/open",
                          "/api/project/edit", "/api/project/close",
                          "/api/model/import", "/api/project/sweep-audio",
                          "/api/project/apply", "/api/audio/", "/api/job")

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            # Audio arrives as raw bytes, not JSON, and is read by the uploader
            # straight off the socket; everything else is small enough to take
            # in one go so that no branch can leave any behind.
            if not path.startswith(("/api/audio/", "/api/project/import")):
                self._take_body()
            if (path.startswith(self.WRITES_TO_DISK + self.STOPS_THE_BRIDGE)
                    and not self._is_local()):
                self._json({"ok": False, "error": self.REMOTE_DENIED}, 403)
                return
            try:
                if path == "/api/config":
                    self._json(server.save_config(self._read_json().get("config", {})))
                elif path == "/api/placement":
                    self._json(server.save_placement(self._read_json()))
                elif path == "/api/quit":
                    self._json(server.request_quit())
                elif path == "/api/blackout":
                    state = bool(self._read_json().get("on", False))
                    server.mapper.set_blackout(state)
                    self._json({"ok": True, "blackout": state})
                elif path.startswith("/api/plane/"):
                    name = unquote(path.split("/api/plane/")[1])
                    self._json(server.write_plane_header(name))
                elif path == "/api/project/new":
                    body = self._read_json()
                    models = body.get("models")
                    self._json(server.session.new_project(
                        str(body.get("name", "")).strip() or "Show",
                        [str(m) for m in models] if isinstance(models, list) else None))
                elif path == "/api/project/edit":
                    body = self._read_json()
                    models = body.get("models")
                    where = body.get("dir")
                    self._json(server.session.edit_project(
                        str(body.get("name", "")),
                        [str(m) for m in models] if isinstance(models, list) else None,
                        str(where) if where else None))
                elif path == "/api/project/close":
                    server.session.close_project()
                    self._json({"ok": True})
                elif path == "/api/project/sweep-audio":
                    self._json(server.session.sweep_audio(
                        str(self._read_json().get("dir", ""))))
                elif path == "/api/model/import":
                    self._json(server.import_model(
                        self._read_json().get("document", {})))
                elif path == "/api/project/open":
                    self._json(server.session.open_project(
                        str(self._read_json().get("dir", ""))))
                elif path == "/api/project":
                    self._json(server.session.save_project(
                        self._read_json().get("project", {})))
                elif path == "/api/project/apply":
                    # Live edit: heard and seen at once, written on save.
                    self._json(server.session.apply_project(
                        self._read_json().get("project", {})))
                elif path == "/api/transport":
                    self._json(server.transport_command(self._read_json()))
                elif path.startswith("/api/audio/"):
                    self._upload_audio(unquote(path.split("/api/audio/")[1]))
                elif path.startswith("/api/project/import"):
                    self._upload_project(parse_qs(urlparse(self.path).query))
                elif path == "/api/job":
                    body = self._read_json()
                    self._json(server.start_job(body.get("kind", ""),
                                                body.get("model")))
                else:
                    self._json({"error": "not found"}, 404)
            except json.JSONDecodeError as exc:
                self._json({"ok": False, "error": f"ungültiges JSON: {exc}"}, 400)
            except AttributeError as exc:
                # `session` is None when the bridge runs without projects, and
                # that is the case this is here for. Anything else reaching this
                # is a bug, and saying so beats reporting a missing session --
                # which is exactly how a missing method once hid for an hour.
                if server.session is None:
                    self._json({"ok": False, "error": "keine Session aktiv"}, 400)
                else:
                    self._json({"ok": False, "error": f"interner Fehler: {exc}"}, 500)

        def _project_zip(self, dirname: str) -> None:
            answer = server.session.export_project(dirname) \
                if server.session else {"ok": False, "error": "keine Session"}
            if isinstance(answer, dict):
                self._json(answer, 404)
                return
            data, name = answer
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition",
                             f'attachment; filename="{name}.lightshow-projekt.zip"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _upload_project(self, query: dict) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_UPLOAD_BYTES:
                self._json({"ok": False, "error":
                            f"Datei zu groß ({length // 1_000_000} MB, erlaubt sind "
                            f"{MAX_UPLOAD_BYTES // 1_000_000} MB)"}, 413)
                return
            data = self.rfile.read(length)
            wanted = (query.get("name") or [""])[0]
            self._json(server.session.import_project(data, unquote(wanted)))

        def _upload_audio(self, filename: str) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_UPLOAD_BYTES:
                self._json({"ok": False, "error":
                            f"Datei zu groß ({length // 1_000_000} MB, erlaubt sind "
                            f"{MAX_UPLOAD_BYTES // 1_000_000} MB)"}, 413)
                return
            data = self.rfile.read(length)
            self._json(server.session.import_audio(filename, data))

    return Handler
