"""Opens the interface in a window of its own.

The bridge is a local web application, but a browser tab does not look like
one: an address bar saying 127.0.0.1, the user's other tabs next to it, and no
place of its own in the task bar. Every Chromium-family browser drops all of
that with `--app=URL`, and that is the whole trick here.

Firefox has nothing equivalent any more, so if none of them is installed the
interface still opens -- as an ordinary tab, which is worse-looking but works.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from pathlib import Path

#: Binaries that understand `--app`, in the order they are tried.
BROWSERS = ("brave-browser", "google-chrome-stable", "google-chrome",
            "chromium", "chromium-browser", "microsoft-edge", "vivaldi-stable")

#: The same browsers as Flatpaks, for desktops that have them only that way.
FLATPAKS = ("com.brave.Browser", "com.google.Chrome", "org.chromium.Chromium",
            "com.microsoft.Edge")

#: Ties the window to our desktop entry, so it gets our icon and its own slot
#: in the task bar instead of the browser's.
WM_CLASS = "Lightshow"

#: Value of LIGHTSHOW_BROWSER that asks for a plain tab after all.
PLAIN_TAB = "tab"

#: What open_window() ended up doing.
WINDOW = "window"
TAB = "tab"


def _window_args(url: str) -> list[str]:
    return [f"--app={url}", f"--class={WM_CLASS}"]


def flatpak_apps() -> set[str]:
    try:
        done = subprocess.run(["flatpak", "list", "--app", "--columns=application"],
                              capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.strip() for line in done.stdout.splitlines() if line.strip()}


def window_command(url: str) -> list[str] | None:
    """The command that opens `url` as its own window, or None if none can."""
    wanted = os.environ.get("LIGHTSHOW_BROWSER", "").strip()
    if wanted == PLAIN_TAB:
        return None

    for name in (wanted,) if wanted else BROWSERS:
        binary = shutil.which(name)
        if binary:
            return [binary, *_window_args(url)]

    if shutil.which("flatpak"):
        installed = flatpak_apps()
        for app in FLATPAKS:
            if app in installed:
                return ["flatpak", "run", app, *_window_args(url)]
    return None


def open_window(url: str) -> tuple[str, str]:
    """Shows the interface.

    Returns (WINDOW, browser) when it got a window of its own, (TAB, "") when
    the interface ended up in an ordinary browser tab. The caller cares,
    because a window is something you close and a tab is not: only in the first
    case does the bridge follow it down.
    """
    command = window_command(url)
    if command is not None:
        try:
            # Its own session: the browser must not inherit the signal that
            # stops the bridge, and must not die with it either.
            subprocess.Popen(command, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            name = command[2] if command[0].endswith("flatpak") else Path(command[0]).name
            return WINDOW, name
        except OSError as exc:
            print(f"kein eigenes Fenster ({exc}), es wird ein Tab")

    webbrowser.open(url)
    return TAB, ""
