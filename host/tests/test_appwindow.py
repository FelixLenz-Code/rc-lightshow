"""Verifies how the interface is put on screen.

A local web application that opens as a browser tab does not look like an
application: address bar, the user's other tabs, no slot of its own in the task
bar. Chromium-family browsers fix that with `--app`. What is pinned down here
is that the right command comes out and that a machine without any of those
browsers still gets its interface.
"""

from __future__ import annotations

import pytest

from lightshow import appwindow


@pytest.fixture(autouse=True)
def no_preference(monkeypatch):
    monkeypatch.delenv("LIGHTSHOW_BROWSER", raising=False)


def only(monkeypatch, *available: str) -> None:
    """Makes exactly these binaries exist."""
    monkeypatch.setattr(appwindow.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name in available else None)


URL = "http://127.0.0.1:8765/"


def test_a_chromium_browser_is_asked_for_a_window(monkeypatch):
    only(monkeypatch, "chromium")
    assert appwindow.window_command(URL) == [
        "/usr/bin/chromium", f"--app={URL}", "--class=Lightshow"]


def test_the_order_of_preference_holds(monkeypatch):
    """Brave before Chromium, because BROWSERS says so and not by accident."""
    only(monkeypatch, "chromium", "brave-browser")
    assert appwindow.window_command(URL)[0] == "/usr/bin/brave-browser"


def test_a_flatpak_browser_counts_too(monkeypatch):
    """Brave is a Flatpak on plenty of desktops -- this one included."""
    only(monkeypatch, "flatpak")
    monkeypatch.setattr(appwindow, "flatpak_apps",
                        lambda: {"org.gnome.Calculator", "com.brave.Browser"})
    assert appwindow.window_command(URL) == [
        "flatpak", "run", "com.brave.Browser", f"--app={URL}", "--class=Lightshow"]


def test_without_a_capable_browser_there_is_no_window(monkeypatch):
    only(monkeypatch)
    assert appwindow.window_command(URL) is None


def test_a_named_browser_wins(monkeypatch):
    only(monkeypatch, "chromium", "vivaldi-stable")
    monkeypatch.setenv("LIGHTSHOW_BROWSER", "vivaldi-stable")
    assert appwindow.window_command(URL)[0] == "/usr/bin/vivaldi-stable"


def test_a_tab_can_be_asked_for(monkeypatch):
    only(monkeypatch, "chromium")
    monkeypatch.setenv("LIGHTSHOW_BROWSER", appwindow.PLAIN_TAB)
    assert appwindow.window_command(URL) is None


def test_a_named_browser_that_is_not_there_falls_back(monkeypatch):
    """Not to another browser -- to a tab, so the interface still shows up."""
    only(monkeypatch, "chromium")
    monkeypatch.setenv("LIGHTSHOW_BROWSER", "netscape")
    assert appwindow.window_command(URL) is None


def test_open_window_falls_back_to_a_tab(monkeypatch):
    only(monkeypatch)
    opened = []
    monkeypatch.setattr(appwindow.webbrowser, "open", opened.append)
    assert appwindow.open_window(URL) == (appwindow.TAB, "")
    assert opened == [URL]


def test_open_window_starts_the_browser_detached(monkeypatch):
    """Detached on purpose: the browser must not take the signal that stops the
    bridge, and must not fall over when the bridge does."""
    only(monkeypatch, "chromium")
    started = {}

    def fake_popen(command, **kwargs):
        started["command"] = command
        started["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(appwindow.subprocess, "Popen", fake_popen)
    assert appwindow.open_window(URL) == (appwindow.WINDOW, "chromium")
    assert started["command"][1] == f"--app={URL}"
    assert started["kwargs"]["start_new_session"] is True


def test_a_browser_that_will_not_start_still_shows_the_interface(monkeypatch):
    only(monkeypatch, "chromium")
    monkeypatch.setattr(appwindow.subprocess, "Popen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    opened = []
    monkeypatch.setattr(appwindow.webbrowser, "open", opened.append)
    assert appwindow.open_window(URL) == (appwindow.TAB, "")
    assert opened == [URL]
