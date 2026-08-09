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

# MIDI seen this recently means "a show is running" and the editor stays locked.
SHOW_ACTIVE_S = 3.0
GENERATED_DIR = "firmware/plane/generated"


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


class Server:
    def __init__(self, show: config_module.ShowCfg, mapper, link, config_path: Path,
                 repo_root: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.show = show
        self.mapper = mapper
        self.link = link
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

        models: list[dict] = []
        for model in self.show.models:
            entries = []
            for slot, value_us in slots:
                if slot.model is not model:
                    continue
                span = max(1, slot.port.max_us - slot.port.min_us)
                fraction = (value_us - slot.port.min_us) / span
                decoded = f"{round(fraction * 100)} %"
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
                    "live": slot.raw is not None,
                })
            models.append({
                "name": model.name,
                "midi_channel": model.midi_channel,
                "tx_port": model.tx_port,
                "zones": model.zone_count,
                "has_plane": model.plane is not None,
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
                self.link.close()  # release the port so the reset can happen
            target = lambda: flasher.flash(job, uf2, device)  # noqa: E731
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

            if path == "/":
                self._send(200, (WEB_ROOT / "index.html").read_bytes(),
                           "text/html; charset=utf-8")
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
            elif path == "/api/events":
                self._events()
            else:
                self._json({"error": "not found"}, 404)

        def _is_local(self) -> bool:
            """Building and flashing run commands, so only the local machine may.

            With --web-host 0.0.0.0 the UI is reachable from the network, and
            nobody there should be able to start a compiler or overwrite a
            board's firmware.
            """
            return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

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

        def do_POST(self) -> None:
            path = urlparse(self.path).path
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
                elif path == "/api/job":
                    if not self._is_local():
                        self._json({"ok": False, "error":
                                    "Bauen und Flashen geht nur direkt am Rechner, "
                                    "nicht über das Netzwerk."}, 403)
                        return
                    body = self._read_json()
                    self._json(server.start_job(body.get("kind", ""),
                                                body.get("model")))
                else:
                    self._json({"error": "not found"}, 404)
            except json.JSONDecodeError as exc:
                self._json({"ok": False, "error": f"ungültiges JSON: {exc}"}, 400)

    return Handler
