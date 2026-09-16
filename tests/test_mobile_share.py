import json
import socket
import sys
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import vantage.helpers.mobile_share as mobile_share_module
from vantage.helpers import config
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton
from vantage.helpers.mobile_share import (
    MobileShareController, MobileShareDialog, _MOBILE_PAGE, _ShareHTTPServer,
    _safe_p99_url, load_mobile_item_detail, parse_mobile_spell_detail)
from vantage.parsers.market import GearItem, GreenMarket


class _FakeGameCapture:
    def status(self):
        return {
            "enabled": True, "available": True, "title": "EverQuest",
            "message": "Local read-only view.", "fps": 5,
            "interactive": False,
        }

    def frame(self):
        return self.status(), b"\xff\xd8vantage-test\xff\xd9"


class _WaitingGameCapture(_FakeGameCapture):
    def frame(self):
        status = self.status()
        status["available"] = False
        status["message"] = "WinEQ2 detected · bring EverQuest to the foreground to continue."
        return status, b""


class _PersistentGameCapture:
    def __init__(self, executable="", fps=5, profile="hd"):
        self.executable = executable
        self.fps = fps
        self.profile = profile
        self.enabled = False

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)

    def status(self):
        return {
            "enabled": self.enabled, "available": False,
            "message": "Ready", "fps": self.fps,
        }


class _FakeMdnsAdvertisement:
    def __init__(self, host_id="", address="", port=0):
        self.host_id = host_id
        self.address = address
        self.port = port
        self.updates = []
        self.closed = False

    def update(self, address):
        self.address = address
        self.updates.append(address)

    def close(self):
        self.closed = True


def _fake_advertisement(host_id, address, port):
    return _FakeMdnsAdvertisement(host_id, address, port)


def _snapshot():
    return {
        "version": 2,
        "timer_zone": "South Karana",
        "timer_zones": ["", "South Karana"],
        "timers": [{"timer_id": "quillmane-id", "name": "Quillmane",
                    "zone": "South Karana", "remaining": "12:34"}],
        "market": {
            "source": "PigParse API · Green",
            "items": (
                {"name": "Jade Mace", "type": 0, "price": 5000,
                 "posts": 12, "quality": "High", "classes": 512,
                 "races": 4096, "slots": 8192, "era": "kunark",
                 "nodrop": False, "stats": {"ac": 15, "wis": 5},
                 "effects": [{"type": "Proc", "name": "Light Strike"}]},
                {"name": "Golden Efreeti Boots", "type": 1, "price": 4500,
                 "posts": 5, "quality": "Medium", "classes": 8192,
                 "races": 1, "slots": 524288},
            ),
        },
        "buffs": {
            "character": "Mindflux", "server": "Green",
            "camp_state": "", "timers": [{
                "key": "you|clarity", "name": "Clarity II", "target": "You",
                "remaining": "12:34", "remaining_seconds": 754,
                "progress": 72, "color": "#477B91", "detrimental": False,
            }],
        },
        "guild": {
            "guild": "Castle", "slug": "castle", "connected": True,
            "authenticated": False, "loading": False,
            "profiles": [
                {"name": "Castle", "slug": "castle"},
                {"name": "Azure Guard", "slug": "azure-guard"}],
            "status": "Public data ready",
            "standings": [{"name": "Mindflux", "class": "Enchanter",
                            "level": "60", "rank": "Raider", "dkp": "125.0"}],
            "loot": [{"date": "Sep 09, 2026", "item": "Crown of Rile",
                      "character": "Mindflux", "dkp": "80.0", "raid": "Tormax",
                      "wiki_url": "https://wiki.project1999.com/Crown_of_Rile"}],
            "raids": [], "auctions": [], "sheets": [],
        },
        "zones": {
            "selected": "west commonlands", "loading": False,
            "status": "West Commonlands · updated now",
            "zones": ({"name": "West Commonlands",
                       "value": "west commonlands"},),
            "data": {"name": "West Commonlands",
                     "unique_items": ["Dragoon Dirk"],
                     "mobs": [{"name": "Kizdean Gix", "named": True,
                               "level": "18", "loot": "Dragoon Dirk"}]},
        },
        "quests": {
            "loading": False, "status": "1 quest · cached",
            "catalog": ("Jboots",), "pending": "",
            "current": {"title": "Jboots", "summary": "Get the boots.",
                        "steps": [{"text": "Hail Hasten Bootstrutter"}],
                        "wiki_url": "https://wiki.project1999.com/Jboots"},
            "checklist": {"title": "Jboots", "checked": []},
        },
    }


