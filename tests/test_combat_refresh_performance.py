"""Guard the real periodic refresh against hidden/unchanged Qt table work."""

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import datetime
import json
from PySide6.QtCore import QItemSelectionModel, QTimer
from vantage.helpers.application import VantageApp
from vantage.helpers import config
import vantage.parsers.combat as combat_module

app = VantageApp([])
combat = app._parsers_dict['combat']
for timer in app.findChildren(QTimer):
    timer.stop()
combat.hide()
combat._set_collapsed(False)
config.data['combat']['encounter_timeout'] = 3600
stamp = datetime.datetime.now()
for index in range(500):
    combat.parse(stamp, 'Alice hits a bat for 10 points of damage.')
combat.parse(stamp, 'Bob hits a bat for 5 points of damage.')

writes = []
original_rows = combat._set_rows
def record_rows(table, rows):
    writes.append(next(name for name, value in combat.tables.items() if value is table))
    return original_rows(table, rows)
combat._set_rows = record_rows
background = []
combat._refresh_live_combat_overlay = lambda: background.append('overlays')
original_expire = combat._tracker.expire
def expire(now):
    background.append('expire')
    return original_expire(now)
combat._tracker.expire = expire
original_scope = combat._scope
scopes = []
def scope():
    scopes.append(True)
    return original_scope()
combat._scope = scope

# Exercise the connected timer, not a special benchmark-only code path.
combat._refresh_timer.timeout.emit()
hidden = not writes and not scopes and background == ['expire', 'overlays']
combat.show()
app.processEvents()
overview_only = writes == ['Overview'] and combat.tables['Timeline'].rowCount() == 0
overview = combat.tables['Overview']
first_item = overview.item(0, 0)
changes = []
overview.model().dataChanged.connect(lambda *args: changes.append(True))
writes.clear()
for _ in range(3):
    combat._refresh_timer.timeout.emit()
unchanged = not writes and not changes and overview.item(0, 0) is first_item

# Re-ranking must keep Alice selected, preserve cells and allow highlighted copy.
alice_row = next(row for row in range(overview.rowCount()) if overview.item(row, 0).text() == 'Alice')
overview.selectRow(alice_row)
combat.parse(stamp, 'Bob hits a bat for 10000 points of damage.')
combat.refresh()
selection = {overview.item(item.row(), 0).text() for item in overview.selectedItems()}
combat._copy_eq_summary(highlighted=True)
highlighted = app.clipboard().text()
selection_safe = selection == {'Alice'} and 'Alice' in highlighted and 'Bob' not in highlighted

writes.clear()
combat.tabs.setCurrentIndex(combat.TABS.index('Timeline'))
timeline = combat.tables['Timeline']
tab_switch = writes == ['Timeline'] and timeline.rowCount() == 502
timeline_item = timeline.item(0, 0)
writes.clear()
combat.refresh()
timeline_unchanged = not writes and timeline.item(0, 0) is timeline_item

combat.hide()
combat.parse(stamp, 'Alice hits a bat for 5 points of damage.')
combat.show()
show_fresh = timeline.rowCount() == 503
combat._set_collapsed(True)
writes.clear()
combat.parse(stamp, 'Alice hits a bat for 5 points of damage.')
combat._refresh_timer.timeout.emit()
rolled = not writes
combat._set_collapsed(False)
expanded = timeline.rowCount() == 504
combat.showMinimized()
writes.clear()
combat._refresh_timer.timeout.emit()
minimized = not writes
combat.showNormal()

# Repeated Session polling must not rebuild combined encounters/chart inputs.
session_calls = []
original_session = combat._tracker.session
def session():
    session_calls.append(True)
    return original_session()
combat._tracker.session = session
combat.mode.setCurrentIndex(combat.mode.findData('session'))
for _ in range(3):
    combat.refresh()
session_cached = len(session_calls) == 1
combat.parse(stamp, 'Alice hits a bat for 5 points of damage.')
combat.refresh()
session_invalidated = len(session_calls) == 2

# Exports populate inactive views deliberately, including while hidden.
combat.hide()
_, _, _, sections = combat._full_report_context()
section_names = {row[0] for row in sections}
export_complete = {'Overview', 'Player DPS', 'Damage Breakdown', 'Timeline'} <= section_names
combat._copy_current_view()
copy_fresh = 'Alice' in app.clipboard().text() and timeline.rowCount() == 505

# Archive expiry continues without showing the panel or rebuilding a table.
combat._tracker.current().last_at = stamp - datetime.timedelta(hours=2)
writes.clear()
combat._refresh_timer.timeout.emit()
hidden_expiry = not combat._tracker.active and combat._combat_archive.count() == 1 and not writes

# Selected scope and history actions use stable archive IDs even if new fights
# arrive while Fights is not visible. Decoding is cached between actual changes.
combat.show()
combat.tabs.setCurrentIndex(combat.TABS.index('Fights'))
combat.tables['Fights'].selectRow(0)
archive_loads = []
original_load = combat._combat_archive.load
def load(ids):
    archive_loads.append(True)
    return original_load(ids)
combat._combat_archive.load = load
combat.mode.setCurrentIndex(combat.mode.findData('selected'))
combat.tabs.setCurrentIndex(combat.TABS.index('Overview'))
for _ in range(3):
    combat.refresh()
