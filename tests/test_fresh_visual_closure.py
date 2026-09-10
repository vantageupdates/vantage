"""Geometry contracts for findings from the final screenshot review."""

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import hashlib
import json
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QToolButton
from vantage.helpers.application import VantageApp
from vantage.parsers.market import WikiItemCard

app = VantageApp([])
combat = app._parsers_dict['combat']
heals = app._parsers_dict['heals']
quests = app._parsers_dict['quests']
zones = app._parsers_dict['zones']
market = app._parsers_dict['market']
maps = app._parsers_dict['maps']
tick = app._parsers_dict['tick']
card = WikiItemCard({'n': "Journeyman's Boots"})

for panel in (combat, heals, quests):
    panel.resize(1, 1)
    panel.show()
app.processEvents()

quests._set_catalog([
    '10th Coldain Ring Quest', 'Druid Epic Quest',
    "Journeyman's Boots Quest"], 'test cache')
quests.quest_title.setText("Journeyman's Boots Quest")
quests.summary.setPlainText(
    'Speak with Hasten Bootstrutter, gather the required items, and return '
    'for the final turn-in. Rewards: Journeyman\'s Boots.')
quests.wiki_button.setEnabled(True)
quests.checklist_button.setEnabled(True)
quest_cases = []
def painted_in_window(widget, image):
    origin = widget.mapTo(quests._surface, QPoint(0, 0))
    scale = quests.width() / quests._surface.width()
    left = max(0, round(origin.x() * scale))
    top = max(0, round(origin.y() * scale))
    right = min(image.width(), left + round(widget.width() * scale))
    bottom = min(image.height(), top + round(widget.height() * scale))
    colors = set()
    for y in range(top, bottom, 2):
        for x in range(left, right, 2):
            colors.add(image.pixelColor(x, y).rgba())
            if len(colors) >= 8:
                return True
    return False

# Reproduce the actual audit lifecycle: the formerly blank frame appeared on
# the fourth show after recommended -> half -> minimum -> short hide cycles.
for width, height in ((900, 580), (720, 580), (720, 580), (900, 420)):
    quests.resize(width, height)
    quests.show()
    app.processEvents()
    surface = quests._surface
    frame = quests.grab().toImage()
    quest_cases.append({
        'window': [quests.width(), quests.height()],
        'surface': [surface.width(), surface.height()],
        'list_width': quests.quest_list.viewport().width(),
        'summary_height': quests.summary.viewport().height(),
        'wiki_full': quests.wiki_button.width() >= quests.wiki_button.sizeHint().width(),
        'checklist_full': quests.checklist_button.width() >= quests.checklist_button.sizeHint().width(),
        'wiki_painted': painted_in_window(quests.wiki_button, frame),
        'checklist_painted': painted_in_window(quests.checklist_button, frame),
        'frame_sha256': hashlib.sha256(bytes(frame.constBits())).hexdigest(),
        'body_foreground_pixels': sum(
            1 for y in range(20, frame.height(), 2)
            for x in range(0, frame.width(), 2)
            if max(frame.pixelColor(x, y).red(),
                   frame.pixelColor(x, y).green(),
                   frame.pixelColor(x, y).blue()) >= 80),
        'source_visible': (
            quests.source_note.isVisibleTo(surface) and
            quests.source_note.mapTo(surface, quests.source_note.rect().bottomLeft()).y()
            <= surface.height()),
        'splitter': quests.splitter.sizes(),
    })
    quests.hide()
    app.processEvents()

result = {
    'combat_tabbar_hidden': combat.tabs.tabBar().isHidden(),
    'combat_selector_count': combat.view_selector.count(),
    'combat_selector_name': combat.view_selector.accessibleName(),
    'combat_sync': [],
    'minimums': {
        panel.name: [panel.minimumWidth(), panel.minimumHeight(),
                     panel.width(), panel.height()]
        for panel in (combat, heals, quests)},
    'readable_minimums': {
        panel.name: [panel.minimumWidth(), panel.minimumHeight()]
        for panel in (maps, tick, market, zones)},
    'quest_cases': quest_cases,
    'combat_native_buttons': {
        'random_split': combat.random_split_button.objectName(),
        'random_clear': combat.random_clear_splits_button.objectName(),
        'log_add': combat.log_save_button.objectName(),
        'log_delete': combat.log_delete_button.objectName(),
    },
    'zone_columns_name': zones.zone_columns_button.accessibleName(),
    'zone_header_css': 'QHeaderView { background-color: #141B21; }' in app.styleSheet(),
    'disabled_tool_css': 'QToolButton:disabled' in app.styleSheet(),
    'source_minimum_height': card.drops.minimumHeight(),
    'source_scroll': card.card_scroll.widget() is not None,
    'recharge_guide': {
        'text': market.recharge_guide_button.text(),
        'name': market.recharge_guide_button.accessibleName(),
        'description': market.recharge_guide_button.accessibleDescription(),
        'tooltip': market.recharge_guide_button.toolTip(),
    },
}
for index in (0, 5, combat.tabs.count() - 1):
    combat.tabs.setCurrentIndex(index)
    app.processEvents()
    result['combat_sync'].append([
        combat.tabs.currentIndex(), combat.view_selector.currentIndex()])
print(json.dumps(result))
card.close()
app.quit()
"""


def test_final_visual_review_contracts(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env, check=True,
        capture_output=True, text=True, timeout=35)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result['combat_tabbar_hidden'] is True
    assert result['combat_selector_count'] == 22
    assert result['combat_selector_name'] == 'Combat analysis view'
    assert result['combat_sync'] == [[0, 0], [5, 5], [21, 21]]
    # Exact replica presets may reach 25% without allowing a blank or clipped
    # logical surface.
    for minimum_width, minimum_height, width, height in result['minimums'].values():
        assert width >= minimum_width and height >= minimum_height
        assert minimum_width >= 130
        assert minimum_height >= 55
    assert result['zone_columns_name'] == 'Resize zone table columns'
    assert result['readable_minimums'] == {
        'maps': [100, 100], 'tick': [65, 36],
        'market': [245, 155], 'zones': [225, 140]}
    assert result['combat_native_buttons'] == {
        'random_split': 'ToolbarAction',
        'random_clear': 'ToolbarAction',
        'log_add': 'ToolbarAction',
        'log_delete': 'ToolbarAction'}
    assert [case['window'] for case in result['quest_cases']] == [
        [900, 580], [720, 580], [720, 580], [900, 420]]
    for case in result['quest_cases']:
        assert case['surface'][0] == 900
        assert case['surface'][1] >= case['window'][1]
        assert case['list_width'] >= 250
        assert case['summary_height'] >= 240
        assert case['wiki_full'] is True
        assert case['checklist_full'] is True
        assert case['wiki_painted'] is True
        assert case['checklist_painted'] is True
        assert case['body_foreground_pixels'] >= 500
        assert case['source_visible'] is True
        assert min(case['splitter']) >= 270
    # Minimum and short are the same clamped size and unchanged state. Both
    # frames are checked from captured pixels above rather than trusting Qt's
    # logical visibility flags. The checksum remains diagnostic evidence; it
    # may differ because the focused search caret blinks independently.
    assert result['zone_header_css'] is True
    assert result['disabled_tool_css'] is True
    assert result['source_minimum_height'] >= 115
    assert result['source_scroll'] is True
    assert result['recharge_guide']['text'] == 'Item Recharge Guide'
    assert 'Project 1999' in result['recharge_guide']['name']
    assert 'not pricing or purchase' in result['recharge_guide']['description']
    assert 'help only' in result['recharge_guide']['tooltip']
