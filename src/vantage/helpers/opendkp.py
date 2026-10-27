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
import hashlib
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
USER_AGENT = "Vantage/1.44.147 (vantagecompanion@gmail.com)"

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
    loot_progress = Signal(str, object)

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
        self._loot_generation = 0
        self._loot_state = None

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

    @property
    def loot_generation(self):
        return self._loot_generation

    def set_guild(self, value):
        slug = normalize_guild_slug(value)
        if not slug:
            raise ValueError(
                "Enter an OpenDKP guild name or guild.opendkp.com address")
        if slug == self.slug:
            return slug
        self._cancel_guild_loot()
        self._cancel_public_requests()
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
        # A repeated refresh must not discard pages already downloaded.
        if self._loot_state is None:
            self.fetch_all_guild_loot()
        self._request("auctions", "GET", root + "/auctions?page=1&ItemsPerPage=500")
        return True

    def _cancel_guild_loot(self):
        self._loot_generation += 1
        state, self._loot_state = self._loot_state, None
        pending = tuple(self._replies.items())
        if state is not None:
            self._end_busy("items")
        for reply, context in pending:
            if str(context.get("operation", "")).startswith("guild_loot|"):
                try:
                    reply.abort()
                except RuntimeError:
                    pass

    def fetch_all_guild_loot(self):
        """Publish one complete guild purchase history, never a partial page.

        OpenDKP's public Items envelope exposes TotalItems, TotalPages and
        CurrentPage. Older list-only responses are read until an empty page.
        There is no history/date/page-count cap; every request remains small.
        """
        if not self.slug:
            return False
        self._cancel_guild_loot()
        state = {"generation": self._loot_generation, "slug": self.slug,
                 "page": 1, "rows": [], "identities": {}, "signatures": set(),
                 "total": None, "pages": None, "operation": ""}
        self._loot_state = state
        self._begin_busy("items")
        self._emit_loot_progress(state, 0)
        self._request_loot_page(state)
        return True

    def _emit_loot_progress(self, state, page, complete=False):
        self.loot_progress.emit(state["slug"], {
            "generation": state["generation"], "page": page,
            "loaded": len(state["rows"]), "total": state["total"],
            "complete": complete})

    def _request_loot_page(self, state):
        if self._loot_state is not state or state["slug"] != self.slug:
            return
        operation = f"guild_loot|{state['generation']}|{state['slug']}|{state['page']}"
        state["operation"] = operation
        self._request(operation, "GET", f"/clients/{quote(state['slug'])}/items"
                      f"?page={state['page']}&ItemsPerPage=500")

    def _fail_guild_loot(self, state, message, status=0):
        if self._loot_state is not state:
            return
        self._loot_state = None
        self._end_busy("items")
        if state["generation"] != self._loot_generation or state["slug"] != self.slug:
            return
        self.failed.emit("items", "Guild loot history could not be completed: " + message +
                         ". The previous complete history is unchanged. Use Refresh to retry.", status)

    @staticmethod
    def _loot_purchase_identity(row):
        for field in ("PurchaseId", "PurchaseID", "CharacterItemId", "CharacterItemID",
                      "LootId", "LootID", "TransactionId", "TransactionID"):
            value = row.get(field)
            if value is not None and not isinstance(value, bool) and str(value).strip() not in ("", "0", "-1"):
                # ItemID and GameItemId describe a type. SourceId is a raid.
                pool = row.get("PoolId", row.get("PoolID", row.get("PoolName", "")))
                return (field.lower(), str(value), str(row.get("CharacterId", row.get("CharacterID", ""))), str(pool))
        return None

    def _receive_loot_page(self, operation, payload, error=False, message="", status=0):
        state = self._loot_state
        if (state is None or state["slug"] != self.slug or
                state["generation"] != self._loot_generation or operation != state["operation"]):
            return
        state["operation"] = ""  # A redundant finished notification cannot append twice.
        if error:
            self._fail_guild_loot(state, message or f"HTTP {status}", status)
            return
        try:
            if isinstance(payload, list):
                rows, metadata = payload, {}
            elif isinstance(payload, dict):
                rows = next((payload[key] for key in ("Items", "Models")
                             if isinstance(payload.get(key), list)), None)
                metadata = payload
            else:
                rows, metadata = None, {}
            if rows is None or any(not isinstance(row, dict) for row in rows):
                raise ValueError("OpenDKP returned an invalid purchase page")
            for field, target in (("TotalItems", "total"), ("TotalPages", "pages"), ("CurrentPage", "current")):
                value = metadata.get(field)
                if value is None:
                    continue
                if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value)):
                    raise ValueError("OpenDKP returned invalid pagination metadata")
                value = int(value)
                if target == "current":
                    if value != state["page"]:
                        raise ValueError("OpenDKP returned a different page than requested")
                elif state[target] is not None and state[target] != value:
                    raise ValueError("The guild loot list changed during loading")
                else:
                    state[target] = value
            before = len(state["rows"])
            if rows:
                serialized = [json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for row in rows]
                signature = hashlib.sha256("\n".join(sorted(serialized)).encode("utf-8")).hexdigest()
                if signature in state["signatures"]:
                    raise ValueError("OpenDKP repeated a page without advancing")
                state["signatures"].add(signature)
                for row, encoded in zip(rows, serialized):
                    identity = self._loot_purchase_identity(row)
                    if identity is not None and identity in state["identities"]:
                        if state["identities"][identity] != encoded:
                            raise ValueError("A purchase changed during loading")
                        continue
                    if identity is not None:
                        state["identities"][identity] = encoded
                    state["rows"].append(row)
            loaded, total, pages = len(state["rows"]), state["total"], state["pages"]
            if rows and loaded == before:
                raise ValueError("OpenDKP returned a page without new purchases")
            if pages is not None and (pages < state["page"] and (rows or pages != 0)):
                raise ValueError("OpenDKP returned inconsistent page totals")
            if total is not None and loaded > total:
                raise ValueError("OpenDKP returned more purchases than its reported total")
            if total is not None and loaded == total and pages is not None and state["page"] < pages:
                raise ValueError("OpenDKP returned inconsistent purchase and page totals")
            if not rows and pages is not None and state["page"] < pages:
                raise ValueError("OpenDKP ended before all reported pages arrived")
            at_end = not rows or (total is not None and loaded == total) or (pages is not None and state["page"] >= pages)
            if at_end and total is not None and loaded != total:
                raise ValueError("OpenDKP ended before all reported purchases arrived")
            if at_end:
                self._loot_state = None
                self._emit_loot_progress(state, state["page"], complete=True)
                self._end_busy("items")
                if state["generation"] != self._loot_generation or state["slug"] != self.slug:
                    return
                self.response.emit("items", {"Items": state["rows"], "TotalItems": loaded,
                    "SourceTotalItems": total, "TotalPages": state["page"], "Complete": True,
                    "GuildSlug": state["slug"], "Generation": state["generation"]})
                return
            self._emit_loot_progress(state, state["page"])
            state["page"] += 1
            QTimer.singleShot(0, lambda current=state: self._request_loot_page(current))
        except (ValueError, TypeError, OverflowError) as exc:
            self._fail_guild_loot(state, str(exc), status)

    def fetch_adjustments(self):
        if self.slug:
            self._request(
                "adjustments", "GET",
                f"/clients/{quote(self.slug)}/adjustments?page=1")

    def character_history_pending(self, character_id, request_token):
        """Whether this character generation still owns a public read."""
        token = str(request_token or "")[:64]
        if not self.slug or not character_id or not token:
            return False
        suffix = f"|{token}|{character_id}"
        return any(
            context.get("public_slug") == self.slug and
            context.get("operation", "").startswith("character_") and
            context["operation"].endswith(suffix)
            for context in self._replies.values())

    def fetch_character_details(self, character_id, lookback=90, request_token=""):
        if not self.slug or not character_id:
            return
        root = (f"/clients/{quote(self.slug)}/characters/"
                f"{quote(str(character_id))}")
        token = str(request_token or "")[:64]
        suffix = f"|{token}|{character_id}" if token else f":{character_id}"
        # Old selections are already ignored by the view, but must also stop
        # occupying the network queue ahead of the newly selected character.
        self._cancel_public_requests(lambda operation: (
            operation.startswith("character_") and not operation.endswith(suffix)
            or operation.startswith("history_detail|") and
            not operation.startswith(f"history_detail|{token}|")))
        days = max(1, min(3650, int(lookback)))
        self._request(f"character_dkp{suffix}", "GET", root + "/dkp")
        self._request(f"character_items{suffix}", "GET", root + "/items")
        self._request(
            f"character_adjustments{suffix}", "GET", root + "/adjustments")
        self._request(
            f"character_raids{suffix}", "GET", root + f"/raids?lookback={days}")

    def fetch_history_raid(self, raid_id, request_token):
        if self.slug and raid_id and request_token:
            self._request(
                f"history_detail|{request_token}|{raid_id}", "GET",
                f"/clients/{quote(self.slug)}/raids/{quote(str(raid_id), safe='')}")

    def fetch_raid_ledger(self, request_token=""):
        """Load a bounded public raid list for local evidence cross-checking."""
        if not self.slug:
            return False
        token = str(request_token or "").strip()[:64]
        operation = f"raid_ledger|{token}" if token else "raid_ledger"
        self._request(
            operation, "GET",
            f"/clients/{quote(self.slug)}/raids?count=100")
        return True

    def fetch_attendance(self, character_id, lookback=90, request_token="", correlate_character=False):
        """Read character attendance directly, without local sessions or login."""
        if not self.slug or not character_id:
            return False
        days = max(1, min(3650, int(lookback)))
        token = str(request_token or "").strip()[:64]
        operation = f"attendance|{token}" + (f"|{character_id}" if correlate_character else "")
        self._request(
            operation, "GET",
            f"/clients/{quote(self.slug)}/characters/"
            f"{quote(str(character_id), safe='')}/raids?lookback={days}")
        return True

    def fetch_attendance_detail(self, raid_id, request_token):
        if not self.slug or not raid_id:
            return False
        self._request(
            f"attendance_detail|{request_token}|{raid_id}", "GET",
            f"/clients/{quote(self.slug)}/raids/{quote(str(raid_id), safe='')}")
        return True

    def fetch_raid_details(self, raid_id, request_token=""):
        """Load one public raid without requiring or mutating guild data."""
        raid_id = str(raid_id or "").strip()
        if not self.slug or not raid_id or len(raid_id) > 128:
            return False
        token = str(request_token or "").strip()[:64]
        operation = (
            f"raid_ledger_detail|{token}|{raid_id}" if token else
            f"raid_ledger_detail:{raid_id}")
        self._request(
            operation, "GET",
            f"/clients/{quote(self.slug)}/raids/{quote(raid_id, safe='')}")
        return True

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
        self._cancel_guild_loot()
        self._cancel_public_requests()
        self.stop_live()
        self._session_retry_timer.stop()
        for reply in tuple(self._replies):
            try:
                reply.abort()
                reply.deleteLater()
            except RuntimeError:
                pass
        self._replies.clear()

    def _cancel_public_requests(self, matches=lambda _operation: True):
        for reply, context in tuple(self._replies.items()):
            if (context.get("kind") != "api" or context.get("auth") or
                    context.get("method") != "GET" or
                    not matches(context["operation"])):
                continue
            # Detach before abort(), which may synchronously emit finished.
            self._replies.pop(reply, None)
            self._end_busy(context["operation"])
            try:
                reply.abort()
                reply.deleteLater()
            except RuntimeError:
                pass

    def _request(self, operation, method, path, body=None,
                 headers=None, retry_auth=False):
        method = str(method).upper()
        public = method == "GET" and not headers
        if public:
            for reply, context in self._replies.items():
                if (context.get("public_slug") == self.slug and
                        context.get("operation") == operation and
                        context.get("path") == path):
                    return reply
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
        if public:
            self._replies[reply]["public_slug"] = self.slug
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
        if "public_slug" in context and context["public_slug"] != self.slug:
            self._end_busy(operation)
            reply.deleteLater()
            return
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
        if operation.startswith("guild_loot|"):
            message = str(payload.get("message") or payload.get("Message") or "") if isinstance(payload, dict) else ""
            self._receive_loot_page(operation, payload, error,
                                    message.strip() or error_string, status)
            return
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
