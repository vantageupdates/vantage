import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication

from vantage.helpers.responsive import ResponsiveActionBar
from vantage.parsers import market
from vantage.parsers.market import (
    GreenMarket, P99_RECHARGE_GUIDE_URL, WikiItemCard, _allowed_source_url,
    item_origin_corroboration, parse_zam_item_html,
    parse_zam_search_html, parse_wiki_item_wikitext)


def test_item_recharge_guide_opens_only_the_exact_p99_help_url(monkeypatch):
    opened = []
    monkeypatch.setattr(market.webbrowser, "open", opened.append)

    assert GreenMarket._open_recharge_guide() is False
    assert opened == [P99_RECHARGE_GUIDE_URL]
    assert P99_RECHARGE_GUIDE_URL == (
        "https://wiki.project1999.com/Guide_to_Recharging_Items")

    monkeypatch.setattr(
        market, "_wiki_target_url", lambda _title: "https://evil.example/help")
    assert GreenMarket._open_recharge_guide() is False
    assert opened == [P99_RECHARGE_GUIDE_URL]


def test_zam_search_requires_an_exact_normalized_name_and_allowlisted_url():
    source = """
      <a href='/db/item.html?item=1'>Fabled Journeyman's Boots</a>
      <a href='https://evil.example/db/item.html?item=2'>Journeyman's Boots</a>
      <a href='/db/item.html?item=3'>Journeyman&#39;s Boots</a>
    """

    match = parse_zam_search_html(source, "Journeyman’s Boots")

    assert match["name"] == "Journeyman's Boots"
    assert match["url"] == (
        "https://everquest.allakhazam.com/db/item.html?item=3")
    assert not parse_zam_search_html(
        "<a href='/db/item.html?item=1'>Fabled Journeyman's Boots</a>",
        "Journeyman's Boots")


@pytest.mark.parametrize("url", [
    "http://everquest.allakhazam.com/db/item.html?item=1",
    "https://evil.example/db/item.html?item=1",
    "https://everquest.allakhazam.com.evil.example/db/item.html?item=1",
    "https://user:pass@everquest.allakhazam.com/db/item.html?item=1",
    "https://everquest.allakhazam.com/comments.html",
])
def test_allakhazam_url_allowlist_rejects_unsafe_targets(url):
    assert _allowed_source_url(url, ("/db/item.html",)) == ""


def test_zam_detail_extracts_only_structured_metadata_not_comments_or_markup():
    source = """
      <title>Journeyman's Boots :: Items :: EverQuest :: ZAM</title>
      <table><tr><td><a href='/db/npc.html?id=7'>Drelzna</a></td>
      <td><a href='/db/zone.html?zone=44'>Najena</a></td></tr></table>
      <section><a href='/db/quest.html?quest=8'>Journeyman's Boots Quest</a></section>
      <div class='user-comments'><a href='/db/npc.html?id=666'>Fake &lt;b&gt;Mob</a>
      <script>alert(1)</script></div>
    """

    data = parse_zam_item_html(source, "Journeyman’s Boots")

    assert [entry["name"] for entry in data["mobs"]] == ["Drelzna"]
    assert [entry["name"] for entry in data["zones"]] == ["Najena"]
    assert [entry["name"] for entry in data["quests"]] == [
        "Journeyman's Boots Quest"]
    assert data["drops"][0]["mob"]["name"] == "Drelzna"
    assert "Fake" not in repr(data)
    assert "script" not in repr(data)


@pytest.mark.parametrize(("p99", "zam", "expected"), [
    ({"drops": [{"npc": "Drelzna", "zone": "Najena"}]},
     {"drops": [{"mob": {"name": "Drelzna"},
                  "zone": {"name": "Najena"}}]}, "Confirmed by both"),
    ({"related_quests": [{"name": "Boots Quest"}]},
     {"quests": [{"name": "Boots Quest"}]}, "Confirmed by both"),
    ({"drops": [{"npc": "Drelzna", "zone": "Najena"}]},
     {"drops": [{"mob": {"name": "Ancient Cyclops"},
                  "zone": {"name": "Ocean of Tears"}}]}, "Sources disagree"),
    ({"notes": "Quest reward."}, {}, "P99-only"),
    ({}, {"mobs": [{"name": "Drelzna"}]}, "ZAM-only"),
    ({}, {}, "No source data"),
])
def test_item_origin_corroboration_uses_exact_structured_intersections(
        p99, zam, expected):
    assert item_origin_corroboration(p99, zam) == expected


