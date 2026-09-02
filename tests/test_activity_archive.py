import datetime

from vantage.helpers.activity_archive import ActivityArchive
from vantage.helpers.combat import CoinEvent, FactionEvent, LootEvent


def test_activity_archive_persists_and_deduplicates_log_events(tmp_path):
    path = tmp_path / 'activity.sqlite'
    stamp = datetime.datetime(2026, 8, 30, 11, 10, 0)
    loot = LootEvent(
        stamp, 'You', 'Crystalline Silk', 2, 'a crystal spider',
        "Velketor's Labyrinth", 'Mindflux', 'Green')
    coin = CoinEvent(
        stamp, '2 platinum and 5 gold', 2500, 'Corpse', '', '',
        "Velketor's Labyrinth", 'Mindflux', 'Green')
    faction = FactionEvent(
        stamp, 'Claws of Veeshan', '+5', "Velketor's Labyrinth", 5,
        'Mindflux', 'Green')

    first = ActivityArchive(path)
    assert first.available
    assert first.append_loot(loot, 'Mindflux', 'Green')
    assert not first.append_loot(loot, 'Mindflux', 'Green')
    assert first.append_coin(coin, 'Mindflux', 'Green')
    assert first.append_faction(faction, 'Mindflux', 'Green')
    first.close()

    restored = ActivityArchive(path)
    assert restored.recent_loot() == [(
        stamp, 'You', 'Crystalline Silk', 2, 'a crystal spider',
        "Velketor's Labyrinth", 'Mindflux', 'Green')]
    assert restored.recent_coins()[0][1:4] == (
        '2 platinum and 5 gold', 2500, 'Corpse')
    assert restored.recent_faction()[0][1:5] == (
        'Claws of Veeshan', '+5', "Velketor's Labyrinth", 5)
    restored.close()
