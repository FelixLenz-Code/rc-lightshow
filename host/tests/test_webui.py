"""Verifies the web interface's HTTP surface.

Two things matter here and neither is cosmetic. The interface is served out of
one flat directory, so no request may reach a file outside it. And with
``--web-host 0.0.0.0`` the page is reachable from the whole WLAN, while the
endpoints that run a compiler or write into the repository must stay on the
machine the bridge runs on.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from lightshow import webui
from lightshow.config import ChannelCfg, ModelCfg, PortCfg, ShowCfg
from lightshow.mapping import Mapper


class FakeLink:
    device = "dry"
    dry_run = True
    connected = True
    frames_sent = 0
    last_error = None
    status_lines: list[str] = []

    def close(self) -> None:
        pass


def make_show() -> ShowCfg:
    return ShowCfg(
        ports=[PortCfg(id=0, name="tx", nchan=8)],
        models=[
            ModelCfg("eule", 1, 0, channels=[
                ChannelCfg(role="cue", cc=20, quantize=32, failsafe=1000),
                ChannelCfg(role="hue", cc=21, failsafe=1500),
                ChannelCfg(role="brightness", cc=22, failsafe=1000),
                ChannelCfg(role="param", cc=23, failsafe=1500),
            ]),
        ],
    )


@pytest.fixture
def server(tmp_path):
    show = make_show()
    server = webui.Server(show, Mapper(show), FakeLink(),
                          config_path=tmp_path / "show.yaml", repo_root=tmp_path,
                          host="127.0.0.1", port=0)
    url = server.start()
    yield server, url.rstrip("/")
    server.stop()


def get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def post(url: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body or {}).encode()
    request = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


# --------------------------------------------------------------- static files


def test_the_interface_is_served(server):
    _, url = server
    status, body = get(url + "/")
    assert status == 200
    assert b"<title>Lightshow</title>" in body


@pytest.mark.parametrize("name", ["app.css", "app.js"])
def test_the_stylesheet_and_script_are_served(server, name):
    _, url = server
    status, body = get(f"{url}/{name}")
    assert status == 200
    assert body


def test_every_file_the_page_asks_for_exists(server):
    """A missing asset would leave a blank page, which is easy to ship."""
    _, url = server
    page = get(url + "/")[1].decode()
    for asset in ("app.css", "app.js"):
        assert asset in page, f"{asset} is not referenced by index.html"
        assert get(f"{url}/{asset}")[0] == 200


@pytest.mark.parametrize("path", [
    "/../webui.py",
    "/%2e%2e/webui.py",
    "/..%2fwebui.py",
    "/subdir/app.js",
    "/app.py",
    "/../../../etc/passwd",
])
def test_nothing_outside_the_web_directory_is_reachable(server, path):
    _, url = server
    status, body = get(url + path)
    assert status == 404, f"{path} returned {status}: {body[:200]!r}"


def test_a_file_type_that_is_not_listed_is_refused(server, tmp_path):
    """Only the handful of types the page actually uses are served."""
    secret = webui.WEB_ROOT / "secret.txt"
    secret.write_text("nicht ausliefern")
    try:
        _, url = server
        assert get(url + "/secret.txt")[0] == 404
    finally:
        secret.unlink()


# ------------------------------------------------------------- the local gate


@pytest.fixture
def remote(monkeypatch):
    """Makes loopback look like another machine on the WLAN."""
    monkeypatch.setattr(webui, "LOCAL_ADDRESSES", frozenset())


def test_building_is_refused_from_the_network(server, remote):
    _, url = server
    status, body = post(url + "/api/job", {"kind": "build-ground"})
    assert status == 403
    assert not body["ok"]


def test_writing_the_plane_header_is_refused_from_the_network(server, remote, tmp_path):
    """It writes into the repository, so it belongs behind the same gate."""
    _, url = server
    status, body = post(url + "/api/plane/eule")
    assert status == 403
    assert not body["ok"]
    assert not (tmp_path / webui.GENERATED_DIR).exists()


def test_building_is_allowed_from_the_machine_itself(server):
    """The gate must not lock out the case it exists for."""
    _, url = server
    status, body = post(url + "/api/job", {"kind": "unfug"})
    assert status == 200            # rejected on its merits, not by the gate
    assert body["error"].startswith("unbekannter Vorgang")


def test_reading_stays_open_so_a_phone_can_watch(server, remote):
    _, url = server
    assert get(url + "/api/state")[0] == 200
    assert get(url + "/")[0] == 200


# ------------------------------------------------------------------- payloads


def test_the_state_names_every_model(server):
    _, url = server
    status, body = get(url + "/api/state")
    assert status == 200
    state = json.loads(body)
    assert [model["name"] for model in state["models"]] == ["eule"]
    assert len(state["models"][0]["channels"]) == 4


def test_an_unknown_endpoint_answers_json(server):
    _, url = server
    status, body = get(url + "/api/gibtsnicht")
    assert status == 404
    assert json.loads(body)["error"]


@pytest.mark.parametrize("path,body", [
    ("/api/config", {"config": {}}),
    ("/api/project/new", {"name": "Nachtflug"}),
    ("/api/project/open", {"dir": "irgendwas"}),
    ("/api/project", {"project": {}}),
    ("/api/project/apply", {"project": {}}),
    ("/api/audio/musik.wav", None),
])
def test_nothing_on_disk_can_be_changed_from_the_network(server, remote, path, body):
    """show.yaml decides the failsafe values and the channel mapping.

    Rewriting it from the WLAN is at least as serious as starting a compiler,
    which was behind the gate from the start.
    """
    _, url = server
    status, payload = post(url + path, body)
    assert status == 403
    assert not payload["ok"]


@pytest.mark.parametrize("path,body", [
    ("/api/blackout", {"on": True}),
    ("/api/transport", {"action": "stop"}),
])
def test_the_running_show_can_still_be_reached_from_a_phone(server, remote, path, body):
    """Blackout and transport change nothing on disk -- that is the point of them."""
    _, url = server
    assert post(url + path, body)[0] == 200
