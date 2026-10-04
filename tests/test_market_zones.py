import copy
import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers import config
from vantage.parsers.maps.mapdata import MapData
from vantage.parsers.market import (
    parse_wiki_entity_wikitext, parse_wiki_zone_payload)
from vantage.parsers.zones import parse_global_mob_pages


ROOT = Path(__file__).resolve().parents[1]


def test_bundled_zone_reference_covers_every_selectable_map_alias():
    payload = json.loads((
        ROOT / "data" / "reference" / "zone_catalog.json"
    ).read_text(encoding="utf-8"))
    bundled = {row["value"] for row in payload["zones"]}
    assert bundled == set(MapData.get_zone_dict())
    assert len(bundled) >= 120
    assert all(row["name"] and row["map"] for row in payload["zones"])


def test_zone_column_width_config_clamps_each_table_independently():
    original = copy.deepcopy(config.data)
    try:
        config.data = {"zones": {"column_widths": {
            "items": [-20, 5000],
            "mobs": [220, 65],
            "nameds": ["bad", 73, 84, 95, 315, 177],
            "all_mobs": [221, 66, 91, 106, 281, 221],
        }}}
        config.verify_settings()
        assert config.data["zones"]["column_widths"] == {
            "items": [38, 1200],
            "nameds": [220, 73, 84, 95, 315, 177],
            "all_mobs": [221, 66, 91, 106, 281, 221],
        }

        config.data = {"zones": ["damaged"]}
        config.verify_settings()
        assert config.data["zones"]["column_widths"] == {}
    finally:
        config.data = original


KEYBOARD_COLUMNS_SCRIPT = r"""
import json
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from vantage.helpers import config
from vantage.helpers.application import VantageApp
import vantage.parsers.zones as zones_module

announcements = []
zones_module._announce_accessible = (
    lambda _widget, text, **_kwargs: announcements.append(text))
app = VantageApp([])
zones = app._parsers_dict['zones']
zones.tabs.setCurrentIndex(0)
zones.item_table.setCurrentCell(0, 0)
original_width = zones.item_table.columnWidth(0)
zones.show()
zones.zone_columns_button.setFocus(Qt.FocusReason.TabFocusReason)
QTimer.singleShot(
    50, lambda: QTest.keyClick(zones.zone_columns_menu, Qt.Key.Key_W))
QTest.keyClick(zones.zone_columns_button, Qt.Key.Key_Space)
QTest.qWait(380)
print(json.dumps({
    'width': zones.item_table.columnWidth(0),
    'original': original_width,
    'announcement': announcements[-1],
    'persisted': config.data['zones']['column_widths']['items'][0],
    'button_tip': zones.zone_columns_button.toolTip(),
    'table_description': zones.item_table.accessibleDescription(),
    'tab_focusable': bool(zones.zone_columns_button.focusPolicy() &
                          Qt.FocusPolicy.TabFocus),
}))
app.quit()
"""


