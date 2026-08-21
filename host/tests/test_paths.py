"""Verifies the writable workspace the bridge uses when it runs from an image.

An AppImage is read-only, the bridge is not: it writes the configuration back,
stores projects and builds firmware. So the first start mirrors the image into
a writable tree that looks like the repository. What must not happen is that an
update takes the user's shows with it -- that is what most of this pins down.
"""

from __future__ import annotations

import pytest

from lightshow import paths
from lightshow.__main__ import repo_root


@pytest.fixture
def image(tmp_path):
    """A stand-in for the mounted AppImage."""
    share = tmp_path / "image" / paths.SHARE
    (share / "firmware" / "plane").mkdir(parents=True)
    (share / "firmware" / "plane" / "main.c").write_text("int main(void){}\n")
    (share / "tools" / "ctest").mkdir(parents=True)
    (share / "tools" / "ctest" / "Makefile").write_text("all:\n")
    (share / "config").mkdir()
    (share / "config" / "show.yaml").write_text("rate_hz: 100\n")
    (share / "VERSION").write_text("v1\n")
    return tmp_path / "image"


@pytest.fixture
def bundled(monkeypatch, tmp_path):
    """Puts the process into image mode with a workspace under tmp_path."""
    root = tmp_path / "workspace"
    monkeypatch.setenv("LIGHTSHOW_ROOT", str(root))
    monkeypatch.delenv("LIGHTSHOW_APPDIR", raising=False)
    return root


def test_checkout_is_left_alone(monkeypatch):
    """Without the launcher's variables nothing about the old behaviour moves."""
    monkeypatch.delenv("LIGHTSHOW_ROOT", raising=False)
    monkeypatch.delenv("LIGHTSHOW_APPDIR", raising=False)
    assert not paths.bundled()
    assert str(paths.default_config()) == "config/show.yaml"
    assert paths.prepare() is None


def test_workspace_follows_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("LIGHTSHOW_ROOT", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert paths.workspace() == tmp_path / "data" / "lightshow"


def test_workspace_defaults_below_home(monkeypatch, tmp_path):
    monkeypatch.delenv("LIGHTSHOW_ROOT", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.workspace() == tmp_path / ".local" / "share" / "lightshow"


def test_seed_builds_a_tree_shaped_like_the_repository(image, bundled):
    assert paths.seed(image, bundled) is True

    assert (bundled / "firmware" / "plane" / "main.c").is_file()
    assert (bundled / "tools" / "ctest" / "Makefile").is_file()
    assert (bundled / "config" / "show.yaml").read_text() == "rate_hz: 100\n"
    for name in paths.WORKDIRS:
        assert (bundled / name).is_dir()

    # The point of the shape: repo_root() finds it without knowing about images.
    assert repo_root(bundled / "config" / "show.yaml") == bundled


def test_seeding_twice_does_nothing(image, bundled):
    paths.seed(image, bundled)
    assert paths.seed(image, bundled) is False


def test_user_files_survive_a_new_version(image, bundled):
    paths.seed(image, bundled)

    (bundled / "projects" / "Nachtflug").mkdir(parents=True)
    (bundled / "projects" / "Nachtflug" / "project.json").write_text("{}")
    (bundled / "config" / "show.yaml").write_text("rate_hz: 50\n")
    (bundled / "build" / "plane-eule").mkdir(parents=True)
    generated = bundled / "firmware" / "plane" / "generated"
    generated.mkdir(parents=True)
    (generated / "eule.h").write_text("#define ZONES 4\n")

    (image / paths.SHARE / "VERSION").write_text("v2\n")
    (image / paths.SHARE / "firmware" / "plane" / "main.c").write_text("// neu\n")
    assert paths.seed(image, bundled) is True

    assert (bundled / "firmware" / "plane" / "main.c").read_text() == "// neu\n"
    assert (bundled / "projects" / "Nachtflug" / "project.json").is_file()
    assert (bundled / "config" / "show.yaml").read_text() == "rate_hz: 50\n"
    assert (bundled / "build" / "plane-eule").is_dir()
    assert (generated / "eule.h").read_text() == "#define ZONES 4\n"


def test_mirror_drops_files_the_image_no_longer_has(image, bundled):
    paths.seed(image, bundled)
    (bundled / "firmware" / "plane" / "alt.c").write_text("weg damit\n")

    (image / paths.SHARE / "VERSION").write_text("v2\n")
    paths.seed(image, bundled)

    assert not (bundled / "firmware" / "plane" / "alt.c").exists()


def test_default_config_points_into_the_workspace(bundled):
    assert paths.default_config() == bundled / "config" / "show.yaml"


def test_prepare_seeds_from_the_image(image, bundled, monkeypatch):
    monkeypatch.setenv("LIGHTSHOW_APPDIR", str(image))
    assert paths.prepare() == bundled
    assert (bundled / "firmware" / "plane" / "main.c").is_file()


def test_repo_root_ignores_a_checkout_we_happen_to_stand_in(bundled, tmp_path,
                                                            monkeypatch):
    """Out of an image the workspace wins, whatever the current directory is.

    Started from the menu the working directory is the home directory, started
    from a shell it can be a checkout -- and if that decided where projects go,
    the same AppImage would keep two separate sets of shows.
    """
    checkout = tmp_path / "checkout"
    (checkout / "firmware").mkdir(parents=True)
    (checkout / "host" / "config").mkdir(parents=True)
    monkeypatch.chdir(checkout)
    assert repo_root(checkout / "host" / "config" / "show.yaml") == bundled


def test_repo_root_finds_the_checkout_without_the_launcher(tmp_path, monkeypatch):
    """The venv workflow is untouched: no image variables, no workspace."""
    monkeypatch.delenv("LIGHTSHOW_ROOT", raising=False)
    monkeypatch.delenv("LIGHTSHOW_APPDIR", raising=False)
    checkout = tmp_path / "checkout"
    (checkout / "firmware").mkdir(parents=True)
    (checkout / "host" / "config").mkdir(parents=True)
    monkeypatch.chdir(checkout)
    assert repo_root(checkout / "host" / "config" / "show.yaml") == checkout
