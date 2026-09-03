import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from vantage.helpers import config
from vantage.parsers import market as market_module
from vantage.parsers.market import (
    GreenMarket, deliver_market_alert, live_auction_watch_matches)


ROOT = Path(__file__).resolve().parents[1]


VISIBLE_WATCHLIST_SCRIPT = r"""
import json
from PySide6.QtWidgets import QListWidget
from vantage.helpers import config
from vantage.helpers.application import VantageApp

app = VantageApp([])
market = app._parsers_dict['market']
config.data['market']['live_watch_items'] = [
    'Manastone', 'Flowing Black Silk Sash', 'Journeyman\'s Boots']
market._refresh_live_watch_items('Flowing Black Silk Sash')
before = [
    market.live_watch_items.item(index).text()
    for index in range(market.live_watch_items.count())]
selected = market.live_watch_items.currentItem().text()
market._remove_live_watch()
after = [
    market.live_watch_items.item(index).text()
    for index in range(market.live_watch_items.count())]
print(json.dumps({
    'is_list': isinstance(market.live_watch_items, QListWidget),
    'before': before,
    'selected': selected,
    'after': after,
    'label': market.live_watch_label.text(),
    'accessible': market.live_watch_items.accessibleDescription(),
}))
app.quit()
"""


LIVE_SEARCH_SCRIPT = r"""
import datetime
import json

from vantage.helpers.application import VantageApp

app = VantageApp([])
market = app._parsers_dict['market']
market._refresh_timer.stop()
market.show()
app.processEvents()
initial_note = market.live_note.text()
stamp = datetime.datetime(2026, 9, 3, 20, 0, 0)
market.parse(stamp, "Trader auctions, 'WTS Manastone 90k PST'")
market.parse(stamp, "Mule auctions, 'WTS Flowing Black Silk Sash 10k PST'")

# The main item-catalog search must not hide the dedicated heard-auction log.
market.search.setText('item catalog query with no auction match')
app.processEvents()
rows_after_catalog_search = market._local_proxy.rowCount()

market.live_search.setText('manastone')
app.processEvents()
first_count = market.live_search_count.text()
first_rows = market._local_proxy.rowCount()

# A matching message arriving later appears immediately under the active filter.
market.parse(stamp, "Buyer auctions, 'WTB Manastone 80k PST'")
app.processEvents()
second_count = market.live_search_count.text()
second_rows = market._local_proxy.rowCount()
visible_messages = [
    market._local_proxy.index(row, 2).data()
    for row in range(market._local_proxy.rowCount())]

market.parse(stamp, 'You have entered Butcherblock Mountains.')
outside_note = market.live_note.text()
market.parse(stamp, 'You have entered East Commonlands.')
inside_note = market.live_note.text()
market._open_live_alerts()
app.processEvents()

print(json.dumps({
    'initial_note': initial_note,
    'outside_note': outside_note,
    'inside_note': inside_note,
    'rows_after_catalog_search': rows_after_catalog_search,
    'first_count': first_count,
    'first_rows': first_rows,
    'second_count': second_count,
    'second_rows': second_rows,
    'visible_messages': visible_messages,
    'search_name': market.live_search.accessibleName(),
    'search_description': market.live_search.accessibleDescription(),
    'search_tooltip': market.live_search.toolTip(),
    'table_description': market.live_table.accessibleDescription(),
    'current_tab': market.tabs.currentIndex(),
    'live_tab': market._live_tab_index,
    'search_focusable': market.live_search.focusPolicy() != 0,
}))
app.quit()
"""


class _Tray:
    def __init__(self, visible=True):
        self.visible = visible
        self.messages = []

    def isVisible(self):
        return self.visible

    def showMessage(self, title, message, icon, msecs):
        self.messages.append((title, message, icon, msecs))


class _AlertApp:
    def __init__(self, overlay_shown=False, tray=None):
        self.overlay_shown = overlay_shown
        self.overlay_calls = []
        self._system_tray = tray

    def show_overlay_notification(self, title, message, **kwargs):
        self.overlay_calls.append((title, message, kwargs))
        return self.overlay_shown


