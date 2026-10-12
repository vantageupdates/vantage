"""Private-token, public-read boat calibrations using only Python's stdlib.

Run behind the local Caddy proxy with ``python boat_server.py --db PATH``.
The HTTP listener is deliberately loopback-only. Public names are self-reported;
corroboration means agreement between device tokens, not verified ownership.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime
import hashlib
from http.client import LineTooLong
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
import math
from pathlib import Path
import re
import secrets
import socket
from socketserver import ThreadingMixIn
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlsplit


SERVERS = ("Green", "Blue")
# (dock offset, source-route period): mirrors vantage.helpers.boats.BOAT_ROUTES.
ROUTES = {
    (0, "oasis"): (119, 779.75),
    (0, "timorous"): (510, 778.75),
    (1, "overthere"): (1975, 2025.0),
    (2, "butcher"): (0, 1230.0),
    (2, "firiona"): (771, 1230.0),
    (3, "nro"): (0, 519.0),
    (3, "iceclad"): (307, 519.0),
}
SCHEMA = 1
ROUTE_MODEL = 1
PHASE_TOLERANCE = 90.0
BODY_LIMIT = 2048
HEADER_LIMIT = 8192
REQUEST_SECONDS = 10
WORKER_LIMIT = 16
PENDING_TTL = 10 * 60
ANCHOR_TTL = 7 * 24 * 60 * 60
DEVICE_TTL = 90 * 24 * 60 * 60
EVENT_TTL = 48 * 60 * 60
HISTORY_TTL = 7 * 24 * 60 * 60
MAX_DEVICES = 4096
MAX_EVENTS = 2048
MAX_HISTORY = 4096
MAX_RATE_KEYS = 4096
MAX_PENDING_PER_SERVER = 64
NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9 '_-]{0,47}\Z", re.ASCII)
EVENT_RE = re.compile(r"[0-9a-fA-F]{32}\Z", re.ASCII)
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,128}\Z", re.ASCII)
OBSERVATION_KEYS = frozenset((
    "server", "boat", "start_point", "kind", "reported_by", "event_id",
    "elapsed_ms"))


class APIError(Exception):
    """An intentionally non-sensitive error safe to return over HTTP."""

    def __init__(self, status, message, retry_after=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


def utc_text(timestamp):
    return datetime.datetime.fromtimestamp(
        timestamp, datetime.timezone.utc).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")


def phase_drift(first, second, period):
    """Shortest distance between two phase origins, across cycle boundaries."""
    return abs((first - second + period / 2.0) % period - period / 2.0)


def validate_observation(payload):
    if not isinstance(payload, dict) or set(payload) != OBSERVATION_KEYS:
        raise APIError(400, "Invalid observation fields.")
    if payload["server"] not in SERVERS:
        raise APIError(400, "Unsupported server.")
    boat = payload["boat"]
    dock = payload["start_point"]
    if type(boat) is not int or not isinstance(dock, str) or (
            boat, dock) not in ROUTES:
        raise APIError(400, "Unsupported boat or dock.")
    if payload["kind"] != "dock_arrival":
        raise APIError(400, "Unsupported observation kind.")
    name = payload["reported_by"]
    event_id = payload["event_id"]
    elapsed = payload["elapsed_ms"]
    if not isinstance(name, str) or NAME_RE.fullmatch(name) is None:
        raise APIError(400, "Invalid public name.")
    if not isinstance(event_id, str) or EVENT_RE.fullmatch(event_id) is None:
        raise APIError(400, "Invalid event ID.")
    if type(elapsed) is not int or not 0 <= elapsed <= 15000:
        raise APIError(400, "Arrival must be reported within 15 seconds.")
    return payload


class BoatStore:
    """One serialized SQLite connection; all public changes are transactional.

    State has both time and count bounds. SQLite is capped at 32 MiB and uses a
    rollback journal rather than an unbounded WAL. Only hashes identify devices
    and client addresses. An idempotent replay returns its original snapshot.
    """

    def __init__(self, database, clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        if str(database) != ":memory:":
            database = Path(database)
            database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            str(database), timeout=3, check_same_thread=False,
            isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 3000")
        self.connection.execute("PRAGMA journal_mode = DELETE")
        self.connection.execute("PRAGMA synchronous = FULL")
        self.connection.execute("PRAGMA secure_delete = ON")
        self.connection.execute("PRAGMA max_page_count = 8192")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS revisions (
                server TEXT PRIMARY KEY, revision INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS devices (
                token_hash TEXT PRIMARY KEY, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS anchors (
                server TEXT NOT NULL, boat INTEGER NOT NULL,
                start_point TEXT NOT NULL, observed_at REAL NOT NULL,
                phase_origin_at REAL NOT NULL, reported_by TEXT NOT NULL,
                confidence TEXT NOT NULL, public_id TEXT NOT NULL,
                token_hash TEXT NOT NULL, PRIMARY KEY(server, boat));
            CREATE TABLE IF NOT EXISTS pending (
                server TEXT NOT NULL, boat INTEGER NOT NULL,
                start_point TEXT NOT NULL, observed_at REAL NOT NULL,
                phase_origin_at REAL NOT NULL, reported_by TEXT NOT NULL,
                public_id TEXT NOT NULL, token_hash TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY(server, boat, token_hash));
            CREATE INDEX IF NOT EXISTS pending_age ON pending(created_at);
            CREATE TABLE IF NOT EXISTS events (
                token_hash TEXT NOT NULL, event_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL, response TEXT NOT NULL,
                created_at REAL NOT NULL, PRIMARY KEY(token_hash, event_id));
            CREATE INDEX IF NOT EXISTS events_age ON events(created_at);
            CREATE TABLE IF NOT EXISTS history (
                public_id TEXT PRIMARY KEY, server TEXT NOT NULL,
                boat INTEGER NOT NULL, start_point TEXT NOT NULL,
                observed_at REAL NOT NULL, phase_origin_at REAL NOT NULL,
                reported_by TEXT NOT NULL, status TEXT NOT NULL,
                created_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS history_age ON history(created_at);
            CREATE TABLE IF NOT EXISTS rate_limits (
                scope TEXT NOT NULL, rate_key TEXT NOT NULL,
                bucket INTEGER NOT NULL, seconds INTEGER NOT NULL,
                count INTEGER NOT NULL,
                PRIMARY KEY(scope, rate_key, bucket, seconds));
            CREATE INDEX IF NOT EXISTS rate_age ON rate_limits(bucket, seconds);
        """)
        for server in SERVERS:
            self.connection.execute(
                "INSERT OR IGNORE INTO revisions VALUES (?, 0)", (server,))
        self.connection.execute(
            "INSERT OR IGNORE INTO metadata VALUES ('address_salt', ?)",
            (secrets.token_hex(32),))
        self.address_salt = self.connection.execute(
            "SELECT value FROM metadata WHERE key = 'address_salt'").fetchone()[0]
        if str(database) != ":memory:":
            # Best effort on Windows; the service account owns the directory.
            Path(database).chmod(0o600)

    def close(self):
        with self.lock:
            self.connection.close()

    @contextmanager
    def _transaction(self):
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except APIError:
                # Retain rate-limit attempts and expiry cleanup on rejection.
                self.connection.execute("COMMIT")
                raise
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise
            else:
                self.connection.execute("COMMIT")

    def _bump(self, server):
        self.connection.execute(
            "UPDATE revisions SET revision = revision + 1 WHERE server = ?",
            (server,))

    def _cleanup(self, now):
        changed = set()
        for table, column, ttl in (("anchors", "observed_at", ANCHOR_TTL),
                                   ("pending", "created_at", PENDING_TTL)):
            changed.update(row[0] for row in self.connection.execute(
                "SELECT DISTINCT server FROM {} WHERE {} <= ?".format(
                    table, column), (now - ttl,)))
            self.connection.execute(
                "DELETE FROM {} WHERE {} <= ?".format(table, column),
                (now - ttl,))
        self.connection.execute(
            "DELETE FROM devices WHERE created_at <= ?", (now - DEVICE_TTL,))
        self.connection.execute(
            "DELETE FROM events WHERE created_at <= ?", (now - EVENT_TTL,))
        self.connection.execute(
            "DELETE FROM history WHERE created_at <= ?", (now - HISTORY_TTL,))
        self.connection.execute(
            "DELETE FROM rate_limits WHERE bucket + seconds <= ?", (now,))
        for server in changed:
            self._bump(server)

    def _ip_key(self, address):
        return hashlib.sha256((self.address_salt + "\0" + address).encode(
            "ascii")).hexdigest()

    @staticmethod
    def _token_hash(token):
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def _rate(self, scope, key, now, limit, seconds):
        bucket = int(math.floor(now / seconds)) * seconds
        row = self.connection.execute(
            "SELECT count FROM rate_limits WHERE scope = ? AND rate_key = ? "
            "AND bucket = ? AND seconds = ?",
            (scope, key, bucket, seconds)).fetchone()
        if row is not None and row[0] >= limit:
            raise APIError(429, "Please wait before trying again.",
                           max(1, int(math.ceil(bucket + seconds - now))))
        if row is None:
            count = self.connection.execute(
                "SELECT COUNT(*) FROM rate_limits").fetchone()[0]
            if count >= MAX_RATE_KEYS:
                raise APIError(429, "Service is busy. Please try again.", 60)
            self.connection.execute(
                "INSERT INTO rate_limits VALUES (?, ?, ?, ?, 1)",
                (scope, key, bucket, seconds))
        else:
            self.connection.execute(
                "UPDATE rate_limits SET count = count + 1 WHERE scope = ? "
                "AND rate_key = ? AND bucket = ? AND seconds = ?",
                (scope, key, bucket, seconds))

    def request_rate(self, address):
        now = self.clock()
        with self._transaction():
            self._cleanup(now)
            self._rate("request", self._ip_key(address), now, 120, 60)

    def enroll(self, address):
        now = self.clock()
        with self._transaction():
            self._cleanup(now)
            key = self._ip_key(address)
            self._rate("enroll", key, now, 4, 3600)
            self._rate("enroll", key, now, 20, 86400)
            count = self.connection.execute(
                "SELECT COUNT(*) FROM devices").fetchone()[0]
            if count >= MAX_DEVICES:
                raise APIError(429, "Enrollment is busy. Please try again.", 3600)
            token = secrets.token_urlsafe(32)
            self.connection.execute(
                "INSERT INTO devices VALUES (?, ?)",
                (self._token_hash(token), now))
            return {"schema": SCHEMA, "token": token}

    def _snapshot(self, server, now):
        observations = []
        for row in self.connection.execute(
                "SELECT * FROM anchors WHERE server = ? ORDER BY boat", (server,)):
            observations.append({
                "boat": row["boat"], "start_point": row["start_point"],
                "kind": "dock_arrival", "observed_at": utc_text(row["observed_at"]),
                "phase_origin_at": utc_text(row["phase_origin_at"]),
                "reported_by": row["reported_by"],
                "confidence": row["confidence"], "id": row["public_id"]})
        return {
            "schema": SCHEMA, "route_model": ROUTE_MODEL, "server": server,
            "server_time": utc_text(now), "revision": self.connection.execute(
                "SELECT revision FROM revisions WHERE server = ?", (server,)
            ).fetchone()[0], "observations": observations,
            "pending_corrections": self.connection.execute(
                "SELECT COUNT(*) FROM pending WHERE server = ? AND created_at > ?",
                (server, now - PENDING_TTL)).fetchone()[0]}

    def snapshot(self, server):
        if server not in SERVERS:
            raise APIError(400, "Unsupported server.")
        now = self.clock()
        with self._transaction():
            self._cleanup(now)
            return self._snapshot(server, now)

    def _accept(self, record, confidence, clear_pending=True):
        self.connection.execute("""
            INSERT OR REPLACE INTO anchors (
                server, boat, start_point, observed_at, phase_origin_at,
                reported_by, confidence, public_id, token_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (record["server"], record["boat"], record["start_point"],
              record["observed_at"], record["phase_origin_at"],
              record["reported_by"], confidence, record["public_id"],
              record["token_hash"]))
        if clear_pending:
            self.connection.execute(
                "DELETE FROM pending WHERE server = ? AND boat = ?",
                (record["server"], record["boat"]))
        else:
            # An ordinary confirming arrival does not erase another device's
            # proposed correction. A device can supersede its own proposal.
            self.connection.execute(
                "DELETE FROM pending WHERE server = ? AND boat = ? AND token_hash = ?",
                (record["server"], record["boat"], record["token_hash"]))
        self._bump(record["server"])

    def observe(self, token, payload, address):
        validate_observation(payload)
        now = self.clock()
        with self._transaction():
            self._cleanup(now)
            ip_key = self._ip_key(address)
            if not isinstance(token, str) or TOKEN_RE.fullmatch(token) is None:
                self._rate("auth", ip_key, now, 20, 60)
                raise APIError(401, "Invalid device credentials.")
            token_hash = self._token_hash(token)
            device = self.connection.execute(
                "SELECT created_at FROM devices WHERE token_hash = ?", (token_hash,)
            ).fetchone()
            if device is None or device[0] <= now - DEVICE_TTL:
                self._rate("auth", ip_key, now, 20, 60)
                raise APIError(401, "Invalid device credentials.")
            event_id = payload["event_id"].lower()
            payload_hash = hashlib.sha256(json.dumps(
                payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            replay = self.connection.execute(
                "SELECT payload_hash, response FROM events WHERE token_hash = ? "
                "AND event_id = ?", (token_hash, event_id)).fetchone()
            if replay is not None:
                if replay[0] != payload_hash:
                    raise APIError(400, "Event ID was already used for another report.")
                return json.loads(replay[1])
            self._rate("report-ip", ip_key, now, 30, 60)
            self._rate("report-ip", ip_key, now, 300, 86400)
            self._rate("report-token", token_hash, now, 8, 60)
            self._rate("report-token", token_hash, now, 100, 86400)
            self._rate("report-boat", token_hash + ":" + str(payload["boat"]),
                       now, 1, 15)
            offset = ROUTES[(payload["boat"], payload["start_point"])][0]
            observed_at = now - payload["elapsed_ms"] / 1000.0
            record = {
                "server": payload["server"], "boat": payload["boat"],
                "start_point": payload["start_point"], "observed_at": observed_at,
                "phase_origin_at": observed_at - offset,
                "reported_by": payload["reported_by"],
                "public_id": secrets.token_urlsafe(18), "token_hash": token_hash}
            anchor = self.connection.execute(
                "SELECT * FROM anchors WHERE server = ? AND boat = ?",
                (record["server"], record["boat"])).fetchone()
            status = "accepted"
            if anchor is None or now - anchor["observed_at"] >= (
                    ROUTES[(anchor["boat"], anchor["start_point"])][1] * 3):
                self._accept(record, "unconfirmed")
            else:
                period = ROUTES[(anchor["boat"], anchor["start_point"])][1]
                drift = phase_drift(record["phase_origin_at"],
                                    anchor["phase_origin_at"], period)
                if drift <= PHASE_TOLERANCE:
                    confidence = (
                        "corroborated" if token_hash != anchor["token_hash"]
                        else anchor["confidence"])
                    # A slower HTTP request must not move freshness backwards.
                    if record["observed_at"] >= anchor["observed_at"]:
                        self._accept(record, confidence, clear_pending=False)
                    elif confidence != anchor["confidence"]:
                        self._accept(anchor, confidence, clear_pending=False)
                else:
                    candidates = self.connection.execute(
                        "SELECT * FROM pending WHERE server = ? AND boat = ? "
                        "AND token_hash != ? AND created_at > ? ORDER BY observed_at DESC",
                        (record["server"], record["boat"], token_hash, now - PENDING_TTL)
                    ).fetchall()
                    partner = next((candidate for candidate in candidates
                        if phase_drift(record["phase_origin_at"],
                                       candidate["phase_origin_at"],
                                       ROUTES[(candidate["boat"],
                                               candidate["start_point"])][1])
                        <= PHASE_TOLERANCE), None)
                    if partner is not None:
                        newest = (record if record["observed_at"] >= partner["observed_at"]
                                  else partner)
                        self._accept(newest, "corroborated")
                    else:
                        existing = self.connection.execute(
                            "SELECT 1 FROM pending WHERE server = ? AND boat = ? "
                            "AND token_hash = ?",
                            (record["server"], record["boat"], token_hash)).fetchone()
                        pending_count = self.connection.execute(
                            "SELECT COUNT(*) FROM pending WHERE server = ?",
                            (record["server"],)).fetchone()[0]
                        if existing is None and pending_count >= MAX_PENDING_PER_SERVER:
                            raise APIError(429, "Corrections are busy. Please try again.",
                                           PENDING_TTL)
                        self.connection.execute("""
                            INSERT OR REPLACE INTO pending VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (record["server"], record["boat"], record["start_point"],
                              observed_at, record["phase_origin_at"], record["reported_by"],
                              record["public_id"], token_hash, now))
                        self._bump(record["server"])
                        status = "pending"
            self.connection.execute(
                "INSERT INTO history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record["public_id"], record["server"], record["boat"],
                 record["start_point"], observed_at, record["phase_origin_at"],
                 record["reported_by"], status, now))
            response = {"schema": SCHEMA, "status": status,
                        "snapshot": self._snapshot(record["server"], now)}
            self.connection.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
                (token_hash, event_id, payload_hash,
                 json.dumps(response, separators=(",", ":")), now))
            for table, limit in (("events", MAX_EVENTS), ("history", MAX_HISTORY)):
                self.connection.execute(
                    "DELETE FROM {} WHERE rowid IN (SELECT rowid FROM {} "
                    "ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET ?)".format(
                        table, table), (limit,))
            return response


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _invalid_constant(unused_value):
    raise ValueError("non-finite JSON value")


