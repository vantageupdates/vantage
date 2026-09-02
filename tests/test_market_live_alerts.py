import datetime
from types import SimpleNamespace

from vantage.helpers import config
from vantage.parsers.market import GreenMarket, live_auction_watch_matches


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
        assert "preserved here" in service._last_live_alert
    finally:
        config.data["market"] = previous