def test_live_log_watch_matches_sale_and_ignores_pure_wtb():
    watches = ["Manastone", "Flowing Black Silk Sash"]

    assert live_auction_watch_matches(
        "WTS Manastone 90k and Flowing Black Silk Sash 10k PST", watches
    ) == watches
    assert live_auction_watch_matches(
        "WTB Manastone 80k PST", watches) == []


def test_live_log_watch_handles_punctuation_and_mixed_macros():
    watches = ["Jboots"]

    assert live_auction_watch_matches(
        "WTB ports / WTS Jboots MQ - PST", watches) == ["Jboots"]


def test_sale_alert_delivery_has_one_clear_fallback_and_optional_sound(
        monkeypatch):
    tray = _Tray()
    app = _AlertApp(overlay_shown=False, tray=tray)
    played = []
    monkeypatch.setattr(
        market_module, "play_alert",
        lambda *args, **kwargs: played.append((args, kwargs)) or True)
    monkeypatch.setattr(market_module, "audio_muted", lambda: False)

    assert deliver_market_alert(
        app, "For sale · Manastone", "Trader · WTS Manastone",
        sound_enabled=False) == ("Windows notification shown", "sound off")
    assert len(tray.messages) == 1
    assert played == []

    app.overlay_shown = True
    assert deliver_market_alert(
        app, "For sale · Manastone", "Trader · WTS Manastone",
        sound_enabled=True) == ("overlay shown", "sound played")
    assert len(tray.messages) == 1
    assert len(played) == 1
    assert played[0][1]["allow_hidden"] is True


def test_sale_alert_watchlist_is_visible_and_removes_the_selected_row(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', VISIBLE_WATCHLIST_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result == {
        'is_list': True,
        'before': [
            'Manastone', 'Flowing Black Silk Sash', "Journeyman's Boots"],
        'selected': 'Flowing Black Silk Sash',
        'after': ['Manastone', "Journeyman's Boots"],
        'label': 'Watching (2)',
        'accessible': (
            "Visible list of every item monitored in this character's EQ log"),
    }


def test_heard_auction_search_is_live_independent_and_explicit_about_ec(
        tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', LIVE_SEARCH_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['rows_after_catalog_search'] == 2
    assert result['first_rows'] == 1
    assert result['first_count'] == 'Showing 1 of 2 heard auctions'
    assert result['second_rows'] == 2
    assert result['second_count'] == 'Showing 2 of 3 heard auctions'
    assert result['visible_messages'] == [
        'WTB Manastone 80k PST', 'WTS Manastone 90k PST']
    assert 'EC TUNNEL REQUIRED' in result['initial_note']
    assert 'during this Vantage session' in result['initial_note']
    assert 'Current zone: Butcherblock Mountains' in result['outside_note']
    assert 'EC TUNNEL READY' in result['inside_note']
    assert 'East Commonlands Tunnel' in result['search_name']
    assert 'current Vantage session' in result['search_description']
    assert 'results update as messages arrive' in result['search_tooltip']
    assert 'current Vantage session' in result['table_description']
    assert result['current_tab'] == result['live_tab']
    assert result['search_focusable'] is True


def test_live_log_alert_service_deduplicates_seller_spam_for_one_minute():
    previous = dict(config.data.get("market", {}))
    try:
        config.data["market"] = {
            "live_alerts_enabled": True,
            "live_watch_items": ["Manastone"],
        }
        service = SimpleNamespace(_live_alerted_at={})
        first = datetime.datetime(2026, 9, 2, 12, 0, 0)

        assert GreenMarket._notify_live_watches(
            service, first, "Trader", "WTS Manastone 90k") == ["Manastone"]
        assert GreenMarket._notify_live_watches(
            service, first + datetime.timedelta(seconds=30),
            "Trader", "WTS Manastone 90k") == []
        assert GreenMarket._notify_live_watches(
            service, first + datetime.timedelta(seconds=61),
            "Trader", "WTS Manastone 90k") == ["Manastone"]
        assert service._live_match_count == 2
        assert "Manastone" in service._last_live_alert
        assert "inline only" in service._last_live_alert
        assert "sound off" in service._last_live_alert
    finally:
        config.data["market"] = previous