selected_cached = len(archive_loads) == 1
combat.parse(stamp, 'Alice hits a rat for 1 points of damage.')
combat.parse(stamp, 'You have slain a rat!')
stable_history = (combat._selected_fight_records()[0].target == 'a bat'
                  and combat._scope().total_damage == 15020)
combat.tabs.setCurrentIndex(combat.TABS.index('Fights'))
stable_selection = combat._selected_fight_records()[0].target == 'a bat'
combat._full_report_context()
export_selection = combat._selected_fight_records()[0].target == 'a bat'

chart_draws = []
original_chart = combat.chart_canvas.set_data
def set_chart(data):
    chart_draws.append(True)
    return original_chart(data)
combat.chart_canvas.set_data = set_chart
combat._chart_signature = None
combat.tabs.setCurrentIndex(combat.TABS.index('Charts'))
for _ in range(3):
    combat.refresh()
chart_cached = len(chart_draws) == 1
combat.parse(stamp, 'Alice hits a flea for 1 points of damage.')
combat.parse(stamp, 'You have slain a flea!')
combat_module.QMessageBox.question = staticmethod(
    lambda *args, **kwargs: combat_module.QMessageBox.StandardButton.Yes)
combat._delete_selected_fights()
delete_safe = {record.target for record in combat._fight_records} == {'a rat', 'a flea'}
combat._undo_fight_change()
undo_safe = {record.target for record in combat._fight_records} == {'a bat', 'a rat', 'a flea'}

# A rendered pet selection must not remove a newly inserted different pet.
combat._tracker.register_pet('Zibb', 'Alice', 'Test')
combat._save_pet_links()
combat.tabs.setCurrentIndex(combat.TABS.index('Pets'))
combat.tables['Pets'].selectRow(0)
combat._tracker.register_pet('Aabb', 'Alice', 'Test')
combat._save_pet_links()
combat._delete_pet_links()
pets_safe = {row['pet'] for row in combat._tracker.pet_rows()} == {'Aabb'}

# Switching through an empty scope must not poison a cached caster detail view.
combat.mode.setCurrentIndex(combat.mode.findData('current'))
combat.parse(stamp, 'Alice hits an orc for 10 points of damage.')
combat.parse(stamp, 'Alice begins casting Ice Comet.')
combat.tabs.setCurrentIndex(combat.TABS.index('Spells'))
combat.tabs.setCurrentIndex(combat.TABS.index('Overview'))
combat._tracker.current().last_at = stamp - datetime.timedelta(hours=2)
combat.refresh()
combat.mode.setCurrentIndex(combat.mode.findData('last'))
combat.tabs.setCurrentIndex(combat.TABS.index('Spells'))
combat._refresh_spell_details()
spell_context = (combat._spell_scope is combat._tracker.last()
                 and combat.tables['Spell Comparison'].rowCount() > 0)

# Identical timestamps still identify different rolls. Current-row actions
# such as Split set must follow the selected event after insertion, too.
rolls = combat.tables['Randoms']
old_rolls = [('12:34:56', 'Alice', '0–100', '10'),
             ('12:34:56', 'Bob', '0–100', '90')]
combat._set_rows(rolls, old_rolls)
rolls.setCurrentCell(1, 0)
rolls.selectRow(1)
new_rolls = [('12:34:56', 'Carol', '0–100', '50'), *old_rolls]
combat._set_rows(rolls, new_rolls)
roll_identity = (rolls.currentRow() == 2 and
                 {item.row() for item in rolls.selectedItems()} == {2}
                 and rolls.item(rolls.currentRow(), 1).text() == 'Bob')
combat._set_rows(rolls, new_rolls[:2])
removed_current = rolls.currentRow() == -1 and not rolls.selectedItems()

casters = combat.tables['Spells']
caster_rows = [(name, 'Unknown', 1, 0, 0, 0, 0, 0) for name in ('Alice', 'Bob')]
combat._set_rows(casters, caster_rows)
casters.setCurrentCell(1, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
for row in range(2):
    for column in range(casters.columnCount()):
        casters.item(row, column).setSelected(True)
combat._set_rows(casters, [('Carol', 'Unknown', 1, 0, 0, 0, 0, 0), *caster_rows])
multi_current = (casters.currentRow() == 2 and
                 {item.row() for item in casters.selectedItems()} == {1, 2})

print(json.dumps(dict(hidden=hidden, overview_only=overview_only, unchanged=unchanged,
    selection_safe=selection_safe, tab_switch=tab_switch, timeline_unchanged=timeline_unchanged,
    show_fresh=show_fresh, rolled=rolled, expanded=expanded, minimized=minimized,
    session_cached=session_cached, session_invalidated=session_invalidated,
    export_complete=export_complete, copy_fresh=copy_fresh, hidden_expiry=hidden_expiry,
    selected_cached=selected_cached, stable_history=stable_history,
    stable_selection=stable_selection, export_selection=export_selection,
    chart_cached=chart_cached, pets_safe=pets_safe,
    delete_safe=delete_safe, undo_safe=undo_safe, spell_context=spell_context,
    roll_identity=roll_identity, removed_current=removed_current,
    multi_current=multi_current)))
combat.close()
app.quit()
"""


def test_combat_periodic_refresh_is_lazy_without_losing_background_or_exports(tmp_path):
    env = os.environ.copy()
    env.update(
        QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(ROOT / "src"),
        VANTAGE_DATA_DIR=str(tmp_path / "profile"))
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=60)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert all(result.values()), result
