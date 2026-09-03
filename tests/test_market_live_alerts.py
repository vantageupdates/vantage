import datetime
from types import SimpleNamespace

from vantage.helpers import config
from vantage.parsers import market as market_module
from vantage.parsers.market import (
    GreenMarket, deliver_market_alert, live_auction_watch_matches)


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