def test_zone_columns_menu_resizes_by_keyboard_and_persists(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", KEYBOARD_COLUMNS_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["width"] == result["original"] + 40
    assert result["persisted"] == result["width"]
    assert result["announcement"] == (
        f"Item column width {result['width']} pixels")
    assert "Alt+C" in result["button_tip"]
    assert "keyboard" in result["table_description"].lower()
    assert result["tab_focusable"] is True

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


def test_global_mob_pages_filters_items_and_keeps_clickable_relationships():
    npc_source = """{{Namedmobpage
| name = Crystal Eyes
| race = Giant Spider
| class = Rogue
| level = 47
| zone = [[Velketor's Labyrinth]]
| location = 20% @ (479, 2)
| known_loot = {{:Crystal Spider Eyes}}, [[Velium Crystal Staff]]
| relatedquests = [[The Lost Map]] and [[Coldain Prayer Shawl Quests|Prayer Shawl]]
}}"""
    item_source = """{{Itembox
| itemname = Crystal Spider Eyes
| statsblock = AC 8
}}"""
    payload = {"query": {"pages": {
        "10": {"title": "Crystal Spider Eyes", "revisions": [
            {"*": item_source}]},
        "11": {"title": "Crystal Eyes", "revisions": [
            {"*": npc_source}]},
    }}}

    results = parse_global_mob_pages(payload, "Crystal Eyes")

    assert len(results) == 1
    mob = results[0]
    assert mob["name"] == "Crystal Eyes"
    assert mob["named"] is True
    assert mob["location"] == (
        "Velketor's Labyrinth · 20% @ (479, 2)")
    assert mob["drops"] == ["Velium Crystal Staff", "Crystal Spider Eyes"]
    assert [quest["name"] for quest in mob["related_quests"]] == [
        "The Lost Map", "Prayer Shawl"]
    assert mob["_entity_loaded"] is True


def test_native_npc_parser_includes_every_related_quest():
    source = """{{Mobpage
| name = an escaped froglok
| relatedquests = [[Froglok Slave Quest]], [[The Missing Piece]]
}}"""

    entity = parse_wiki_entity_wikitext(source, "an escaped froglok", "npc")

    assert entity["related_quests"] == [
        {"name": "Froglok Slave Quest", "target": "Froglok Slave Quest",
         "url": "https://wiki.project1999.com/Froglok_Slave_Quest"},
        {"name": "The Missing Piece", "target": "The Missing Piece",
         "url": "https://wiki.project1999.com/The_Missing_Piece"},
    ]


UI_SCRIPT = r"""
import json
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolButton
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
selected_name = zones._selected_value()['name']
selected_drop = zones.zone_drop_selector.currentText()
map_enabled = zones.zone_map_button.isEnabled()
named_rows = zones.named_table.rowCount()
global_mob = {
    'name': 'Crystal Eyes', 'target': 'Crystal Eyes', 'named': True,
    'level': '47', 'class': 'Rogue', 'race': 'Giant Spider',
    'location': "Velketor's Labyrinth · (479, 2)",
    'drops': ['Crystal Spider Eyes', 'Velium Crystal Staff'],
    'loot': 'Crystal Spider Eyes, Velium Crystal Staff',
    'related_quests': [
        {'name': 'The Lost Map', 'target': 'The Lost Map'},
        {'name': 'Prayer Shawl', 'target': 'Coldain Prayer Shawl Quests'},
    ], '_entity_loaded': True,
}
zones._global_mob_results = [global_mob]
zones._fill_mobs(zones.all_mob_table, zones._global_mob_results)
zones.tabs.setCurrentIndex(3)
zones.all_mob_table.selectRow(0)
app.processEvents()
relation_html = zones.all_mob_relations.text()
relation_accessible = zones.all_mob_relations.accessibleName()
opened_items = []
opened_quests = []
market._show_wiki_item_name = lambda name: opened_items.append(name)
market._show_wiki_entity = (
    lambda target, label, kind: opened_quests.append((target, label, kind)))
zones.all_mob_relations.linkActivated.emit(
    'vantage://item/Crystal%20Spider%20Eyes')
zones.all_mob_relations.linkActivated.emit(
    'vantage://quest/Coldain%20Prayer%20Shawl%20Quests')
auto_load_calls = []
zones._load_zone = lambda *_args, **kwargs: auto_load_calls.append((
    zones.zone_selector.currentData(), kwargs.get('announce'))) or True
kael_index = next(
    index for index in range(zones.zone_selector.count())
    if zones.zone_selector.itemData(index) == 'kael drakkel')
zones.zone_selector.setCurrentIndex(kael_index)
zones.zone_selector.setCurrentIndex(kael_index)
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
    'named_rows': named_rows,
    'selected': selected_name,
    'drop': selected_drop,
    'map_enabled': map_enabled,
    'table_name': zones.named_table.accessibleName(),
    'search_tip': zones.zone_search.toolTip(),
    'all_mob_search_name': zones.all_mob_search.accessibleName(),
    'all_mob_search_description': zones.all_mob_search.accessibleDescription(),
    'all_mob_visible_help': zones.all_mob_search_status.text(),
    'relation_html': relation_html,
    'relation_accessible': relation_accessible,
    'relation_keyboard': bool(
        zones.all_mob_relations.textInteractionFlags() &
        Qt.TextInteractionFlag.LinksAccessibleByKeyboard),
    'all_mob_clear_name': zones.all_mob_search.findChild(
        QToolButton).accessibleName(),
    'opened_items': opened_items,
    'opened_quests': opened_quests,
    'quickbar_has_zones': 'zones' in app._parsers_dict['quickbar']._buttons,
    'selection_auto_loads_once': auto_load_calls[:1] == [
        ('kael drakkel', True)] and len(auto_load_calls) == 2,
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
        "zone_tabs": ["Items", "Mobs", "Nameds", "Any Mob"],
        "selector_editable": False,
        "filtered_items": 1,
        "named_rows": 1,
        "selected": "Crystal Eyes",
        "drop": "Crystal Spider Eyes",
        "map_enabled": True,
        "table_name": "Named NPCs in selected zone",
        "search_tip": (
            "Filter the loaded zone's mobs, nameds, item drops, and locations"),
        "all_mob_search_name": (
            "Search mobs across every Project 1999 zone"),
        "all_mob_search_description": (
            "Enter at least two characters. Results are not limited by the "
            "zone selected above"),
        "all_mob_visible_help": (
            "Enter at least two characters. Search is independent of the "
            "selected zone."),
        "relation_html": (
            "<b>Crystal Eyes</b><br><b>Drops:</b> "
            "<a href=\"vantage://item/Crystal%20Spider%20Eyes\">"
            "Crystal Spider Eyes</a>, "
            "<a href=\"vantage://item/Velium%20Crystal%20Staff\">"
            "Velium Crystal Staff</a><br><b>Related quests:</b> "
            "<a href=\"vantage://quest/The%20Lost%20Map\">The Lost Map</a>, "
            "<a href=\"vantage://quest/Coldain%20Prayer%20Shawl%20Quests\">"
            "Prayer Shawl</a>"),
        "relation_accessible": (
            "Crystal Eyes. Drops: Crystal Spider Eyes, Velium Crystal Staff. "
            "Related quests: The Lost Map, Prayer Shawl"),
        "relation_keyboard": True,
        "all_mob_clear_name": "Clear all-zone mob search",
        "opened_items": ["Crystal Spider Eyes"],
        "opened_quests": [[
            "Coldain Prayer Shawl Quests", "Coldain Prayer Shawl Quests",
            "quest"]],
        "quickbar_has_zones": True,
        "selection_auto_loads_once": True,
        "explicit_and_log_announce_modes": [
            ["kael drakkel", True],
            ["velketor's labyrinth", False]],
        "announcements_before_debounce": 0,
        "filter_announcements": 1,
        "selector_focused_on_open": True,
        "launcher_focus_safe": True,
    }


GLOBAL_MOB_SEARCH_SCRIPT = r"""
import json
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtTest import QTest
from vantage.helpers.application import VantageApp

class FakeReply(QObject):
    finished = Signal()
    def __init__(self):
        super().__init__()
        self.payload = b'{}'
        self.aborted = False
    def abort(self):
        self.aborted = True
    def error(self):
        return (QNetworkReply.NetworkError.OperationCanceledError
                if self.aborted else QNetworkReply.NetworkError.NoError)
    def errorString(self):
        return 'cancelled' if self.aborted else ''
    def readAll(self):
        return self.payload

class FakeNetwork:
    def __init__(self):
        self.replies = []
        self.urls = []
    def get(self, request):
        reply = FakeReply()
        self.replies.append(reply)
        self.urls.append(request.url().toString())
        return reply

app = VantageApp([])
zones = app._parsers_dict['zones']
network = FakeNetwork()
zones._network = network
zones.tabs.setCurrentIndex(3)
zones.show()
app.processEvents()
zones.all_mob_search.setText('Crystal Eyes')
QTest.keyClick(zones.all_mob_search, Qt.Key.Key_Return)
search_reply = network.replies[0]
search_reply.payload = json.dumps({'query': {'search': [
    {'title': 'Crystal Eyes'}, {'title': 'Crystal Spider Eyes'}
]}}).encode()
search_reply.finished.emit()

npc = '''{{Namedmobpage
| name = Crystal Eyes
| race = Giant Spider
| class = Rogue
| level = 47
| zone = [[Velketor's Labyrinth]]
| location = (479, 2)
| known_loot = {{:Crystal Spider Eyes}}, [[Velium Crystal Staff]]
| relatedquests = [[The Lost Map]]
}}'''
item = '''{{Itembox
| itemname = Crystal Spider Eyes
| statsblock = AC 8
}}'''
pages_reply = network.replies[1]
pages_reply.payload = json.dumps({'query': {'pages': {
    '1': {'title': 'Crystal Eyes', 'revisions': [{'*': npc}]},
    '2': {'title': 'Crystal Spider Eyes', 'revisions': [{'*': item}]},
}}}).encode()
pages_reply.finished.emit()
app.processEvents()

print(json.dumps({
    'requests': len(network.urls),
    'search_endpoint': 'list=search' in network.urls[0],
    'batch_endpoint': 'prop=revisions' in network.urls[1],
    'rows': zones.all_mob_table.rowCount(),
    'selected': zones._selected_value()['name'],
    'focused': zones.all_mob_table.hasFocus(),
    'button_enabled': zones.all_mob_search_button.isEnabled(),
    'status': zones.all_mob_search_status.text(),
    'item_link': 'vantage://item/Crystal%20Spider%20Eyes' in
                 zones.all_mob_relations.text(),
    'quest_link': 'vantage://quest/The%20Lost%20Map' in
                  zones.all_mob_relations.text(),
}))
app.quit()
"""


def test_any_mob_search_uses_enter_batches_pages_and_focuses_results(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", GLOBAL_MOB_SEARCH_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        "requests": 2,
        "search_endpoint": True,
        "batch_endpoint": True,
        "rows": 1,
        "selected": "Crystal Eyes",
        "focused": True,
        "button_enabled": True,
        "status": (
            "1 mob found across all zones · select a row for every linked "
            "drop and quest"),
        "item_link": True,
        "quest_link": True,
    }


STALE_MOB_SEARCH_SCRIPT = r"""
import json
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtTest import QTest
from vantage.helpers.application import VantageApp

class FakeReply(QObject):
    finished = Signal()
    def __init__(self):
        super().__init__()
        self.aborted = False
        self.payload = b'{}'
    def abort(self):
        self.aborted = True
    def error(self):
        return (QNetworkReply.NetworkError.OperationCanceledError
                if self.aborted else QNetworkReply.NetworkError.NoError)
    def errorString(self):
        return 'cancelled' if self.aborted else ''
    def readAll(self):
        return self.payload

class FakeNetwork:
    def __init__(self):
        self.replies = []
    def get(self, _request):
        reply = FakeReply()
        self.replies.append(reply)
        return reply

app = VantageApp([])
zones = app._parsers_dict['zones']
network = FakeNetwork()
zones._network = network
zones.tabs.setCurrentIndex(3)
zones.show()
zones.all_mob_search.setFocus(Qt.FocusReason.OtherFocusReason)
zones.all_mob_search.setText('Crystal Eyes')
QTest.keyClick(zones.all_mob_search, Qt.Key.Key_Return)
old_reply = network.replies[0]
zones.all_mob_search.setText('Dread')
old_reply.payload = json.dumps({'query': {'search': [
    {'title': 'Crystal Eyes'}
]}}).encode()
old_reply.finished.emit()
app.processEvents()
print(json.dumps({
    'aborted': old_reply.aborted,
    'rows': zones.all_mob_table.rowCount(),
    'focused': zones.all_mob_search.hasFocus(),
    'button_enabled': zones.all_mob_search_button.isEnabled(),
    'status': zones.all_mob_search_status.text(),
}))
app.quit()
"""


def test_editing_submitted_mob_query_cancels_stale_results_and_keeps_focus(
        tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", STALE_MOB_SEARCH_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    assert json.loads(completed.stdout.strip().splitlines()[-1]) == {
        "aborted": True,
        "rows": 0,
        "focused": True,
        "button_enabled": True,
        "status": (
            "Search text changed · press Enter or Search all zones for the "
            "new mob name."),
    }


EMPTY_MOB_SEARCH_SCRIPT = r"""
import json
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtTest import QTest
from vantage.helpers.application import VantageApp

class FakeReply(QObject):
    finished = Signal()
    def __init__(self):
        super().__init__()
        self.payload = b'{"query":{"search":[]}}'
    def abort(self):
        pass
    def error(self):
        return QNetworkReply.NetworkError.NoError
    def errorString(self):
        return ''
    def readAll(self):
        return self.payload

class FakeNetwork:
    def __init__(self):
        self.reply = None
    def get(self, _request):
        self.reply = FakeReply()
        return self.reply

app = VantageApp([])
zones = app._parsers_dict['zones']
network = FakeNetwork()
zones._network = network
zones.tabs.setCurrentIndex(3)
zones.show()
app.processEvents()
zones.all_mob_search.setText('No Such Mob')
zones.all_mob_search_button.setFocus(Qt.FocusReason.OtherFocusReason)
button_focused_before_search = zones.all_mob_search_button.hasFocus()
QTest.keyClick(zones.all_mob_search_button, Qt.Key.Key_Space)
focused_while_loading = zones.all_mob_search.hasFocus()
network.reply.finished.emit()
app.processEvents()
print(json.dumps({
    'button_focused_before_search': button_focused_before_search,
    'focused_while_loading': focused_while_loading,
    'focused_after_empty': zones.all_mob_search.hasFocus(),
    'button_enabled': zones.all_mob_search_button.isEnabled(),
    'status': zones.all_mob_search_status.text(),
}))
app.quit()
"""


def test_keyboard_search_button_keeps_retry_focus_when_results_are_empty(
        tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", EMPTY_MOB_SEARCH_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    assert json.loads(completed.stdout.strip().splitlines()[-1]) == {
        "button_focused_before_search": True,
        "focused_while_loading": True,
        "focused_after_empty": True,
        "button_enabled": True,
        "status": (
            "No P99 NPC pages matched No Such Mob. Try a shorter mob name."),
    }


SAVE_COLUMN_WIDTHS_SCRIPT = r"""
import json
from vantage.helpers.application import VantageApp
from vantage.helpers import config

app = VantageApp([])
zones = app._parsers_dict['zones']
widths = {
    'items': [411, 222],
    'mobs': [211, 72, 83, 94, 305, 176],
    'nameds': [251, 73, 84, 95, 315, 177],
    'all_mobs': [231, 74, 85, 96, 325, 207],
}
for key, values in widths.items():
    table = zones._zone_tables[key]
    for column, width in enumerate(values):
        table.setColumnWidth(column, width)
zones._save_column_widths()
print(json.dumps(config.data['zones']['column_widths']))
app.quit()
"""


RESTORE_COLUMN_WIDTHS_SCRIPT = r"""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView
from vantage.helpers.application import VantageApp

app = VantageApp([])
zones = app._parsers_dict['zones']
print(json.dumps({
    'widths': {
        key: [table.columnWidth(column) for column in range(table.columnCount())]
        for key, table in zones._zone_tables.items()
    },
    'interactive': all(
        table.horizontalHeader().sectionResizeMode(column) ==
        QHeaderView.ResizeMode.Interactive
        for table in zones._zone_tables.values()
        for column in range(table.columnCount())),
    'scrollable': all(
        table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        for table in zones._zone_tables.values()),
    'header_help': all(
        'drag a divider' in table.horizontalHeader().toolTip().lower()
        and table.horizontalHeader().accessibleDescription()
        for table in zones._zone_tables.values()),
}))
app.quit()
"""


def test_zone_column_widths_are_interactive_distinct_and_persisted(tmp_path):
    profile = tmp_path / "profile"
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(profile)
    saved = subprocess.run(
        [sys.executable, "-c", SAVE_COLUMN_WIDTHS_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    restored = subprocess.run(
        [sys.executable, "-c", RESTORE_COLUMN_WIDTHS_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    expected = {
        "items": [411, 222],
        "mobs": [211, 72, 83, 94, 305, 176],
        "nameds": [251, 73, 84, 95, 315, 177],
        "all_mobs": [231, 74, 85, 96, 325, 207],
    }
    assert json.loads(saved.stdout.strip().splitlines()[-1]) == expected
    result = json.loads(restored.stdout.strip().splitlines()[-1])
    assert result == {
        "widths": expected,
        "interactive": True,
        "scrollable": True,
        "header_help": True,
    }


ASYNC_ZONE_STRESS_SCRIPT = r"""
import json
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtTest import QTest
from vantage.helpers.application import VantageApp

class FakeReply(QObject):
    finished = Signal()
    def __init__(self):
        super().__init__()
        self.payload = b'{}'
        self.aborted = False
    def abort(self):
        self.aborted = True
        self.finished.emit()
    def error(self):
        return (QNetworkReply.NetworkError.OperationCanceledError
                if self.aborted else QNetworkReply.NetworkError.NoError)
    def errorString(self):
        return 'cancelled' if self.aborted else ''
    def readAll(self):
        return self.payload

class FakeNetwork:
    def __init__(self):
        self.replies = []
    def get(self, _request):
        reply = FakeReply()
        self.replies.append(reply)
        return reply

def payload(name, mob_name):
    wiki = ("{{Velious Era}}\n"
            "{| class=\"zoneTopTable\"\n"
            "! Level of Monsters:\n| 40-60\n|-\n"
            "! Notable NPCs:\n| [[%s]]\n|-\n"
            "! Unique Items:\n| [[Test Item]]\n|}\n"
            "== What's in this zone? ==\n") % mob_name
    rendered = '''<h2>What's in this zone?</h2>
<table class="eoTable3 sortable"><tr><th>NPC Name</th><th>Race</th>
<th>Class</th><th>Level</th><th>Location</th><th>Known Loot</th></tr>
<tr><td><a href="/%s">%s</a></td><td>Giant</td><td>Warrior</td>
<td>55</td><td>1, 2</td><td><a href="/Test_Item">Test Item</a></td></tr>
</table>''' % (mob_name.replace(' ', '_'), mob_name)
    return json.dumps({'parse': {
        'title': name, 'wikitext': {'*': wiki}, 'text': {'*': rendered}
    }}).encode()

app = VantageApp([])
zones = app._parsers_dict['zones']
network = FakeNetwork()
zones._network = network

def index_for(value):
    return next(index for index in range(zones.zone_selector.count())
                if zones.zone_selector.itemData(index) == value)

zones.zone_selector.setCurrentIndex(index_for('kael drakkel'))
first = network.replies[-1]
zones.zone_selector.setCurrentIndex(index_for("velketor's labyrinth"))
second = network.replies[-1]
# A reply that completes after being superseded must stay disconnected and
# must never overwrite the new selection.
first.payload = payload('Kael Drakkel', 'King Tormax')
first.finished.emit()
zones.hide()
zones.show()
second.payload = payload("Velketor's Labyrinth", 'Crystal Eyes')
second.finished.emit()
QTest.qWait(10)

# Rebuild populated sortable tables repeatedly; selection-change callbacks
# must not re-enter while rows and header state are changing.
data = dict(zones._zone_data)
for _ in range(100):
    zones._set_zone_data(data, announce=False)

zones.zone_selector.setCurrentIndex(index_for('kael drakkel'))
invalid = network.replies[-1]
invalid.payload = json.dumps({'error': {'info': 'missing title'}}).encode()
invalid.finished.emit()
zones.zone_selector.setCurrentIndex(index_for("velketor's labyrinth"))
shutdown_reply = network.replies[-1]
zones._cancel_network_requests()

print(json.dumps({
    'first_aborted': first.aborted,
    'latest_name': data.get('name'),
    'latest_mob': data.get('mobs', [{}])[0].get('name'),
    'second_is_retired': zones._zone_reply is None or zones._zone_reply is not second,
    'invalid_handled': invalid is not zones._zone_reply,
    'shutdown_aborted': shutdown_reply.aborted,
    'pending_drops': len(zones._drop_reply_contexts),
}))
app.quit()
"""


def test_zone_async_switch_hide_invalid_and_shutdown_are_crash_safe(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", ASYNC_ZONE_STRESS_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    assert json.loads(completed.stdout.strip().splitlines()[-1]) == {
        "first_aborted": True,
        "latest_name": "Velketor's Labyrinth",
        "latest_mob": "Crystal Eyes",
        "second_is_retired": True,
        "invalid_handled": True,
        "shutdown_aborted": True,
        "pending_drops": 0,
    }