def test_p99_item_parser_keeps_related_quests_and_notes():
    data = parse_wiki_item_wikitext("""{{Itempage
      |itemname=Journeyman's Boots
      |relatedquests=* [[Journeyman's Boots Quest|JBoots Quest]]
      |notes=The classic quest version is usable on Project 1999.
    }}""")

    assert data["related_quests"][0]["name"] == "JBoots Quest"
    assert data["related_quests"][0]["target"] == (
        "Journeyman's Boots Quest")
    assert data["related_quests"][0]["url"].startswith(
        "https://wiki.project1999.com/")
    assert "classic quest" in data["notes"]


def test_item_card_keeps_sources_safe_compact_and_keyboard_accessible():
    app = QApplication.instance() or QApplication([])
    card = WikiItemCard({"n": "Journeyman's Boots"})
    card.set_item_data({
        "name": "Journeyman's Boots", "stats": "MAGIC ITEM",
        "drops": [{"npc": "<img src=x onerror=bad>", "zone": "Najena"}],
        "related_quests": [{"name": "<script>bad()</script>",
                            "target": "Boots Quest"}],
        "notes": "<b>Not trusted HTML</b>",
    })
    card.set_zam_error("blocked")
    app.processEvents()

    rendered = card.drops.text()
    assert "&lt;img" in rendered and "&lt;script&gt;" in rendered
    assert "<script>" not in rendered and "onerror=bad>" not in rendered
    assert "P99 applies to this server" in rendered
    assert card.drops.focusPolicy().name == "StrongFocus"
    assert card.scaled_surface.findChild(ResponsiveActionBar) is not None
    assert card.source_retry_button.isEnabled()
    assert card.source_retry_button.toolTip()
    card.close()


class _Timer:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class _Reply:
    def __init__(self, error, payload=b"", error_text="blocked"):
        self._error = error
        self._payload = payload
        self._error_text = error_text
        self.deleted = False

    def error(self):
        return self._error

    def errorString(self):
        return self._error_text

    def readAll(self):
        return self._payload

    def deleteLater(self):
        self.deleted = True


class _Card:
    wiki_name = "Journeyman's Boots"
    _source_request_token = 2
    _zam_origin = {"mobs": [{"name": "cached"}]}
    _p99_origin = {"notes": "cached P99"}

    def __init__(self):
        self.errors = []
        self.data = []

    def set_zam_error(self, message, cached=False, token=None):
        self.errors.append((message, cached, token))

    def set_zam_data(self, data, cached=False, token=None):
        self.data.append((data, cached, token))

    def set_p99_error(self, message, cached=False, token=None):
        self.errors.append((message, cached, token))


def _network_host(reply, *, token=2, attempt=0, timed_out=False,
                  phase="search", tmp_path=Path("unused")):
    card = _Card()
    context = {
        "timer": _Timer(), "timed_out": timed_out,
        "url": "https://everquest.allakhazam.com/search.html?q=boots",
        "card": card, "token": token, "cache": tmp_path,
        "phase": phase, "attempt": attempt,
        "detail_url": "https://everquest.allakhazam.com/db/item.html?item=3",
    }
    host = SimpleNamespace(_zam_inflight={reply: context}, requested=[])
    host._zam_request = lambda *args: host.requested.append(args)
    return host, card, context


def test_zam_timeout_retries_once_then_keeps_cached_p99_fallback(monkeypatch):
    monkeypatch.setattr(market.QTimer, "singleShot", lambda _delay, call: call())
    first = _Reply(QNetworkReply.NetworkError.OperationCanceledError)
    host, card, context = _network_host(first, timed_out=True)

    GreenMarket._zam_finished(host, first)

    assert len(host.requested) == 1
    assert host.requested[0][5] == 1
    assert not card.errors
    assert context["timer"].stopped and first.deleted

    last = _Reply(QNetworkReply.NetworkError.OperationCanceledError)
    host, card, _context = _network_host(last, timed_out=True, attempt=1)
    GreenMarket._zam_finished(host, last)
    assert card.errors == [("Timed out", True, 2)]
    assert last.deleted


def test_stale_zam_reply_cannot_replace_newer_item_card_state():
    reply = _Reply(QNetworkReply.NetworkError.NoError, b"irrelevant")
    host, card, _context = _network_host(reply, token=1)

    GreenMarket._zam_finished(host, reply)

    assert not card.data and not card.errors and not host.requested
    assert reply.deleted


