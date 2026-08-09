"""Verifies building and flashing from the UI.

The parts worth pinning down are the ones that decide whether an image ends up
on the right board: recognising a bootloader volume, refusing to guess when
several are plugged in, and reporting a missing toolchain instead of a cryptic
compiler error.
"""

from __future__ import annotations

from pathlib import Path

from lightshow import flasher


def make_bootsel(root: Path, name: str = "RPI-RP2") -> Path:
    drive = root / name
    drive.mkdir(parents=True)
    (drive / flasher.BOOTSEL_MARKER).write_text("UF2 Bootloader v3.0\n")
    return drive


# ------------------------------------------------------------------ bootsel


def test_a_bootloader_volume_is_recognised(tmp_path):
    make_bootsel(tmp_path)
    assert flasher.find_bootsel([tmp_path]) == [str(tmp_path / "RPI-RP2")]


def test_an_ordinary_drive_is_not_mistaken_for_one(tmp_path):
    (tmp_path / "Urlaubsfotos").mkdir()
    assert flasher.find_bootsel([tmp_path]) == []


def test_missing_mount_roots_do_not_raise(tmp_path):
    assert flasher.find_bootsel([tmp_path / "gibtsnicht"]) == []


def test_two_boards_are_both_reported(tmp_path):
    make_bootsel(tmp_path, "RPI-RP2")
    make_bootsel(tmp_path, "RPI-RP2-1")
    assert len(flasher.find_bootsel([tmp_path])) == 2


# -------------------------------------------------------------------- flash


def test_flashing_copies_the_image_to_the_board(tmp_path):
    drive = make_bootsel(tmp_path)
    uf2 = tmp_path / "lightshow_plane.uf2"
    uf2.write_bytes(b"UF2\x0a" * 64)

    job = flasher.Job("test")
    flasher.flash(job, uf2, None, roots=[tmp_path])

    assert job.ok, job.lines
    assert (drive / "lightshow_plane.uf2").read_bytes() == uf2.read_bytes()


def test_flashing_without_a_board_explains_bootsel(tmp_path):
    uf2 = tmp_path / "x.uf2"
    uf2.write_bytes(b"x")
    job = flasher.Job("test")
    flasher.flash(job, uf2, None, roots=[tmp_path])
    assert not job.ok
    assert "BOOTSEL" in "\n".join(job.lines)


def test_flashing_refuses_to_guess_between_two_boards(tmp_path):
    make_bootsel(tmp_path, "RPI-RP2")
    make_bootsel(tmp_path, "RPI-RP2-1")
    uf2 = tmp_path / "x.uf2"
    uf2.write_bytes(b"x")

    job = flasher.Job("test")
    flasher.flash(job, uf2, None, roots=[tmp_path])
    assert not job.ok
    assert "Mehrere Boards" in "\n".join(job.lines)
    # Nothing may have been written to either drive.
    assert not (tmp_path / "RPI-RP2" / "x.uf2").exists()


def test_flashing_a_missing_image_says_build_first(tmp_path):
    job = flasher.Job("test")
    flasher.flash(job, tmp_path / "nicht-gebaut.uf2", None, roots=[tmp_path])
    assert not job.ok
    assert "bauen" in "\n".join(job.lines)


# ---------------------------------------------------------------- toolchain


def test_toolchain_reports_a_missing_sdk(monkeypatch, tmp_path):
    monkeypatch.delenv("PICO_SDK_PATH", raising=False)
    status = flasher.toolchain_status()
    assert not status["ok"]
    assert any("PICO_SDK_PATH" in item for item in status["missing"])
    assert "apt install" in status["hint"]


def test_toolchain_accepts_a_real_sdk_layout(monkeypatch, tmp_path):
    (tmp_path / "external").mkdir()
    (tmp_path / "external" / "pico_sdk_import.cmake").write_text("")
    monkeypatch.setenv("PICO_SDK_PATH", str(tmp_path))
    monkeypatch.setattr(flasher.shutil, "which", lambda name: "/usr/bin/" + name)

    status = flasher.toolchain_status()
    assert status["ok"] and status["sdk"] == str(tmp_path)


def test_toolchain_rejects_a_directory_that_is_not_the_sdk(monkeypatch, tmp_path):
    monkeypatch.setenv("PICO_SDK_PATH", str(tmp_path))
    assert not flasher.toolchain_status()["ok"]


# ---------------------------------------------------------------------- job


def test_job_log_is_capped_so_a_long_build_cannot_grow_forever():
    job = flasher.Job("test")
    for index in range(1000):
        job.log(f"line {index}")
    state = job.snapshot()
    assert len(state["lines"]) == 400
    assert state["lines"][-1] == "line 999"


def test_build_refuses_without_a_generated_header(tmp_path, monkeypatch):
    monkeypatch.setattr(flasher, "toolchain_status",
                        lambda: {"ok": True, "missing": [], "hint": ""})
    job = flasher.Job("test")
    flasher.build_plane(job, tmp_path, "eule")
    assert not job.ok
    assert "config.h" in "\n".join(job.lines)
