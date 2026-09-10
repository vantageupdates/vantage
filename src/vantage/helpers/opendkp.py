"""OpenDKP API, authentication, and live-auction integration.

The hosted OpenDKP client exposes read-only guild data through its REST API
and protects live auctions and bid mutations with an AWS Cognito ID token.
Vantage stores only the renewable token in Windows Credential Manager; a
password is kept solely in the temporary JSON request used to sign in.
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import re
import sys
import time
from urllib.parse import quote, urlparse

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import (
    QAbstractSocket, QNetworkAccessManager, QNetworkReply, QNetworkRequest)
from PySide6.QtWebSockets import QWebSocket


API_ROOT = "https://api.opendkp.com"
COGNITO_ROOT = "https://cognito-idp.us-east-2.amazonaws.com/"
COGNITO_TARGET = "AWSCognitoIdentityProviderService.InitiateAuth"
LIVE_ROOT = "wss://a2d3ggob45.execute-api.us-east-2.amazonaws.com/production"
USER_AGENT = "Vantage/1.44.77 (vantagecompanion@gmail.com)"

_GUILD_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_guild_slug(value):
    """Return a safe OpenDKP subdomain from a slug or guild URL."""
    raw = str(value or "").strip().casefold()
    if not raw:
        return ""
    if "://" not in raw and ("/" in raw or "." in raw):
        raw = "https://" + raw
    if "://" in raw:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").strip(".").casefold()
        if not host:
            return ""
        if host.endswith(".opendkp.com"):
            raw = host[:-len(".opendkp.com")].split(".")[-1]
        else:
            # A custom guild website does not reveal the OpenDKP tenant. Do
            # not guess from it: callers can ask for the guild subdomain.
            return ""
    raw = raw.strip().strip("./")
    return raw if _GUILD_SLUG.fullmatch(raw) else ""


def rows_from_payload(payload, *keys):
    """Coerce the array shapes used by old and current OpenDKP endpoints."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            rows = payload.get(key)
            if isinstance(rows, list):
                return rows
    return []


def auction_item_name(auction):
    """Return the best human-facing item name from an auction model."""
    auction = auction if isinstance(auction, dict) else {}
    item = auction.get("Item")
    if isinstance(item, dict):
        name = item.get("Name") or item.get("ItemName")
        if name:
            return " ".join(str(name).split())
    return " ".join(str(
        auction.get("ItemName") or auction.get("Name") or "Unknown item"
    ).split())


def auction_id(auction):
    """Return the positive identifier used by OpenDKP auction routes."""
    auction = auction if isinstance(auction, dict) else {}
    raw = auction.get("AuctionId", auction.get("Id", auction.get("id")))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def auction_bids(auction):
    """Return the bid array from current and legacy auction payloads."""
    auction = auction if isinstance(auction, dict) else {}
    return rows_from_payload(auction, "Bids", "bids")


def watch_matches(auction, watches):
    """Return configured watch phrases found in an auction item name."""
    name = auction_item_name(auction).casefold()
    return [str(watch).strip() for watch in (watches or [])
            if str(watch).strip() and str(watch).strip().casefold() in name]


def decode_token_username(token):
    """Read the display username from an already-issued JWT payload."""
    try:
        encoded = str(token).split(".", 2)[1]
        encoded += "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
        return str(payload.get("cognito:username") or
                   payload.get("username") or "").strip()
    except (IndexError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return ""


def _credential_target(slug):
    return f"Vantage.OpenDKP.{normalize_guild_slug(slug)}"


if sys.platform == "win32":
    class _CredentialAttribute(ctypes.Structure):
        _fields_ = (
            ("Keyword", wintypes.LPWSTR), ("Flags", wintypes.DWORD),
            ("ValueSize", wintypes.DWORD),
            ("Value", ctypes.POINTER(ctypes.c_ubyte)))


    class _Credential(ctypes.Structure):
        _fields_ = (
            ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.POINTER(_CredentialAttribute)),
            ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR))


