import datetime
import http.client
import json
import socket
import sqlite3
import threading
import uuid

import pytest

from locationserver import boat_server
from vantage.helpers.boats import BOAT_ROUTES


class Clock:
    def __init__(self):
        self.now = 1788172800.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def store(tmp_path):
    value = boat_server.BoatStore(tmp_path / "boats.sqlite3", clock=Clock())
    yield value
    value.close()


def enroll(store, address="198.51.100.1"):
    return store.enroll(address)["token"]


def report(server="Green", boat=0, dock="oasis", name="Mindflux", **changes):
    result = {
        "server": server, "boat": boat, "start_point": dock,
        "kind": "dock_arrival", "reported_by": name,
        "event_id": uuid.uuid4().hex, "elapsed_ms": 0}
    result.update(changes)
    return result


def parsed_time(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def observe(store, token, payload=None, address="198.51.100.1"):
    return store.observe(token, payload or report(), address)


@pytest.fixture
def http_server(store):
    server = boat_server.BoatHTTPServer(("127.0.0.1", 0), store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def request(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
    actual_headers = dict(headers or {})
    if body is not None and not isinstance(body, (str, bytes)):
        body = json.dumps(body)
        actual_headers.setdefault("Content-Type", "application/json")
    connection.request(method, path, body=body, headers=actual_headers)
    response = connection.getresponse()
    raw = response.read()
    result = (response.status, dict(response.getheaders()), json.loads(raw) if raw else None)
    connection.close()
    return result


def test_route_offsets_and_distinct_periods_match_existing_model():
    assert boat_server.ROUTES == {
        (route.boat_id, route.start_point): (
            route.announcement_to_dock, route.trip_seconds)
        for route in BOAT_ROUTES}
    assert boat_server.ROUTES[(0, "oasis")][1] != boat_server.ROUTES[(0, "timorous")][1]


def test_expiry_deletes_clear_sqlite_record_content(store):
    assert store.connection.execute("PRAGMA secure_delete").fetchone()[0] == 1


def test_empty_health_and_server_separation(http_server):
    status, headers, health = request(http_server, "GET", "/health")
    assert status == 200
    assert health == {"schema": 1, "service": "Vantage Boats", "route_model": 1,
                      "servers": ["Green", "Blue"]}
    assert headers["Cache-Control"] == "no-store"
    for name in ("Green", "Blue"):
        status, unused_headers, snapshot = request(
            http_server, "GET", "/v1/boats?server=" + name)
        assert status == 200
        assert snapshot["server"] == name
        assert snapshot["observations"] == []
        assert snapshot["revision"] == snapshot["pending_corrections"] == 0
    for path in ("/v1/boats", "/v1/boats?server=Red", "/v1/boats?server=green",
                 "/v1/boats?server=Green&server=Blue", "/v1/boats?server=Green&x=1"):
        assert request(http_server, "GET", path)[0] == 400


@pytest.mark.parametrize("boat,dock", list(boat_server.ROUTES))
def test_manual_arrival_uses_server_time_and_dock_offset(store, boat, dock):
    token = enroll(store)
    response = observe(store, token, report(boat=boat, dock=dock, elapsed_ms=1250))
    assert response["status"] == "accepted"
    snapshot = response["snapshot"]
    row = snapshot["observations"][0]
    assert row["confidence"] == "unconfirmed"
    assert row["kind"] == "dock_arrival"
    assert parsed_time(row["observed_at"]) == store.clock.now - 1.25
    assert parsed_time(row["phase_origin_at"]) == (
        store.clock.now - 1.25 - boat_server.ROUTES[(boat, dock)][0])
    assert parsed_time(snapshot["server_time"]) == store.clock.now
    assert snapshot["revision"] == 1
    assert store.snapshot("Blue")["observations"] == []
    assert store.snapshot("Blue")["revision"] == 0


def test_authenticated_idempotency_replays_original_result_transactionally(store):
    token = enroll(store)
    payload = report()
    original = observe(store, token, payload)
    store.clock.advance(60)
    assert observe(store, token, dict(reversed(list(payload.items())))) == original
    assert store.connection.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 1
    assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert store.snapshot("Green")["revision"] == 1
    for mutation in ({"reported_by": "Other"}, {"server": "Blue"}, {"elapsed_ms": 1}):
        altered = dict(payload, **mutation)
        with pytest.raises(boat_server.APIError) as failure:
            observe(store, token, altered)
        assert failure.value.status == 400
    second = enroll(store, "198.51.100.2")
    # Idempotency is private to each device token, not a public global event ID.
    assert observe(store, second, payload)["snapshot"]["revision"] == 2


def test_persistence_and_private_fields_never_leak(tmp_path):
    path = tmp_path / "boats.sqlite3"
    clock = Clock()
    store = boat_server.BoatStore(path, clock=clock)
    token = enroll(store, "203.0.113.77")
    payload = report()
    first = observe(store, token, payload, "203.0.113.77")
    public = json.dumps(first)
    assert token not in public and "203.0.113.77" not in public
    assert "token_hash" not in public and "rate_key" not in public
    row = first["snapshot"]["observations"][0]
    assert set(row) == {"boat", "start_point", "kind", "observed_at",
                        "phase_origin_at", "reported_by", "confidence", "id"}
    assert row["id"] != token
    store.close()
    assert token.encode() not in path.read_bytes()
    assert b"203.0.113.77" not in path.read_bytes()
    reopened = boat_server.BoatStore(path, clock=clock)
    try:
        assert observe(reopened, token, payload, "203.0.113.77") == first
        assert reopened.snapshot("Green")["revision"] == 1
    finally:
        reopened.close()


def test_independent_consistent_token_corroborates_and_same_token_does_not(store):
    first, second = enroll(store), enroll(store, "198.51.100.2")
    observe(store, first)
    store.clock.advance(30)
    same = observe(store, first)
    assert same["snapshot"]["observations"][0]["confidence"] == "unconfirmed"
    store.clock.advance(20)
    independent = observe(store, second)
    assert independent["status"] == "accepted"
    assert independent["snapshot"]["observations"][0]["confidence"] == "corroborated"


def test_phase_correction_is_pending_until_independently_corroborated(store):
    first, correcting, corroborating = (
        enroll(store, "198.51.100." + str(number)) for number in (1, 2, 3))
    accepted = observe(store, first)
    initial = accepted["snapshot"]["observations"][0]
    store.clock.advance(200)
    correction = report(name="Second")
    pending = observe(store, correcting, correction)
    assert pending["status"] == "pending"
    assert pending["snapshot"]["observations"] == [initial]
    assert pending["snapshot"]["pending_corrections"] == 1
    assert pending["snapshot"]["revision"] == 2
    assert store.snapshot("Blue")["pending_corrections"] == 0
    store.clock.advance(20)
    same_device = observe(store, correcting, report(name="Second"))
    assert same_device["status"] == "pending"
    assert same_device["snapshot"]["pending_corrections"] == 1
    store.clock.advance(20)
    supported = observe(store, corroborating, report(name="Third"))
    assert supported["status"] == "accepted"
    row = supported["snapshot"]["observations"][0]
    assert row["reported_by"] == "Third"
    assert row["confidence"] == "corroborated"
    assert parsed_time(row["observed_at"]) == store.clock.now
    assert supported["snapshot"]["pending_corrections"] == 0
    # A pending event remains the same result when retried after corroboration.
    assert observe(store, correcting, correction) == pending


def test_normal_confirmation_preserves_another_devices_pending_correction(store):
    first, second, third, fourth = (
        enroll(store, "198.51.100." + str(number)) for number in (1, 2, 3, 4))
    observe(store, first, report(boat=3, dock="nro"))
    store.clock.advance(200)
    observe(store, second, report(boat=3, dock="nro"))
    store.clock.advance(307 - 200)
    consistent = observe(store, third, report(boat=3, dock="iceclad"))
    assert consistent["status"] == "accepted"
    assert consistent["snapshot"]["pending_corrections"] == 1
    # The second device's origin is 200. This other dock now corroborates it.
    store.clock.advance(200)
    correction = observe(store, fourth, report(boat=3, dock="iceclad"))
    assert correction["status"] == "accepted"
    assert correction["snapshot"]["observations"][0]["confidence"] == "corroborated"
    assert correction["snapshot"]["pending_corrections"] == 0
    assert parsed_time(correction["snapshot"]["observations"][0]["phase_origin_at"]) == (
        store.clock.now - 307)


def test_newest_corroborating_arrival_wins_even_if_new_request_is_older(store):
    first, second, third = (
        enroll(store, "198.51.100." + str(number)) for number in (1, 2, 3))
    observe(store, first)
    store.clock.advance(200)
    observe(store, second, report(name="Newest"))
    store.clock.advance(1)
    final = observe(store, third, report(name="Older", elapsed_ms=15000))
    assert final["status"] == "accepted"
    assert final["snapshot"]["observations"][0]["reported_by"] == "Newest"
    assert parsed_time(final["snapshot"]["observations"][0]["observed_at"]) == (
        store.clock.now - 1)


def test_modulo_cycle_and_cross_dock_consistency_are_preserved(store):
    first, second, third = (
        enroll(store, "198.51.100." + str(number)) for number in (1, 2, 3))
    initial = observe(store, first)
    origin = parsed_time(initial["snapshot"]["observations"][0]["phase_origin_at"])
    store.clock.advance(510 - 119)
    dock = observe(store, second, report(dock="timorous"))
    assert dock["status"] == "accepted"
    assert parsed_time(dock["snapshot"]["observations"][0]["phase_origin_at"]) == origin
    store.clock.advance(778.75)
    repeated = observe(store, third, report(dock="timorous"))
    assert repeated["status"] == "accepted"
    assert repeated["snapshot"]["observations"][0]["confidence"] == "corroborated"
    assert boat_server.phase_drift(519 - 5, 5, 519) == 10
    assert boat_server.phase_drift(3 * 779.75, 0, 779.75) == 0


def test_stale_arrival_is_measured_from_arrival_not_origin(store):
    first, second, third = (
        enroll(store, "198.51.100." + str(number)) for number in (1, 2, 3))
    # This dock's offset is almost a whole trip. Origin age is not freshness.
    observe(store, first, report(boat=1, dock="overthere"))
    store.clock.advance(2025 * 3 - 1975 + 150)
    fresh = observe(store, second, report(boat=1, dock="overthere"))
    assert fresh["status"] == "pending"
    store.clock.advance(1975 - 150)
    recalibration = observe(store, third, report(boat=1, dock="overthere"))
    assert recalibration["status"] == "accepted"
    assert recalibration["snapshot"]["observations"][0]["confidence"] == "unconfirmed"


def test_stale_at_exact_three_cycles_accepts_single_new_calibration(store):
    first, second = enroll(store), enroll(store, "198.51.100.2")
    observe(store, first, report(boat=3, dock="nro"))
    store.clock.advance(519 * 3)
    response = observe(store, second, report(boat=3, dock="iceclad"))
    assert response["status"] == "accepted"
    assert response["snapshot"]["observations"][0]["confidence"] == "unconfirmed"


@pytest.mark.parametrize("change", [
    {"server": "Red"}, {"server": None}, {"boat": True}, {"boat": 4},
    {"boat": "0"}, {"boat": 0.0}, {"start_point": "butcher"},
    {"start_point": ["oasis"]}, {"kind": "announcement"},
    {"elapsed_ms": True}, {"elapsed_ms": -1}, {"elapsed_ms": 15001},
    {"elapsed_ms": 0.0}, {"reported_by": ""}, {"reported_by": "7Name"},
    {"reported_by": "<script>"}, {"reported_by": "Name\n"},
    {"reported_by": "Name\u0000"}, {"reported_by": "José"},
    {"reported_by": "A" * 49}, {"event_id": "xyz"},
    {"event_id": "1" * 33}, {"unexpected": "value"}])
def test_strict_observation_validation(store, change):
    with pytest.raises(boat_server.APIError) as failure:
        observe(store, enroll(store), report(**change))
    assert failure.value.status == 400
    assert store.snapshot("Green")["observations"] == []


def test_name_allows_documented_ascii_characters(store):
    row = observe(store, enroll(store), report(name="A1 O'Name_under-score"))[
        "snapshot"]["observations"][0]
    assert row["reported_by"] == "A1 O'Name_under-score"


def test_enrollment_and_bad_auth_are_limited_without_secret_errors(store):
    for unused in range(4):
        enroll(store)
    with pytest.raises(boat_server.APIError) as failure:
        enroll(store)
    assert failure.value.status == 429 and failure.value.retry_after > 0
    for unused in range(20):
        with pytest.raises(boat_server.APIError) as failure:
            observe(store, "bogus-private-token")
        assert failure.value.status == 401
        assert "bogus" not in str(failure.value)
    with pytest.raises(boat_server.APIError) as failure:
        observe(store, "bogus-private-token")
    assert failure.value.status == 429


def test_report_rate_limits_preserve_idempotent_replay(store):
    token = enroll(store)
    payload = report()
    original = observe(store, token, payload)
    with pytest.raises(boat_server.APIError) as failure:
        observe(store, token)
    assert failure.value.status == 429
    assert observe(store, token, payload) == original
    assert store.connection.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 1


def test_four_anchors_maximum_and_servers_do_not_mix(store):
    token = enroll(store)
    for boat, dock in ((0, "oasis"), (1, "overthere"), (2, "butcher"), (3, "nro")):
        observe(store, token, report(boat=boat, dock=dock))
    assert len(store.snapshot("Green")["observations"]) == 4
    store.clock.advance(15)
    blue = observe(store, token, report(server="Blue"))
    assert len(blue["snapshot"]["observations"]) == 1
    assert len(store.snapshot("Green")["observations"]) == 4
    assert blue["snapshot"]["revision"] == 1


def test_pending_expiry_anchor_expiry_and_device_expiry(store):
    first, second = enroll(store), enroll(store, "198.51.100.2")
    observe(store, first)
    store.clock.advance(200)
    observe(store, second)
    store.clock.advance(boat_server.PENDING_TTL)
    snapshot = store.snapshot("Green")
    assert snapshot["pending_corrections"] == 0
    assert snapshot["revision"] == 3
    assert len(snapshot["observations"]) == 1
    store.clock.advance(boat_server.ANCHOR_TTL)
    assert store.snapshot("Green")["observations"] == []
    assert store.connection.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 0
    assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    store.clock.advance(boat_server.DEVICE_TTL)
    with pytest.raises(boat_server.APIError) as failure:
        observe(store, first)
    assert failure.value.status == 401
    assert store.connection.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0


def test_persistence_count_and_database_size_limits(store, monkeypatch):
    monkeypatch.setattr(boat_server, "MAX_EVENTS", 2)
    monkeypatch.setattr(boat_server, "MAX_HISTORY", 2)
    token = enroll(store)
    for unused in range(3):
        observe(store, token)
        store.clock.advance(15)
    assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
    assert store.connection.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 2
    assert store.connection.execute("PRAGMA max_page_count").fetchone()[0] == 8192
    assert store.connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    monkeypatch.setattr(boat_server, "MAX_DEVICES", 1)
    with pytest.raises(boat_server.APIError) as failure:
        enroll(store, "198.51.100.2")
    assert failure.value.status == 429


def test_pending_and_rate_key_capacity_are_bounded(store, monkeypatch):
    tokens = [enroll(store, "198.51.100." + str(number)) for number in (1, 2, 3, 4)]
    monkeypatch.setattr(boat_server, "MAX_PENDING_PER_SERVER", 2)
    observe(store, tokens[0])
    for token in tokens[1:3]:
        store.clock.advance(200)
        assert observe(store, token)["status"] == "pending"
    store.clock.advance(200)
    with pytest.raises(boat_server.APIError) as failure:
        observe(store, tokens[3])
    assert failure.value.status == 429
    assert store.snapshot("Green")["pending_corrections"] == 2
    with store._transaction():
        store.connection.execute("DELETE FROM rate_limits")
    monkeypatch.setattr(boat_server, "MAX_RATE_KEYS", 1)
    store.request_rate("203.0.113.1")
    with pytest.raises(boat_server.APIError) as failure:
        store.request_rate("203.0.113.2")
    assert failure.value.status == 429
    assert store.connection.execute("SELECT COUNT(*) FROM rate_limits").fetchone()[0] == 1
    store.clock.advance(61)
    store.request_rate("203.0.113.2")


def test_parallel_duplicate_reports_commit_only_one_observation(store):
    token = enroll(store)
    payload = report()
    barrier = threading.Barrier(8)
    results, failures = [], []

    def submit():
        barrier.wait(timeout=2)
        try:
            results.append(observe(store, token, payload))
        except Exception as error:
            failures.append(error)

    threads = [threading.Thread(target=submit) for unused in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
    assert not failures and len(results) == 8
    assert all(result == results[0] for result in results)
    assert store.snapshot("Green")["revision"] == 1
    assert store.connection.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 1


def test_failed_transaction_does_not_leave_partial_anchor_or_revision(store, monkeypatch):
    token = enroll(store)
    with monkeypatch.context() as patcher:
        def fail_snapshot(unused_server, unused_now):
            raise sqlite3.OperationalError("test failure")

        patcher.setattr(store, "_snapshot", fail_snapshot)
        with pytest.raises(sqlite3.OperationalError):
            observe(store, token)
    snapshot = store.snapshot("Green")
    assert snapshot["observations"] == [] and snapshot["revision"] == 0
    assert store.connection.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 0
    assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_http_enrollment_auth_and_input_errors(http_server):
    assert request(http_server, "POST", "/v1/devices", {"unexpected": 1})[0] == 400
    status, unused_headers, enrolled = request(http_server, "POST", "/v1/devices", {})
    assert status == 200 and enrolled["schema"] == 1
    payload = report()
    assert request(http_server, "POST", "/v1/observations", payload)[0] == 401
    authorization = {"Authorization": "Bearer " + enrolled["token"]}
    assert request(http_server, "POST", "/v1/observations", payload,
                   authorization)[0] == 200
    assert request(http_server, "GET", "/v1/devices")[0] == 405
    assert request(http_server, "PUT", "/health")[0] == 405
    assert request(http_server, "GET", "/missing")[0] == 404
    assert request(http_server, "POST", "/v1/devices", "{}", {})[0] == 400
    for body in ("[]", "{", '{"a":1,"a":2}', '{"a":NaN}', b"\xff"):
        assert request(http_server, "POST", "/v1/devices", body,
                       {"Content-Type": "application/json"})[0] == 400
    status, unused_headers, error = request(
        http_server, "POST", "/v1/devices", b"x" * (boat_server.BODY_LIMIT + 1),
        {"Content-Type": "application/json"})
    assert status == 413 and "token" not in json.dumps(error)


def test_http_retry_after_and_loopback_proxy_address_limit(http_server):
    for number in range(4):
        assert request(http_server, "POST", "/v1/devices", {},
                       {"X-Vantage-Client-IP": "203.0.113.8"})[0] == 200
    status, headers, unused_body = request(
        http_server, "POST", "/v1/devices", {}, {"X-Vantage-Client-IP": "203.0.113.8"})
    assert status == 429 and int(headers["Retry-After"]) > 0
    assert request(http_server, "POST", "/v1/devices", {},
                   {"X-Vantage-Client-IP": "203.0.113.9"})[0] == 200
    assert request(http_server, "GET", "/health", headers={
        "X-Vantage-Client-IP": "203.0.113.8, 203.0.113.9"})[0] == 400
    assert request(http_server, "POST", "/v1/devices", "{}", {
        "Content-Type": "application/json", "Transfer-Encoding": "chunked"})[0] == 400


def test_http_database_failure_does_not_leak_private_error(http_server, monkeypatch):
    def fail_request(unused_token, unused_payload, unused_address):
        raise sqlite3.OperationalError("Bearer PRIVATE_TOKEN from 203.0.113.88")

    monkeypatch.setattr(http_server.store, "observe", fail_request)
    status, headers, body = request(http_server, "POST", "/v1/observations", report())
    assert status == 503 and int(headers["Retry-After"]) > 0
    assert "PRIVATE_TOKEN" not in json.dumps(body) and "203.0.113.88" not in json.dumps(body)


def test_incomplete_request_has_a_total_deadline(http_server, monkeypatch):
    monkeypatch.setattr(boat_server, "REQUEST_SECONDS", 0.1)
    with socket.create_connection(http_server.server_address, timeout=3) as connection:
        connection.sendall(b"POST /v1/devices HTTP/1.1\r\nHost: localhost\r\nCont")
        try:
            assert connection.recv(4096) == b""
        except ConnectionResetError:
            pass


def test_duplicate_http_content_length_and_oversized_headers_reject(http_server):
    def raw_request(raw):
        with socket.create_connection(http_server.server_address, timeout=3) as connection:
            connection.sendall(raw)
            response = connection.recv(4096)
            return int(response.split(b" ")[1])

    assert raw_request(
        b"POST /v1/devices HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n"
        b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}") == 400
    assert raw_request(
        b"GET /health HTTP/1.1\r\nHost: localhost\r\nX-Large: " + b"x" * 9000 +
        b"\r\n\r\n") == 431


def test_binding_requires_loopback(store):
    with pytest.raises(ValueError, match="loopback"):
        boat_server.BoatHTTPServer(("0.0.0.0", 0), store)


def test_request_worker_admission_is_bounded(store, monkeypatch):
    server = boat_server.BoatHTTPServer(("127.0.0.1", 0), store)
    acquired = [server._workers.acquire(blocking=False)
                for unused in range(boat_server.WORKER_LIMIT)]
    assert all(acquired)
    closed = []
    monkeypatch.setattr(server, "shutdown_request", lambda request: closed.append(request))
    class RequestMarker:
        response = b""

        def settimeout(self, timeout):
            assert timeout <= 0.25

        def sendall(self, response):
            self.response = response

    request_marker = RequestMarker()
    server.process_request(request_marker, ("127.0.0.1", 12345))
    assert closed == [request_marker]
    assert request_marker.response.startswith(b"HTTP/1.1 429")
    assert b"Retry-After: 1" in request_marker.response
    for unused in acquired:
        server._workers.release()
    server.server_close()