def test_card_announces_one_current_combined_source_result(monkeypatch):
    app = QApplication.instance() or QApplication([])
    announcements = []
    monkeypatch.setattr(
        market, "_announce_accessible",
        lambda _owner, message: announcements.append(message))
    card = WikiItemCard({"n": "Journeyman's Boots"})
    card.begin_source_request(4)
    card.set_zam_data(
        {"item_name": card.wiki_name, "mobs": [{"name": "Cached mob"}]},
        cached=True, token=4)
    card.set_item_data({
        "name": card.wiki_name, "stats": "MAGIC ITEM",
        "drops": [{"npc": "Drelzna", "zone": "Najena"}]}, token=4)
    assert announcements == [
        "Checking P99 and Allakhazam sources for Journeyman's Boots"]

    card.set_zam_error("Timed out", cached=True, token=4)
    assert len(announcements) == 2
    assert announcements[-1].startswith("Item source research complete.")
    assert "Cached fallback: ZAM" in announcements[-1]

    # A duplicate or stale completion cannot announce another confidence.
    card.set_zam_error("late duplicate", cached=True, token=4)
    current_origin = dict(card._zam_origin)
    card.set_zam_data({"mobs": [{"name": "stale"}]}, token=3)
    assert len(announcements) == 2
    assert card._zam_origin == current_origin
    app.processEvents()
    card.close()


def test_card_waits_for_both_authoritative_sources_before_confidence(monkeypatch):
    app = QApplication.instance() or QApplication([])
    announcements = []
    monkeypatch.setattr(
        market, "_announce_accessible",
        lambda _owner, message: announcements.append(message))
    card = WikiItemCard({"n": "Journeyman's Boots"})
    card.begin_source_request(8)
    card.set_zam_data({
        "drops": [{"mob": {"name": "Drelzna"},
                   "zone": {"name": "Najena"}}],
        "mobs": [{"name": "Drelzna"}], "zones": [{"name": "Najena"}],
    }, token=8)
    assert len(announcements) == 1
    assert "Checking sources" in card.drops.text()

    card.set_item_data({
        "name": card.wiki_name, "stats": "MAGIC ITEM",
        "drops": [{"npc": "Drelzna", "zone": "Najena"}]}, token=8)
    assert announcements[-1] == (
        "Item source research complete. Confirmed by both")
    assert "Confirmed by both" in card.drops.text()
    app.processEvents()
    card.close()


def test_p99_timeout_retries_once_then_reports_cached_fallback(monkeypatch,
                                                               tmp_path):
    monkeypatch.setattr(market.QTimer, "singleShot", lambda _delay, call: call())
    first = _Reply(QNetworkReply.NetworkError.OperationCanceledError)
    card = _Card()
    timer = _Timer()
    context = {
        "timer": timer, "timed_out": True, "card": card, "token": 2,
        "json_path": tmp_path / "item.json",
        "icon_path": tmp_path / "icon.png", "wiki_name": card.wiki_name,
        "attempt": 0}
    host = SimpleNamespace(
        _p99_item_inflight={first: context}, requested=[])
    host._p99_item_request = lambda *args: host.requested.append(args)

    GreenMarket._p99_item_request_finished(host, first)

    assert len(host.requested) == 1
    assert host.requested[0][-1] == 1
    assert timer.stopped and first.deleted

    last = _Reply(QNetworkReply.NetworkError.OperationCanceledError)
    context = dict(context, timer=_Timer(), attempt=1)
    host._p99_item_inflight = {last: context}
    GreenMarket._p99_item_request_finished(host, last)
    assert card.errors == [("Timed out", True, 2)]
    assert last.deleted


def test_retry_cancels_prior_p99_and_zam_requests():
    class AbortReply:
        def __init__(self):
            self.aborted = 0
        def abort(self):
            self.aborted += 1

    card = _Card()
    other = _Card()
    p99, zam, untouched = AbortReply(), AbortReply(), AbortReply()
    host = SimpleNamespace(
        _p99_item_inflight={p99: {"card": card}, untouched: {"card": other}},
        _zam_inflight={zam: {"card": card}})

    GreenMarket._cancel_item_source_replies(host, card)

    assert p99.aborted == 1 and zam.aborted == 1
    assert untouched.aborted == 0