def _request(base, path, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with urlopen(Request(base + path, headers=headers), timeout=3) as response:
        return response.status, response.read(), dict(response.headers)


def _post(base, path, token, data):
    payload = json.dumps(data).encode("utf-8")
    request = Request(
        base + path, data=payload, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    with urlopen(request, timeout=3) as response:
        return response.status, json.loads(response.read())


def test_mobile_page_accessibility_updates_preserve_the_private_session():
    assert 'id="skipLink"' in _MOBILE_PAGE
    assert "skipLink.addEventListener('click'" in _MOBILE_PAGE
    assert "event.preventDefault();mainContent.focus" in _MOBILE_PAGE
    assert 'id="timerStatus"' in _MOBILE_PAGE
    assert "let timerStates=new Map()" in _MOBILE_PAGE
    assert "announce(gameState" in _MOBILE_PAGE
    assert "gameShell.setAttribute('aria-busy'" not in _MOBILE_PAGE
    assert '<span id="state">Connecting…</span>' in _MOBILE_PAGE
    assert '<img class="mark" src="/icon.png"' in _MOBILE_PAGE
    assert '<span class="mark"' not in _MOBILE_PAGE
    assert 'id="connectionStatus"' in _MOBILE_PAGE
    assert 'id="tabSpells"' in _MOBILE_PAGE
    assert 'id="tabBuffs"' in _MOBILE_PAGE
    assert 'id="tabGuild"' in _MOBILE_PAGE
    assert 'id="guildSelect"' in _MOBILE_PAGE
    assert 'id="tabZones"' in _MOBILE_PAGE
    assert 'id="zoneReload"' in _MOBILE_PAGE
    assert 'id="tabQuests"' in _MOBILE_PAGE
    assert 'id="installApp"' in _MOBILE_PAGE
    assert "Save Vantage to your Home Screen" in _MOBILE_PAGE
    assert "vantageMobileSessionToken" in _MOBILE_PAGE
    assert "history.replaceState" not in _MOBILE_PAGE
    assert "vantageMobilePairingV1" in _MOBILE_PAGE
    assert 'rel="manifest" href="/manifest.webmanifest"' in _MOBILE_PAGE
    assert "navigator.serviceWorker.register('/sw.js'" in _MOBILE_PAGE
    assert "Showing saved data while Vantage reconnects" in _MOBILE_PAGE
    assert "OFFLINE · SAVED" in _MOBILE_PAGE
    assert 'role="status" aria-live="polite"' in _MOBILE_PAGE
    assert "function announceConnectionPolitely" in _MOBILE_PAGE
    assert "8000-(Date.now()-lastPoliteConnectionAt)" in _MOBILE_PAGE
    assert "if(actionRequired)" in _MOBILE_PAGE
    assert "No saved Vantage link exists" in _MOBILE_PAGE
    assert "This saved Vantage link no longer exists" in _MOBILE_PAGE
    assert (
        "setConnection('RECONNECTING · SAVED',true,'Vantage is closed" in
        _MOBILE_PAGE)
    assert (
        "setConnection('OFFLINE · SAVED',true,'Connection lost."
        " Showing saved data while Vantage reconnects. If its private"
        " address changed, scan the new QR.',true" not in _MOBILE_PAGE)
    assert "syncGuildOptions(guildData)" in _MOBILE_PAGE
    assert "pendingZone||data.selected" in _MOBILE_PAGE
    assert "function stableReplace" in _MOBILE_PAGE
    assert "contains(document.activeElement)" in _MOBILE_PAGE
    assert 'aria-describedby="buffNote"' in _MOBILE_PAGE
    assert "function createBuffRow" in _MOBILE_PAGE
    assert "function updateBuffRow" in _MOBILE_PAGE
    assert "buffRosterSignature" in _MOBILE_PAGE
    assert "nextRoster.set(key,{name,descriptor})" in _MOBILE_PAGE
    assert "if(buffRoster!==null&&rosterSignature!==buffRosterSignature)" in (
        _MOBILE_PAGE)
    assert "value.name+' added.'" in _MOBILE_PAGE
    assert "value.name+' ended.'" in _MOBILE_PAGE
    assert "buffRoot.replaceChildren" not in _MOBILE_PAGE
    assert "Search included and cached P99 quests" in _MOBILE_PAGE
    assert "live Wiki mobs, drops, and nameds are temporarily unavailable" in _MOBILE_PAGE
    assert "RELOAD SELECTED ZONE" in _MOBILE_PAGE
    assert 'id="zoomLock"' in _MOBILE_PAGE
    assert "vantageZoomLock" in _MOBILE_PAGE
    assert "maximum-scale=5,user-scalable=yes" in _MOBILE_PAGE
    assert "maximum-scale=1,user-scalable=no" not in _MOBILE_PAGE
    assert "touches.length>1" in _MOBILE_PAGE
    assert "gameShell.addEventListener('touchmove'" in _MOBILE_PAGE
    assert "document.addEventListener('touchmove'" not in _MOBILE_PAGE
    assert "'gesturestart','gesturechange','gestureend'" in _MOBILE_PAGE
    assert "for(let level=1;level<=60" not in _MOBILE_PAGE
    assert "syncSpellLevels(data.available_levels)" in _MOBILE_PAGE
    assert "/api/spell-detail?name=" in _MOBILE_PAGE
    assert 'id="mt"' not in _MOBILE_PAGE
    assert ">Listing<" not in _MOBILE_PAGE
    assert "/api/timers/action" in _MOBILE_PAGE
    assert "toggleAction+' '+name+' timer'" in _MOBILE_PAGE
    assert "in a new tab" in _MOBILE_PAGE


def test_mobile_smart_timers_render_generic_modes_and_restart_semantics():
    assert '<h2 class="panel-title">Smart timers</h2>' in _MOBILE_PAGE
    assert "function timerMode(t)" in _MOBILE_PAGE
    assert "pn==='available'?'DONE'" in _MOBILE_PAGE
    assert "pn==='available'?'READY'" in _MOBILE_PAGE
    assert "return'Start again'" in _MOBILE_PAGE
    assert "mode==='countdown'?'COUNTDOWN':'REUSABLE COOLDOWN'" in \
        _MOBILE_PAGE
    assert "'duration '+String(t.duration||'--:--')" in _MOBILE_PAGE
    assert "previous.running!==running&&!completed" in _MOBILE_PAGE


def test_mobile_pwa_shell_routes_are_cacheable_without_caching_private_api():
    server = _ShareHTTPServer(("127.0.0.1", 0), "secret-token", _snapshot)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, manifest_payload, manifest_headers = _request(
            base, "/manifest.webmanifest")
        manifest = json.loads(manifest_payload)
        assert manifest["name"] == "Vantage P99 Companion"
        assert manifest["display"] == "standalone"
        assert "start_url" not in manifest
        assert "token" not in manifest_payload.decode("utf-8").casefold()
        assert manifest_headers["Content-Type"].startswith(
            "application/manifest+json")
        assert manifest_headers["Cache-Control"] == "no-cache"

        _, worker, worker_headers = _request(base, "/sw.js")
        worker_text = worker.decode("utf-8")
        assert "vantage-mobile-shell-v1" in worker_text
        assert "request.mode==='navigate'" in worker_text
        assert "url.pathname.startsWith('/api/')" in worker_text
        assert "Authorization" not in worker_text
        assert worker_headers["Service-Worker-Allowed"] == "/"
        assert worker_headers["Cache-Control"] == "no-cache"

        _, _, page_headers = _request(base, "/")
        csp = page_headers["Content-Security-Policy"]
        assert "worker-src 'self'" in csp
        assert "manifest-src 'self'" in csp

        _, _, api_headers = _request(base, "/api/state", "secret-token")
        assert api_headers["Cache-Control"] == "no-store, max-age=0"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_mobile_page_restores_cached_data_and_retains_it_on_fetch_failure():
    assert "const savedState=readCached('/api/state')" in _MOBILE_PAGE
    assert "drawTimers(savedState.data)" in _MOBILE_PAGE
    assert "writeCached(path,data)" in _MOBILE_PAGE
    assert "while(index.length>=24)" in _MOBILE_PAGE
    assert "function retainOrExplain" in _MOBILE_PAGE
    assert "Showing the last saved data." in _MOBILE_PAGE
    assert "window.addEventListener('online'" in _MOBILE_PAGE
    assert "window.addEventListener('offline'" in _MOBILE_PAGE
    assert "showListMessage(buffRoot,'Buff timers could not be loaded.')" not in (
        _MOBILE_PAGE)
    assert "render(cached.data,{cached:true,savedAt:" in _MOBILE_PAGE
    assert "function savedBuffAge" in _MOBILE_PAGE
    assert "' · SAVED · '+savedBuffAge" in _MOBILE_PAGE
    assert "reconnecting for current timers" in _MOBILE_PAGE
    assert "saved buff data remains visible" in _MOBILE_PAGE


def test_mobile_config_defaults_and_validates_persistent_session_settings():
    original = config.data
    try:
        config.data = {}
        config.verify_settings()
        assert config.data["mobile"]["game_enabled"] is True
        assert config.data["mobile"]["auto_start"] is False
        assert config.data["mobile"]["preferred_port"] == 8765
        assert config.data["mobile"]["lan_token"] == ""
        assert config.data["mobile"]["host_id"] == ""

        config.data["mobile"] = {
            "game_enabled": False, "auto_start": "yes",
            "preferred_port": 80, "lan_token": "unsafe-token",
            "host_id": "NOT-A-HOST-ID",
        }
        config.verify_settings()
        assert config.data["mobile"]["game_enabled"] is False
        assert config.data["mobile"]["auto_start"] is False
        assert config.data["mobile"]["preferred_port"] == 8765
        assert config.data["mobile"]["lan_token"] == ""
        assert config.data["mobile"]["host_id"] == ""

        config.data["mobile"].update({
            "lan_token": "L" * 43, "host_id": "0123456789"})
        config.verify_settings()
        assert config.data["mobile"]["lan_token"] == "L" * 43
        assert config.data["mobile"]["host_id"] == "0123456789"
    finally:
        config.data = original


def test_mdns_advertises_stable_http_host_without_pairing_secret(monkeypatch):
    created = []

    class FakeServiceInfo:
        def __init__(self, service_type, name, **values):
            self.type = service_type
            self.name = name
            self.__dict__.update(values)

    class FakeZeroconf:
        def __init__(self, **values):
            self.values = values
            self.registered = []
            self.updated = []
            self.unregistered = []
            self.closed = False
            created.append(self)

        def register_service(self, info):
            self.registered.append(info)

        def update_service(self, info):
            self.updated.append(info)

        def unregister_service(self, info):
            self.unregistered.append(info)

        def close(self):
            self.closed = True

    fake_module = SimpleNamespace(
        IPVersion=SimpleNamespace(V4Only="v4"),
        ServiceInfo=FakeServiceInfo, Zeroconf=FakeZeroconf)
    monkeypatch.setitem(sys.modules, "zeroconf", fake_module)

    registration = mobile_share_module._advertise_mobile_host(
        "0123456789", "192.168.1.7", 8765)

    assert registration is not None
    info = created[0].registered[0]
    assert info.type == "_http._tcp.local."
    assert info.server == "vantage-0123456789.local."
    assert info.port == 8765
    assert info.addresses == [socket.inet_aton("192.168.1.7")]
    assert info.properties == {}
    assert "pair" not in repr(info.__dict__).casefold()
    registration.update("192.168.1.8")
    assert created[0].updated[0].addresses == [
        socket.inet_aton("192.168.1.8")]
    assert created[0].updated[0].server == info.server
    registration.close()
    assert created[0].closed is True


def test_mdns_registration_failure_closes_backend_and_uses_safe_fallback(
        monkeypatch):
    instances = []

    class FakeServiceInfo:
        def __init__(self, *_args, **values):
            self.__dict__.update(values)

    class FailingZeroconf:
        def __init__(self, **_values):
            self.closed = False
            instances.append(self)

        def register_service(self, _info):
            raise OSError("multicast unavailable")

        def close(self):
            self.closed = True

    monkeypatch.setitem(sys.modules, "zeroconf", SimpleNamespace(
        IPVersion=SimpleNamespace(V4Only="v4"),
        ServiceInfo=FakeServiceInfo, Zeroconf=FailingZeroconf))

    assert mobile_share_module._advertise_mobile_host(
        "0123456789", "192.168.1.7", 8765) is None
    assert instances[0].closed is True
    assert mobile_share_module._advertise_mobile_host(
        "unsafe", "192.168.1.7", 8765) is None
    instance_count = len(instances)
    for unsafe_address in ("127.0.0.1", "0.0.0.0", "224.0.0.251"):
        assert mobile_share_module._advertise_mobile_host(
            "0123456789", unsafe_address, 8765) is None
    assert len(instances) == instance_count


def test_mobile_controller_rejects_loopback_mdns_and_uses_ip_fallback(
        monkeypatch):
    app = QApplication.instance() or QApplication([])
    original = config.data
    try:
        config.data = {"mobile": {
            "game_enabled": True, "auto_start": False,
            "preferred_port": 8765, "lan_token": "F" * 43,
            "host_id": "9999999999",
        }}
        monkeypatch.setattr(
            mobile_share_module, "GameWindowCapture", _PersistentGameCapture)
        monkeypatch.setattr(config, "save", lambda: None)
        monkeypatch.setattr(
            mobile_share_module, "_lan_address", lambda: "127.0.0.1")
        controller = MobileShareController(_snapshot)
        controller._preferred_port = 0
        controller.start()

        assert controller.local_url == controller.ip_fallback_url
        assert urlsplit(controller.local_url).hostname == "127.0.0.1"
        assert controller.host_url.startswith(
            "http://vantage-9999999999.local:")
        controller.shutdown()
        controller._snapshot_timer.stop()
        assert app is not None
    finally:
        config.data = original


def test_mobile_controller_reuses_lan_session_and_preserves_choices_on_shutdown(
        monkeypatch):
    app = QApplication.instance() or QApplication([])
    original = config.data
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    preferred_port = probe.getsockname()[1]
    probe.close()
    token = "A" * 43
    saves = []
    try:
        config.data = {"mobile": {
            "game_enabled": False, "auto_start": False,
            "preferred_port": preferred_port, "lan_token": token,
            "host_id": "0123456789",
        }}
        monkeypatch.setattr(
            mobile_share_module, "GameWindowCapture", _PersistentGameCapture)
        monkeypatch.setattr(config, "save", lambda: saves.append(True))
        monkeypatch.setattr(
            mobile_share_module, "_advertise_mobile_host",
            _fake_advertisement)

        first = MobileShareController(_snapshot)
        assert first.game_capture.enabled is False
        first.set_game_enabled(True)
        assert config.data["mobile"]["game_enabled"] is True
        first.start()
        first_url = urlsplit(first.local_url)
        assert first_url.hostname == "vantage-0123456789.local"
        assert first_url.port == preferred_port
        assert first_url.fragment == token
        assert urlsplit(first.ip_fallback_url).port == preferred_port
        assert config.data["mobile"]["auto_start"] is True
        first.shutdown()
        assert config.data["mobile"]["auto_start"] is True
        assert first.game_capture.enabled is True
        first._snapshot_timer.stop()

        second = MobileShareController(_snapshot)
        second.start()
        second_url = urlsplit(second.local_url)
        assert second_url.hostname == "vantage-0123456789.local"
        assert second_url.port == preferred_port
        assert second_url.fragment == token
        second.stop()
        assert config.data["mobile"]["auto_start"] is False
        assert config.data["mobile"]["lan_token"] == token
        assert config.data["mobile"]["host_id"] == "0123456789"
        assert second.game_capture.enabled is True
        second._snapshot_timer.stop()
        assert len(saves) >= 4
        assert app is not None
    finally:
        config.data = original


def test_saved_home_screen_link_reconnects_after_companion_shutdown_and_reopen(
        monkeypatch):
    app = QApplication.instance() or QApplication([])
    original = config.data
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    preferred_port = probe.getsockname()[1]
    probe.close()
    token = "R" * 43
    try:
        config.data = {"mobile": {
            "game_enabled": True, "auto_start": True,
            "preferred_port": preferred_port, "lan_token": token,
            "host_id": "abcdef0123",
        }}
        monkeypatch.setattr(
            mobile_share_module, "GameWindowCapture", _PersistentGameCapture)
        monkeypatch.setattr(config, "save", lambda: None)
        monkeypatch.setattr(
            mobile_share_module, "_advertise_mobile_host",
            _fake_advertisement)

        first = MobileShareController(_snapshot)
        first.start()
        old_url = urlsplit(first.local_url)
        first_fallback = urlsplit(first.ip_fallback_url)
        _, before, _ = _request(
            f"http://127.0.0.1:{first_fallback.port}", "/api/state", token)
        assert json.loads(before)["version"] == 2
        first.shutdown()
        first._snapshot_timer.stop()
        assert config.data["mobile"]["auto_start"] is True

        # The saved Home Screen origin/hash can retry the same host, port and
        # private token after Vantage opens again; no replacement QR is needed.
        second = MobileShareController(_snapshot)
        second.start()
        reopened = urlsplit(second.local_url)
        assert reopened.port == old_url.port == preferred_port
        assert reopened.fragment == old_url.fragment == token
        _, after, _ = _request(
            f"http://127.0.0.1:{urlsplit(second.ip_fallback_url).port}",
            "/api/state", token)
        assert json.loads(after)["version"] == 2
        second.shutdown()
        second._snapshot_timer.stop()
        assert app is not None
    finally:
        config.data = original


def test_mobile_controller_falls_back_when_saved_port_is_busy(monkeypatch):
    app = QApplication.instance() or QApplication([])
    original = config.data
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("0.0.0.0", 0))
    occupied.listen(1)
    busy_port = occupied.getsockname()[1]
    statuses = []
    try:
        config.data = {"mobile": {
            "game_enabled": True, "auto_start": True,
            "preferred_port": busy_port, "lan_token": "B" * 43,
            "host_id": "fedcba9876",
        }}
        monkeypatch.setattr(
            mobile_share_module, "GameWindowCapture", _PersistentGameCapture)
        monkeypatch.setattr(config, "save", lambda: None)
        monkeypatch.setattr(
            mobile_share_module, "_advertise_mobile_host",
            _fake_advertisement)
        controller = MobileShareController(_snapshot)
        controller.status_changed.connect(statuses.append)
        controller.start()
        assert urlsplit(controller.local_url).port != busy_port
        assert config.data["mobile"]["preferred_port"] == urlsplit(
            controller.local_url).port
        assert any("saved port was busy" in status for status in statuses)
        controller.shutdown()
        assert config.data["mobile"]["auto_start"] is True
        controller._snapshot_timer.stop()
        assert app is not None
    finally:
        occupied.close()
        config.data = original


def test_mobile_host_keeps_stable_name_and_refreshes_ip_fallback(monkeypatch):
    app = QApplication.instance() or QApplication([])
    original = config.data
    addresses = ["192.168.10.4"]
    advertisements = []
    try:
        config.data = {"mobile": {
            "game_enabled": True, "auto_start": False,
            "preferred_port": 0, "lan_token": "I" * 43,
            "host_id": "1111111111",
        }}
        monkeypatch.setattr(
            mobile_share_module, "GameWindowCapture", _PersistentGameCapture)
        monkeypatch.setattr(config, "save", lambda: None)
        monkeypatch.setattr(
            mobile_share_module, "_lan_address", lambda: addresses[0])

        def advertise(host_id, address, port):
            result = _FakeMdnsAdvertisement(host_id, address, port)
            advertisements.append(result)
            return result

        monkeypatch.setattr(
            mobile_share_module, "_advertise_mobile_host", advertise)
        controller = MobileShareController(_snapshot)
        controller._preferred_port = 0
        controller.start()
        original_host_link = controller.local_url
        original_fallback = controller.ip_fallback_url

        addresses[0] = "192.168.10.9"
        controller._refresh_network_address()

        assert controller.local_url == original_host_link
        assert controller.host_url == original_host_link
        assert controller.ip_fallback_url != original_fallback
        assert urlsplit(controller.ip_fallback_url).hostname == "192.168.10.9"
        assert advertisements[0].updates == ["192.168.10.9"]
        controller.shutdown()
        controller._snapshot_timer.stop()
        assert app is not None
    finally:
        config.data = original


def test_mdns_update_and_reregister_failure_switches_qr_to_ip_fallback(
        monkeypatch):
    app = QApplication.instance() or QApplication([])
    original = config.data
    addresses = ["192.168.20.4"]
    registration = _FakeMdnsAdvertisement()
    registration.update = lambda _address: False
    advertisements = []
    links = []
    try:
        config.data = {"mobile": {
            "game_enabled": True, "auto_start": True,
            "preferred_port": 8765, "lan_token": "U" * 43,
            "host_id": "4444444444",
        }}
        monkeypatch.setattr(
            mobile_share_module, "GameWindowCapture", _PersistentGameCapture)
        monkeypatch.setattr(config, "save", lambda: None)
        monkeypatch.setattr(
            mobile_share_module, "_lan_address", lambda: addresses[0])

        def advertise(*args):
            advertisements.append(args)
            return registration if len(advertisements) == 1 else None

        monkeypatch.setattr(
            mobile_share_module, "_advertise_mobile_host", advertise)
        controller = MobileShareController(_snapshot)
        controller._preferred_port = 0
        controller.link_changed.connect(
            lambda link, is_host: links.append((link, is_host)))
        controller.start()
        assert urlsplit(controller.local_url).hostname == (
            "vantage-4444444444.local")

        addresses[0] = "192.168.20.9"
        controller._refresh_network_address()

        assert registration.closed is True
        assert len(advertisements) == 2
        assert advertisements[1][1] == "192.168.20.9"
        assert controller._mdns is None
        assert controller.local_url == controller.ip_fallback_url
        assert urlsplit(controller.local_url).hostname == "192.168.20.9"
        assert links[-1] == (controller.ip_fallback_url, False)
        controller.shutdown()
        controller._snapshot_timer.stop()
        assert app is not None
    finally:
        config.data = original


def test_installed_cloudflared_is_never_started_or_used(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    original = config.data
    (tmp_path / "cloudflared.exe").write_bytes(b"installed but unused")
    try:
        config.data = {"mobile": {
            "game_enabled": True, "auto_start": False,
            "preferred_port": 8765, "lan_token": "C" * 43,
            "host_id": "2222222222",
        }}
        monkeypatch.setattr(
            mobile_share_module, "GameWindowCapture", _PersistentGameCapture)
        monkeypatch.setattr(config, "save", lambda: None)
        monkeypatch.setattr(
            mobile_share_module, "data_dir", lambda *_parts: tmp_path)
        monkeypatch.setattr(
            mobile_share_module, "_advertise_mobile_host",
            _fake_advertisement)
        controller = MobileShareController(_snapshot)
        controller._preferred_port = 0
        controller.start()

        assert controller.active is True
        assert controller.local_url.startswith(
            "http://vantage-2222222222.local:")
        assert not hasattr(controller, "_process")
        assert "trycloudflare" not in controller.local_url
        controller.shutdown()
        controller._snapshot_timer.stop()
        assert app is not None
    finally:
        config.data = original


def test_regenerate_pairing_key_revokes_old_link_and_restarts_same_host(
        monkeypatch):
    app = QApplication.instance() or QApplication([])
    original = config.data
    try:
        config.data = {"mobile": {
            "game_enabled": True, "auto_start": True,
            "preferred_port": 8765, "lan_token": "O" * 43,
            "host_id": "3333333333",
        }}
        monkeypatch.setattr(
            mobile_share_module, "GameWindowCapture", _PersistentGameCapture)
        monkeypatch.setattr(config, "save", lambda: None)
        monkeypatch.setattr(
            mobile_share_module, "_advertise_mobile_host",
            _fake_advertisement)
        controller = MobileShareController(_snapshot)
        controller._preferred_port = 0
        controller.start()
        old_token = "O" * 43
        old_url = urlsplit(controller.local_url)
        old_port = old_url.port
        _, payload, _ = _request(
            f"http://127.0.0.1:{old_port}", "/api/state", old_token)
        assert json.loads(payload)["version"] == 2

        controller.regenerate_pairing_key()

        new_url = urlsplit(controller.local_url)
        new_token = new_url.fragment
        assert new_token != old_token
        assert new_url.hostname == old_url.hostname
        assert new_url.port == old_port
        assert controller.host_id == "3333333333"
        assert config.data["mobile"]["auto_start"] is True
        try:
            _request(
                f"http://127.0.0.1:{old_port}", "/api/state", old_token)
            assert False, "the old pairing key must be revoked immediately"
        except HTTPError as error:
            assert error.code == 403
        _, payload, _ = _request(
            f"http://127.0.0.1:{old_port}", "/api/state", new_token)
        assert json.loads(payload)["version"] == 2
        controller.shutdown()
        assert config.data["mobile"]["auto_start"] is True
        controller._snapshot_timer.stop()
        assert app is not None
    finally:
        config.data = original


def test_application_mobile_autostart_invokes_the_saved_controller():
    from vantage.helpers.application import VantageApp

    calls = []
    controller = SimpleNamespace(start=lambda: calls.append("start"))
    host = SimpleNamespace(
        _mobile_share_instance=controller,
        _ensure_mobile_share=lambda: calls.append("ensure"))
    VantageApp._auto_start_mobile_share(host)
    assert calls == ["ensure", "start"]


def test_mobile_dialog_is_local_persistent_accessible_and_has_no_remote_controls(
        monkeypatch):
    app = QApplication.instance() or QApplication([])
    controller = MobileShareController(_snapshot)
    dialog = MobileShareDialog(controller)
    labels = " ".join(
        label.text() for label in dialog.scaled_surface.findChildren(QLabel))
    buttons = [
        button.text() for button in
        dialog.scaled_surface.findChildren(QPushButton)]
    live_setup_labels = " ".join(
        label.text() for label in
        dialog._live_setup.scaled_surface.findChildren(QLabel))

    assert app is not None
    assert dialog.windowTitle() == "Vantage Mobile Host"
    assert dialog.toggle.text() == "Start Mobile Host"
    assert "Copy Host Link" in buttons
    assert "Copy IP Fallback" in buttons
    assert "Regenerate Pairing Key…" in buttons
    assert "TIMERS · BUFFS · MARKET · SPELLS · GUILD · ZONES · QUESTS" in labels
    assert "same Wi-Fi" in labels
    assert "Vantage tray" in labels
    assert "starts with Vantage" in labels
    assert "Copy IP Fallback" in labels
    assert "Private networks in Windows Firewall" in labels
    assert "temporary external link" not in labels
    assert "Every tab uses the local same-Wi-Fi Mobile Host" in (
        live_setup_labels)
    assert "temporary external link" not in live_setup_labels
    assert "CLOUDFLARE" not in (labels + " " + " ".join(buttons)).upper()
    assert "REMOTE" not in " ".join(buttons).upper()
    assert dialog.qr.accessibleName() == "Mobile Host pairing QR code"
    assert "generate the private" in dialog.qr.accessibleDescription()
    assert dialog.status.accessibleName() == "Mobile Host status"
    assert dialog.copy_host.accessibleName() == "Copy Host Link"
    assert dialog.copy_ip.accessibleName() == "Copy IP Fallback"
    assert dialog.rotate.accessibleName() == "Regenerate Pairing Key"
    assert not dialog.connection_help.isHidden()
    assert dialog.connection_help.accessibleName() == (
        "Mobile Host connection help")
    assert "Windows Firewall" in (
        dialog.connection_help.accessibleDescription())
    rotations = []
    monkeypatch.setattr(
        controller, "regenerate_pairing_key", lambda: rotations.append(True))
    confirmation = {}

    def reject_regeneration(*args):
        confirmation["default"] = args[4]
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", reject_regeneration)
    dialog._confirm_regenerate()
    assert rotations == []
    assert confirmation["default"] == QMessageBox.StandardButton.No
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    dialog._confirm_regenerate()
    assert rotations == [True]

    assert dialog.toggle.accessibleName() == "Start Mobile Host"
    assert "Start Mobile Host" in dialog.qr.toolTip()
    assert "Start Mobile Host to generate" in (
        dialog.qr.accessibleDescription())
    dialog._set_running(True)
    dialog._set_link(
        "http://vantage-0123456789.local:8765/#" + "A" * 43, True)
    assert dialog.toggle.accessibleName() == "Stop Mobile Host"
    assert "stable local host" in dialog.qr.toolTip()
    assert "stable local host" in dialog.qr.accessibleDescription()
    dialog._set_link("", False)
    dialog._set_running(False)
    assert dialog.toggle.accessibleName() == "Start Mobile Host"
    assert "Start Mobile Host" in dialog.qr.toolTip()
    assert "stopped; start it" in dialog.qr.accessibleDescription()

    controller._snapshot_timer.stop()
    dialog.close()


def test_mobile_page_protects_state_and_filters_pigparse():
    server = _ShareHTTPServer(("127.0.0.1", 0), "secret-token", _snapshot)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, page, headers = _request(base, "/")
        assert status == 200
        assert b"PIGPARSE MARKET" in page
        assert b"EVERQUEST LIVE" in page
        assert b"READ ONLY" in page
        assert headers["Referrer-Policy"] == "no-referrer"

        icon_status, icon, icon_headers = _request(base, "/icon.png")
        assert icon_status == 200
        assert icon.startswith(b"\x89PNG\r\n\x1a\n")
        assert icon_headers["Content-Type"] == "image/png"

        try:
            _request(base, "/api/state", "wrong-token")
            assert False, "invalid token should be rejected"
        except HTTPError as error:
            assert error.code == 403

        _, payload, _ = _request(base, "/api/state", "secret-token")
        state = json.loads(payload)
        assert state["timers"][0]["name"] == "Quillmane"
        assert state["timer_zone"] == "South Karana"
        assert state["timer_zones"] == ["", "South Karana"]
        assert "items" not in state["market"]

        _, payload, _ = _request(
            base, "/api/market?q=jade&class=512&race=4096&slot=8192",
            "secret-token")
        market = json.loads(payload)
        assert market["total"] == 1
        assert market["items"][0]["name"] == "Jade Mace"
        assert market["items"][0]["stats"]["ac"] == 15
        assert market["source"] == "PigParse API · Green"
        assert market["server"] == "Green"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_mobile_market_source_follows_pc_selected_blue_server():
    def blue_snapshot():
        data = _snapshot()
        data["market"]["server"] = "Blue"
        # The mobile endpoint must derive a matching fallback rather than
        # retaining an old Green source label.
        data["market"].pop("source", None)
        return data

    server = _ShareHTTPServer(
        ("127.0.0.1", 0), "secret", blue_snapshot)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, state_payload, _ = _request(base, "/api/state", "secret")
        state = json.loads(state_payload)
        assert state["market"] == {
            "server": "Blue", "source": "PigParse API · Blue",
            "revision": 0}

        _, market_payload, _ = _request(base, "/api/market", "secret")
        market = json.loads(market_payload)
        assert market["server"] == "Blue"
        assert market["source"] == "PigParse API · Blue"
        assert "marketHeading.textContent='PIGPARSE '+server.toUpperCase()" in (
            _MOBILE_PAGE)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_mobile_market_filters_effect_drop_era_and_sorts_stats():
    server = _ShareHTTPServer(("127.0.0.1", 0), "secret", _snapshot)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, payload, _ = _request(
            base,
            "/api/market?q=light&effect=proc&drop=drop&era=kunark&sort=ac",
            "secret")
        market = json.loads(payload)
        assert market["total"] == 1
        assert market["items"][0]["name"] == "Jade Mace"
        assert market["items"][0]["effects"][0]["name"] == "Light Strike"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_mobile_item_detail_fetches_once_and_reuses_bounded_cache(
        monkeypatch, tmp_path):
    wiki = """
{{Itembox
| itemname = Jade Mace
| statsblock = MAGIC ITEM LORE ITEM<br>Slot: PRIMARY<br>AC: 9<br>DMG: 9<br>Delay: 22<br>
Effect: [[Light Strike]] (Combat)
| dropsfrom = West Commonlands
* [[Kizdean Gix]]
| relatedquests = [[Test Quest]]
| notes = A useful weapon.
}}
"""
    payload = json.dumps({
        "parse": {"wikitext": {"*": wiki}}}).encode("utf-8")
    calls = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, limit):
            assert limit == mobile_share_module.MAX_WIKI_RESPONSE + 1
            return payload

    monkeypatch.setattr(
        mobile_share_module, "_mobile_item_detail_path",
        lambda name: tmp_path / "jade-mace.json")
    monkeypatch.setattr(
        mobile_share_module, "urlopen",
        lambda request, timeout: calls.append(request.full_url) or _Response())
    item = {
        "name": "Jade Mace", "price": 5000, "posts": 12,
        "stats": {"ac": 15}, "class_names": ("Shaman",),
        "race_names": ("Iksar",), "slot_names": ("Primary",),
        "gear_id": 101, "peq_id": 202,
    }

    first = load_mobile_item_detail(item)
    monkeypatch.setattr(
        mobile_share_module, "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cache should prevent a second request")))
    second = load_mobile_item_detail(item)

    assert len(calls) == 1
    assert first["status"] == "complete"
    assert first["stats"]["ac"] == 15
    assert first["stats"]["dmg"] == 9
    assert first["stats"]["dly"] == 22
    assert "MAGIC ITEM" in first["stats_text"]
    assert first["restrictions"]["classes"] == ["Shaman"]
    assert first["effects"][0]["name"] == "Light Strike"
    assert first["drops"][0]["npc"] == "Kizdean Gix"
    assert first["related_quests"][0]["name"] == "Test Quest"
    assert first["notes"] == "A useful weapon."
    assert first["ids"] == {"market": "", "item": 101, "peq": 202}
    assert second["drops"] == first["drops"]


