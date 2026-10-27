"""Wiki failures must never destroy a usable local reference."""

import json
from types import SimpleNamespace

from PySide6.QtNetwork import QNetworkReply
import pytest

import vantage.helpers.wiki_access as access
from vantage.parsers import market, quests, zones


class Reply:
    def __init__(self, payload, status=200, headers=None, properties=None):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.status = status
        self.headers = headers or {}
        self.properties = properties or {}
        self.deleted = False

    def readAll(self):
        payload, self.payload = self.payload, b""
        return payload

    def attribute(self, _attribute):
        return self.status

    def rawHeader(self, key):
        return self.headers.get(key, b"")

    def error(self):
        return (QNetworkReply.NetworkError.ContentAccessDenied if self.status >= 400
                else QNetworkReply.NetworkError.NoError)

    def errorString(self):
        return "HTTP error"

    def property(self, name):
        return self.properties.get(name)

    def deleteLater(self):
        self.deleted = True


class Control:
    def __init__(self):
        self.value = ""
        self.enabled = None

    def setText(self, value):
        self.value = value

    def text(self):
        return self.value

    def setAccessibleName(self, _value):
        pass

    def setEnabled(self, value):
        self.enabled = value

    def stop(self):
        pass


@pytest.fixture
def gate(monkeypatch):
    now = [100.0]
    gate = access.WikiAccess(clock=lambda: now[0])
    for module in (access, market, quests, zones):
        monkeypatch.setattr(module, "wiki_access", gate)
    for module in (market, quests, zones):
        monkeypatch.setattr(module, "_announce_accessible", lambda *_a, **_kw: None)
    gate.now = now
    return gate


@pytest.mark.parametrize("status,headers", [
    (403, {b"cf-mitigated": b"challenge"}), (200, {}),
])
def test_challenge_stops_requests_even_when_http_status_is_success(gate, status, headers):
    reply = Reply(b"<!DOCTYPE html><html><title>Just a moment...</title></html>",
                  status=status, headers=headers)
    with pytest.raises(ValueError, match="browser verification"):
        access.read_wiki_reply(reply, page=True)
    assert "5 min" in gate.status()
    gate.now[0] += 301
    assert not gate.status()


def test_retry_after_is_respected_and_repeated_failures_back_off(gate):
    with pytest.raises(ValueError, match="limiting"):
        access.read_wiki_reply(Reply({}, 429, {b"retry-after": b"900"}))
    assert "15 min" in gate.status()
    gate.now[0] += 901
    with pytest.raises(ValueError):
        access.read_wiki_reply(Reply({"error": {"code": "maxlag"}}))
    assert "2 min" in gate.status()


def test_success_does_not_clear_active_pause_but_resets_recovered_backoff(gate):
    gate.pause("Blocked", challenge=True)
    valid = {"parse": {"wikitext": {"*": "== Quest ==\n* Collect an item."}}}
    assert access.read_wiki_reply(Reply(valid), page=True) == valid
    assert "5 min" in gate.status()
    gate.now[0] += 301
    access.read_wiki_reply(Reply(valid), page=True)
    gate.pause("Blocked", challenge=True)
    assert "5 min" in gate.status()


def test_missing_rendered_zone_table_is_not_a_complete_refresh(gate):
    with pytest.raises(ValueError, match="incomplete page content"):
        access.read_wiki_reply(Reply({"parse": {
            "wikitext": {"*": "{{Zonepage}}"}, "text": {"*": ""}}}),
            page=True, rendered=True)


@pytest.mark.parametrize("payload", [
    {}, [], {"query": []}, {"error": {}}, {"parse": {}},
    {"parse": {"title": "Najena", "wikitext": {"*": " "}}},
    {"error": {"code": "missingtitle"}},
])
def test_invalid_or_empty_page_never_becomes_a_reference(gate, payload):
    with pytest.raises(ValueError):
        access.read_wiki_reply(Reply(payload), page=True)
    assert not gate.status()


def test_atomic_cache_write_preserves_old_data_when_replacement_fails(tmp_path, monkeypatch):
    target = tmp_path / "reference.json"
    assert access.write_wiki_cache(target, {"name": "Najena", "mobs": [{"name": "Drelzna"}]})
    original = target.read_bytes()
    cached = json.loads(original)
    assert cached["_wiki_cache"]["coverage"] == "on-demand reference"
    assert "UTC" in access.cached_reference_status(cached)

    def fail_replace(*_args):
        raise OSError("Locked cache")

    monkeypatch.setattr(access.os, "replace", fail_replace)
    assert not access.write_wiki_cache(target, {"name": "changed"})
    assert target.read_bytes() == original
    assert list(tmp_path.glob("*.part")) == []


