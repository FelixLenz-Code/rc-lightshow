"""Where the bridge keeps its files when it is not run from a checkout.

In a source checkout everything lives in the tree: the configuration in
``host/config/show.yaml``, projects in ``projects/``, firmware builds in
``build/``.  An AppImage cannot work that way, because its own tree is a
read-only squashfs.  So the launcher points ``LIGHTSHOW_APPDIR`` at the mounted
image and the first start mirrors the read-only parts into a writable workspace
that has the *same shape as the repository*:

    ~/.local/share/lightshow/
        firmware/          mirrored from the image, renewed on a new version
        tools/             mirrored from the image
        host/              empty marker, so repo_root() recognises the tree
        config/show.yaml   seeded once, a user file from then on
        projects/          user data, never touched again
        build/             firmware artefacts
        .seeded            the version that was mirrored

Keeping the repository shape is what makes the rest of the code work unchanged:
``repo_root()`` still finds ``firmware/`` next to ``host/``, the flash tab still
builds into ``build/``, and projects still land in ``projects/``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

#: Subdirectories of the image that are mirrored into the workspace.
MIRRORED = ("firmware", "tools")

#: Mirrored paths that hold generated files and survive a version change.
PRESERVED = ("firmware/plane/generated",)

#: Directories the bridge writes into and that the mirror must not own.
WORKDIRS = ("host", "projects", "build")

SHARE = "usr/share/lightshow"


def appdir() -> Path | None:
    """The mounted AppImage, or None when the bridge runs from a checkout."""
    value = os.environ.get("LIGHTSHOW_APPDIR", "")
    return Path(value) if value else None


def workspace() -> Path:
    """The writable tree that stands in for the repository."""
    override = os.environ.get("LIGHTSHOW_ROOT", "")
    if override:
        return Path(override)
    data = os.environ.get("XDG_DATA_HOME", "") or "~/.local/share"
    return Path(data).expanduser() / "lightshow"


def bundled() -> bool:
    """True when a launcher has told us we are running from an image."""
    return bool(os.environ.get("LIGHTSHOW_APPDIR") or os.environ.get("LIGHTSHOW_ROOT"))


def default_config() -> Path:
    """Where ``--config`` points when nobody says otherwise."""
    if bundled():
        return workspace() / "config" / "show.yaml"
    return Path("config/show.yaml")


def _mirror(src: Path, dst: Path, preserve: tuple[str, ...] = ()) -> None:
    """Replaces `dst` with `src` but carries generated subtrees across."""
    saved: dict[str, Path] = {}
    for rel in preserve:
        path = dst / rel
        if path.is_dir():
            # Parked next to the workspace, because `dst` is about to go.
            saved[rel] = dst.parent / f".keep-{rel.replace('/', '-')}"
            if saved[rel].exists():
                shutil.rmtree(saved[rel])
            path.replace(saved[rel])
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    for rel, parked in saved.items():
        target = dst / rel
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        parked.replace(target)


def seed(image: Path, root: Path) -> bool:
    """Brings the workspace up to the image's version.

    Returns True when something was mirrored.  The configuration is copied only
    if it is missing -- from the second start on it belongs to the user, as do
    `projects/` and `build/`, which the mirror never writes to at all.
    """
    share = Path(image) / SHARE
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    version = (share / "VERSION").read_text().strip() if (share / "VERSION").is_file() else ""
    stamp = root / ".seeded"
    current = stamp.read_text().strip() if stamp.is_file() else None
    if current == version and all((root / name).is_dir() for name in MIRRORED):
        return False

    for name in MIRRORED:
        source = share / name
        if source.is_dir():
            _mirror(source, root / name,
                    tuple(rel[len(name) + 1:] for rel in PRESERVED
                          if rel.startswith(f"{name}/")))
    for name in WORKDIRS:
        (root / name).mkdir(exist_ok=True)

    config = root / "config" / "show.yaml"
    if not config.exists() and (share / "config" / "show.yaml").is_file():
        config.parent.mkdir(exist_ok=True)
        shutil.copy2(share / "config" / "show.yaml", config)

    stamp.write_text(version + "\n")
    return True


def prepare() -> Path | None:
    """Seeds the workspace if we run from an image.  Returns it, or None."""
    if not bundled():
        return None
    root = workspace()
    image = appdir()
    if image is not None:
        seed(image, root)
    return root
