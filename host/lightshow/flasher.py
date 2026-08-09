"""Building and flashing the firmware from the web UI.

Two boards, two ways onto them:

* The ground station runs USB stdio, so the SDK's reset-via-baud-rate is
  active: opening its serial port at 1200 baud drops it into the bootloader.
  No picotool, no udev rules, no sudo -- it then appears as a USB drive and the
  .uf2 is a plain file copy.
* The airborne controller has USB disabled (the port is unpowered in flight and
  the console lives on the UART pins). It cannot be reset from here at all; the
  BOOTSEL button has to be held while plugging it in.

Long jobs run in a thread and stream their output into a Job object the UI
polls, so a five second cmake run does not block the request.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

BOOTSEL_MARKER = "INFO_UF2.TXT"
MAGIC_BAUD = 1200


# --------------------------------------------------------------- toolchain --


def toolchain_status() -> dict:
    """What is missing before a build can even be attempted."""
    sdk = os.environ.get("PICO_SDK_PATH", "")
    sdk_ok = bool(sdk) and (Path(sdk) / "external" / "pico_sdk_import.cmake").is_file()
    compiler = shutil.which("arm-none-eabi-gcc")
    cmake = shutil.which("cmake")

    missing = []
    if not cmake:
        missing.append("cmake")
    if not compiler:
        missing.append("gcc-arm-none-eabi")
    if not sdk_ok:
        missing.append("PICO_SDK_PATH auf ein pico-sdk-Verzeichnis")

    return {
        "ok": not missing,
        "cmake": cmake,
        "compiler": compiler,
        "sdk": sdk if sdk_ok else None,
        "missing": missing,
        "hint": ("sudo apt install gcc-arm-none-eabi libnewlib-arm-none-eabi "
                 "libstdc++-arm-none-eabi-newlib && "
                 "export PICO_SDK_PATH=~/pico-sdk") if missing else "",
    }


# ------------------------------------------------------------ bootsel drive --


def default_mount_roots() -> list[Path]:
    user = os.environ.get("USER", "")
    return [Path("/media") / user, Path("/run/media") / user,
            Path("/media"), Path("/mnt")]


def find_bootsel(roots: list[Path] | None = None) -> list[str]:
    """Mounted RP2040 bootloader volumes, recognised by their INFO_UF2.TXT."""
    roots = default_mount_roots() if roots is None else roots
    found: list[str] = []
    for root in roots:
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if (entry / BOOTSEL_MARKER).is_file() and str(entry) not in found:
                    found.append(str(entry))
            except OSError:
                continue
    return found


def reboot_to_bootsel(device: str) -> tuple[bool, str]:
    """Drops a board with USB stdio into the bootloader by touching 1200 baud."""
    try:
        import serial
    except ImportError:  # pragma: no cover - pyserial is a hard dependency
        return False, "pyserial fehlt"

    try:
        port = serial.Serial(device, baudrate=MAGIC_BAUD)
        port.dtr = False
        port.close()
    except (OSError, Exception) as exc:  # serial.SerialException subclasses OSError
        return False, f"{device}: {exc}"

    # The board re-enumerates as a mass storage device; give udisks a moment.
    for _ in range(50):
        time.sleep(0.2)
        if find_bootsel():
            return True, "Board ist im Bootloader"
    return False, ("Board hat den Bootloader nicht gemeldet. Wenn es nicht "
                   "automatisch eingehängt wird, BOOTSEL gedrückt halten und "
                   "neu anstecken.")


# ---------------------------------------------------------------- the jobs --


@dataclass
class Job:
    name: str
    lines: list[str] = field(default_factory=list)
    done: bool = False
    ok: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def log(self, text: str) -> None:
        with self._lock:
            self.lines.append(text.rstrip())
            del self.lines[:-400]

    def snapshot(self) -> dict:
        with self._lock:
            return {"name": self.name, "lines": list(self.lines),
                    "done": self.done, "ok": self.ok}

    def finish(self, ok: bool, message: str = "") -> None:
        if message:
            self.log(message)
        with self._lock:
            self.ok = ok
            self.done = True


def _run(job: Job, command: list[str], cwd: Path) -> bool:
    job.log("$ " + " ".join(command))
    try:
        process = subprocess.Popen(command, cwd=str(cwd), stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, bufsize=1)
    except OSError as exc:
        job.log(f"! {exc}")
        return False
    assert process.stdout is not None
    for line in process.stdout:
        job.log(line)
    return process.wait() == 0


def build_plane(job: Job, repo: Path, model: str) -> None:
    """Configures and builds the airborne firmware for one model."""
    status = toolchain_status()
    if not status["ok"]:
        job.finish(False, "Toolchain unvollständig: " + ", ".join(status["missing"])
                   + "\n" + status["hint"])
        return

    header = repo / "firmware" / "plane" / "generated" / f"{model}.h"
    if not header.is_file():
        job.finish(False, f"{header} fehlt — zuerst config.h schreiben")
        return

    build_dir = f"build/plane-{model}"
    ok = _run(job, ["cmake", "-S", "firmware/plane", "-B", build_dir,
                    "-DCMAKE_BUILD_TYPE=Release",
                    f"-DPLANE_CONFIG=generated/{model}.h"], repo)
    if ok:
        ok = _run(job, ["cmake", "--build", build_dir, "-j4"], repo)

    artefact = plane_image(repo, model)
    if ok and artefact is not None:
        job.finish(True, f"fertig: {artefact}")
    else:
        job.finish(False, "Build fehlgeschlagen")


def plane_image(repo: Path, model: str) -> Path | None:
    """The built image for a model, if there is one.

    Images are named after the model so four aircraft cannot end up with four
    identically named files -- and the pin assignment differs per model, so
    flashing the wrong one is not a cosmetic mistake.
    """
    build_dir = repo / f"build/plane-{model}"
    for name in (f"lightshow_plane_{model}.uf2", "lightshow_plane.uf2"):
        candidate = build_dir / name
        if candidate.is_file():
            return candidate
    return None


def build_ground(job: Job, repo: Path) -> None:
    status = toolchain_status()
    if not status["ok"]:
        job.finish(False, "Toolchain unvollständig: " + ", ".join(status["missing"])
                   + "\n" + status["hint"])
        return

    ok = _run(job, ["cmake", "-S", "firmware/pico", "-B", "build/pico",
                    "-DCMAKE_BUILD_TYPE=Release"], repo)
    if ok:
        ok = _run(job, ["cmake", "--build", "build/pico", "-j4"], repo)

    artefact = repo / "build" / "pico" / "lightshow_tx.uf2"
    job.finish(bool(ok and artefact.is_file()),
               f"fertig: {artefact}" if ok else "Build fehlgeschlagen")


def flash(job: Job, uf2: Path, auto_reset_device: str | None = None,
          roots: list[Path] | None = None) -> None:
    """Copies a .uf2 onto a bootloader volume, resetting the board if it can."""
    if not uf2.is_file():
        job.finish(False, f"{uf2} fehlt — zuerst bauen")
        return

    drives = find_bootsel(roots)
    if not drives and auto_reset_device:
        job.log(f"Kein Bootloader gefunden, versuche Reset über {auto_reset_device} "
                f"({MAGIC_BAUD} Baud)")
        ok, message = reboot_to_bootsel(auto_reset_device)
        job.log(message)
        if ok:
            drives = find_bootsel(roots)

    if not drives:
        job.finish(False, "Kein Board im Bootloader gefunden. BOOTSEL gedrückt "
                          "halten, USB anstecken, Taste loslassen — das Laufwerk "
                          "RPI-RP2 muss eingehängt sein.")
        return
    if len(drives) > 1:
        job.finish(False, "Mehrere Boards im Bootloader: "
                   + ", ".join(drives)
                   + ". Nur eines anstecken, damit nichts verwechselt wird.")
        return

    target = Path(drives[0]) / uf2.name
    job.log(f"kopiere {uf2.name} ({uf2.stat().st_size // 1024} KB) nach {drives[0]}")
    try:
        shutil.copyfile(uf2, target)
        # The board reboots the moment it has the image; a failing flush here is
        # normal and not an error.
        try:
            os.sync()
        except OSError:
            pass
    except OSError as exc:
        # Same story: it may disconnect mid-write once the image is complete.
        job.log(f"Hinweis beim Schreiben: {exc}")

    job.finish(True, "Aufgespielt. Das Board startet selbständig neu.")