def test_zone_empty_success_does_not_replace_saved_mobs(tmp_path, gate, monkeypatch):
    target = tmp_path / "zone.json"
    previous = {"name": "Najena", "mobs": [{"name": "Drelzna"}]}
    target.write_text(json.dumps(previous), encoding="utf-8")
    monkeypatch.setattr(zones, "_wiki_zone_cache_path", lambda _name: target)
    reply = Reply({"parse": {"title": "Najena", "wikitext": {"*": ""}}}, properties={
        "zoneRequested": "Najena", "zoneRequestId": 1,
        "zoneAttempt": zones.ZONE_NETWORK_RETRIES,
    })
    host = SimpleNamespace(
        sender=lambda: reply, _zone_reply=reply, _zone_request_id=1,
        _zone_data=previous, zone_summary=Control(), zone_load_button=Control())
    zones.Zones._zone_finished(host)
    assert json.loads(target.read_text("utf-8")) == previous
    assert host._zone_data == previous
    assert "temporarily unavailable" in host.zone_summary.text()
    assert host.zone_load_button.enabled and reply.deleted


def test_item_challenge_keeps_cache_and_does_not_retry(tmp_path, gate):
    target = tmp_path / "item.json"
    target.write_text('{"name":"Boots","stats":"AC: 5"}', encoding="utf-8")
    before = target.read_bytes()
    errors, requested = [], []
    reply = Reply(b"<html>Just a moment</html>", 403,
                  {b"cf-mitigated": b"challenge"})
    card = SimpleNamespace(_source_request_token=1, _p99_origin={"stats": "AC: 5"},
        set_p99_error=lambda *args: errors.append(args))
    context = {"timer": Control(), "card": card, "token": 1, "attempt": 0,
               "json_path": target, "icon_path": tmp_path / "icon.png",
               "wiki_name": "Boots", "timed_out": False}
    host = SimpleNamespace(_p99_item_inflight={reply: context},
                           _p99_item_request=lambda *args: requested.append(args))
    market.GreenMarket._p99_item_request_finished(host, reply)
    assert target.read_bytes() == before
    assert not requested
    assert "browser verification" in errors[0][0] and errors[0][1] is True
    # A different Wiki view respects the same pause before sending any request.
    host = SimpleNamespace(catalog_status=Control())
    quests.Quests._fetch_catalog(host, force=True)
    assert "offline quest catalog" in host.catalog_status.text()
    assert reply.deleted


@pytest.mark.parametrize("body", [b"<html>Just a moment</html>", b"invalid image"])
def test_invalid_icon_cannot_overwrite_saved_image(tmp_path, gate, body):
    target = tmp_path / "icon.png"
    target.write_bytes(b"previous valid image")
    reply = Reply(body)
    card = SimpleNamespace(set_icon_data=lambda _body: False)
    market.GreenMarket._wiki_icon_finished(reply, card, target)
    assert target.read_bytes() == b"previous valid image"
    assert reply.deleted


def test_partial_catalog_limit_retains_complete_offline_catalog(tmp_path, gate, monkeypatch):
    target = tmp_path / "catalog.json"
    before = {"version": 1, "titles": ["A Quest", "B Quest"]}
    target.write_text(json.dumps(before), encoding="utf-8")
    reply = Reply({"query": {"categorymembers": [{"title": "A Quest"}]},
                   "continue": {"cmcontinue": "more"}})
    monkeypatch.setattr(quests, "_announce_accessible", lambda *_a, **_kw: None)
    host = SimpleNamespace(_catalog_reply=reply, _catalog_generation=1,
        _catalog_watchdog=Control(), _catalog_seen=set(),
        _catalog_pages=quests.MAX_CATALOG_PAGES, _catalog_loading=True,
        _catalog=before["titles"], _catalog_cache_path=target,
        catalog_status=Control(), _dispose_reply=quests.Quests._dispose_reply)
    quests.Quests._catalog_page_finished(host, reply, 1)
    assert host._catalog == before["titles"]
    assert json.loads(target.read_text("utf-8")) == before
    assert "incomplete" in host.catalog_status.text()


def test_selecting_cached_quest_invalidates_an_older_live_request(tmp_path, gate):
    target = tmp_path / "quest.json"
    target.write_text(json.dumps({"title": "Saved Quest",
        "wikitext": "== Checklist ==\n* Obtain the saved quest item."}), encoding="utf-8")
    shown, notes = [], []
    old = Reply({"parse": {"title": "Old Quest", "wikitext": {"*": "old"}}})
    host = SimpleNamespace(_quest_generation=1, _quest_reply=old,
        _quest_cache_path=lambda _title: target, _show_quest=lambda quest: shown.append(quest),
        summary=SimpleNamespace(append=notes.append),
        _dispose_reply=quests.Quests._dispose_reply)
    host._cancel_quest_request = lambda: setattr(host, "_quest_reply", None)
    quests.Quests._load_quest(host, "Saved Quest")
    quests.Quests._quest_finished(host, old, 1)
    assert host._quest_generation == 2
    assert len(shown) == 1 and shown[0]["title"] == "Saved Quest"
    assert "freshness unverified" in notes[0]
    assert old.deleted
