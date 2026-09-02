import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import datetime
import json
from PySide6.QtWidgets import QAbstractItemView, QTabWidget, QWidget
from vantage.helpers.application import VantageApp

app = VantageApp([])
combat = app._parsers_dict['combat']
combat.show()
stamp = datetime.datetime.now()
lines = (
    'You hit a giant for 1 point of damage.',
    'You begin casting Ignite.',
    'Your target resisted the Ignite spell.',
    'Alice begins casting Complete Heal.',
    "Alice's spell is interrupted.",
    'You score a critical hit! (100)',
    'You slash a giant for 125 points of damage.',
)
for offset, line in enumerate(lines):
    combat.parse(stamp + datetime.timedelta(seconds=offset), line)
combat.refresh()
app.processEvents()

overview = combat.tables['Spells']
overview_rows = [[
    overview.item(row, column).text()
    for column in range(overview.columnCount())]
    for row in range(overview.rowCount())]
for row in range(overview.rowCount()):
    for column in range(overview.columnCount()):
        overview.item(row, column).setSelected(True)
combat._refresh_spell_details()

comparison = combat.tables['Spell Comparison']
comparison_rows = [[
    comparison.item(row, column).text()
    for column in range(comparison.columnCount())]
    for row in range(comparison.rowCount())]
timeline = combat.tables['Spell Timeline']
timeline_rows = [[
    timeline.item(row, column).text()
    for column in range(timeline.columnCount())]
    for row in range(timeline.rowCount())]
mods = combat.tables['Damage Mods']
mods_rows = [[
    mods.item(row, column).text()
    for column in range(mods.columnCount())]
    for row in range(mods.rowCount())]

combat._copy_spell_casters_eq()
spell_clipboard = app.clipboard().text()
combat._copy_damage_mods_eq()
mods_clipboard = app.clipboard().text()

spells_index = next(
    index for index in range(combat.tabs.count())
    if combat.tabs.tabText(index) == 'Spells')
combat.tabs.setCurrentIndex(spells_index)
combat.spell_tabs.setCurrentIndex(1)
label, _encounter, headers, rows = combat._current_table_data()

host = combat.tabs.widget(spells_index)
missing_tooltips = []
for widget in host.findChildren(QWidget):
    if (isinstance(widget, (QAbstractItemView, QTabWidget))
            and not widget.toolTip().strip()):
        missing_tooltips.append(
            widget.accessibleName() or widget.objectName()
            or type(widget).__name__)

print(json.dumps({
    'overview_rows': overview_rows,
    'comparison_rows': comparison_rows,
    'timeline_outcomes': [row[3] for row in timeline_rows],
    'mods_rows': mods_rows,
    'spell_clipboard': spell_clipboard,
    'mods_clipboard': mods_clipboard,
    'current_label': label,
    'current_headers': headers,
    'current_rows': len(rows),
    'subtab_tooltips': [
        bool(combat.spell_tabs.tabToolTip(index))
        for index in range(combat.spell_tabs.count())],
    'missing_tooltips': missing_tooltips,
}))
combat.close()
app.quit()
"""


def test_spell_views_damage_mods_clipboard_and_tooltips(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    by_caster = {row[0]: row for row in result['overview_rows']}
    assert by_caster['You'][2:] == ['1', '0', '0', '1', '0', '0']
    assert by_caster['Alice'][2:] == ['1', '0', '1', '0', '0', '0']
    assert {tuple(row[:2]) for row in result['comparison_rows']} == {
        ('You', 'Ignite'), ('Alice', 'Complete Heal')}
    assert result['timeline_outcomes'] == ['Resist', 'Interrupt']
    assert result['mods_rows'] == [[
        'You', 'Slashing', 'Critical', '100.0', '125.0', '+25.0%', '1']]
    assert 'You - 1 casts' in result['spell_clipboard']
    assert 'Alice - 1 casts' in result['spell_clipboard']
    assert 'Slashing +25.0% (1)' in result['mods_clipboard']
    assert result['current_label'] == 'Spells · Comparison'
    assert result['current_headers'][:2] == ['Caster', 'Spell / action']
    assert result['current_rows'] == 2
    assert result['subtab_tooltips'] == [True, True, True]
    assert result['missing_tooltips'] == []
