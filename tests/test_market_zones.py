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
from PySide6.QtTest import QTest
import vantage.parsers.zones as zones_module
from vantage.helpers.application import VantageApp

app = VantageApp([])
announcements = []
zones_module._announce_accessible = lambda _widget, text, **_kwargs: announcements.append(text)
market = app._parsers_dict['market']
market._refresh_timer.stop()
zones = app._parsers_dict['zones']
zones._set_zone_data({
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
zones.tabs.setCurrentIndex(0)
announcements.clear()
zones.zone_search.setText('crystal')
zones.zone_search.setText('crystal spider')
zones.zone_search.setText('crystal spider eyes')
app.processEvents()
announcements_before_debounce = len(announcements)
QTest.qWait(340)
filtered_items = zones.item_table.rowCount()
filter_announcements = len(announcements)
zones.zone_search.clear()
QTest.qWait(340)
zones.tabs.setCurrentIndex(2)
zones.named_table.selectRow(0)
app.processEvents()
auto_load_calls = []
zones._load_zone = lambda *_args, **kwargs: auto_load_calls.append((
    zones.zone_selector.currentData(), kwargs.get('announce'))) or True
zones._zone_selected(zones.zone_selector.currentIndex())
zones.parse(None, "You have entered Velketor's Labyrinth.")
bar = app._parsers_dict['quickbar']
bar._trigger('zones')
QTest.qWait(20)
selector_focused_on_open = zones.zone_selector.hasFocus()
bar._trigger('zones')
QTest.qWait(20)
launcher_focus_safe = (
    bar._buttons['zones'].hasFocus() or not bar.isActiveWindow())
print(json.dumps({
    'market_tabs': [market.tabs.tabText(i) for i in range(market.tabs.count())],
    'zone_tabs': [zones.tabs.tabText(i) for i in range(zones.tabs.count())],
    'selector_editable': zones.zone_selector.isEditable(),
    'filtered_items': filtered_items,
    'named_rows': zones.named_table.rowCount(),
    'selected': zones._selected_value()['name'],
    'drop': zones.zone_drop_selector.currentText(),
    'map_enabled': zones.zone_map_button.isEnabled(),
    'table_name': zones.named_table.accessibleName(),
    'search_tip': zones.zone_search.toolTip(),
    'quickbar_has_zones': 'zones' in app._parsers_dict['quickbar']._buttons,
    'selection_auto_loads': auto_load_calls[:1] == [
        ("velketor's labyrinth", True)],
    'explicit_and_log_announce_modes': auto_load_calls,
    'announcements_before_debounce': announcements_before_debounce,
    'filter_announcements': filter_announcements,
    'selector_focused_on_open': selector_focused_on_open,
    'launcher_focus_safe': launcher_focus_safe,
}))
app.quit()
"""


def test_independent_zone_window_filters_tabs_and_exposes_selected_drop(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", UI_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result == {
        "market_tabs": [
            "PigParse · prices", "Gear · stats", "WTS / WTB Builder",
            "Sale Alerts · 0"],
        "zone_tabs": ["Items", "Mobs", "Nameds"],
        "selector_editable": False,
        "filtered_items": 1,
        "named_rows": 1,
        "selected": "Crystal Eyes",
        "drop": "Crystal Spider Eyes",
        "map_enabled": True,
        "table_name": "Named NPCs in selected zone",
        "search_tip": (
            "Filter the loaded zone's mobs, nameds, item drops, and locations"),
        "quickbar_has_zones": True,
        "selection_auto_loads": True,
        "explicit_and_log_announce_modes": [
            ["velketor's labyrinth", True],
            ["velketor's labyrinth", False]],
        "announcements_before_debounce": 0,
        "filter_announcements": 1,
        "selector_focused_on_open": True,
        "launcher_focus_safe": True,
    }
