import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import vantage.helpers.mobile_share as mobile_share_module
from vantage.helpers.mobile_share import (
    _MOBILE_PAGE, _ShareHTTPServer, parse_mobile_spell_detail)


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


def test_mobile_page_accessibility_updates_preserve_the_session_fragment():
    assert 'id="skipLink"' in _MOBILE_PAGE
    assert "skipLink.addEventListener('click'" in _MOBILE_PAGE
    assert "event.preventDefault();mainContent.focus" in _MOBILE_PAGE
    assert 'id="timerStatus"' in _MOBILE_PAGE
    assert "let timerStates=new Map()" in _MOBILE_PAGE
    assert "announce(gameState" in _MOBILE_PAGE
    assert "gameShell.setAttribute('aria-busy'" not in _MOBILE_PAGE
    assert '<span id="state">Connecting…</span>' in _MOBILE_PAGE
    assert 'id="connectionStatus"' in _MOBILE_PAGE
    assert 'id="tabSpells"' in _MOBILE_PAGE
    assert 'id="zoomLock"' in _MOBILE_PAGE
    assert "vantageZoomLock" in _MOBILE_PAGE
    assert "maximum-scale=1,user-scalable=no" in _MOBILE_PAGE
    assert "touches.length>1" in _MOBILE_PAGE
    assert "document.addEventListener('touchmove'" in _MOBILE_PAGE
    assert "'gesturestart','gesturechange','gestureend'" in _MOBILE_PAGE
    assert "for(let level=1;level<=60" not in _MOBILE_PAGE
    assert "syncSpellLevels(data.available_levels)" in _MOBILE_PAGE
    assert "/api/spell-detail?name=" in _MOBILE_PAGE
    assert 'id="mt"' not in _MOBILE_PAGE
    assert ">Listing<" not in _MOBILE_PAGE
    assert "/api/timers/action" in _MOBILE_PAGE
    assert "Pause or resume this timer" in _MOBILE_PAGE


def test_mobile_page_protects_state_and_filters_pigparse():
    server = _ShareHTTPServer(("127.0.0.1", 0), "secret-token", _snapshot)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, page, headers = _request(base, "/")
        assert status == 200
        assert b"PIGPARSE GREEN" in page
        assert b"EVERQUEST LIVE" in page
        assert b"READ ONLY" in page
        assert headers["Referrer-Policy"] == "no-referrer"

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
