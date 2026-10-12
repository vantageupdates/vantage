"""Community client tests use only an in-process loopback HTTP server."""
import copy
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
import threading
import time
from urllib.parse import urlsplit

from PySide6.QtWidgets import QApplication
import pytest

from vantage.helpers import boat_community as community
from vantage.helpers.boats import BOAT_ROUTES, _phase_seconds, _remaining_seconds


UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
TEST_TOKEN = "private_test_token_" + "a" * 24


def snapshot(server="Green", when=NOW, observations=None, revision=1, pending=0):
    return {
        "schema": 1, "route_model": 1, "server": server,
        "server_time": when.isoformat(), "revision": revision,
        "observations": [] if observations is None else observations,
        "pending_corrections": pending}


def observation(route=BOAT_ROUTES[0], when=NOW, reporter="Mindflux"):
    return {
        "boat": route.boat_id, "start_point": route.start_point,
        "kind": "dock_arrival", "observed_at": when.isoformat(),
        "phase_origin_at": (when - datetime.timedelta(
            seconds=route.announcement_to_dock)).isoformat(),
        "reported_by": reporter, "confidence": "unconfirmed",
        "id": f"public-{route.boat_id}"}


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def wait_for(app, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert predicate(), "The fake-network workflow did not finish."


@pytest.fixture
def server():
    class FakeServer(ThreadingHTTPServer):
        daemon_threads = True

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.respond("GET")

        def do_POST(self):
            self.respond("POST")

        def respond(self, method):
            size = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(size) if size else b""
            body = json.loads(raw_body) if raw_body else None
            endpoint = urlsplit(self.path).path
            self.server.calls.append({
                "method": method, "path": self.path, "body": body,
                "authorization": self.headers.get("Authorization", "")})
            actions = self.server.actions.get((method, endpoint), [])
            action = actions.pop(0) if actions else {}
            if callable(action):
                action = action(body)
            if action.get("delay"):
                time.sleep(action["delay"])
            if endpoint == "/v1/devices":
                default = {"schema": 1, "token": TEST_TOKEN}
            elif endpoint == "/v1/observations":
                default = {"schema": 1, "status": "accepted",
                           "snapshot": snapshot(body["server"], datetime.datetime.now(UTC),
                                                [observation(when=datetime.datetime.now(UTC)
                                                             - datetime.timedelta(seconds=1))])}
            else:
                query_server = "Blue" if "server=Blue" in self.path else "Green"
                default = snapshot(query_server, datetime.datetime.now(UTC))
            payload = action.get("raw")
            if payload is None:
                payload = json.dumps(action.get("payload", default)).encode("utf-8")
            try:
                self.send_response(action.get("status", 200))
                self.send_header("Content-Type", "application/json")
                if action.get("content_length", True):
                    self.send_header("Content-Length", str(len(payload)))
                for name, value in action.get("headers", {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(payload)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    instance = FakeServer(("127.0.0.1", 0), Handler)
    instance.calls = []
    instance.actions = {}
    thread = threading.Thread(
        target=instance.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    instance.url = f"http://127.0.0.1:{instance.server_port}"
    yield instance
    instance.shutdown()
    instance.server_close()
    thread.join(timeout=1)


@pytest.fixture
def clients(app, tmp_path, server):
    created = []

    def make(**kwargs):
        client = community.CommunityBoatClient(
            base_url=kwargs.pop("base_url", server.url),
            cache_dir=kwargs.pop("cache_dir", tmp_path), **kwargs)
        created.append(client)
        return client

    yield make
    for client in created:
        for reply in list(client._requests):
            reply.abort()
        client.deleteLater()
    app.processEvents()


def test_parser_expands_seven_rows_with_clock_offset_and_actual_arrival_age():
    reports = [observation(route) for route in (
        BOAT_ROUTES[0], BOAT_ROUTES[2], BOAT_ROUTES[3], BOAT_ROUTES[5])]
    local_received = NOW + datetime.timedelta(hours=8)
    rows = community.parse_snapshot(
        snapshot(observations=reports), "Green", local_received,
        local_received + datetime.timedelta(seconds=10))
    assert [row.route for row in rows] == list(BOAT_ROUTES)
    assert len(rows) == 7
    assert all(row.last_seen == local_received for row in rows)
    assert all(row.reporter == "Mindflux" and row.confidence == "unconfirmed"
               and row.source == "Vantage Community · Green" and not row.stale
               for row in rows)
    assert rows[0].phase_origin_at == local_received - datetime.timedelta(seconds=119)
    assert rows[0].remaining_seconds == 769
    assert rows[1].remaining_seconds == 381
    assert rows[2].remaining_seconds == 2015


@pytest.mark.parametrize("index", range(7))
def test_dock_anchor_preserves_original_selected_route_period(index):
    route = BOAT_ROUTES[index]
    arrival = NOW - datetime.timedelta(seconds=route.trip_seconds * 7 + 18)
    rows = community.parse_snapshot(
        snapshot(observations=[observation(route, arrival)]), "Green", NOW, NOW)
    phase = _phase_seconds(
        route, (NOW - arrival).total_seconds() + route.announcement_to_dock)
    assert rows and all(row.stale for row in rows)
    assert all(row.remaining_seconds == _remaining_seconds(row.route, phase)
               for row in rows)


def test_empty_snapshot_never_fabricates_arrivals():
    assert community.parse_snapshot(snapshot("Blue"), "Blue", NOW, NOW) == []


def test_arrival_freshness_does_not_include_the_large_dock_offset():
    value = snapshot(observations=[observation(BOAT_ROUTES[2])])
    rows = community.parse_snapshot(value, "Green", NOW, NOW)
    assert rows[0].last_seen == NOW and not rows[0].stale
    assert rows[0].phase_origin_at == NOW - datetime.timedelta(seconds=1975)


def test_cached_age_becomes_stale_without_resetting_the_receipt_offset():
    value = snapshot(observations=[observation(BOAT_ROUTES[5])])
    rows = community.parse_snapshot(
        value, "Green", NOW, NOW + datetime.timedelta(seconds=519 * 3))
    assert rows[0].last_seen == NOW
    assert rows[0].stale


@pytest.mark.parametrize("mutate", [
    lambda value: value.update(schema=True),
    lambda value: value.update(schema=2),
    lambda value: value.update(route_model=True),
    lambda value: value.update(route_model=2),
    lambda value: value.update(server="Blue"),
    lambda value: value.update(revision=True),
    lambda value: value.update(revision=-1),
    lambda value: value.update(pending_corrections=True),
    lambda value: value.update(pending_corrections=-1),
    lambda value: value.update(server_time="2026-10-12T12:00:00"),
    lambda value: value.update(server_time="2026-10-12T12:00:00+01:00"),
    lambda value: value.update(token="must-not-be-public"),
    lambda value: value.update(observations={}),
    lambda value: value["observations"].append(copy.deepcopy(value["observations"][0])),
    lambda value: value["observations"][0].update(boat=True),
    lambda value: value["observations"][0].update(boat=9),
    lambda value: value["observations"][0].update(start_point="Oasis"),
    lambda value: value["observations"][0].update(start_point="butcher"),
    lambda value: value["observations"][0].update(kind="announcement"),
    lambda value: value["observations"][0].update(reported_by="<b>Mindflux</b>"),
    lambda value: value["observations"][0].update(reported_by="Náme"),
    lambda value: value["observations"][0].update(reported_by="Mind\nflux"),
    lambda value: value["observations"][0].update(reported_by="1Mindflux"),
    lambda value: value["observations"][0].update(reported_by="M" * 49),
    lambda value: value["observations"][0].update(confidence="verified"),
    lambda value: value["observations"][0].update(observed_at=(NOW + datetime.timedelta(seconds=1)).isoformat()),
    lambda value: value["observations"][0].update(phase_origin_at=NOW.isoformat()),
    lambda value: value["observations"][0].update(device_id="private"),
    lambda value: value["observations"][0].update(id="<public>"),
])
def test_parser_rejects_invalid_document_instead_of_partial_data(mutate):
    value = snapshot(observations=[observation()])
    mutate(value)
    with pytest.raises(ValueError):
        community.parse_snapshot(value, "Green", NOW, NOW)


def test_parser_rejects_excess_observations_and_unknown_server():
    value = snapshot(observations=[observation()] * 5)
    with pytest.raises(ValueError):
        community.validate_snapshot(value, "Green")
    with pytest.raises(ValueError):
        community.validate_snapshot(snapshot(), "Red")


@pytest.mark.parametrize("name", ["M", "Mindflux", "Mind Flux", "O'Brien_2-Green"])
def test_valid_public_name_is_accepted_by_parser(name):
    value = snapshot(observations=[observation(reporter=name)])
    assert community.validate_snapshot(value, "Green") is value


def test_refresh_is_nonblocking_coalesced_and_does_not_enroll(app, server, clients):
    client = clients()
    responses = []
    busy = []
    client.schedules_ready.connect(lambda *args: responses.append(args))
    client.busy_changed.connect(busy.append)
    server.actions[("GET", "/v1/boats")] = [{"delay": 0.15}]
    start = time.monotonic()
    assert client.refresh("Green")
    assert time.monotonic() - start < 0.1
    assert not client.refresh("Green")
    assert not client.is_reporting
    wait_for(app, lambda: bool(responses))
    assert responses[0][0] == "Green" and responses[0][1] == []
    assert "No community arrivals" in responses[0][2]
    assert [(call["method"], call["path"]) for call in server.calls] == [
        ("GET", "/v1/boats?server=Green")]
    assert busy == [True, False]
    assert not client._token_path.exists()


def test_cache_preserves_saved_clock_offset_and_separates_servers(app, server, clients):
    client = clients()
    received = datetime.datetime.now(UTC)
    remote = received - datetime.timedelta(hours=11)
    value = snapshot("Green", remote, [observation(when=remote)], revision=7)
    # Deliberately store an aged receipt. Loading it must not rebase to now.
    old_receipt = received - datetime.timedelta(seconds=120)
    client._update_snapshot("Green", value, old_receipt)
    before = client.cached_schedules("Green")
    reloaded = clients()
    after = reloaded.cached_schedules("Green")
    assert before[0].last_seen == after[0].last_seen == old_receipt
    assert abs(before[0].remaining_seconds - after[0].remaining_seconds) <= 1
    assert (received - after[0].last_seen).total_seconds() >= 120
    assert reloaded.cached_schedules("Blue") == []
    raw = json.loads(client._cache_path("Green").read_text("utf-8"))
    assert raw["snapshot"] == value and raw["received_at"] == old_receipt.isoformat()
    assert "token" not in raw and "device_id" not in raw


def test_refresh_failure_retains_cached_rows_and_invalid_snapshot_does_not_poison_cache(
        app, server, clients):
    client = clients()
    current = datetime.datetime.now(UTC)
    client._update_snapshot(
        "Green", snapshot("Green", current, [observation(when=current)]), current)
    responses = []
    client.schedules_ready.connect(lambda *args: responses.append(args))
    server.actions[("GET", "/v1/boats")] = [
        {"status": 503, "raw": TEST_TOKEN.encode()},
        {"payload": snapshot("Blue", current)}]
    assert client.refresh("Green")
    wait_for(app, lambda: len(responses) == 1)
    assert responses[0][1] and responses[0][2].startswith("Offline")
    assert client.refresh("Green")
    wait_for(app, lambda: len(responses) == 2)
    assert responses[1][1] and responses[1][2].startswith("Offline")
    assert client.cached_schedules("Green")[0].reporter == "Mindflux"
    assert TEST_TOKEN not in repr(responses)


def test_concurrent_server_requests_keep_their_own_identity(app, server, clients):
    client = clients()
    responses = []
    client.schedules_ready.connect(lambda *args: responses.append(args))
    assert client.refresh("Green")
    assert client.refresh("Blue")
    wait_for(app, lambda: len(responses) == 2)
    assert {response[0] for response in responses} == {"Green", "Blue"}
    assert set(client._snapshots) == {"Green", "Blue"}
    assert client._cache_path("Green") != client._cache_path("Blue")


def test_enroll_and_manual_report_use_exact_contract_and_private_persistent_token(
        app, server, clients):
    client = clients()
    finished = []
    busy = []
    client.report_finished.connect(lambda *args: finished.append(args))
    client.busy_changed.connect(busy.append)
    assert client.report_arrival("Green", 0, "oasis", "Mindflux")
    assert client.is_reporting
    assert not client.report_arrival("Blue", 0, "oasis", "Other")
    wait_for(app, lambda: bool(finished))
    assert finished[0][0:2] == ("Green", True)
    assert not client.is_reporting
    assert busy == [True, False]
    assert len(server.calls) == 2
    enrolled, sent = server.calls
    assert enrolled["path"] == "/v1/devices" and enrolled["body"] == {}
    assert enrolled["authorization"] == ""
    assert sent["path"] == "/v1/observations"
    assert sent["authorization"] == f"Bearer {TEST_TOKEN}"
    assert set(sent["body"]) == {
        "server", "boat", "start_point", "kind", "reported_by", "event_id", "elapsed_ms"}
    assert sent["body"]["server"] == "Green"
    assert sent["body"]["kind"] == "dock_arrival"
    assert len(sent["body"]["event_id"]) == 32
    assert type(sent["body"]["elapsed_ms"]) is int
    assert 0 <= sent["body"]["elapsed_ms"] <= 15000
    assert client.cached_schedules("Green")
    assert client._token_path.exists()
    assert TEST_TOKEN not in client._cache_path("Green").read_text("utf-8")
    assert TEST_TOKEN not in repr(finished)
    reloaded = clients()
    assert reloaded._token == TEST_TOKEN
    result = []
    reloaded.report_finished.connect(lambda *args: result.append(args))
    assert reloaded.report_arrival("Blue", 0, "oasis", "Mindflux")
    wait_for(app, lambda: bool(result))
    assert [call["path"] for call in server.calls].count("/v1/devices") == 1
    assert server.calls[-1]["body"]["server"] == "Blue"


def test_pending_report_is_not_reported_as_global_acceptance(app, server, clients):
    server.actions[("POST", "/v1/observations")] = [{
        "payload": {"schema": 1, "status": "pending",
                    "snapshot": snapshot("Green", datetime.datetime.now(UTC), pending=1)}}]
    client = clients()
    finished = []
    client.report_finished.connect(lambda *args: finished.append(args))
    assert client.report_arrival("Green", 0, "oasis", "Mindflux")
    wait_for(app, lambda: bool(finished))
    assert finished[0][1] is False and "pending independent confirmation" in finished[0][2]
    assert client.cached_schedules("Green") == []


@pytest.mark.parametrize("status", [400, 401, 429, 503])
def test_report_failure_is_never_requeued_or_automatically_reenrolled(
        app, server, clients, status):
    client = clients()
    client._token = TEST_TOKEN
    client._write_private(client._token_path, {"schema": 1, "token": TEST_TOKEN})
    server.actions[("POST", "/v1/observations")] = [
        {"status": status, "raw": TEST_TOKEN.encode()}]
    finished = []
    client.report_finished.connect(lambda *args: finished.append(args))
    assert client.report_arrival("Green", 0, "oasis", "Mindflux")
    wait_for(app, lambda: bool(finished))
    assert finished[0][1] is False
    assert TEST_TOKEN not in repr(finished)
    assert not client.is_reporting and not client._requests
    assert len(server.calls) == 1
    if status == 401:
        assert not client._token and not client._token_path.exists()


def test_enrollment_failure_does_not_send_observation(app, server, clients):
    server.actions[("POST", "/v1/devices")] = [{"status": 429}]
    client = clients()
    finished = []
    client.report_finished.connect(lambda *args: finished.append(args))
    assert client.report_arrival("Green", 0, "oasis", "Mindflux")
    wait_for(app, lambda: bool(finished))
    assert not finished[0][1]
    assert [call["path"] for call in server.calls] == ["/v1/devices"]
    assert not client._token_path.exists()


def test_expired_enrollment_never_publishes_a_delayed_report(app, server, clients, monkeypatch):
    monkeypatch.setattr(community, "MAX_REPORT_AGE_MS", 30)
    server.actions[("POST", "/v1/devices")] = [{"delay": 0.1}]
    client = clients()
    finished = []
    client.report_finished.connect(lambda *args: finished.append(args))
    assert client.report_arrival("Green", 0, "oasis", "Mindflux")
    wait_for(app, lambda: bool(finished))
    assert not finished[0][1] and "expired" in finished[0][2]
    assert [call["path"] for call in server.calls] == ["/v1/devices"]


def test_request_timeout_is_bounded_and_leaves_client_reusable(app, server, clients, monkeypatch):
    monkeypatch.setattr(community, "REQUEST_TIMEOUT_MS", 40)
    server.actions[("GET", "/v1/boats")] = [{"delay": 0.15}, {}]
    client = clients()
    responses = []
    busy = []
    client.schedules_ready.connect(lambda *args: responses.append(args))
    client.busy_changed.connect(busy.append)
    assert client.refresh("Green")
    wait_for(app, lambda: len(responses) == 1)
    assert responses[0][2].startswith("Offline")
    assert not client._requests and not client._refreshing
    assert client.refresh("Green")
    wait_for(app, lambda: len(responses) == 2)
    assert not responses[1][2].startswith("Offline")
    assert busy == [True, False, True, False]


@pytest.mark.parametrize("length_header", [True, False])
def test_oversized_response_is_rejected_before_parsing(
        app, server, clients, length_header):
    server.actions[("GET", "/v1/boats")] = [{
        "raw": b"x" * (community.MAX_RESPONSE_BYTES + 100),
        "content_length": length_header}]
    client = clients()
    responses = []
    client.schedules_ready.connect(lambda *args: responses.append(args))
    assert client.refresh("Green")
    wait_for(app, lambda: bool(responses))
    assert responses[0][1] == [] and responses[0][2].startswith("Offline")
    assert not client._snapshots


def test_same_origin_redirect_is_allowed_and_cross_origin_is_rejected(app, server, clients):
    server.actions[("GET", "/v1/boats")] = [
        {"status": 307, "headers": {"Location": "/redirected?server=Green"}},
        {"status": 307, "headers": {"Location": "https://invalid.example/v1/boats"}}]
    client = clients()
    responses = []
    client.schedules_ready.connect(lambda *args: responses.append(args))
    assert client.refresh("Green")
    wait_for(app, lambda: len(responses) == 1)
    assert not responses[0][2].startswith("Offline")
    assert server.calls[1]["path"] == "/redirected?server=Green"
    assert client.refresh("Green")
    wait_for(app, lambda: len(responses) == 2)
    assert responses[1][2].startswith("Offline")
    assert len(server.calls) == 3


def test_post_redirect_cannot_leak_token_to_another_origin(app, server, clients):
    server.actions[("POST", "/v1/observations")] = [{
        "status": 307, "headers": {"Location": "https://invalid.example/v1/observations"}}]
    client = clients()
    client._token = TEST_TOKEN
    finished = []
    client.report_finished.connect(lambda *args: finished.append(args))
    assert client.report_arrival("Green", 0, "oasis", "Mindflux")
    wait_for(app, lambda: bool(finished))
    assert not finished[0][1] and "redirect" in finished[0][2]
    assert len(server.calls) == 1
    assert TEST_TOKEN not in repr(finished)


def test_redirect_loop_is_bounded_without_reenrollment(app, server, clients):
    server.actions[("GET", "/v1/boats")] = [
        {"status": 307, "headers": {"Location": "/v1/boats?server=Green"}}
        for _index in range(5)]
    client = clients()
    responses = []
    client.schedules_ready.connect(lambda *args: responses.append(args))
    assert client.refresh("Green")
    wait_for(app, lambda: bool(responses))
    assert responses[0][2].startswith("Offline")
    assert len(server.calls) == 4 and not client._requests


def test_enrollment_token_from_invalid_json_is_never_persisted(app, server, clients):
    server.actions[("POST", "/v1/devices")] = [{
        "payload": {"schema": 1, "token": "<private>invalid</private>"}}]
    client = clients()
    finished = []
    client.report_finished.connect(lambda *args: finished.append(args))
    assert client.report_arrival("Green", 0, "oasis", "Mindflux")
    wait_for(app, lambda: bool(finished))
    assert not finished[0][1] and not client._token_path.exists()
    assert [call["path"] for call in server.calls] == ["/v1/devices"]


def test_report_timeout_never_retries_the_arrival(app, server, clients, monkeypatch):
    monkeypatch.setattr(community, "REQUEST_TIMEOUT_MS", 40)
    server.actions[("POST", "/v1/observations")] = [{"delay": 0.15}]
    client = clients()
    client._token = TEST_TOKEN
    finished = []
    client.report_finished.connect(lambda *args: finished.append(args))
    assert client.report_arrival("Green", 0, "oasis", "Mindflux")
    wait_for(app, lambda: bool(finished))
    assert not finished[0][1] and "timed out" in finished[0][2]
    assert len(server.calls) == 1 and not client.is_reporting


@pytest.mark.parametrize("url", [
    "http://example.com", "ftp://127.0.0.1",
    "https://user:pass@example.com", "https://example.com/path",
    "https://example.com?token=private", "https://example.com#fragment"])
def test_only_https_or_explicit_loopback_base_is_allowed(app, tmp_path, url):
    with pytest.raises(ValueError):
        community.CommunityBoatClient(base_url=url, cache_dir=tmp_path)


def test_tokens_and_snapshots_are_isolated_between_service_origins(app, clients):
    client = clients()
    client._write_private(client._token_path, {"schema": 1, "token": TEST_TOKEN})
    other = clients(base_url="https://example.com")
    assert other._token_path != client._token_path and not other._token
    assert other.cached_schedules("Green") == []


@pytest.mark.parametrize("server_name,boat,start_point,reporter", [
    ("Red", 0, "oasis", "Mindflux"),
    ("green", 0, "oasis", "Mindflux"),
    ("Green", True, "oasis", "Mindflux"),
    ("Green", 0, "nro", "Mindflux"),
    ("Green", 0, "oasis", "<script>"),
])
def test_invalid_manual_reports_do_not_enroll_or_send(
        app, server, clients, server_name, boat, start_point, reporter):
    client = clients()
    finished = []
    client.report_finished.connect(lambda *args: finished.append(args))
    assert not client.report_arrival(server_name, boat, start_point, reporter)
    assert finished and not finished[0][1]
    assert not client.is_reporting and not server.calls


def test_invalid_cache_and_credentials_are_ignored_safely(app, clients):
    client = clients()
    client._write_private(client._token_path, {"schema": True, "token": TEST_TOKEN})
    client._write_private(client._cache_path("Green"), {
        "schema": 1, "received_at": NOW.isoformat(), "snapshot": snapshot("Blue")})
    reloaded = clients()
    assert reloaded.cached_schedules("Green") == [] and not reloaded._token


def test_old_inflight_snapshot_cannot_overwrite_newer_report_revision(app, clients):
    client = clients()
    current = datetime.datetime.now(UTC)
    accepted = snapshot("Green", current, [observation(when=current)], revision=9)
    client._update_snapshot("Green", accepted, current)
    client._update_snapshot("Green", snapshot("Green", current, revision=8), current)
    assert client._snapshots["Green"][0]["revision"] == 9
    assert client.cached_schedules("Green")[0].reporter == "Mindflux"


@pytest.mark.parametrize("raw", [
    b'{"schema":1,"schema":1}',
    b'{"schema":NaN}',
    b'\xff',
    b'{"schema":',
])
def test_malformed_json_workflow_finishes_without_gui_exception(app, server, clients, raw):
    server.actions[("GET", "/v1/boats")] = [{"raw": raw}]
    client = clients()
    responses = []
    client.schedules_ready.connect(lambda *args: responses.append(args))
    assert client.refresh("Green")
    wait_for(app, lambda: bool(responses))
    assert responses[0][2].startswith("Offline") and not client._requests


@pytest.mark.parametrize("oversized", [False, True])
def test_real_qt_content_length_callback_has_no_binding_exception(
        app, server, clients, monkeypatch, oversized):
    # ThreadingHTTPServer exercises an actual QNetworkReply. Qt delivers Python
    # slot errors through sys.excepthook rather than failing the request, so a
    # successful snapshot alone would miss a broken metadata-size guard.
    callback_errors = []
    monkeypatch.setattr(sys, "excepthook",
                        lambda _kind, error, _traceback: callback_errors.append(error))
    if oversized:
        server.actions[("GET", "/v1/boats")] = [{
            "raw": b"x" * (community.MAX_RESPONSE_BYTES + 100)}]
    client = clients()
    responses = []
    client.schedules_ready.connect(lambda *args: responses.append(args))
    assert client.refresh("Green")
    wait_for(app, lambda: bool(responses))
    assert callback_errors == []
    assert responses[0][2].startswith("Offline") is oversized
    assert len(server.calls) == 1