def test_market_mobile_snapshot_includes_readable_restrictions_and_ids():
    gear = GearItem(
        name="Jade Mace", id=101, peqId=202, classes=512,
        races=4096, slots=8192, ac=15, procName="Light Strike")
    host = SimpleNamespace(
        _proxy=SimpleNamespace(gear={"jade mace": gear}),
        _model=SimpleNamespace(items=[{
            "n": "Jade Mace", "a30": 5000, "t30": 12,
            "l": "today", "i": "market-1",
        }]),
        _mobile_items=(), _mobile_revision=0)

    GreenMarket._rebuild_mobile_items(host)

    item = host._mobile_items[0]
    assert item["class_names"] == ("Shaman",)
    assert item["race_names"] == ("Iksar",)
    assert item["slot_names"] == ("Primary",)
    assert item["gear_id"] == 101
    assert item["peq_id"] == 202


def test_mobile_item_detail_endpoint_is_authenticated_allowlisted_and_falls_back(
        monkeypatch):
    calls = []

    def load_detail(item):
        calls.append(item["name"])
        return {
            "status": "complete", "name": item["name"],
            "stats": {"ac": 15}, "stats_text": "MAGIC ITEM",
            "effects": [{"type": "Proc", "name": "Light Strike",
                         "url": "https://wiki.project1999.com/Light_Strike"}],
            "restrictions": {"binding": "Droppable", "era": "Kunark",
                             "classes": ["Shaman"], "races": ["Iksar"],
                             "slots": ["Primary"]},
            "ids": {"market": "1", "item": 2, "peq": 3},
            "drops": [{"npc": "Kizdean Gix", "zone": "West Commonlands",
                       "npc_url": "https://wiki.project1999.com/Kizdean_Gix",
                       "zone_url": "https://wiki.project1999.com/West_Commonlands"}],
            "related_quests": [{"name": "Test Quest",
                                "url": "https://wiki.project1999.com/Test_Quest"}],
            "notes": "Useful", "wiki_url": item.get("wiki_url", ""),
            "price": item.get("price", 0), "posts": item.get("posts", 0),
            "source": "Project 1999 Wiki",
        }

    monkeypatch.setattr(
        mobile_share_module, "load_mobile_item_detail", load_detail)
    server = _ShareHTTPServer(("127.0.0.1", 0), "secret", _snapshot)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        try:
            _request(base, "/api/item-detail?name=Jade%20Mace")
            assert False, "item detail must require the private token"
        except HTTPError as error:
            assert error.code == 403

        _, payload, _ = _request(
            base, "/api/item-detail?name=Jade%20Mace", "secret")
        detail = json.loads(payload)
        assert detail["drops"][0]["zone"] == "West Commonlands"
        assert detail["related_quests"][0]["name"] == "Test Quest"

        _, payload, _ = _request(
            base, "/api/item-detail?name=Dragoon%20Dirk", "secret")
        assert json.loads(payload)["name"] == "Dragoon Dirk"
        assert calls == ["Jade Mace", "Dragoon Dirk"]

        for path, code in (
                ("/api/item-detail?name=Unknown", 404),
                ("/api/item-detail?name=" + "x" * 161, 400),
                ("/api/item-detail?" + "x" * 513, 400)):
            try:
                _request(base, path, "secret")
                assert False, f"{path} should be rejected"
            except HTTPError as error:
                assert error.code == code
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_mobile_item_detail_ui_uses_safe_links_live_status_and_offline_fallback():
    assert "/api/item-detail?name=" in _MOBILE_PAGE
    assert "Loading complete Project 1999 Wiki item details" in _MOBILE_PAGE
    assert "Saved item data and the Wiki link remain available" in _MOBILE_PAGE
    assert "function safeWikiUrl" in _MOBILE_PAGE
    assert "url.hostname.toLowerCase()==='wiki.project1999.com'" in _MOBILE_PAGE
    assert "effect.url,effect.name" in _MOBILE_PAGE
    assert "drop.npc_url,drop.npc" in _MOBILE_PAGE
    assert "quest.url,quest.name" in _MOBILE_PAGE
    assert "detailReturnFocus" in _MOBILE_PAGE
    assert "byId('detailClose').focus" in _MOBILE_PAGE
    assert "detailDialog.addEventListener('close'" in _MOBILE_PAGE
    assert "tabs.find(tab=>tab.getAttribute('aria-selected')==='true')" in (
        _MOBILE_PAGE)
    assert 'id="detailStatus" class="sr-only" role="status"' in _MOBILE_PAGE
    assert 'aria-live="polite" aria-atomic="true"' in _MOBILE_PAGE
    assert "requestAnimationFrame(()=>announce(detailStatus" in _MOBILE_PAGE
    assert "dmg:'DMG',dly:'DLY'" in _MOBILE_PAGE
    assert "['dmg','dly'].includes(key)?String(value)" in _MOBILE_PAGE
    assert "label+'; opens in a new tab'" in _MOBILE_PAGE
    assert ".innerHTML" not in _MOBILE_PAGE
    assert "restarts this saved same-Wi-Fi Mobile Host automatically" in (
        _MOBILE_PAGE)
    assert "An explicit Stop Mobile Host keeps saved data" in _MOBILE_PAGE
    assert _safe_p99_url(
        "javascript:alert(1)", fallback_name="Jade Mace") == (
            "https://wiki.project1999.com/Jade_Mace")
    assert _safe_p99_url(
        "https://evil.example/?next=https://wiki.project1999.com/Jade_Mace",
        fallback_name="Jade Mace") == (
            "https://wiki.project1999.com/Jade_Mace")
    assert _safe_p99_url(
        "https://wiki.project1999.com:8443/Jade_Mace",
        fallback_name="Jade Mace") == (
            "https://wiki.project1999.com/Jade_Mace")


