import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import datetime
import json

from vantage.helpers.application import VantageApp

app = VantageApp([])
combat = app._parsers_dict['combat']
combat._active_character = 'Mindflux'
combat._active_server = 'Green'
stamp = datetime.datetime(2026, 8, 30, 12, 0, 0)
for offset, line in enumerate((
        "You have entered Velketor's Labyrinth.",
        "--You have looted 2 Crystalline Silk from a crystal spider.--",
        "You receive 3 platinum, 5 gold, 7 silver and 9 copper from the corpse.",
        "You receive 1 platinum, 2 silver as your split.",
        "Your faction standing with Claws of Veeshan has been adjusted by 5.",
        "Your faction standing with Kromzek got worse.")):
    combat.parse(stamp + datetime.timedelta(seconds=offset), line)
combat._activity_signature = None
combat._refresh_activity()

result = {
    'loot_rows': combat.tables['Loot'].rowCount(),
    'coin_rows': combat.tables['Coin'].rowCount(),
    'faction_rows': combat.tables['Faction'].rowCount(),
    'loot_item': combat.tables['Loot'].item(0, 2).text(),
    'loot_qty': combat.tables['Loot'].item(0, 3).text(),
    'loot_source': combat.tables['Loot'].item(0, 4).text(),
    'loot_profile': combat.tables['Loot'].item(0, 6).text(),
    'coin_total': combat.loot_notice.text(),
    'profiles': [combat.loot_profile.itemText(index)
                 for index in range(combat.loot_profile.count())],
    'zones': [combat.loot_zone.itemText(index)
              for index in range(combat.loot_zone.count())],
    'control_tooltips': all(widget.toolTip().strip() for widget in (
        combat.loot_search, combat.loot_profile, combat.loot_zone,
        combat.faction_search, combat.faction_change,
        combat.faction_profile, combat.faction_zone,
        combat.loot_tabs)),
    'header_tooltips': all(
        combat.tables[name].horizontalHeaderItem(column).toolTip().strip()
        for name in ('Loot', 'Coin', 'Faction')
        for column in range(combat.tables[name].columnCount())),
}

combat.loot_search.setText('crystal spider')
result['filtered_loot_rows'] = combat.tables['Loot'].rowCount()
result['filtered_coin_rows'] = combat.tables['Coin'].rowCount()
combat.loot_search.clear()
combat.faction_change.setCurrentIndex(
    combat.faction_change.findData('gain'))
result['gain_rows'] = combat.tables['Faction'].rowCount()
result['gain_change'] = combat.tables['Faction'].item(0, 2).text()

print(json.dumps(result))
app.quit()
"""


def test_persistent_activity_views_filter_totals_and_tooltips(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        'loot_rows': 1,
        'coin_rows': 2,
        'faction_rows': 2,
        'loot_item': 'Crystalline Silk',
        'loot_qty': '2',
        'loot_source': 'a crystal spider',
        'loot_profile': 'Mindflux · Green',
        'coin_total': (
            'LOOT · 2 items · 2 coin events · 4p 5g 9s 9c · persistent'),
        'profiles': ['All profiles', 'Mindflux · Green'],
        'zones': ["All zones", "Velketor's Labyrinth"],
        'control_tooltips': True,
        'header_tooltips': True,
        'filtered_loot_rows': 1,
        'filtered_coin_rows': 0,
        'gain_rows': 1,
        'gain_change': '+5',
    }