def write_refresh_token(slug, username, token):
    """Persist a refresh token with Windows-managed user protection."""
    slug = normalize_guild_slug(slug)
    token = str(token or "")
    if sys.platform != "win32" or not slug or not token:
        return False
    blob = token.encode("utf-16-le")
    buffer = ctypes.create_string_buffer(blob)
    credential = _Credential()
    credential.Type = 1  # CRED_TYPE_GENERIC
    credential.TargetName = _credential_target(slug)
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(
        buffer, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = str(username or slug)
    advapi = ctypes.WinDLL("Advapi32.dll")
    advapi.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
    advapi.CredWriteW.restype = wintypes.BOOL
    return bool(advapi.CredWriteW(ctypes.byref(credential), 0))


def read_refresh_token(slug):
    """Return ``(username, token)`` from Windows Credential Manager."""
    slug = normalize_guild_slug(slug)
    if sys.platform != "win32" or not slug:
        return "", ""
    advapi = ctypes.WinDLL("Advapi32.dll")
    pointer = ctypes.POINTER(_Credential)()
    advapi.CredReadW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_Credential))]
    advapi.CredReadW.restype = wintypes.BOOL
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    if not advapi.CredReadW(_credential_target(slug), 1, 0,
                            ctypes.byref(pointer)):
        return "", ""
    try:
        credential = pointer.contents
        raw = ctypes.string_at(
            credential.CredentialBlob, credential.CredentialBlobSize)
        return str(credential.UserName or ""), raw.decode("utf-16-le")
    except (OSError, UnicodeError, ValueError):
        return "", ""
    finally:
        advapi.CredFree(pointer)


def delete_refresh_token(slug):
    """Remove one guild token without touching any other credential."""
    slug = normalize_guild_slug(slug)
    if sys.platform != "win32" or not slug:
        return False
    advapi = ctypes.WinDLL("Advapi32.dll")
    advapi.CredDeleteW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi.CredDeleteW.restype = wintypes.BOOL
    return bool(advapi.CredDeleteW(_credential_target(slug), 1, 0))


