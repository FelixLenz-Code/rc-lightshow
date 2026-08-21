"""Verifies the web interface's HTTP surface.

Two things matter here and neither is cosmetic. The interface is served out of
one flat directory, so no request may reach a file outside it. And with
``--web-host 0.0.0.0`` the page is reachable from the whole WLAN, while the
endpoints that run a compiler or write into the repository must stay on the
machine the bridge runs on.
"""

from __future__ import annotations

import http.client
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from lightshow import config as config_module
from lightshow import __main__ as entry
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

    def __init__(self) -> None:
        self.reconfigured: list[int] = []

    def close(self) -> None:
        pass

    def reconfigure(self, device, wire_ports) -> None:
        self.device = device
        self.reconfigured.append(len(wire_ports))


def make_show() -> ShowCfg:
    return ShowCfg(
        ports=[PortCfg(id=0, name="tx", nchan=8)],
        models=[
            ModelCfg("eule", 0, channels=[
                ChannelCfg(role="cue", quantize=32, failsafe=1000),
                ChannelCfg(role="hue", failsafe=1500),
                ChannelCfg(role="brightness", failsafe=1000),
                ChannelCfg(role="param", failsafe=1500),
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


# ------------------------------------------------- the preview's physical view


def chain_show():
    """One model whose single chain is cut into two zones -- the case the
    preview exists for, and the one a per-zone view cannot show."""
    from lightshow.config import (BusCfg, OutputCfg, NavLightCfg, PlaneCfg,
                                  SegmentCfg)

    show = make_show()
    model = show.models[0]
    model.channels = model.channels + [
        ChannelCfg(role="cue", quantize=32, failsafe=1000),
        ChannelCfg(role="hue", failsafe=1500),
        ChannelCfg(role="brightness", failsafe=1000),
        ChannelCfg(role="param", failsafe=1500),
    ]
    model.bus = BusCfg()
    model.plane = PlaneCfg(outputs=[OutputCfg(
        name="rumpf", pin=2, count=60, segments=[
            SegmentCfg("vorn", start=0, count=20, zone=0),
            SegmentCfg("hinten", start=20, count=40, zone=1, reverse=True),
        ])],
        nav_lights=[NavLightCfg(output=0, index=59, color=(255, 255, 255))])
    return show


def test_the_state_describes_the_physical_chains():
    """The zone view answers "what does this zone drive"; the preview needs the
    other direction -- what does the chain on GP2 show, all 60 pixels of it."""
    model = chain_show().models[0]
    chains = webui.model_chains(model)
    assert len(chains) == 1
    chain = chains[0]
    assert (chain["name"], chain["pin"], chain["count"]) == ("rumpf", 2, 60)
    assert [(s["start"], s["count"], s["zone"]) for s in chain["segments"]] \
        == [(0, 20, 0), (20, 40, 1)]
    assert chain["segments"][1]["reverse"] is True


def test_a_navigation_light_belongs_to_its_own_chain():
    """It is stamped at an absolute index, so the preview must not have to
    work out which zone happens to cover that pixel."""
    chains = webui.model_chains(chain_show().models[0])
    assert chains[0]["nav_lights"] == [{"index": 59, "color": [255, 255, 255]}]


def test_a_model_without_a_board_has_no_chains():
    assert webui.model_chains(make_show().models[0]) == []


def test_the_preview_page_and_its_script_are_served(server):
    """It is a second window on the same origin, so it comes from here."""
    _, url = server
    for name in ("preview.html", "preview.js", "effects.js"):
        status, body = get(f"{url}/{name}")
        assert status == 200, name
        assert body, name


def test_a_placement_is_written_on_its_own(server):
    """The preview is a second window: sending a whole configuration from there
    would undo whatever the models view has open and unsaved."""
    srv, url = server
    model = srv.show.models[0]
    from lightshow.config import BusCfg, OutputCfg, PlaneCfg, SegmentCfg
    model.bus = BusCfg()
    model.plane = PlaneCfg(outputs=[OutputCfg("rumpf", 2, 30, segments=[
        SegmentCfg("ganz", start=0, count=30, zone=0)])])

    status, answer = post(f"{url}/api/placement", {
        "model": model.name, "output": 0, "segment": 0,
        "place": {"view": "left", "x1": 0.1, "y1": 0.2, "x2": 0.9, "y2": 0.3}})
    assert status == 200 and answer["ok"], answer
    place = model.plane.outputs[0].segments[0].place
    assert (place.view, place.x2) == ("left", 0.9)


def test_a_placement_may_be_taken_back(server):
    srv, url = server
    model = srv.show.models[0]
    from lightshow.config import (BusCfg, OutputCfg, PlacementCfg, PlaneCfg,
                                  SegmentCfg)
    model.bus = BusCfg()
    model.plane = PlaneCfg(outputs=[OutputCfg("rumpf", 2, 30, segments=[
        SegmentCfg("ganz", start=0, count=30, zone=0, place=PlacementCfg())])])

    _, answer = post(f"{url}/api/placement",
                     {"model": model.name, "output": 0, "segment": 0, "place": None})
    assert answer["ok"]
    assert model.plane.outputs[0].segments[0].place is None


def test_a_placement_naming_nothing_says_so(server):
    srv, url = server
    from lightshow.config import BusCfg, OutputCfg, PlaneCfg, SegmentCfg
    model = srv.show.models[0]
    model.bus = BusCfg()
    model.plane = PlaneCfg(outputs=[OutputCfg("rumpf", 2, 30, segments=[
        SegmentCfg("ganz", start=0, count=30, zone=0)])])

    for body, word in [
        ({"model": "gibtsnicht", "output": 0, "segment": 0}, "kein Modell"),
        ({"model": "eule", "output": 9, "segment": 0}, "Ausgang"),
    ]:
        _, answer = post(f"{url}/api/placement", body)
        assert not answer["ok"] and word in answer["error"], answer


# ------------------------------------------------ taking an edit without a restart


def edited_show_dict() -> dict:
    """The fixture's model with a second zone, as the interface would send it."""
    show = make_show()
    model = show.models[0]
    model.channels = model.channels + [
        ChannelCfg(role="cue", quantize=32, failsafe=1000),
        ChannelCfg(role="hue", failsafe=1500),
        ChannelCfg(role="brightness", failsafe=1000),
        ChannelCfg(role="param", failsafe=1500),
    ]
    return config_module.to_dict(show)


def test_a_saved_configuration_is_in_force_at_once(server):
    """Saving used to mean "the next start will do this", which is no answer.

    The list showed the new zones while the wire still carried the old ones, and
    nothing said which of the two was true.
    """
    handle, url = server
    assert handle.show.models[0].zone_count == 1

    status, answer = post(f"{url}/api/config", {"config": edited_show_dict()})
    assert (status, answer["ok"]) == (200, True)

    assert handle.show.models[0].zone_count == 2
    state = json.loads(get(f"{url}/api/state")[1])
    assert state["models"][0]["zones"] == 2


def test_the_mapper_is_rebuilt_for_the_new_zones(server):
    """A rebuilt slot table is the point: an added zone brings its own channels,
    and the encoder that carries them has to grow with it."""
    handle, url = server
    mapper = handle.mapper
    assert len(mapper.slots) == 4
    assert mapper.bus_encoders["eule"].zones == 1

    post(f"{url}/api/config", {"config": edited_show_dict()})

    assert len(mapper.slots) == 8
    assert mapper.bus_encoders["eule"].zones == 2


def test_the_ground_station_is_told_the_new_port_setup(server):
    """It hears the setup once, when it connects, and has no other way to know."""
    handle, url = server
    assert handle.link.reconfigured == []
    post(f"{url}/api/config", {"config": edited_show_dict()})
    assert handle.link.reconfigured == [1]


def test_everything_holding_the_configuration_sees_the_change(server):
    """One configuration in the process, before and after -- not two."""
    handle, url = server
    held = handle.show
    post(f"{url}/api/config", {"config": edited_show_dict()})
    assert handle.show is held
    assert handle.mapper.show is held
    assert held.models[0].zone_count == 2


def test_a_request_body_never_becomes_the_next_request(server):
    """Keep-alive: a body left in the socket is not thrown away.

    It becomes the first bytes of whatever comes next, and the server then sees
    a method called `{}GET`. One branch forgetting to read its body was enough,
    so the body is taken before the branches run -- and this is what says so.
    """
    _, url = server
    host = url.split("//", 1)[1]
    connection = http.client.HTTPConnection(host, timeout=5)
    try:
        # A route whose handler wants nothing from the body.
        connection.request("POST", "/api/project/close", body=json.dumps({}),
                           headers={"Content-Type": "application/json"})
        connection.getresponse().read()
        # Same connection, straight after.
        connection.request("GET", "/api/state")
        second = connection.getresponse()
        assert second.status == 200
        assert json.loads(second.read())["models"]
    finally:
        connection.close()


# ------------------------------------------------- the launcher's questions


def test_browser_url_never_hands_over_a_bind_address():
    """0.0.0.0 is an address to listen on, not one a browser can open."""
    assert entry.browser_url("0.0.0.0", 8765) == "http://127.0.0.1:8765/"
    assert entry.browser_url("::", 8765) == "http://127.0.0.1:8765/"
    assert entry.browser_url("127.0.0.1", 9000) == "http://127.0.0.1:9000/"


def test_already_running_sees_a_live_bridge(server):
    """Double-clicking the launcher twice must find the first bridge.

    Without this a second start would run on blind -- the port is taken, so it
    gets no web interface, but it does grab the serial port and the MIDI name.
    """
    running, url = server
    port = int(url.rsplit(":", 1)[1])
    assert entry.already_running("127.0.0.1", port) is True

    running.stop()
    assert entry.already_running("127.0.0.1", port) is False


# ------------------------------------------------------------- switching off


@pytest.fixture
def stopped(monkeypatch):
    """Catches the shutdown instead of killing the test run."""
    fired = threading.Event()
    monkeypatch.setattr(webui, "stop_process", fired.set)
    monkeypatch.setattr(webui, "QUIT_DELAY_S", 0.01)
    return fired


def test_quit_answers_before_it_stops(server, stopped):
    """The answer has to be out of the door first.

    Stopping tears the web server down with everything else, so a shutdown that
    fires inside the handler would leave the browser with a dead socket and no
    way to tell a refusal from a success.
    """
    _, url = server
    status, body = post(url + "/api/quit")
    assert status == 200 and body["ok"]
    assert stopped.wait(2.0), "die Bridge wurde nicht gestoppt"


def test_quitting_is_refused_from_the_network(server, remote, stopped):
    """A phone in a field must not be able to end the show for everybody."""
    _, url = server
    status, body = post(url + "/api/quit")
    assert status == 403
    assert not body["ok"]
    assert not stopped.wait(0.3), "trotz Absage gestoppt"


# ------------------------------------------------ following the window down


def watch(url: str) -> http.client.HTTPConnection:
    """Opens the event stream the way a window does, and reads one frame."""
    connection = http.client.HTTPConnection(url.split("//", 1)[1], timeout=5)
    connection.request("GET", "/api/events")
    response = connection.getresponse()
    assert response.status == 200
    response.readline()                  # wait until we are really counted
    return connection


def test_the_bridge_follows_the_last_window_down(server, stopped, monkeypatch):
    """Closing the application window is the way out, so it has to work.

    Nothing else would stop a bridge that was started from the menu: there is
    no terminal behind it to press Ctrl-C in.
    """
    running, url = server
    monkeypatch.setattr(webui, "IDLE_QUIT_S", 0.05)
    running.quit_when_idle = True

    connection = watch(url)
    assert not stopped.is_set()
    connection.close()

    assert stopped.wait(2.0), "das letzte Fenster ging, die Bridge blieb"


def test_a_second_window_keeps_it_alive(server, stopped, monkeypatch):
    running, url = server
    monkeypatch.setattr(webui, "IDLE_QUIT_S", 0.05)
    running.quit_when_idle = True

    first, second = watch(url), watch(url)
    first.close()
    assert not stopped.wait(0.4), "eine offene Ansicht war noch da"

    second.close()
    assert stopped.wait(2.0)


def test_a_reload_is_not_a_closed_window(server, stopped, monkeypatch):
    """The stream drops on a reload too -- that is what the wait is for."""
    running, url = server
    monkeypatch.setattr(webui, "IDLE_QUIT_S", 0.5)
    running.quit_when_idle = True

    watch(url).close()
    time.sleep(0.1)
    back = watch(url)                    # the browser is back, as after F5

    assert not stopped.wait(0.9), "ein Neuladen hat die Bridge umgebracht"
    back.close()


def test_without_a_window_of_its_own_nothing_follows(server, stopped, monkeypatch):
    """Started into a browser tab, or from a terminal: closing it means
    nothing, and the bridge keeps running until it is told otherwise."""
    _, url = server
    monkeypatch.setattr(webui, "IDLE_QUIT_S", 0.05)

    watch(url).close()
    assert not stopped.wait(0.4)


def test_a_window_that_never_opened_does_not_stop_anything(server, stopped, monkeypatch):
    """The browser needs a moment to start; an empty count before the first
    window has connected must not be read as 'the last one closed'."""
    running, _ = server
    monkeypatch.setattr(webui, "IDLE_QUIT_S", 0.05)
    running.quit_when_idle = True

    running.watcher_left()               # as a stray disconnect would
    assert not stopped.wait(0.4)