class _HeaderReader:
    """Cap header bytes while the standard HTTP parser reads them."""

    def __init__(self, stream):
        self.stream = stream
        self.remaining = HEADER_LIMIT

    def readline(self, size=-1):
        maximum = self.remaining + 1
        if size >= 0:
            maximum = min(maximum, size)
        value = self.stream.readline(maximum)
        self.remaining -= len(value)
        if self.remaining < 0:
            raise LineTooLong("request headers")
        return value


class BoatRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "VantageBoats"
    sys_version = ""

    def setup(self):
        self.request.settimeout(3)
        super().setup()

    def parse_request(self):
        stream = self.rfile
        self.rfile = _HeaderReader(stream)
        try:
            return super().parse_request()
        finally:
            self.rfile = stream

    def handle(self):
        # A total deadline also bounds slow requests which send one byte at a time.
        timer = threading.Timer(REQUEST_SECONDS, self._expire_request)
        timer.daemon = True
        timer.start()
        try:
            super().handle()
        finally:
            timer.cancel()

    def _expire_request(self):
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def log_message(self, format, *args):
        # Do not persist access paths, remote addresses, or credentials in logs.
        pass

    def _reply(self, status, payload, retry_after=None):
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        if retry_after is not None:
            self.send_header("Retry-After", str(max(1, int(retry_after))))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_error(self, code, message=None, explain=None):
        self._reply(code, {"schema": SCHEMA, "error": "Invalid HTTP request."})

    def handle_expect_100(self):
        self._reply(400, {"schema": SCHEMA, "error": "Unsupported HTTP expectation."})
        return False

    def _address(self):
        peer = ipaddress.ip_address(self.client_address[0])
        proxy_headers = self.headers.get_all("X-Vantage-Client-IP", [])
        if peer.is_loopback and proxy_headers:
            if len(proxy_headers) != 1:
                raise APIError(400, "Invalid proxy address.")
            try:
                return str(ipaddress.ip_address(proxy_headers[0].strip()))
            except ValueError:
                raise APIError(400, "Invalid proxy address.") from None
        return str(peer)

    def _body(self):
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or re.fullmatch(r"[0-9]{1,10}", lengths[0]) is None:
            raise APIError(400, "A valid content length is required.")
        length = int(lengths[0])
        if length > BODY_LIMIT:
            raise APIError(413, "Request body is too large.")
        content_types = self.headers.get_all("Content-Type", [])
        if len(content_types) != 1 or content_types[0].strip().lower() not in (
                "application/json", "application/json; charset=utf-8"):
            raise APIError(400, "JSON content type is required.")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise APIError(400, "Incomplete request body.")
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                               parse_constant=_invalid_constant)
        except (UnicodeError, ValueError, RecursionError):
            raise APIError(400, "Invalid JSON body.") from None
        if not isinstance(value, dict):
            raise APIError(400, "JSON object is required.")
        return value

    def _dispatch(self):
        if len(self.path) > 256 or sum(len(key) + len(value) + 4
                for key, value in self.headers.items()) > HEADER_LIMIT:
            raise APIError(400, "HTTP request is too large.")
        if self.headers.get_all("Transfer-Encoding", []):
            raise APIError(400, "Transfer encoding is unsupported.")
        if self.headers.get_all("Expect", []):
            raise APIError(400, "Unsupported HTTP expectation.")
        target = urlsplit(self.path)
        if target.scheme or target.netloc or target.fragment:
            raise APIError(400, "Invalid request target.")
        address = self._address()
        self.server.store.request_rate(address)
        if target.path == "/health":
            if self.command != "GET":
                raise APIError(405, "Method is unsupported.")
            if target.query:
                raise APIError(400, "Unexpected query fields.")
            return {"schema": SCHEMA, "service": "Vantage Boats",
                    "route_model": ROUTE_MODEL, "servers": list(SERVERS)}
        if target.path == "/v1/boats":
            if self.command != "GET":
                raise APIError(405, "Method is unsupported.")
            query = parse_qs(target.query, keep_blank_values=True, max_num_fields=4)
            if set(query) != {"server"} or len(query["server"]) != 1:
                raise APIError(400, "Exactly one server is required.")
            return self.server.store.snapshot(query["server"][0])
        if target.path in ("/v1/devices", "/v1/observations"):
            if self.command != "POST":
                raise APIError(405, "Method is unsupported.")
            if target.query:
                raise APIError(400, "Unexpected query fields.")
            payload = self._body()
            if target.path == "/v1/devices":
                if payload:
                    raise APIError(400, "Enrollment body must be empty.")
                return self.server.store.enroll(address)
            authorizations = self.headers.get_all("Authorization", [])
            token = None
            if len(authorizations) == 1 and authorizations[0].startswith("Bearer "):
                token = authorizations[0][7:]
            return self.server.store.observe(token, payload, address)
        raise APIError(404, "Unknown endpoint.")

    def _run(self):
        try:
            self._reply(200, self._dispatch())
        except APIError as error:
            self._reply(error.status, {"schema": SCHEMA, "error": error.message},
                        error.retry_after)
        except (socket.timeout, ConnectionError, OSError):
            self.close_connection = True
        except (ValueError, RecursionError):
            self._reply(400, {"schema": SCHEMA, "error": "Invalid request."})
        except sqlite3.Error:
            self._reply(503, {"schema": SCHEMA, "error": "Service is busy."}, 60)
        except Exception:
            self._reply(500, {"schema": SCHEMA, "error": "Request could not be processed."})

    do_GET = do_POST = do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _run
    do_TRACE = do_CONNECT = _run


class BoatHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    block_on_close = True
    request_queue_size = WORKER_LIMIT
    allow_reuse_address = True

    def __init__(self, address, store):
        if not ipaddress.ip_address(address[0]).is_loopback:
            raise ValueError("Boat server must bind to loopback.")
        self.store = store
        self._workers = threading.BoundedSemaphore(WORKER_LIMIT)
        super().__init__(address, BoatRequestHandler)

    def process_request(self, request, client_address):
        if not self._workers.acquire(blocking=False):
            body = b'{"schema":1,"error":"Service is busy."}'
            response = (
                "HTTP/1.1 429 Too Many Requests\r\n"
                "Content-Type: application/json\r\n"
                "Content-Length: {}\r\nRetry-After: 1\r\n"
                "Cache-Control: no-store\r\nConnection: close\r\n\r\n".format(
                    len(body))).encode("ascii") + body
            try:
                request.settimeout(0.25)
                request.sendall(response)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._workers.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._workers.release()

    def handle_error(self, request, client_address):
        # Exceptions must not emit addresses or request data to service logs.
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="Vantage Boats community service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--db", type=Path,
                        default=Path(__file__).with_name("boat-community.sqlite3"))
    args = parser.parse_args(argv)
    with_ip = ipaddress.ip_address(args.host)
    if not with_ip.is_loopback or with_ip.version != 4:
        parser.error("host must be an IPv4 loopback address")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    store = BoatStore(args.db)
    server = BoatHTTPServer((args.host, args.port), store)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()


if __name__ == "__main__":
    main()