class OpenDkpClient(QObject):
    """Asynchronous REST/Cognito/WebSocket client for any OpenDKP guild."""

    response = Signal(str, object)
    failed = Signal(str, str, int)
    busy_changed = Signal(bool, str)
    auth_changed = Signal(str, str)
    live_changed = Signal(str)
    auction_event = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.slug = ""
        self.client_details = {}
        self.username = ""
        self._id_token = ""
        self._refresh_token = ""
        self._token_expires_at = 0.0
        self._pending_auth = []
        self._refreshing = False
        self._replies = {}
        self._busy_count = 0
        self._active_auctions = {}
        self._live_requested = False
        self._reconnect_attempt = 0

        self.socket = QWebSocket("Vantage OpenDKP", parent=self)
        self.socket.connected.connect(self._socket_connected)
        self.socket.disconnected.connect(self._socket_disconnected)
        self.socket.textMessageReceived.connect(self._socket_message)
        self.socket.errorOccurred.connect(self._socket_error)
        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(5 * 60 * 1000)
        self._ping_timer.timeout.connect(self._socket_ping)
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._open_socket)
        self._session_retry_timer = QTimer(self)
        self._session_retry_timer.setSingleShot(True)
        self._session_retry_timer.setInterval(30 * 1000)
        self._session_retry_timer.timeout.connect(self.restore_session)

    @property
    def authenticated(self):
        return bool(self._id_token and time.monotonic() < self._token_expires_at)

    def set_guild(self, value):
        slug = normalize_guild_slug(value)
        if not slug:
            raise ValueError(
                "Enter an OpenDKP guild name or guild.opendkp.com address")
        if slug == self.slug:
            return slug
        self.stop_live()
        self._session_retry_timer.stop()
        self.slug = slug
        self.client_details = {}
        self._id_token = ""
        self._token_expires_at = 0.0
        self.username, self._refresh_token = read_refresh_token(slug)
        self.auth_changed.emit("saved" if self._refresh_token else "public",
                               self.username)
        return slug

    def load_guild(self, value):
        slug = self.set_guild(value)
        self._request("client", "GET", f"/clients/{quote(slug)}")
        return slug

    def refresh_public(self):
        if not self.slug:
            return False
        root = f"/clients/{quote(self.slug)}"
        self._request("dkp", "GET", root + "/dkp")
        self._request("characters", "GET", root + "/characters")
        self._request("raids", "GET", root + "/raids?page=1&ItemsPerPage=250")
        self._request("items", "GET", root + "/items?page=1&ItemsPerPage=500")
        self._request("auctions", "GET", root + "/auctions?page=1&ItemsPerPage=500")
        return True

    def fetch_adjustments(self):
        if self.slug:
            self._request(
                "adjustments", "GET",
                f"/clients/{quote(self.slug)}/adjustments?page=1")

    def fetch_character_details(self, character_id):
        if not self.slug or not character_id:
            return
        root = (f"/clients/{quote(self.slug)}/characters/"
                f"{quote(str(character_id))}")
        suffix = str(character_id)
        self._request(f"character_dkp:{suffix}", "GET", root + "/dkp")
        self._request(f"character_items:{suffix}", "GET", root + "/items")
        self._request(
            f"character_adjustments:{suffix}", "GET", root + "/adjustments")
        self._request(
            f"character_raids:{suffix}", "GET", root + "/raids?lookback=90")

    def login(self, username, password):
        username = str(username or "").strip()
        password = str(password or "")
        client_id = str(self.client_details.get("WebClientId") or "").strip()
        if not client_id:
            self.failed.emit("login", "This guild did not provide a login client", 0)
            return False
        if not username or not password:
            self.failed.emit("login", "Enter your OpenDKP username and password", 0)
            return False
        self.username = username
        self.auth_changed.emit("connecting", username)
        self._cognito_request("login", {
            "AuthFlow": "USER_PASSWORD_AUTH",
            "ClientId": client_id,
            "AuthParameters": {"USERNAME": username, "PASSWORD": password},
        })
        return True

    def restore_session(self):
        if not self._refresh_token:
            return False
        return self._start_refresh()

    def logout(self):
        slug = self.slug
        self.stop_live()
        self._session_retry_timer.stop()
        self._id_token = ""
        self._refresh_token = ""
        self._token_expires_at = 0.0
        self._pending_auth.clear()
        try:
            delete_refresh_token(slug)
        except OSError:
            pass
        self.auth_changed.emit("public", "")

    def fetch_active_auctions(self):
        if not self.slug:
            return False
        self._authorized_request(
            "active_auctions", "GET",
            f"/clients/{quote(self.slug)}/auctions/active")
        return True

    def place_bid(self, auction_id, character, value, priority=1):
        character = character if isinstance(character, dict) else {}
        body = {
            "CharacterId": int(character.get("CharacterId") or 0),
            "Priority": max(1, int(priority or 1)),
            "Rank": str(character.get("Rank") or "").strip(),
            "SessionId": int(auction_id),
            "Value": max(1, int(value)),
        }
        if not body["CharacterId"] or not body["Rank"]:
            self.failed.emit("place_bid", "Choose an eligible linked character", 0)
            return False
        self._authorized_request(
            "place_bid", "PUT",
            f"/clients/{quote(self.slug)}/auctions/{body['SessionId']}/bids",
            body)
        return True

    def update_bid(self, auction_id, bid, value):
        body = dict(bid or {})
        bid_id = int(body.get("BidId") or 0)
        session_id = int(auction_id)
        if not bid_id:
            return False
        body["Value"] = max(1, int(value))
        self._authorized_request(
            "update_bid", "POST",
            f"/clients/{quote(self.slug)}/auctions/{session_id}/bids/{bid_id}",
            body)
        return True

    def delete_bid(self, auction_id, bid):
        body = dict(bid or {})
        bid_id = int(body.get("BidId") or 0)
        session_id = int(auction_id)
        if not bid_id:
            return False
        self._authorized_request(
            "delete_bid", "DELETE",
            f"/clients/{quote(self.slug)}/auctions/{session_id}/bids/{bid_id}",
            body)
        return True

    def start_live(self):
        self._live_requested = True
        if not self.authenticated:
            self._ensure_auth(lambda _token: self._open_socket())
            return
        self._open_socket()

    def stop_live(self):
        self._live_requested = False
        self._reconnect_timer.stop()
        self._ping_timer.stop()
        self._reconnect_attempt = 0
        self.socket.close()
        self.live_changed.emit("off")

    def close(self):
        self.stop_live()
        self._session_retry_timer.stop()
        for reply in tuple(self._replies):
            try:
                reply.abort()
                reply.deleteLater()
            except RuntimeError:
                pass
        self._replies.clear()

    def _request(self, operation, method, path, body=None,
                 headers=None, retry_auth=False):
        request = QNetworkRequest(QUrl(API_ROOT + path))
        request.setTransferTimeout(30000)
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        request.setRawHeader(b"Accept", b"application/json")
        merged_headers = dict(headers or {})
        for name, value in merged_headers.items():
            request.setRawHeader(str(name).encode("ascii"),
                                 str(value).encode("utf-8"))
        payload = b""
        if body is not None:
            payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                              "application/json")
        method = str(method).upper()
        if method == "GET":
            reply = self.network.get(request)
        elif method == "POST":
            reply = self.network.post(request, payload)
        elif method == "PUT":
            reply = self.network.put(request, payload)
        elif method == "DELETE":
            reply = self.network.sendCustomRequest(request, b"DELETE", payload)
        else:
            raise ValueError(f"Unsupported OpenDKP method: {method}")
        self._replies[reply] = {
            "kind": "api", "operation": operation, "method": method,
            "path": path, "body": body, "auth": "Authorization" in merged_headers,
            "retry_auth": bool(retry_auth),
        }
        self._begin_busy(operation)
        reply.finished.connect(lambda current=reply: self._reply_finished(current))
        return reply

    def _authorized_request(self, operation, method, path, body=None):
        self._ensure_auth(lambda token: self._request(
            operation, method, path, body,
            {"Authorization": f"Bearer {token}"}))

    def _ensure_auth(self, action):
        if self.authenticated:
            action(self._id_token)
            return True
        self._pending_auth.append(action)
        if self._refreshing:
            return True
        if not self._refresh_token:
            self._pending_auth.clear()
            self.auth_changed.emit("required", self.username)
            self.failed.emit("auth", "Sign in to OpenDKP for live auctions and bids", 401)
            return False
        return self._start_refresh()

    def _start_refresh(self):
        client_id = str(self.client_details.get("WebClientId") or "").strip()
        if not client_id or not self._refresh_token or self._refreshing:
            return False
        self._refreshing = True
        self.auth_changed.emit("connecting", self.username)
        self._cognito_request("refresh", {
            "AuthFlow": "REFRESH_TOKEN_AUTH",
            "ClientId": client_id,
            "AuthParameters": {"REFRESH_TOKEN": self._refresh_token},
        })
        return True

    def _cognito_request(self, operation, body):
        request = QNetworkRequest(QUrl(COGNITO_ROOT))
        request.setTransferTimeout(30000)
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        request.setRawHeader(b"X-Amz-Target", COGNITO_TARGET.encode("ascii"))
        request.setRawHeader(b"Content-Type", b"application/x-amz-json-1.1")
        reply = self.network.post(
            request, json.dumps(body, separators=(",", ":")).encode("utf-8"))
        self._replies[reply] = {"kind": "cognito", "operation": operation}
        self._begin_busy(operation)
        reply.finished.connect(lambda current=reply: self._reply_finished(current))

    def _reply_finished(self, reply):
        context = self._replies.pop(reply, None)
        if context is None:
            reply.deleteLater()
            return
        operation = context["operation"]
        status = int(reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0)
        raw = bytes(reply.readAll())
        # Capture the native message before deleteLater; bindings may reject
        # method calls as soon as ownership has been queued for destruction.
        error_string = str(reply.errorString() or "")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except (UnicodeError, ValueError, json.JSONDecodeError):
            payload = {}
        error = reply.error() != QNetworkReply.NetworkError.NoError or status >= 400
        self._end_busy(operation)
        reply.deleteLater()
        if error:
            message = ""
            if isinstance(payload, dict):
                message = str(payload.get("message") or payload.get("Message") or "")
            message = message.strip() or error_string or f"HTTP {status}"
            if context["kind"] == "cognito":
                self._auth_failed(operation, message, status)
                return
            if (status == 401 and context.get("auth") and
                    not context.get("retry_auth") and self._refresh_token):
                self._id_token = ""
                self._token_expires_at = 0.0
                self._ensure_auth(lambda token, saved=dict(context): self._request(
                    saved["operation"], saved["method"], saved["path"],
                    saved["body"], {"Authorization": f"Bearer {token}"},
                    retry_auth=True))
                return
            self.failed.emit(operation, message, status)
            return
        if context["kind"] == "cognito":
            self._auth_succeeded(operation, payload)
            return
        if operation == "client" and isinstance(payload, dict):
            self.client_details = payload
        if operation == "active_auctions":
            rows = rows_from_payload(payload, "Auctions", "BidSessions")
            self._active_auctions = {
                str(auction_id(row)): row for row in rows
                if auction_id(row)}
            payload = list(self._active_auctions.values())
        self.response.emit(operation, payload)

    def _auth_succeeded(self, operation, payload):
        self._refreshing = False
        self._session_retry_timer.stop()
        result = payload.get("AuthenticationResult", {}) \
            if isinstance(payload, dict) else {}
        token = str(result.get("IdToken") or "")
        if not token:
            self._auth_failed(operation, "OpenDKP did not return an ID token", 0)
            return
        self._id_token = token
        self._token_expires_at = time.monotonic() + max(
            60, int(result.get("ExpiresIn") or 3600)) - 45
        returned_refresh = str(result.get("RefreshToken") or "")
        if returned_refresh:
            self._refresh_token = returned_refresh
        token_username = decode_token_username(token)
        if token_username:
            self.username = token_username
        if self._refresh_token:
            try:
                write_refresh_token(self.slug, self.username, self._refresh_token)
            except OSError:
                pass
        self.auth_changed.emit("connected", self.username)
        actions, self._pending_auth = self._pending_auth, []
        for action in actions:
            action(self._id_token)
        if operation == "login":
            self.response.emit("login", {"username": self.username})

    def _auth_failed(self, operation, message, status):
        self._refreshing = False
        self._id_token = ""
        self._token_expires_at = 0.0
        self._pending_auth.clear()
        if operation == "refresh":
            # A timeout, offline startup, rate limit, or server error does not
            # invalidate a renewable session. Keep the Windows credential and
            # retry so a temporary network failure never signs the user out.
            rejected = int(status or 0) in (400, 401, 403)
            if rejected:
                self._refresh_token = ""
                try:
                    delete_refresh_token(self.slug)
                except OSError:
                    pass
                self.auth_changed.emit("expired", self.username)
                self.failed.emit("login", message, status)
            else:
                self.auth_changed.emit("saved", self.username)
                if self._refresh_token and self.client_details.get("WebClientId"):
                    self._session_retry_timer.start()
                self.failed.emit("session", message, status)
            return
        self.auth_changed.emit("error", self.username)
        self.failed.emit("login", message, status)

    def _begin_busy(self, label):
        self._busy_count += 1
        self.busy_changed.emit(True, str(label))

    def _end_busy(self, label):
        self._busy_count = max(0, self._busy_count - 1)
        self.busy_changed.emit(self._busy_count > 0, str(label))

    def _open_socket(self):
        if not self._live_requested:
            return
        if not self.authenticated:
            self._ensure_auth(lambda _token: self._open_socket())
            return
        if self.socket.state() != QAbstractSocket.SocketState.UnconnectedState:
            return
        self.live_changed.emit("connecting")
        self.socket.open(QUrl(LIVE_ROOT))

    def _socket_connected(self):
        self._reconnect_attempt = 0
        self.live_changed.emit("live")
        self._ping_timer.start()
        self._ensure_auth(lambda token: self.socket.sendTextMessage(json.dumps({
            "Token": token, "Action": "INIT",
            "ClientId": self.client_details.get("ClientId"),
        }, separators=(",", ":"))))

    def _socket_disconnected(self):
        self._ping_timer.stop()
        if not self._live_requested:
            self.live_changed.emit("off")
            return
        self.live_changed.emit("reconnecting")
        self._reconnect_attempt += 1
        self._reconnect_timer.start(min(60000, 2000 * self._reconnect_attempt))

    def _socket_error(self, _error):
        if self._live_requested:
            self.live_changed.emit("error")

    def _socket_ping(self):
        if self.socket.state() != QAbstractSocket.SocketState.ConnectedState:
            return
        self._ensure_auth(lambda token: self.socket.sendTextMessage(json.dumps({
            "Token": token, "Action": "PING",
            "ClientId": self.client_details.get("ClientId"),
        }, separators=(",", ":"))))

    def _socket_message(self, message):
        try:
            payload = json.loads(str(message))
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        action = str(payload.get("Action") or "").upper()
        rows = rows_from_payload(payload, "BidSessions", "Auctions")
        if action == "AUCTION_UPDATE":
            for row in rows:
                row_id = auction_id(row)
                if row_id:
                    self._active_auctions[str(row_id)] = row
            self.response.emit(
                "active_auctions", list(self._active_auctions.values()))
            self.auction_event.emit("update", rows)
        elif action == "AUCTION_DELETE":
            for row in rows:
                if isinstance(row, dict):
                    self._active_auctions.pop(str(auction_id(row)), None)
            self.response.emit(
                "active_auctions", list(self._active_auctions.values()))
            self.auction_event.emit("delete", rows)