def test_mobile_timer_controls_require_wifi_key_and_queue_action():
    actions = []
    server = _ShareHTTPServer(
        ("127.0.0.1", 0), "public", _snapshot, None, "wifi",
        lambda action, target: actions.append((action, target)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        try:
            _post(base, "/api/timers/action", "public", {
                "action": "restart", "target": "quillmane-id"})
            assert False, "public tunnel must not mutate local timers"
        except HTTPError as error:
            assert error.code == 403
        status, response = _post(base, "/api/timers/action", "wifi", {
            "action": "restart", "target": "quillmane-id"})
        assert status == 202
        assert response == {"accepted": True}
        assert actions == [("restart", "quillmane-id")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_mobile_buffs_guild_zones_and_quests_are_private_and_browseable():
    actions = []
    server = _ShareHTTPServer(
        ("127.0.0.1", 0), "secret", _snapshot,
        browse_action=lambda action, target: actions.append((action, target)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, payload, _ = _request(base, "/api/buffs", "secret")
        assert json.loads(payload)["timers"][0]["name"] == "Clarity II"

        _, payload, _ = _request(base, "/api/guild", "secret")
        guild = json.loads(payload)
        assert guild["loot"][0]["item"] == "Crown of Rile"
        assert [row["slug"] for row in guild["profiles"]] == [
            "castle", "azure-guard"]

        _, payload, _ = _request(base, "/api/zones", "secret")
        assert json.loads(payload)["data"]["mobs"][0]["name"] == "Kizdean Gix"

        _, payload, _ = _request(base, "/api/quests?q=jbo", "secret")
        quests = json.loads(payload)
        assert quests["titles"] == ["Jboots"]
        assert quests["current"]["steps"][0]["text"].startswith("Hail")

        status, response = _post(base, "/api/browser/action", "secret", {
            "action": "guild", "target": "azure-guard"})
        assert status == 202 and response == {"accepted": True}
        status, response = _post(base, "/api/browser/action", "secret", {
            "action": "zone", "target": "west commonlands"})
        assert status == 202 and response == {"accepted": True}
        status, _ = _post(base, "/api/browser/action", "secret", {
            "action": "quest", "target": "Jboots"})
        assert status == 202
        assert actions == [
            ("guild", "azure-guard"),
            ("zone", "west commonlands"), ("quest", "Jboots")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_mobile_spell_tab_filters_class_level_and_adds_market_price():
    spells = ({
        "spell_id": 42, "name": "Clarity",
        "class_levels": (("Enchanter", 29),), "icon_id": 5,
        "effect_hint": "Improves mana regeneration.",
        "wiki_url": "https://wiki.project1999.com/Clarity",
    }, {
        "spell_id": 43, "name": "Torpor",
        "class_levels": (("Shaman", 60),), "icon_id": 6,
        "effect_hint": "Regenerates health while slowing movement.",
        "wiki_url": "https://wiki.project1999.com/Torpor",
    })

    def snapshot():
        data = _snapshot()
        data["market"]["items"] = tuple(data["market"]["items"]) + ({
            "name": "Spell: Torpor", "type": 0, "price": 50000,
            "posts": 9, "quality": "High"},)
        return data

    server = _ShareHTTPServer(
        ("127.0.0.1", 0), "secret", snapshot, spells=spells)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, payload, _ = _request(
            base, "/api/spells?q=tor&class=Shaman&level=60", "secret")
        result = json.loads(payload)
        assert result["total"] == 1
        assert result["items"][0]["name"] == "Torpor"
        assert result["items"][0]["selected_level"] == 60
        assert result["items"][0]["price"] == 50000
        assert result["items"][0]["effect_hint"].startswith("Regenerates")
        assert result["available_levels"] == [60]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_mobile_spell_detail_parser_exposes_description_and_slot_effects():
    detail = parse_mobile_spell_detail("""
{{Spellpage
| description = Surrounds your group in clarity, increasing mana regeneration.<br>Velious era.
| slots =
{{SpellSlotRow|1|Increase Mana by 10 per tick}}
{{SpellSlotRow|2|Decrease Movement Speed by 20%}}
| skill = Alteration
}}
""")

    assert "increasing mana regeneration" in detail["description"]
    assert detail["effects"] == [
        "Increase Mana by 10 per tick",
        "Decrease Movement Speed by 20%",
    ]
    assert detail["source"] == "Project 1999 Wiki"


def test_mobile_spell_detail_endpoint_uses_exact_known_spell(monkeypatch):
    spell = {
        "spell_id": 42, "name": "Clarity",
        "class_levels": (("Enchanter", 29),), "icon_id": 5,
        "effect_hint": "Improves mana regeneration.",
        "wiki_url": "https://wiki.project1999.com/Clarity",
    }
    monkeypatch.setattr(
        mobile_share_module, "load_mobile_spell_detail",
        lambda name: {
            "description": f"{name} exact description",
            "effects": ["Increase Mana by 10 per tick"],
            "source": "Project 1999 Wiki",
        })
    server = _ShareHTTPServer(
        ("127.0.0.1", 0), "secret", _snapshot, spells=(spell,))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, payload, _ = _request(
            base, "/api/spell-detail?name=Clarity", "secret")
        detail = json.loads(payload)
        assert detail["description"] == "Clarity exact description"
        assert detail["effects"] == ["Increase Mana by 10 per tick"]
        try:
            _request(base, "/api/spell-detail?name=Unknown", "secret")
            assert False, "unknown spell names must not trigger Wiki fetches"
        except HTTPError as error:
            assert error.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_game_view_requires_the_separate_lan_token():
    capture = _FakeGameCapture()
    server = _ShareHTTPServer(
        ("127.0.0.1", 0), "public-token", _snapshot,
        capture, "wifi-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        try:
            _request(base, "/api/game/status", "public-token")
            assert False, "public tunnel token must not expose the game view"
        except HTTPError as error:
            assert error.code == 403

        _, payload, _ = _request(base, "/api/game/status", "wifi-token")
        assert json.loads(payload)["interactive"] is False
        _, frame, headers = _request(base, "/api/game/frame", "wifi-token")
        assert frame.startswith(b"\xff\xd8")
        assert headers["Content-Type"] == "image/jpeg"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_game_frame_preserves_wineq_status_instead_of_generic_waiting_text():
    capture = _WaitingGameCapture()
    server = _ShareHTTPServer(
        ("127.0.0.1", 0), "public-token", _snapshot,
        capture, "wifi-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        try:
            _request(base, "/api/game/frame", "wifi-token")
            assert False, "unavailable frame should return a service status"
        except HTTPError as error:
            assert error.code == 503
            payload = json.loads(error.read())
            assert "WinEQ2 detected" in payload["message"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
