"""Local web interface for the bridge.

Runs a small HTTP server in a background thread, using nothing but the standard
library. It shows whether the DAW and the ground Pico are connected, what is
arriving on each channel, lets you edit the per-model output configuration and
generates the airborne controller's header plus its wiring list.

Configuration cannot be edited while a show is running: as long as MIDI keeps
arriving, the editor is locked so a mapping cannot change mid-show.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

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
}

# Loopback, in every shape the socket layer reports it. Requests from anywhere
# else may look but not build, flash or write into the repository.
LOCAL_ADDRESSES = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})

# MIDI seen this recently means "a show is running" and the editor stays locked.
SHOW_ACTIVE_S = 3.0
GENERATED_DIR = "firmware/plane/generated"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


def alsa_connections(port_name: str) -> list[str]:
    """Clients connected to our MIDI input, via aconnect.

    This is what answers "is the DAW actually wired up", as opposed to "are
    messages arriving". Returns an empty list if aconnect is unavailable.
    """
    try:
        out = subprocess.run(["aconnect", "-l"], capture_output=True, timeout=2,
                             check=True).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return []

    sources: list[str] = []
    clients: dict[str, str] = {}
    current_client = ""
    in_our_port = False

    for line in out.splitlines():
        if line.startswith("client "):
            # client 128: 'lightshow' [type=user,...]
            parts = line.split("'")
            current_client = parts[1] if len(parts) > 1 else line
            number = line.split()[1].rstrip(":")
            clients[number] = current_client
            in_our_port = False
        elif line.startswith("    ") and "'" in line and not line.strip().startswith("Connect"):
            in_our_port = port_name in line and port_name in current_client
        elif in_our_port and "Connecting From:" in line:
            for ref in line.split("Connecting From:")[1].split(","):
                ref = ref.strip()
                number = ref.split(":")[0]
                sources.append(f"{clients.get(number, 'Client ' + number)} ({ref})")
    return sources


def zone_outputs(model: config_module.ModelCfg) -> list[dict]:
    """Which lamps and relays each zone of a model actually drives.

    A light track in the editor addresses a zone, and a zone is only a number
    until you know what hangs on it. This is what lets the editor say "this
    effect runs on flaeche_links and flaeche_rechts, 60 pixels" instead of
    "Zone 1", and what lets it show which relays a cue will switch.
    """
    out: list[dict] = []
    plane = model.plane

    for zone in range(model.zone_count):
        strips = [s for s in plane.strips if s.zone == zone] if plane else []
        relays = [r for r in plane.relays if r.zone == zone] if plane else []
        # The virtual chain a chase runs across is as long as the furthest
        # strip reaches, not the sum of their pixel counts -- strips that share
        # an offset are mirrors of each other.
        pixels = max((s.offset + s.count for s in strips), default=0)
        out.append({
            "zone": zone,
            "base_channel": model.zone_base_channel(zone),
            "pixels": pixels,
            "strips": [{"name": s.name, "pin": s.pin, "count": s.count,
                        "offset": s.offset, "reverse": s.reverse} for s in strips],
            "relays": [{"name": r.name, "pin": r.pin, "source": r.source,
                        "arg": r.arg, "threshold": r.threshold,
                        "active_low": r.active_low, "min_on_ms": r.min_on_ms,
                        "min_off_ms": r.min_off_ms} for r in relays],
        })
    return out


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

        self._last_message_count = 0
        self._last_message_at = 0.0
        self._midi_rate = 0.0
        self._rate_window = (0.0, 0)
        self._alsa: list[str] = []
        self._alsa_checked = 0.0
        self._job: flasher.Job | None = None

    # ------------------------------------------------------------------ state

    def show_running(self) -> bool:
        """A show is running while the transport plays or MIDI keeps arriving."""
        if self.session is not None and self.session.transport.playing:
            return True
        return (time.monotonic() - self._last_message_at) < SHOW_ACTIVE_S

    def _refresh_counters(self) -> None:
        _, messages, _ = self.mapper.snapshot()
        now = time.monotonic()
        if messages != self._last_message_count:
            self._last_message_count = messages
            self._last_message_at = now

        window_start, window_count = self._rate_window
        if now - window_start >= 1.0:
            if window_start:
                self._midi_rate = (messages - window_count) / (now - window_start)
            self._rate_window = (now, messages)

        if now - self._alsa_checked > 3.0:
            self._alsa_checked = now
            self._alsa = alsa_connections(self.show.midi_port_name)

    def state(self) -> dict:
        self._refresh_counters()
        blackout, messages, slots = self.mapper.snapshot()

        # The values actually being sent, whatever produced them. Falling back
        # to the MIDI snapshot keeps this working without a session.
        sent = self.session.last_frame if self.session is not None else None

        models: list[dict] = []
        for model in self.show.models:
            entries = []
            for slot, snapshot_us in slots:
                if slot.model is not model:
                    continue
                value_us = snapshot_us
                if sent is not None and slot.model.tx_port < len(sent):
                    port_values = sent[slot.model.tx_port]
                    if slot.port_index < len(port_values):
                        value_us = port_values[slot.port_index]
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
                    "cc": slot.channel.cc,
                    "cc_lsb": slot.channel.cc_lsb,
                    "channel": slot.port_index + 1,
                    "us": value_us,
                    "fraction": round(fraction, 4),
                    "decoded": decoded,
                    # What the airborne firmware will decode this to: a step
                    # index for quantised channels, 0..255 otherwise. The
                    # interface previews the effect from these, so it must not
                    # have to parse `decoded` back apart.
                    "step": step,
                    "level": round(fraction * 255),
                    "live": slot.raw is not None or value_us != slot.channel.failsafe,
                })
            models.append({
                "name": model.name,
                "midi_channel": model.midi_channel,
                "tx_port": model.tx_port,
                "tx_offset": model.tx_offset,
                "zones": model.zone_count,
                "has_plane": model.plane is not None,
                # The interface previews the effect this model will show, and
                # the ceiling is part of what it looks like.
                "max_brightness": model.plane.max_brightness if model.plane else 255,
                "outputs": zone_outputs(model),
                "channels": entries,
            })

        return {
            "midi": {
                "port": self.show.midi_port_name,
                "connections": self._alsa,
                "messages": messages,
                "rate": round(self._midi_rate, 1),
                "receiving": self.show_running(),
            },
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

    def save_config(self, data: dict) -> dict:
        if self.show_running():
            return {"ok": False, "error":
                    "Es läuft eine Show — MIDI kommt gerade herein. "
                    "Zum Bearbeiten die Wiedergabe in der DAW stoppen."}
        try:
            new_show = config_module.load_dict(data)
        except config_module.ConfigError as exc:
            return {"ok": False, "error": str(exc)}
        except (TypeError, ValueError, KeyError) as exc:
            return {"ok": False, "error": f"ungültige Eingabe: {exc}"}

        with self._lock:
            config_module.save(new_show, self.config_path)
        return {"ok": True,
                "note": "Gespeichert. Die Bridge übernimmt Änderungen beim "
                        "nächsten Start; die Bordkonfiguration muss neu "
                        "generiert und geflasht werden."}

    def model_by_name(self, name: str) -> config_module.ModelCfg | None:
        for model in self.show.models:
            if model.name == name:
                return model
        return None

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
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


def _make_handler(server: Server):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        REMOTE_DENIED = ("Das geht nur direkt am Rechner, auf dem die Bridge "
                         "läuft — nicht über das Netzwerk.")

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
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length) or b"{}")

        # ------------------------------------------------------------ GET ---

        def do_GET(self) -> None:
            path = urlparse(self.path).path

            if path == "/" or not path.startswith("/api/"):
                self._static(path)
            elif path == "/api/state":
                self._json(server.state())
            elif path == "/api/config":
                self._json({"config": config_module.to_dict(server.show),
                            "locked": server.show_running(),
                            "path": str(server.config_path)})
            elif path.startswith("/api/plane/"):
                self._json(server.plane_payload(unquote(path.split("/api/plane/")[1])))
            elif path == "/api/toolchain":
                payload = flasher.toolchain_status()
                payload["bootsel"] = flasher.find_bootsel()
                payload["local"] = self._is_local()
                self._json(payload)
            elif path == "/api/job":
                self._json(server.job_state())
            elif path == "/api/projects":
                self._json({"projects": server.session.list_projects()
                            if server.session else []})
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
            try:
                while True:
                    payload = json.dumps(server.state())
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(0.2)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # browser navigated away

        # ----------------------------------------------------------- POST ---

        # Everything that leaves something behind on disk. Blackout and the
        # transport only move the running show, so a phone on the field may
        # still reach those; the rest changes what the next start will do.
        WRITES_TO_DISK = ("/api/config", "/api/plane/", "/api/project",
                          "/api/project/new", "/api/project/open",
                          "/api/project/apply", "/api/audio/", "/api/job")

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path.startswith(self.WRITES_TO_DISK) and not self._is_local():
                self._json({"ok": False, "error": self.REMOTE_DENIED}, 403)
                return
            try:
                if path == "/api/config":
                    self._json(server.save_config(self._read_json().get("config", {})))
                elif path == "/api/blackout":
                    state = bool(self._read_json().get("on", False))
                    server.mapper.set_blackout(state)
                    self._json({"ok": True, "blackout": state})
                elif path.startswith("/api/plane/"):
                    name = unquote(path.split("/api/plane/")[1])
                    self._json(server.write_plane_header(name))
                elif path == "/api/project/new":
                    self._json(server.session.new_project(
                        str(self._read_json().get("name", "")).strip() or "Show"))
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
                elif path == "/api/job":
                    body = self._read_json()
                    self._json(server.start_job(body.get("kind", ""),
                                                body.get("model")))
                else:
                    self._json({"error": "not found"}, 404)
            except json.JSONDecodeError as exc:
                self._json({"ok": False, "error": f"ungültiges JSON: {exc}"}, 400)
            except AttributeError:
                # session is None when the bridge runs without projects
                self._json({"ok": False, "error": "keine Session aktiv"}, 400)

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
