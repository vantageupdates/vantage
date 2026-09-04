import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.parsers.market import parse_wiki_zone_payload


ROOT = Path(__file__).resolve().parents[1]

ZONE_WIKITEXT = """
{{Velious Era}}
This is the ancient home and laboratory of the exiled Giant sorcerer Velketor.
{| class="zoneTopTable"
! ''' Level of Monsters: '''
| 45-60+
|-
! ''' Types of Monsters: '''
| Spiders, Kobolds, Golems
|-
! ''' Notable NPCs: '''
| [[Crystal Eyes]], [[Velketor the Sorcerer]]
|-
! ''' Unique Items: '''
| {{:Crystal Spider Eyes}}, [[Silver Chitin Hand Wraps]]
|}
== Map ==
[[Image:map_velketors_labyrinth.jpg|right|border]]
== What's in this zone? ==
{{Special:DynamicZoneList/Velketor's Labyrinth}}
"""

ZONE_HTML = """
<h2><span>What's in this zone?</span></h2>
<table class="eoTable3 sortable" style="width:100%;">
<tr><th>NPC Name</th><th>Race</th><th>Class</th><th>Level</th>
<th>Location</th><th>Known Loot</th><th>Description</th></tr>
<tr><td><a href="/A_crystalline_devourer">A crystalline devourer</a></td>
<td>Giant Spider</td><td><a href="/Rogue">Rogue</a></td><td>47</td>
<td>Many</td><td>Various</td><td>Backstabs.</td></tr>
<tr><td><a href="/Crystal_Eyes">Crystal Eyes</a></td>
<td>Giant Spider</td><td>Rogue</td><td>47</td><td>20% @ (479, 2)</td>
<td><div class="hbdiv"><a href="/Crystal_Spider_Eyes">Crystal Spider Eyes</a>
<span class="hb"><div>Crystal Spider Eyes AC: 8 Class: ALL</div></span></div>,
<a href="/Silver_Chitin_Hand_Wraps">Silver Chitin Hand Wraps</a></td>
<td>Named spider.</td></tr>
</table>
"""


def test_zone_wiki_payload_extracts_searchable_mobs_nameds_drops_and_map():
    zone = parse_wiki_zone_payload(
        ZONE_WIKITEXT, ZONE_HTML, "Velketor's Labyrinth")

    assert zone["name"] == "Velketor's Labyrinth"
    assert zone["era"] == "Velious"
    assert zone["levels"] == "45-60+"
    assert zone["types"] == "Spiders, Kobolds, Golems"
    assert zone["map_image"] == "map_velketors_labyrinth.jpg"
    assert zone["unique_items"] == [
        "Silver Chitin Hand Wraps", "Crystal Spider Eyes"]
    assert len(zone["mobs"]) == 2
    assert zone["mobs"][0]["named"] is False
    assert zone["mobs"][1]["name"] == "Crystal Eyes"
    assert zone["mobs"][1]["named"] is True
    assert zone["mobs"][1]["drops"] == [
        "Crystal Spider Eyes", "Silver Chitin Hand Wraps"]
    assert "AC: 8" not in zone["mobs"][1]["loot"]


UI_SCRIPT = r"""
import json
from vantage.helpers.application import VantageApp

app = VantageApp([])
market = app._parsers_dict['market']
market._refresh_timer.stop()
market._set_zone_data({
    'name': "Velketor's Labyrinth",
    'era': 'Velious',
    'levels': '45-60+',
    'types': 'Spiders and kobolds',
    'mobs': [
        {'name': 'A crystalline devourer', 'target': 'A_crystalline_devourer',
         'named': False, 'level': '47', 'class': 'Rogue',
         'race': 'Giant Spider', 'location': 'Many', 'drops': [],
         'loot': 'Various', 'description': 'Backstabs.'},
        {'name': 'Crystal Eyes', 'target': 'Crystal_Eyes', 'named': True,
         'level': '47', 'class': 'Rogue', 'race': 'Giant Spider',
         'location': '(479, 2)', 'drops': ['Crystal Spider Eyes'],
         'loot': 'Crystal Spider Eyes', 'description': 'Named spider.'},
    ],
})
market.zone_search.setText('crystal spider eyes')
app.processEvents()
filtered = market.zone_table.rowCount()
market.zone_search.clear()
market.zone_named_only.setChecked(True)
app.processEvents()
market.zone_table.selectRow(0)
app.processEvents()
print(json.dumps({
    'tab': market.tabs.tabText(market._zone_tab_index),
    'filtered': filtered,
    'named_rows': market.zone_table.rowCount(),
    'selected': market._selected_zone_mob()['name'],
    'drop': market.zone_drop_selector.currentText(),
    'map_enabled': market.zone_map_button.isEnabled(),
    'table_name': market.zone_table.accessibleName(),
    'search_tip': market.zone_search.toolTip(),
}))
app.quit()
"""


def test_zone_tab_filters_inside_zone_and_exposes_selected_drop(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", UI_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result == {
        "tab": "Zones",
        "filtered": 1,
        "named_rows": 1,
        "selected": "Crystal Eyes",
        "drop": "Crystal Spider Eyes",
        "map_enabled": True,
        "table_name": "Mobs in selected Project 1999 zone",
        "search_tip": (
            "Filter the loaded zone by NPC, level, class, race, location, "
            "drop, or notes"),
    }
