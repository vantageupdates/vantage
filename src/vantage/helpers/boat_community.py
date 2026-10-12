"""Public community boat estimates and a bounded, nonblocking Qt client.

Only an explicit report_arrival call enrolls a device or sends an arrival.
Private enrollment credentials live outside the synced profile export.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
import uuid

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .boats import BOAT_ROUTES, BoatSchedule, _phase_seconds, _remaining_seconds
from .portable import data_dir


DEFAULT_BASE_URL = "https://vantage-boats.217-216-55-237.sslip.io"
SERVERS = ("Green", "Blue")
UTC = datetime.timezone.utc
MAX_RESPONSE_BYTES = 64 * 1024
REQUEST_TIMEOUT_MS = 10_000
MAX_REPORT_AGE_MS = 15_000
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9 '_-]{0,47}", re.ASCII)
_TOKEN = re.compile(r"[A-Za-z0-9_-]{20,256}", re.ASCII)
_PUBLIC_ID = re.compile(r"[A-Za-z0-9_-]{1,128}", re.ASCII)
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)",
    re.ASCII)
_SNAPSHOT_KEYS = {
    "schema", "route_model", "server", "server_time", "revision",
    "observations", "pending_corrections"}
_OBSERVATION_KEYS = {
    "boat", "start_point", "kind", "observed_at", "phase_origin_at",
    "reported_by", "confidence", "id"}


def _timestamp(value):
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise ValueError("Invalid UTC timestamp.")
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Invalid UTC timestamp.") from None


def _utc(value):
    if isinstance(value, str):
        return _timestamp(value)
    if not isinstance(value, datetime.datetime) or value.tzinfo is None:
        raise ValueError("An aware local timestamp is required.")
    return value.astimezone(UTC)


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _route(boat, start_point):
    if not _integer(boat) or not isinstance(start_point, str):
        return None
    return next((route for route in BOAT_ROUTES
                 if route.boat_id == boat and route.start_point == start_point), None)


def validate_snapshot(snapshot, server):
    """Validate the entire public v1 document; never accept partial rows."""
    if server not in SERVERS:
        raise ValueError("Unsupported community server.")
    if not isinstance(snapshot, dict) or set(snapshot) != _SNAPSHOT_KEYS:
        raise ValueError("Invalid community snapshot.")
    if (type(snapshot["schema"]) is not int or snapshot["schema"] != 1 or
            type(snapshot["route_model"]) is not int or
            snapshot["route_model"] != 1 or snapshot["server"] != server):
        raise ValueError("The community snapshot does not match this server.")
    if (not _integer(snapshot["revision"]) or
            not _integer(snapshot["pending_corrections"])):
        raise ValueError("Invalid community revision.")
    server_time = _timestamp(snapshot["server_time"])
    observations = snapshot["observations"]
    if not isinstance(observations, list) or len(observations) > 4:
        raise ValueError("Invalid community observations.")
    boats = set()
    public_ids = set()
    for observation in observations:
        if (not isinstance(observation, dict) or
                set(observation) != _OBSERVATION_KEYS):
            raise ValueError("Invalid community observation.")
        route = _route(observation["boat"], observation["start_point"])
        if route is None or observation["boat"] in boats:
            raise ValueError("Invalid or repeated community boat.")
        if (observation["kind"] != "dock_arrival" or
                observation["confidence"] not in ("unconfirmed", "corroborated") or
                not isinstance(observation["reported_by"], str) or
                not _NAME.fullmatch(observation["reported_by"]) or
                not isinstance(observation["id"], str) or
                not _PUBLIC_ID.fullmatch(observation["id"]) or
                observation["id"] in public_ids):
            raise ValueError("Invalid public community attribution.")
        observed_at = _timestamp(observation["observed_at"])
        origin = _timestamp(observation["phase_origin_at"])
        if (observed_at > server_time or
                observed_at - origin != datetime.timedelta(
                    seconds=route.announcement_to_dock)):
            raise ValueError("Invalid community boat phase.")
        boats.add(observation["boat"])
        public_ids.add(observation["id"])
    return snapshot


def parse_snapshot(snapshot, server, received_at=None, now=None):
    """Expand accepted anchors into routes using their original clock offset.

    Pass the saved received_at when loading cache. Replacing it with today's
    time would incorrectly make old observations look fresh.
    """
    validate_snapshot(snapshot, server)
    now = _utc(now if now is not None else datetime.datetime.now(UTC))
    received_at = _utc(received_at if received_at is not None else now)
    offset = received_at - _timestamp(snapshot["server_time"])
    rows = {}
    try:
        for observation in snapshot["observations"]:
            source = _route(observation["boat"], observation["start_point"])
            last_seen = _timestamp(observation["observed_at"]) + offset
            origin = _timestamp(observation["phase_origin_at"]) + offset
            phase = _phase_seconds(source, max(0, (now - origin).total_seconds()))
            stale = max(0, (now - last_seen).total_seconds()) >= source.trip_seconds * 3
            for route in BOAT_ROUTES:
                if route.boat_id == source.boat_id:
                    rows[(route.boat_id, route.start_point)] = BoatSchedule(
                        route, last_seen, _remaining_seconds(route, phase),
                        f"Vantage Community · {server}", stale,
                        reporter=observation["reported_by"],
                        confidence=observation["confidence"],
                        phase_origin_at=origin)
    except (OverflowError, TypeError):
        raise ValueError("Invalid normalized community timestamp.") from None
    return [rows[(route.boat_id, route.start_point)] for route in BOAT_ROUTES
            if (route.boat_id, route.start_point) in rows]


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated JSON field.")
        result[key] = value
    return result


def _decode(payload):
    def reject_constant(_value):
        raise ValueError("Invalid JSON value.")
    return json.loads(payload.decode("utf-8"), object_pairs_hook=_json_object,
                      parse_constant=reject_constant)


def _origin(url):
    parts = urlsplit(url)
    if (parts.username is not None or parts.password is not None or
            not parts.hostname or parts.fragment):
        raise ValueError("Invalid community service URL.")
    return (parts.scheme.lower(), parts.hostname.lower(),
            parts.port or (443 if parts.scheme.lower() == "https" else 80))


def _base_url(value):
    if not isinstance(value, str):
        raise ValueError("Invalid community service URL.")
    parts = urlsplit(value)
    origin = _origin(value)
    if (origin[0] not in ("https", "http") or
            (origin[0] == "http" and origin[1] not in
             ("127.0.0.1", "::1", "localhost")) or
            parts.query or parts.path not in ("", "/") or
            not QUrl(value).isValid()):
        raise ValueError("Community service requires HTTPS.")
    return value.rstrip("/"), origin


@dataclass
class _Report:
    server: str
    payload: dict
    clicked_at: float


@dataclass
class _Request:
    kind: str
    server: str
    url: str
    body: bytes
    deadline: float
    report: object = None
    redirects: int = 0
    buffer: bytearray = field(default_factory=bytearray)
    failure: str = ""
    timer: object = None


class CommunityBoatClient(QObject):
    schedules_ready = Signal(str, object, str)
    status_changed = Signal(str, str)
    report_finished = Signal(str, bool, str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None, base_url=DEFAULT_BASE_URL, cache_dir=None):
        super().__init__(parent)
        self.base_url, self._origin = _base_url(base_url)
        root = Path(cache_dir) if cache_dir is not None else data_dir(
            "boat-community", create=False)
        # A test/staging endpoint must never receive production credentials.
        endpoint = hashlib.sha256(self.base_url.encode("utf-8")).hexdigest()[:24]
        self._cache_dir = root / endpoint
        self._token_path = self._cache_dir / "device-token.json"
        self._network = QNetworkAccessManager(self)
        self._requests = {}
        self._refreshing = set()
        self._snapshots = {}
        self._report = None
        self._busy = False
        self._token = self._load_token()
        for server in SERVERS:
            self._load_cache(server)

    @property
    def is_reporting(self):
        return self._report is not None

    def _sync_busy(self):
        busy = bool(self._requests or self._report)
        if busy != self._busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    def _cache_path(self, server):
        return self._cache_dir / f"snapshot-{server.lower()}.json"

    def _read_private(self, path, limit):
        try:
            with path.open("rb") as stream:
                payload = stream.read(limit + 1)
            if len(payload) <= limit:
                return _decode(payload)
        except (OSError, UnicodeError, ValueError, RecursionError):
            pass
        return None

    def _write_private(self, path, value):
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            payload = json.dumps(value, separators=(",", ":"), ensure_ascii=True)
            with temporary.open("x", encoding="utf-8") as stream:
                os.chmod(temporary, 0o600)
                stream.write(payload)
            os.replace(temporary, path)
            return True
        except (OSError, TypeError, ValueError):
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def _load_token(self):
        value = self._read_private(self._token_path, 1024)
        if (isinstance(value, dict) and set(value) == {"schema", "token"} and
                type(value["schema"]) is int and value["schema"] == 1 and
                isinstance(value["token"], str) and _TOKEN.fullmatch(value["token"])):
            return value["token"]
        return ""

    def _clear_token(self):
        self._token = ""
        try:
            self._token_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _load_cache(self, server):
        value = self._read_private(self._cache_path(server), MAX_RESPONSE_BYTES + 1024)
        if not isinstance(value, dict) or set(value) != {
                "schema", "received_at", "snapshot"}:
            return
        try:
            if type(value["schema"]) is not int or value["schema"] != 1:
                return
            received_at = _timestamp(value["received_at"])
            parse_snapshot(value["snapshot"], server, received_at)
            self._snapshots[server] = (value["snapshot"], received_at)
        except (ValueError, TypeError, OverflowError):
            pass

    def cached_schedules(self, server):
        if server not in SERVERS or server not in self._snapshots:
            return []
        snapshot, received_at = self._snapshots[server]
        try:
            return parse_snapshot(snapshot, server, received_at)
        except (ValueError, TypeError, OverflowError):
            return []

    def refresh(self, server):
        if server not in SERVERS:
            self.status_changed.emit(str(server or ""), "Unsupported community server.")
            return False
        if server in self._refreshing:
            return False
        self._refreshing.add(server)
        self.status_changed.emit(server, "Refreshing community estimates…")
        request = _Request(
            "refresh", server, f"{self.base_url}/v1/boats?server={server}", b"",
            time.monotonic() + REQUEST_TIMEOUT_MS / 1000)
        return self._start(request)

    def report_arrival(self, server, boat, start_point, reported_by):
        if self.is_reporting:
            return False
        if server not in SERVERS:
            self.report_finished.emit(
                str(server or ""), False, "This server is not supported for community reports.")
            return False
        if _route(boat, start_point) is None:
            self.report_finished.emit(server, False, "Choose a valid boat arrival.")
            return False
        if not isinstance(reported_by, str) or not _NAME.fullmatch(reported_by):
            self.report_finished.emit(
                server, False, "Public name must start with a letter and use 1–48 letters, "
                "digits, spaces, apostrophes, underscores or hyphens.")
            return False
        report = _Report(server, {
            "server": server, "boat": boat, "start_point": start_point,
            "kind": "dock_arrival", "reported_by": reported_by,
            "event_id": uuid.uuid4().hex}, time.monotonic())
        self._report = report
        self._sync_busy()
        self.status_changed.emit(server, "Sending your manual dock arrival…")
        if self._token:
            return self._send_report(report)
        request = _Request(
            "enroll", server, f"{self.base_url}/v1/devices", b"{}",
            time.monotonic() + REQUEST_TIMEOUT_MS / 1000, report)
        return self._start(request)

    def _send_report(self, report):
        if self._report is not report:
            return False
        elapsed_ms = max(0, int((time.monotonic() - report.clicked_at) * 1000))
        if elapsed_ms > MAX_REPORT_AGE_MS:
            self._finish_report(report, False, "Arrival expired; report again when the boat docks.")
            return False
        body = json.dumps(
            dict(report.payload, elapsed_ms=elapsed_ms),
            separators=(",", ":"), ensure_ascii=True).encode("ascii")
        deadline = min(time.monotonic() + REQUEST_TIMEOUT_MS / 1000,
                       report.clicked_at + MAX_REPORT_AGE_MS / 1000)
        return self._start(_Request(
            "observe", report.server, f"{self.base_url}/v1/observations",
            body, deadline, report))

    def _start(self, operation):
        try:
            if (_origin(operation.url) != self._origin or
                    (self._origin[0] == "http" and self._origin[1] not in
                     ("127.0.0.1", "::1", "localhost"))):
                raise ValueError("Unsafe service redirect.")
            if operation.deadline <= time.monotonic():
                self._failure(operation, "The request timed out.")
                self._sync_busy()
                return False
            request = QNetworkRequest(QUrl(operation.url))
            request.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
            request.setAttribute(
                QNetworkRequest.Attribute.CacheLoadControlAttribute,
                QNetworkRequest.CacheLoadControl.AlwaysNetwork)
            request.setAttribute(
                QNetworkRequest.Attribute.CacheSaveControlAttribute, False)
            request.setRawHeader(b"Accept", b"application/json")
            request.setRawHeader(b"Cache-Control", b"no-store")
            request.setRawHeader(b"User-Agent", b"Vantage-Boats/1")
            if operation.kind == "refresh":
                reply = self._network.get(request)
            else:
                request.setRawHeader(b"Content-Type", b"application/json")
                if operation.kind == "observe":
                    request.setRawHeader(
                        b"Authorization", f"Bearer {self._token}".encode("ascii"))
                reply = self._network.post(request, QByteArray(operation.body))
            self._requests[reply] = operation
            reply.setReadBufferSize(MAX_RESPONSE_BYTES + 1)
            operation.timer = QTimer(self)
            operation.timer.setSingleShot(True)
            operation.timer.timeout.connect(lambda current=reply: self._timeout(current))
            reply.readyRead.connect(lambda current=reply: self._read(current))
            reply.metaDataChanged.connect(lambda current=reply: self._metadata(current))
            reply.finished.connect(lambda current=reply: self._finished(current))
            operation.timer.start(max(1, math.ceil(
                (operation.deadline - time.monotonic()) * 1000)))
            self._sync_busy()
            return True
        except (ValueError, RuntimeError, TypeError, UnicodeError):
            self._failure(operation, "Could not start the community request.")
            self._sync_busy()
            return False

    def _metadata(self, reply):
        operation = self._requests.get(reply)
        if operation is None or operation.failure:
            return
        length = bytes(reply.rawHeader("Content-Length"))
        if length and (not length.isdigit() or len(length) > 10 or
                       int(length) > MAX_RESPONSE_BYTES):
            operation.failure = "Community response was too large."
            reply.abort()

    def _read(self, reply):
        operation = self._requests.get(reply)
        if operation is None or operation.failure:
            return
        operation.buffer.extend(bytes(reply.read(
            MAX_RESPONSE_BYTES + 1 - len(operation.buffer))))
        if len(operation.buffer) > MAX_RESPONSE_BYTES:
            operation.failure = "Community response was too large."
            reply.abort()

    def _timeout(self, reply):
        operation = self._requests.get(reply)
        if operation is not None:
            operation.failure = "The request timed out."
            reply.abort()

    def _finished(self, reply):
        operation = self._requests.get(reply)
        if operation is None:
            return
        # Capture receipt before parsing or disk I/O, for clock normalization.
        received_at = datetime.datetime.now(UTC)
        if operation.deadline <= time.monotonic() and not operation.failure:
            operation.failure = "The request timed out."
        self._read(reply)
        if reply not in self._requests:
            return
        self._requests.pop(reply)
        operation.timer.stop()
        operation.timer.deleteLater()
        status = int(reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0)
        redirect = reply.attribute(
            QNetworkRequest.Attribute.RedirectionTargetAttribute)
        error = reply.error()
        reply_url = reply.url()
        reply.deleteLater()
        try:
            if operation.failure:
                self._failure(operation, operation.failure)
            elif status in (301, 302, 303, 307, 308) and redirect is not None:
                destination = reply_url.resolved(QUrl(redirect)).toString()
                if (operation.redirects >= 3 or _origin(destination) != self._origin or
                        (operation.kind != "refresh" and status not in (307, 308))):
                    self._failure(operation, "Community service redirect was rejected.")
                else:
                    self._start(_Request(
                        operation.kind, operation.server, destination, operation.body,
                        operation.deadline, operation.report, operation.redirects + 1))
            elif status == 401 and operation.kind == "observe":
                self._clear_token()
                self._failure(operation, "Report authorization expired; submit a new arrival.")
            elif status == 429:
                self._failure(operation, "Community service is busy; try again later.")
            elif status != 200 or error != QNetworkReply.NetworkError.NoError:
                self._failure(operation, "Community service is unavailable.")
            else:
                self._success(operation, _decode(bytes(operation.buffer)), received_at)
        except (ValueError, TypeError, KeyError, UnicodeError, OverflowError,
                RecursionError, RuntimeError):
            self._failure(operation, "Community service returned an invalid response.")
        finally:
            self._sync_busy()

    def _success(self, operation, value, received_at):
        if operation.kind == "refresh":
            self._update_snapshot(operation.server, value, received_at)
            self._refreshing.discard(operation.server)
            self._emit_schedules(operation.server)
            return
        if self._report is not operation.report:
            return
        if operation.kind == "enroll":
            if (not isinstance(value, dict) or set(value) != {"schema", "token"} or
                    type(value["schema"]) is not int or value["schema"] != 1 or
                    not isinstance(value["token"], str) or
                    not _TOKEN.fullmatch(value["token"])):
                raise ValueError("Invalid enrollment response.")
            self._token = value["token"]
            self._write_private(self._token_path, value)
            self._send_report(operation.report)
            return
        if (not isinstance(value, dict) or set(value) != {"schema", "status", "snapshot"} or
                type(value["schema"]) is not int or value["schema"] != 1 or
                value["status"] not in ("accepted", "pending")):
            raise ValueError("Invalid report response.")
        self._update_snapshot(operation.server, value["snapshot"], received_at)
        self._emit_schedules(operation.server)
        accepted = value["status"] == "accepted"
        message = ("Arrival accepted as a community estimate." if accepted else
                   "Correction pending independent confirmation; global timing has not changed.")
        self._finish_report(operation.report, accepted, message)

    def _update_snapshot(self, server, snapshot, received_at):
        parse_snapshot(snapshot, server, received_at, received_at)
        previous = self._snapshots.get(server)
        if previous:
            current = previous[0]
            if (snapshot["revision"] < current["revision"] or
                    (snapshot["revision"] == current["revision"] and
                     _timestamp(snapshot["server_time"]) < _timestamp(current["server_time"]))):
                return
        self._snapshots[server] = (snapshot, received_at)
        self._write_private(self._cache_path(server), {
            "schema": 1, "received_at": received_at.isoformat(), "snapshot": snapshot})

    def _emit_schedules(self, server, offline=False):
        schedules = self.cached_schedules(server)
        if offline:
            status = ("Offline · showing cached community estimates." if schedules else
                      f"Offline · no cached community arrivals for {server}.")
        elif not schedules:
            status = f"No community arrivals reported for {server} yet."
        else:
            snapshot = self._snapshots[server][0]
            count = snapshot["pending_corrections"]
            status = f"Community estimates · {server}"
            if count:
                status += f" · {count} correction(s) pending"
        self.status_changed.emit(server, status)
        self.schedules_ready.emit(server, schedules, status)

    def _failure(self, operation, message):
        if operation.kind == "refresh":
            self._refreshing.discard(operation.server)
            self._emit_schedules(operation.server, offline=True)
        elif operation.report is not None:
            self._finish_report(operation.report, False, message)

    def _finish_report(self, report, accepted, message):
        if self._report is not report:
            return
        self._report = None
        self.status_changed.emit(report.server, message)
        self.report_finished.emit(report.server, accepted, message)
        self._sync_busy()
